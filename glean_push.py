"""
glean_push.py — SCREAMING FROG ZOS
Pushes audit snapshots to Glean as indexed documents so the team can query
technical audit history in natural language via ZOS.

Usage:
  python3 glean_push.py --client extend
  python3 glean_push.py --all

NOTE: Uses GLEAN_INDEXING_API_TOKEN (separate from Client API token).
      Datasource "screamingfrogaudits" must be created in Glean Admin Console first.
"""

import os
import json
import argparse
import httpx
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

from config import CLIENTS, get_client, OUTPUT_DIR, SEVERITY_ORDER

OUTPUT_DIR = Path(OUTPUT_DIR)

# Indexing API — separate token, separate base URL, NO X-Glean-ActAs
GLEAN_INDEXING_TOKEN = os.environ.get("GLEAN_INDEXING_API_TOKEN", "")
GLEAN_INDEX_URL = f"{os.environ.get('GLEAN_SERVER_URL', 'https://your-company-be.glean.com')}/api/index/v1/indexdocument"
GLEAN_DATASOURCE = "screamingfrogaudits"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {GLEAN_INDEXING_TOKEN}",
        "Content-Type": "application/json",
    }


def snapshot_to_document(snapshot: dict) -> dict:
    client_name = snapshot["client_name"]
    crawl_date = snapshot["crawl_date"]
    total_urls = snapshot["total_urls"]
    html_urls = snapshot["html_urls"]
    issues = snapshot.get("issues", [])

    severity_counts = defaultdict(int)
    by_category = defaultdict(list)
    for issue in issues:
        severity_counts[issue["severity"]] += 1
        by_category[issue["category"]].append(issue)

    total_issues = sum(severity_counts.values())

    lines = [
        f"SCREAMING FROG TECHNICAL AUDIT — {client_name.upper()}",
        f"Crawl Date: {crawl_date}",
        f"URLs Crawled: {total_urls} total | {html_urls} HTML pages",
        f"Total Issues: {total_issues}", "",
        "SEVERITY SUMMARY",
    ]
    for sev in SEVERITY_ORDER:
        lines.append(f"  {sev}: {severity_counts.get(sev, 0)}")
    lines.append("")
    lines.append("ISSUES BY CATEGORY")
    for category, cat_issues in sorted(by_category.items()):
        lines.append(f"\n{category.upper().replace('_', ' ')} ({len(cat_issues)} issues)")
        by_check = defaultdict(list)
        for issue in cat_issues:
            by_check[issue["check_name"]].append(issue["url"])
        for check_name, urls in sorted(by_check.items()):
            lines.append(f"  • {check_name} — {len(urls)} URL(s)")
            for url in urls[:3]:
                lines.append(f"    - {url}")
            if len(urls) > 3:
                lines.append(f"    ... and {len(urls) - 3} more")
    lines.append("")
    critical_issues = [i for i in issues if i["severity"] == "Critical"]
    if critical_issues:
        lines.append("CRITICAL ISSUES — FULL LIST")
        for issue in critical_issues:
            lines.append(f"  [{issue['check_name']}] {issue['url']}")

    # Doc ID — alphanumeric only per Glean spec
    doc_id = f"sfaudit{client_name.lower().replace(' ', '').replace('-', '')}{crawl_date.replace('-', '')}"

    return {
        "document": {
            "datasource": GLEAN_DATASOURCE,
            "id": doc_id,
            "title": f"Screaming Frog Audit — {client_name} — {crawl_date}",
            "viewURL": "https://github.com/Avenue-Z/avenue-z-screaming-frog-zos/tree/main/output",
            "body": {
                "mimeType": "text/plain",
                "textContent": "\n".join(lines),
            },
            "permissions": {"allowAnonymousAccess": True},
            "updatedAt": int(__import__("datetime").datetime.strptime(crawl_date, "%Y-%m-%d").timestamp()),
        },
    }


def push_snapshot(snapshot: dict) -> bool:
    if not GLEAN_INDEXING_TOKEN:
        print("  [glean] ❌ GLEAN_INDEXING_API_TOKEN not set in .env")
        return False

    client_name = snapshot["client_name"]
    crawl_date = snapshot["crawl_date"]
    payload = snapshot_to_document(snapshot)

    try:
        resp = httpx.post(GLEAN_INDEX_URL, json=payload, headers=_headers(), timeout=30)
        if resp.status_code in (200, 202):
            print(f"  [glean] ✅ Pushed: {client_name} ({crawl_date})")
            return True
        else:
            print(f"  [glean] ❌ Failed: {client_name} — HTTP {resp.status_code}")
            print(f"  [glean] Response: {resp.text[:500]}")
            return False
    except Exception as e:
        print(f"  [glean] ❌ Exception: {e}")
        return False


def load_latest_snapshot(client_slug: str) -> dict | None:
    snapshots = sorted(OUTPUT_DIR.glob(f"*_{client_slug}.json"))
    if not snapshots:
        return None
    with open(snapshots[-1]) as f:
        return json.load(f)


def load_all_latest_snapshots() -> list[dict]:
    snapshots = []
    seen_clients = set()
    for path in sorted(OUTPUT_DIR.glob("*.json"), reverse=True):
        if "_diff" in path.name:
            continue
        with open(path) as f:
            try:
                data = json.load(f)
                slug = data.get("client_name", "").lower().replace(" ", "-")
                if slug and slug not in seen_clients:
                    seen_clients.add(slug)
                    snapshots.append(data)
            except Exception:
                continue
    return snapshots


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", help="Client slug (e.g. extend)")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--file", help="Specific snapshot JSON file")
    args = parser.parse_args()

    if args.file:
        with open(args.file) as f:
            push_snapshot(json.load(f))
    elif args.client:
        snapshot = load_latest_snapshot(args.client.lower())
        if not snapshot:
            print(f"  No snapshot found for {args.client}. Run parser.py --save first.")
            return
        push_snapshot(snapshot)
    elif args.all:
        snapshots = load_all_latest_snapshots()
        if not snapshots:
            print("  No snapshots found. Run parser.py --save first.")
            return
        success = sum(1 for s in snapshots if push_snapshot(s))
        print(f"\n  Done: {success}/{len(snapshots)} pushed.")
    else:
        print("  Provide --client, --all, or --file")


if __name__ == "__main__":
    main()
