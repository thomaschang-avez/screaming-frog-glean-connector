"""
crew.py — AVENUE Z CREWAI TEMPLATE
Assembles the crew, runs it for one client, handles all output routing.

This is the orchestration layer. It imports from all other files,
runs the pipeline, and routes to exactly ONE of the four notification states.

CUSTOMIZATION CHECKLIST FOR NEW PROJECTS:
  [ ] Import your agents from agents.py (update build_agent_* names)
  [ ] Import your tasks from tasks.py (update build_task_* names)
  [ ] Update _notify_success() — what does the Slack message look like?
  [ ] Update _create_output_doc() — what goes in the Google Doc?
  [ ] Update the JSON parsing in _notify_success() to match tasks.py final schema
  [ ] Switch TEST_CHANNEL to client.output_channel_id when going to production
"""

import os
import json
import time
import traceback
from datetime import datetime
from dotenv import load_dotenv
from crewai import Crew, Process
from slack_sdk import WebClient
from google.oauth2.credentials import Credentials as GoogleCredentials
from googleapiclient.discovery import build as gdrive_build

from config import ClientConfig, load_clients
from filters import fetch_and_filter, articles_to_payload
from agents import (
    build_agent_one,
    build_agent_two,
    # build_agent_three,  # uncomment if using web supplement agent
    build_agent_four,
)
from tasks import (
    build_task_one,
    build_task_two,
    # build_task_three_supplement,
    build_task_four_final,
)

load_dotenv()

# ─────────────────────────────────────────────────────────────────
# CONSTANTS — UPDATE BEFORE GOING TO PRODUCTION
# ─────────────────────────────────────────────────────────────────

# ⚠️  PRODUCTION SWITCH: Replace TEST_CHANNEL with client.output_channel_id
TEST_CHANNEL   = os.environ.get("TEST_CHANNEL", "YOUR_TEST_CHANNEL_ID")
ERROR_CHANNEL  = os.environ.get("ERROR_CHANNEL", "YOUR_ERROR_CHANNEL_ID")
THOMAS_USER_ID = "U0AT132KJCD"    # Thomas's Slack user ID — pinged on errors

USE_TEST_CHANNEL = True  # ← FLIP TO FALSE FOR PRODUCTION


def _output_channel(client: ClientConfig) -> str:
    """Returns the correct Slack channel based on production/test mode."""
    if USE_TEST_CHANNEL:
        return TEST_CHANNEL
    return client.output_channel_id


# ─────────────────────────────────────────────────────────────────
# SLACK CLIENT
# ─────────────────────────────────────────────────────────────────

def _slack() -> WebClient:
    return WebClient(token=os.environ["SLACK_BOT_TOKEN"])


def _post_slack(channel: str, text: str, blocks: list = None) -> None:
    try:
        kwargs = {"channel": channel, "text": text}
        if blocks:
            kwargs["blocks"] = blocks
        _slack().chat_postMessage(**kwargs)
    except Exception as e:
        print(f"[crew] Slack post error: {e}")


# ─────────────────────────────────────────────────────────────────
# GOOGLE DOC CREATION
# Uses Application Default Credentials (ADC) — same pattern as auto-slide-decks.
# Creates a native Google Doc in the configured Google Drive account.
# ─────────────────────────────────────────────────────────────────

def _create_output_doc(client: ClientConfig, data: dict) -> str:
    """
    Create a formatted Google Doc with the crew's final output.
    Returns the URL of the created doc.

    UPDATE: customize the doc structure and HTML for your deliverable type.
    """
    try:
        # ADC credentials — written by main.py _bootstrap_adc() on Cloud Run, or from local gcloud auth
        SCOPES = ["https://www.googleapis.com/auth/drive.file"]
        ADC_PATH = os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
        creds = GoogleCredentials.from_authorized_user_file(ADC_PATH, scopes=SCOPES)
        drive = gdrive_build("drive", "v3", credentials=creds)

        # ── UPDATE: Build your HTML document structure ──
        today = datetime.now().strftime("%B %d, %Y")
        title = f"{client.name} — [DELIVERABLE TYPE] — {today}"

        html_parts = [
            f"<html><body>",
            f"<h1>{client.name} — [DELIVERABLE TYPE]</h1>",
            f"<p><em>Generated: {today}</em></p>",
            f"<hr>",
        ]

        items = data.get("items", [])
        if not items:
            html_parts.append("<p>No qualifying items this run.</p>")
        else:
            for i, item in enumerate(items, 1):
                html_parts.extend([
                    f"<h2>Item {i}: {item.get('headline', 'Untitled')}</h2>",
                    f"<p><strong>Score:</strong> {item.get('relevance_score', 'N/A')}/10</p>",
                    f"<p><strong>Source:</strong> <a href='{item.get('source_url', '')}'>",
                    f"{item.get('outlet', '')} — {item.get('publish_date', '')}</a></p>",
                    f"<p><strong>Client Angle:</strong> {item.get('client_angle', '')}</p>",
                    f"<p><strong>Talking Point:</strong> {item.get('talking_point', '')}</p>",
                    f"<h3>Contacts</h3>",
                ])
                for contact in item.get("contacts", []):
                    html_parts.append(
                        f"<p>{contact.get('name')} — {contact.get('beat')} at {contact.get('outlet')}</p>"
                    )

                deliverable = item.get("deliverable", {})
                if deliverable:
                    html_parts.extend([
                        f"<h3>Deliverable</h3>",
                        f"<p><strong>Subject:</strong> {deliverable.get('subject_line', '')}</p>",
                        f"<pre>{deliverable.get('body', '')}</pre>",
                    ])
                html_parts.append("<hr>")

        html_parts.append("</body></html>")
        html_content = "\n".join(html_parts)

        # Upload as native Google Doc via HTML conversion
        from googleapiclient.http import MediaInMemoryUpload
        media = MediaInMemoryUpload(
            html_content.encode("utf-8"),
            mimetype="text/html",
            resumable=False,
        )
        metadata = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",
        }
        result = drive.files().create(body=metadata, media_body=media, fields="id,webViewLink").execute()
        doc_url = result.get("webViewLink", "")
        print(f"[crew] Google Doc created: {doc_url}")
        return doc_url

    except Exception as e:
        print(f"[crew] Google Doc creation error: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────
# FOUR NOTIFICATION STATES
# Every client run produces EXACTLY ONE Slack message.
# ─────────────────────────────────────────────────────────────────

def _notify_success(client: ClientConfig, crew_output: str) -> None:
    """
    SUCCESS: Items found AND qualified. Post results + Google Doc link.
    UPDATE: customize the Slack message format and what goes in the doc.
    """
    # Extract JSON using index/rindex (production pattern — not regex)
    json_match = None
    try:
        start = crew_output.index("{")
        end = crew_output.rindex("}") + 1
        json_match = crew_output[start:end]
        json.loads(json_match)  # validate
    except (ValueError, json.JSONDecodeError):
        json_match = None

    if not json_match:
        _notify_error(client, f"Crew returned non-JSON output: {crew_output[:500]}")
        return

    try:
        data = json.loads(json_match)
    except Exception:
        _notify_error(client, f"Could not parse crew output as JSON: {crew_output[:500]}")
        return

    items = data.get("items", [])
    if not items:
        _notify_no_qualifying(client)
        return

    # Create Google Doc first
    doc_url = _create_output_doc(client, data)

    # Build Slack message
    lines = [f"✅ *{client.name}* — {len(items)} qualifying item(s) found\n"]
    for item in items:
        score   = item.get("relevance_score", "?")
        headline = item.get("headline", "No headline")[:80]
        outlet  = item.get("outlet", "Unknown outlet")
        contacts = item.get("contacts", [])
        contact_names = ", ".join(c.get("name", "") for c in contacts[:3])

        lines.append(f"*Score: {score}/10* | {outlet}")
        lines.append(f"_{headline}_")
        if contact_names:
            lines.append(f"Contacts: {contact_names}")
        lines.append("")

    if doc_url:
        lines.append(f"📄 <{doc_url}|View Full [DELIVERABLE TYPE]>")

    _post_slack(_output_channel(client), "\n".join(lines))


def _notify_no_qualifying(client: ClientConfig) -> None:
    """
    NO_QUALIFYING_ITEMS: Data found but nothing met the quality bar.
    The quality filter is working. This is correct behavior, not a failure.
    """
    msg = (
        f"🟡 *{client.name}* — Items found but none met the quality threshold today.\n"
        f"_Quality filter working correctly — no action needed._"
    )
    _post_slack(_output_channel(client), msg)


def _notify_no_data(client: ClientConfig) -> None:
    """
    NO_DATA: No input data found in the date window after filtering.
    Check source system (e.g. Muck Rack alerts) for this client.
    """
    msg = (
        f"📭 *{client.name}* — No new data found in the past {7} days.\n"
        f"_Check source alerts/configuration for this client if this recurs._"
    )
    _post_slack(_output_channel(client), msg)


def _notify_error(client: ClientConfig, error: str) -> None:
    """
    ERROR: Pipeline failure at any point.
    Always routes to ERROR_CHANNEL. Client channel never sees infrastructure errors.
    """
    msg = (
        f"🔴 *Pipeline Error — {client.name}*\n"
        f"<@{THOMAS_USER_ID}> pipeline failed for this client.\n\n"
        f"```{error[:500]}```"
    )
    _post_slack(ERROR_CHANNEL, msg)


# ─────────────────────────────────────────────────────────────────
# MAIN PIPELINE — ONE CLIENT
# ─────────────────────────────────────────────────────────────────

def run_client(client: ClientConfig) -> None:
    """
    Full pipeline for one client:
    1. Fetch and filter input data
    2. Build agents with correct LLM modes
    3. Assemble and run crew
    4. Route to correct notification state
    """
    print(f"\n{'='*60}")
    print(f"Running pipeline for: {client.name}")
    print(f"{'='*60}")

    try:
        # ── STEP 1: Fetch and filter input data ──
        filter_result = fetch_and_filter(client)

        if filter_result.status == "NO_NEWS":           # string comparison — not Enum
            print(f"[crew] {client.name}: NO_DATA")
            _notify_no_data(client)
            return

        data_payload = articles_to_payload(filter_result.articles)  # pass .articles, not FilterResult

        # ── STEP 2: Build agents (all share same Glean endpoint — no separate LLM modes) ──
        agent1 = build_agent_one(client)
        agent2 = build_agent_two(client)
        # agent3 = build_agent_three(client)  # web supplement — uncomment if needed
        agent4 = build_agent_four(client)

        # ── STEP 3: Build tasks WITHOUT context ──
        task1 = build_task_one(agent1, client, data_payload)
        task2 = build_task_two(agent2, client)
        # task3 = build_task_three_supplement(agent3, client)
        task4 = build_task_four_final(agent4, client)

        # ── STEP 4: Chain context AFTER building all tasks ──
        task2.context = [task1]
        task4.context = [task1, task2]              # add task3 here if using: [task1, task2, task3]

        # ── STEP 5: Assemble and run crew ──
        crew = Crew(
            agents=[agent1, agent2, agent4],        # add agent3 if using
            tasks=[task1, task2, task4],             # add task3 if using
            process=Process.sequential,
            verbose=False,                           # False in production
        )

        result = crew.kickoff()
        output = str(result)

        print(f"[crew] {client.name}: crew completed")

        # ── STEP 6: Route to notification state ──
        # Check if the output signals no qualifying items
        try:
            data = json.loads(output)
            if data.get("qualifying_count", 1) == 0 or not data.get("items"):
                _notify_no_qualifying(client)
                return
        except Exception:
            pass  # If we can't parse, try success route and let it handle the error

        _notify_success(client, output)

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        print(f"[crew] ERROR for {client.name}: {error_msg}")
        _notify_error(client, error_msg)


# ─────────────────────────────────────────────────────────────────
# RUN ALL CLIENTS
# ─────────────────────────────────────────────────────────────────

def run_all_clients(client_filter: str = None) -> None:
    """
    Loop through all clients. Accepts optional name filter for single-client testing.
    Adds sleep between clients to respect Glean Chat API rate limits (0.5 req/sec).
    """
    clients = load_clients()

    if client_filter:
        clients = [c for c in clients if c.name.lower() == client_filter.lower()]
        if not clients:
            print(f"Client '{client_filter}' not found.")
            return

    print(f"Running pipeline for {len(clients)} client(s)...")

    for i, client in enumerate(clients):
        run_client(client)
        if i < len(clients) - 1:
            time.sleep(2)  # Rate limit buffer between clients — increase to 5 if 429s appear

    print(f"\n✅ Pipeline complete. {len(clients)} clients processed.")
