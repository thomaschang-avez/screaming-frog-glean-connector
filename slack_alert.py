"""
slack_alert.py — SCREAMING FROG ZOS
Posts a diff summary to Slack after each audit run.

Usage:
  python3 slack_alert.py --client extend
  python3 slack_alert.py --client extend --channel YOUR_CHANNEL_ID

Called automatically by diff.py when --alert flag is passed:
  python3 diff.py --client extend --alert
"""

import os
import json
import argparse
import httpx
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

from config import SLACK_BOT_TOKEN, USE_TEST_CHANNEL, TEST_CHANNEL, ERROR_CHANNEL, CLIENTS, get_client

load_dotenv()

OUTPUT_DIR = Path("output")
SEVERITY_ORDER = ["Critical", "High", "Medium", "Low"]
SEVERITY_EMOJI = {
    "Critical": "🔴",
    "High": "🟠",
    "Medium": "🟡",
    "Low": "⚪",
}


# ─────────────────────────────────────────────────────────────────
# SLACK POST
# ─────────────────────────────────────────────────────────────────

def post_to_slack(channel: str, text: str) -> bool:
    """Post a message to Slack. Returns True on success."""
    try:
        resp = httpx.post(
            "https://slack.com/api/chat.postMessage",
            json={"channel": channel, "text": text, "mrkdwn": True},
            headers={
                "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        data = resp.json()
        if data.get("ok"):
            print(f"  [slack] Posted to {channel}")
            return True
        else:
            print(f"  [slack] Error: {data.get('error')}")
            return False
    except Exception as e:
        print(f"  [slack] Exception: {e}")
        return False


# ─────────────────────────────────────────────────────────────────
# FORMAT DIFF ALERT
# ─────────────────────────────────────────────────────────────────

def format_diff_alert(diff: dict) -> str:
    """Format a diff result into a Slack message."""
    client = diff["client"]
    old_date = diff["old_date"]
    new_date = diff["new_date"]
    old_total = diff["old_total"]
    new_total = diff["new_total"]
    delta = new_total - old_total
    delta_str = f"+{delta}" if delta > 0 else str(delta)
    delta_emoji = "📈" if delta > 0 else "📉" if delta < 0 else "➡️"

    fixed_count = diff["fixed_count"]
    introduced_count = diff["introduced_count"]
    persisted_count = diff["persisted_count"]

    lines = [
        f"*🔍 Screaming Frog Audit — {client}*",
        f"_{old_date} → {new_date}_",
        "",
        f"*Total Issues:* {old_total} → {new_total} ({delta_str}) {delta_emoji}",
        f"✅ Fixed: *{fixed_count}* | 🔴 New: *{introduced_count}* | ⏳ Persisted: *{persisted_count}*",
    ]

    # Fixed by severity
    if fixed_count > 0:
        fixed_parts = []
        for sev in SEVERITY_ORDER:
            count = diff["fixed_by_severity"].get(sev, 0)
            if count:
                fixed_parts.append(f"{SEVERITY_EMOJI[sev]} {sev}: {count}")
        if fixed_parts:
            lines.append(f"\n*Fixed:* {' | '.join(fixed_parts)}")

    # New by severity
    if introduced_count > 0:
        new_parts = []
        for sev in SEVERITY_ORDER:
            count = diff["introduced_by_severity"].get(sev, 0)
            if count:
                new_parts.append(f"{SEVERITY_EMOJI[sev]} {sev}: {count}")
        if new_parts:
            lines.append(f"*New:* {' | '.join(new_parts)}")

    # Top 5 new critical/high issues
    priority_new = [
        i for i in diff.get("introduced_issues", [])
        if i["severity"] in ("Critical", "High")
    ]
    if priority_new:
        lines.append(f"\n*Top New Issues (Critical/High):*")
        for issue in priority_new[:5]:
            emoji = SEVERITY_EMOJI.get(issue["severity"], "•")
            url_short = issue["url"][:80] + "…" if len(issue["url"]) > 80 else issue["url"]
            lines.append(f"{emoji} {issue['check_name']}")
            lines.append(f"   `{url_short}`")

    lines.append("")
    lines.append(f"_Run `python3 diff.py --client {client.lower()}` for full report_")

    return "\n".join(lines)


def format_first_audit_alert(snapshot: dict) -> str:
    """Format a first-run audit (no diff available) into a Slack message."""
    client = snapshot["client_name"]
    crawl_date = snapshot["crawl_date"]
    total_urls = snapshot["total_urls"]
    html_urls = snapshot["html_urls"]

    # Count by severity
    severity_counts = defaultdict(int)
    for issue in snapshot.get("issues", []):
        severity_counts[issue["severity"]] += 1

    total_issues = sum(severity_counts.values())

    lines = [
        f"*🔍 Screaming Frog Audit — {client}* (First Run)",
        f"_{crawl_date}_",
        "",
        f"*URLs Crawled:* {total_urls} total | {html_urls} HTML pages",
        f"*Issues Found:* {total_issues}",
    ]

    for sev in SEVERITY_ORDER:
        count = severity_counts.get(sev, 0)
        if count:
            lines.append(f"  {SEVERITY_EMOJI[sev]} {sev}: {count}")

    # Top 5 critical issues
    critical_issues = [
        i for i in snapshot.get("issues", [])
        if i["severity"] == "Critical"
    ]
    if critical_issues:
        lines.append(f"\n*Top Critical Issues:*")
        seen_checks = set()
        for issue in critical_issues:
            if issue["check_name"] not in seen_checks:
                seen_checks.add(issue["check_name"])
                lines.append(f"🔴 {issue['check_name']} ({sum(1 for i in critical_issues if i['check_name'] == issue['check_name'])} URLs)")
            if len(seen_checks) >= 5:
                break

    lines.append("")
    lines.append(f"_Snapshot saved. Run next month to start tracking changes._")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# FIND LATEST DIFF OR SNAPSHOT
# ─────────────────────────────────────────────────────────────────

def load_latest_diff(client_slug: str) -> dict | None:
    """Load the most recent diff JSON for a client."""
    diffs = sorted(OUTPUT_DIR.glob(f"*_{client_slug}_diff.json"))
    if not diffs:
        return None
    with open(diffs[-1]) as f:
        return json.load(f)


def load_latest_snapshot(client_slug: str) -> dict | None:
    """Load the most recent snapshot JSON for a client."""
    snapshots = sorted(OUTPUT_DIR.glob(f"*_{client_slug}.json"))
    if not snapshots:
        return None
    with open(snapshots[-1]) as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────
# RESOLVE OUTPUT CHANNEL
# ─────────────────────────────────────────────────────────────────

def resolve_channel(client_slug: str, override: str = None) -> str:
    """Return the correct Slack channel for this client."""
    if override:
        return override
    if USE_TEST_CHANNEL:
        return TEST_CHANNEL
    client = get_client(client_slug)
    if client and client.output_channel_id != "PENDING":
        return client.output_channel_id
    return TEST_CHANNEL


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

def send_alert(client_slug: str, channel_override: str = None, diff: dict = None, snapshot: dict = None) -> bool:
    """
    Send a Slack alert for a client.
    Pass diff= for a diff alert, snapshot= for a first-run alert.
    If neither is passed, auto-loads the latest diff or snapshot from output/.
    """
    channel = resolve_channel(client_slug, channel_override)

    if diff is None and snapshot is None:
        diff = load_latest_diff(client_slug)

    if diff:
        message = format_diff_alert(diff)
    elif snapshot:
        message = format_first_audit_alert(snapshot)
    else:
        # Try loading latest snapshot as first-run alert
        snapshot = load_latest_snapshot(client_slug)
        if snapshot:
            message = format_first_audit_alert(snapshot)
        else:
            print(f"  [slack] No diff or snapshot found for {client_slug}")
            return False

    return post_to_slack(channel, message)


def main():
    parser = argparse.ArgumentParser(description="Post Screaming Frog audit alert to Slack")
    parser.add_argument("--client", required=True, help="Client slug (e.g. extend)")
    parser.add_argument("--channel", help="Override Slack channel ID")
    parser.add_argument("--first-run", action="store_true", help="Force first-run format (no diff)")
    args = parser.parse_args()

    client_slug = args.client.lower()

    if args.first_run:
        snapshot = load_latest_snapshot(client_slug)
        if not snapshot:
            print(f"  No snapshot found for {client_slug}. Run parser.py --save first.")
            return
        success = send_alert(client_slug, channel_override=args.channel, snapshot=snapshot)
    else:
        success = send_alert(client_slug, channel_override=args.channel)

    if success:
        print(f"  Alert sent for {client_slug}")
    else:
        print(f"  Alert failed for {client_slug}")


if __name__ == "__main__":
    main()
