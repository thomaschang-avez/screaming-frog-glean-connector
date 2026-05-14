"""
filters.py — AVENUE Z CREWAI TEMPLATE
Data ingestion and cleaning. Runs BEFORE agents. Outputs clean payload for Agent 1.

Rule: Never send more than 20-30 items to an agent. More degrades output.
Rule: Clean data in = clean output. This file is as important as agents.py.

CUSTOMIZATION CHECKLIST FOR NEW PROJECTS:
  [ ] Replace Slack channel reading with your actual data source
  [ ] Update BLOCKED_DOMAINS list (copy from reference/blocked-domains.md)
  [ ] Adjust DATE_CUTOFF_DAYS to match your use case (7 days for PR newsjacking)
  [ ] Adjust MAX_ARTICLES cap (20 for PR newsjacking)
  [ ] Update FilterResult fields to match what your agents actually need
  [ ] Run: python3 filters.py --client [ClientName] to validate before building tools.py
"""

import os
import json
import hashlib
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import List, Optional
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from config import ClientConfig

load_dotenv()

# ─────────────────────────────────────────────────────────────────
# CONSTANTS — UPDATE FOR YOUR USE CASE
# ─────────────────────────────────────────────────────────────────

DATE_CUTOFF_DAYS = 7         # articles older than this are filtered out
MAX_ARTICLES = 20            # max articles passed to Agent 1 — never exceed 30
SLACK_HISTORY_LIMIT = 200    # messages to fetch per channel per API call

# ── BLOCKED DOMAINS — copy full list from reference/blocked-domains.md ──
# These domains are filtered out before articles reach the agents.
# Wire services, client press releases, social media — anything with no pitch value.
BLOCKED_DOMAINS = [
    "prnewswire.com",
    "businesswire.com",
    "globenewswire.com",
    "accesswire.com",
    "einpresswire.com",
    "prlog.org",
    "newswire.com",
    "send2press.com",
    "prweb.com",
    "businessinsider.com",  # NOTE: may need to unblock depending on dept
    "twitter.com",
    "x.com",
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "reddit.com",
    "youtube.com",
    "tiktok.com",
    # ADD MORE from reference/blocked-domains.md and filters.py in pr-newsjacking
]


# ─────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────

@dataclass
class Article:
    url: str
    title: str
    source: str
    published_at: Optional[str]
    channel_id: str
    raw_text: str


@dataclass
class FilterResult:
    status: str              # "HAS_NEWS" or "NO_NEWS" — plain string, not Enum
    articles: List[Article]
    client_name: str
    channels_checked: List[str]
    articles_before_filter: int
    articles_after_filter: int


# ─────────────────────────────────────────────────────────────────
# SLACK CLIENT
# ─────────────────────────────────────────────────────────────────

def _get_slack_client() -> WebClient:
    return WebClient(token=os.environ["SLACK_BOT_TOKEN"])


# ─────────────────────────────────────────────────────────────────
# CORE FILTER FUNCTIONS
# ─────────────────────────────────────────────────────────────────

def _extract_urls_from_message(message: dict) -> List[str]:
    """
    Extract all URLs from a Slack message (attachments, blocks, text).
    Muck Rack posts URLs in attachments[].original_url and blocks[].elements[].url.
    UPDATE THIS if your Slack messages have a different structure.
    """
    urls = []

    # Check attachments (Muck Rack primary URL location)
    for att in message.get("attachments", []):
        url = att.get("original_url") or att.get("title_link") or att.get("from_url")
        if url:
            urls.append(url)

    # Check unfurled links in blocks
    for block in message.get("blocks", []):
        for element in block.get("elements", []):
            if element.get("type") == "link":
                urls.append(element.get("url", ""))

    # Fallback: parse URLs from text
    text = message.get("text", "")
    if "<http" in text:
        import re
        found = re.findall(r'<(https?://[^|>]+)', text)
        urls.extend(found)

    return [u for u in urls if u]


def _is_blocked(url: str) -> bool:
    """Return True if this URL's domain is in the blocked list."""
    from urllib.parse import urlparse
    try:
        domain = urlparse(url).netloc.lower().lstrip("www.")
        return any(blocked in domain for blocked in BLOCKED_DOMAINS)
    except Exception:
        return False


def _is_within_cutoff(message: dict, cutoff_days: int = DATE_CUTOFF_DAYS) -> bool:
    """Return True if the message was posted within the cutoff window."""
    ts = message.get("ts")
    if not ts:
        return False
    try:
        msg_time = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=cutoff_days)
        return msg_time >= cutoff
    except Exception:
        return False


def _extract_article_from_message(message: dict, channel_id: str) -> Optional[Article]:
    """
    Convert a Slack message to an Article object.
    Returns None if no valid URL found.
    UPDATE: pull title and source from attachment metadata if available.
    """
    urls = _extract_urls_from_message(message)
    if not urls:
        return None

    url = urls[0]  # Use first URL found

    # Try to get title from attachment
    title = ""
    source = ""
    for att in message.get("attachments", []):
        title = att.get("title", "") or att.get("text", "")[:100]
        source = att.get("service_name", "") or att.get("author_name", "")
        if title:
            break

    # Fallback title from text
    if not title:
        title = message.get("text", "")[:100].strip()

    ts = message.get("ts", "")
    published_at = None
    if ts:
        try:
            published_at = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
        except Exception:
            pass

    return Article(
        url=url,
        title=title,
        source=source,
        published_at=published_at,
        channel_id=channel_id,
        raw_text=message.get("text", ""),
    )


# ─────────────────────────────────────────────────────────────────
# MAIN FETCH FUNCTION
# ─────────────────────────────────────────────────────────────────

def fetch_and_filter(client: ClientConfig) -> FilterResult:
    """
    Fetch articles from all client Slack channels, apply all filters,
    return a FilterResult with status HAS_NEWS or NO_NEWS.

    This function reads Slack directly (NOT through Glean) because the
    Glean REST token scope does not include Slack message search.
    """
    slack = _get_slack_client()
    channel_ids = client.all_channel_ids

    if not channel_ids:
        print(f"[filters] {client.name}: no channel IDs configured")
        return FilterResult(
            status="NO_NEWS",
            articles=[],
            client_name=client.name,
            channels_checked=[],
            articles_before_filter=0,
            articles_after_filter=0,
        )

    raw_articles = []
    seen_urls = set()

    for channel_id in channel_ids:
        try:
            response = slack.conversations_history(
                channel=channel_id,
                limit=SLACK_HISTORY_LIMIT,
            )
            messages = response.get("messages", [])
            print(f"[filters] {client.name} | channel {channel_id}: {len(messages)} messages fetched")

            for msg in messages:
                # Date cutoff
                if not _is_within_cutoff(msg):
                    continue

                article = _extract_article_from_message(msg, channel_id)
                if not article:
                    continue

                # Dedup by URL
                url_key = article.url.rstrip("/").lower()
                if url_key in seen_urls:
                    continue
                seen_urls.add(url_key)

                # Blocked domain filter
                if _is_blocked(article.url):
                    continue

                raw_articles.append(article)

        except SlackApiError as e:
            print(f"[filters] Warning: Slack API error for channel {channel_id}: {e.response['error']}")
            continue

    # Sort by recency (most recent first)
    def sort_key(a: Article):
        try:
            return a.published_at or ""
        except Exception:
            return ""

    raw_articles.sort(key=sort_key, reverse=True)

    # Cap at MAX_ARTICLES — never send more than 20 to agents
    total_before_cap = len(raw_articles)
    raw_articles = raw_articles[:MAX_ARTICLES]

    status = "HAS_NEWS" if raw_articles else "NO_NEWS"

    print(f"[filters] {client.name}: {total_before_cap} articles found → {len(raw_articles)} after filter")

    return FilterResult(
        status=status,
        articles=raw_articles,
        client_name=client.name,
        channels_checked=channel_ids,
        articles_before_filter=total_before_cap,
        articles_after_filter=len(raw_articles),
    )


def articles_to_payload(articles: List[Article]) -> str:
    """
    Serialize article list to a clean JSON string for agent consumption.
    Agent 1 receives this string as part of its task description.

    IMPORTANT: takes list[Article] directly — pass filter_result.articles, not the FilterResult.
    Usage: payload = articles_to_payload(filter_result.articles)
    """
    articles_data = []
    for a in articles:
        articles_data.append({
            "url": a.url,
            "title": a.title,
            "source": a.source,
            "published_at": a.published_at,
        })

    return json.dumps({
        "article_count": len(articles_data),
        "articles": articles_data,
    }, indent=2)


# ─────────────────────────────────────────────────────────────────
# VALIDATION — Run directly to test
# python3 filters.py --client MDVIP
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from config import load_clients

    target = None
    if "--client" in sys.argv:
        idx = sys.argv.index("--client")
        if idx + 1 < len(sys.argv):
            target = sys.argv[idx + 1]

    clients = load_clients()
    if target:
        clients = [c for c in clients if c.name.lower() == target.lower()]
        if not clients:
            print(f"Client '{target}' not found. Available: {[c.name for c in load_clients()]}")
            sys.exit(1)

    for client in clients:
        print(f"\n{'='*60}")
        print(f"Testing: {client.name}")
        result = fetch_and_filter(client)
        payload = articles_to_payload(result)
        print(f"Status: {result.status.value}")
        print(f"Articles: {result.articles_after_filter}")
        if result.articles:
            print(f"First URL: {result.articles[0].url}")
        print(payload[:500])
