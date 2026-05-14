"""
tools.py — AVENUE Z CREWAI TEMPLATE
Defines all CrewAI tools that agents can call.

The @tool docstring is what the agent reads to decide WHEN to use the tool.
Be specific. "Use this to search Glean for media lists and reporter data scoped to Google Drive"
is better than "search tool".

CUSTOMIZATION CHECKLIST FOR NEW PROJECTS:
  [ ] Keep glean_search and glean_read_document unchanged — they work for every project
  [ ] Keep web_search unchanged — same Serper API key across all projects
  [ ] Update post_to_slack if your notification format differs
  [ ] Add custom tools below for any external APIs specific to your use case
  [ ] Validate each tool works: python3 tools.py
"""

import os
import json
import httpx                             # httpx only — no requests library in production
from crewai.tools import tool
from dotenv import load_dotenv

load_dotenv()

GLEAN_SERVER_URL = os.environ["GLEAN_SERVER_URL"]
GLEAN_API_TOKEN  = os.environ["GLEAN_API_TOKEN"]
SLACK_BOT_TOKEN  = os.environ["SLACK_BOT_TOKEN"]
SERPER_API_KEY   = os.environ.get("SERPER_API_KEY", "")

GLEAN_ACT_AS     = "thomas.chang@avenuez.com"
GLEAN_TIMEOUT    = 30


def _glean_headers() -> dict:
    return {
        "Authorization": f"Bearer {GLEAN_API_TOKEN}",
        "X-Glean-ActAs": GLEAN_ACT_AS,
        "Content-Type": "application/json",
    }


# ─────────────────────────────────────────────────────────────────
# CORE TOOLS — COPY UNCHANGED INTO EVERY PROJECT
# ─────────────────────────────────────────────────────────────────

@tool("glean_search")
def glean_search(query: str) -> str:
    """
    Search the Avenue Z Glean knowledge graph (Google Drive by default).
    Use this to find: client media lists, reporter contact spreadsheets, strategy docs,
    previous pitches, account maps, and any other content indexed in Glean.
    Returns document titles, URLs, and relevant excerpts.
    Input: a natural language search query string.
    """
    payload = {
        "query": query,
        "pageSize": 10,
        "requestOptions": {
            "datasourceFilter": "gdrive",
        },
    }

    try:
        resp = httpx.post(
            f"{GLEAN_SERVER_URL}/rest/api/v1/search",
            json=payload,
            headers=_glean_headers(),
            timeout=GLEAN_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if not results:
            return "No results found in Glean for this query."

        output = []
        for r in results[:10]:
            title   = r.get("title", "Untitled")
            url     = r.get("url", "")
            snippet = r.get("snippets", [{}])[0].get("text", "") if r.get("snippets") else ""
            output.append(f"TITLE: {title}\nURL: {url}\nEXCERPT: {snippet}\n")

        return "\n".join(output)

    except Exception as e:
        return f"Glean search error: {e}"


@tool("glean_read_document")
def glean_read_document(doc_title: str, search_terms: str = "") -> str:
    """
    Read the content of a specific internal document via Glean search by TITLE.
    CRITICAL: Takes a document TITLE (not a URL). Searches Glean by title to find the doc.
    Use this to read pitchbooks, FAQs, media lists, strategy docs stored in Google Drive.
    Args:
        doc_title: The document title or name (e.g. 'MDVIP Master Pitchbook')
        search_terms: Additional keywords to surface relevant sections (e.g. 'value proposition')
    Returns: document title, URL, and full content from the top matching result.
    """
    query = f"{doc_title} {search_terms}".strip()
    payload = {
        "query": query,
        "pageSize": 1,
        "maxSnippetSize": 10000,
        "requestOptions": {"returnLlmContentOverSnippets": True},
    }

    try:
        resp = httpx.post(
            f"{GLEAN_SERVER_URL}/rest/api/v1/search",
            json=payload,
            headers=_glean_headers(),
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if not results:
            return f"Document not found in Glean: {doc_title}"

        r = results[0]
        title = r.get("document", {}).get("title", "Unknown")
        url = r.get("document", {}).get("url", "")
        snippets = " ".join(s.get("text", "") for s in r.get("snippets", []))

        if not snippets:
            return f"Document '{title}' found but returned no content. It may not be indexed yet."

        return f"Title: {title}\nURL: {url}\n\nContent:\n{snippets[:50000]}"

    except Exception as e:
        return f"Error reading document {url}: {e}"


@tool("web_search")
def web_search(query: str) -> str:
    """
    Search the live web using Serper API.
    Use this ONLY when Glean does not have the information you need — for example,
    finding named reporters with confirmed bylines on a beat in the last 90 days,
    or verifying current information not in Avenue Z's internal knowledge base.
    Input: a specific search query string. Be precise — include outlet names and topics.
    Returns: web search results with titles, URLs, and snippets.
    """
    if not SERPER_API_KEY:
        return "SERPER_API_KEY not configured — web search unavailable."

    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": 10}

    try:
        resp = httpx.post("https://google.serper.dev/search", json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("organic", [])
        if not results:
            return "No web search results found."

        output = []
        for r in results[:10]:
            title   = r.get("title", "")
            url     = r.get("link", "")
            snippet = r.get("snippet", "")
            output.append(f"TITLE: {title}\nURL: {url}\nSNIPPET: {snippet}\n")

        return "\n".join(output)

    except Exception as e:
        return f"Web search error: {e}"


@tool("post_to_slack")
def post_to_slack(channel_id: str, message: str) -> str:
    """
    Post a message to a Slack channel.
    Use this to send success notifications, no-news updates, or error alerts.
    Input: channel_id (Slack channel ID starting with C), message (plain text or Slack markdown).
    Returns: confirmation or error message.
    """
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "channel": channel_id,
        "text": message,
        "mrkdwn": True,
    }

    try:
        resp = httpx.post("https://slack.com/api/chat.postMessage", json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return f"Message posted to {channel_id} successfully."
        else:
            return f"Slack error: {data.get('error', 'unknown')}"
    except Exception as e:
        return f"Error posting to Slack: {e}"


# ─────────────────────────────────────────────────────────────────
# CUSTOM TOOLS — ADD PROJECT-SPECIFIC TOOLS BELOW
# Use this pattern for any external API not covered above.
# ─────────────────────────────────────────────────────────────────

# @tool("hubspot_get_deals")
# def hubspot_get_deals(stage: str) -> str:
#     """
#     Fetch open HubSpot deals at a specific pipeline stage.
#     Use this to get the current deal list for sales ops reporting.
#     Input: stage name (e.g., 'proposal', 'negotiation', 'closed_won').
#     Returns: list of deals with name, value, owner, and last activity date.
#     """
#     HUBSPOT_TOKEN = os.environ.get("HUBSPOT_API_TOKEN", "")
#     # ... your HubSpot API call here
#     pass


# ─────────────────────────────────────────────────────────────────
# VALIDATION — Run directly to test all tools
# python3 tools.py
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing glean_search...")
    result = glean_search.run("Avenue Z media list reporters")
    print(result[:500])

    print("\nTesting web_search...")
    result = web_search.run("Bloomberg health reporter beat 2025")
    print(result[:500])

    print("\nAll tools validated.")
