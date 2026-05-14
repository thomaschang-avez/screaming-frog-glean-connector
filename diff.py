"""
diff.py — SCREAMING FROG ZOS
Compare two audit snapshots for the same client. Shows what's new, what's fixed, what changed.

Usage:
  python3 diff.py --client extend
  python3 diff.py --client extend --old output/2026-04-01_extend.json --new output/2026-05-07_extend.json
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict

OUTPUT_DIR = Path("output")


# ─────────────────────────────────────────────────────────────────
# LOAD SNAPSHOTS
# ─────────────────────────────────────────────────────────────────

def find_snapshots(client: str):
    """Find all snapshots for a client, sorted oldest → newest."""
    files = sorted(OUTPUT_DIR.glob(f"*_{client}.json"))
    return files


def load_snapshot(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────
# DIFF LOGIC
# ─────────────────────────────────────────────────────────────────

def issues_by_key(issues: list) -> dict:
    """Index issues by (check_id, url) for comparison."""
    index = {}
    for issue in issues:
        key = (issue["check_id"], issue["url"])
        index[key] = issue
    return index


def diff_snapshots(old: dict, new: dict) -> dict:
    old_index = issues_by_key(old["issues"])
    new_index = issues_by_key(new["issues"])

    old_keys = set(old_index.keys())
    new_keys = set(new_index.keys())

    fixed = old_keys - new_keys          # existed before, gone now
    introduced = new_keys - old_keys     # new issues not in old snapshot
    persisted = old_keys & new_keys      # still present in both

    # Summarize by severity
    def severity_counts(keys, index):
        counts = defaultdict(int)
        for k in keys:
            counts[index[k]["severity"]] += 1
        return dict(counts)

    return {
        "old_date": old["crawl_date"],
        "new_date": new["crawl_date"],
        "client": new["client_name"],
        "old_total": len(old_keys),
        "new_total": len(new_keys),
        "fixed_count": len(fixed),
        "introduced_count": len(introduced),
        "persisted_count": len(persisted),
        "fixed_by_severity": severity_counts(fixed, old_index),
        "introduced_by_severity": severity_counts(introduced, new_index),
        "fixed_issues": [old_index[k] for k in sorted(fixed)],
        "introduced_issues": [new_index[k] for k in sorted(introduced)],
        "persisted_issues": [new_index[k] for k in sorted(persisted)],
    }


# ─────────────────────────────────────────────────────────────────
# PRINT REPORT
# ─────────────────────────────────────────────────────────────────

SEVERITY_ORDER = ["Critical", "High", "Medium", "Low"]

def print_diff_report(diff: dict):
    client = diff["client"].upper()
    delta = diff["new_total"] - diff["old_total"]
    delta_str = f"+{delta}" if delta > 0 else str(delta)

    print()
    print("=" * 60)
    print(f"  {client} — AUDIT DIFF")
    print(f"  {diff['old_date']}  →  {diff['new_date']}")
    print("=" * 60)
    print()
    print(f"  Total issues:  {diff['old_total']} → {diff['new_total']}  ({delta_str})")
    print()

    # Fixed
    print(f"  ✅ FIXED: {diff['fixed_count']} issues resolved")
    for sev in SEVERITY_ORDER:
        count = diff["fixed_by_severity"].get(sev, 0)
        if count:
            print(f"     {sev}: {count}")

    print()

    # Introduced
    print(f"  🔴 NEW: {diff['introduced_count']} issues introduced")
    for sev in SEVERITY_ORDER:
        count = diff["introduced_by_severity"].get(sev, 0)
        if count:
            print(f"     {sev}: {count}")

    print()
    print(f"  ⏳ PERSISTED: {diff['persisted_count']} issues unchanged")
    print()

    # Show top 10 new critical/high issues
    new_issues = diff["introduced_issues"]
    priority_new = [i for i in new_issues if i["severity"] in ("Critical", "High")]
    if priority_new:
        print(f"  TOP NEW CRITICAL/HIGH ISSUES (showing up to 10):")
        print()
        for issue in priority_new[:10]:
            print(f"  [{issue['severity'].upper()}] {issue['check_name']}")
            print(f"  URL: {issue['url']}")
            if issue.get("detail"):
                print(f"  Detail: {issue['detail']}")
            print()

    # Show top 10 fixed critical/high issues
    fixed_issues = diff["fixed_issues"]
    priority_fixed = [i for i in fixed_issues if i["severity"] in ("Critical", "High")]
    if priority_fixed:
        print(f"  TOP FIXED CRITICAL/HIGH ISSUES (showing up to 10):")
        print()
        for issue in priority_fixed[:10]:
            print(f"  [{issue['severity'].upper()}] {issue['check_name']}")
            print(f"  URL: {issue['url']}")
            print()

    print("=" * 60)
    print()


# ─────────────────────────────────────────────────────────────────
# SAVE DIFF
# ─────────────────────────────────────────────────────────────────

def save_diff(diff: dict, client: str):
    today = datetime.now().strftime("%Y-%m-%d")
    path = OUTPUT_DIR / f"{today}_{client}_diff.json"
    with open(path, "w") as f:
        json.dump(diff, f, indent=2)
    print(f"  Diff saved to: {path}")


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Diff two Screaming Frog audit snapshots")
    parser.add_argument("--client", required=True, help="Client name (e.g. extend)")
    parser.add_argument("--old", help="Path to older snapshot JSON (optional — auto-detects)")
    parser.add_argument("--new", help="Path to newer snapshot JSON (optional — auto-detects)")
    parser.add_argument("--save", action="store_true", help="Save diff result to output/")
    args = parser.parse_args()

    client = args.client.lower()

    if args.old and args.new:
        old_path = Path(args.old)
        new_path = Path(args.new)
    else:
        snapshots = find_snapshots(client)
        if len(snapshots) < 2:
            print(f"  Need at least 2 snapshots for {client} to diff.")
            print(f"  Found: {[str(s) for s in snapshots]}")
            print(f"  Run parser.py --save to build more snapshots first.")
            sys.exit(1)
        old_path = snapshots[-2]
        new_path = snapshots[-1]

    print(f"  Comparing:")
    print(f"    OLD: {old_path}")
    print(f"    NEW: {new_path}")

    old = load_snapshot(old_path)
    new = load_snapshot(new_path)

    diff = diff_snapshots(old, new)
    print_diff_report(diff)

    if args.save:
        save_diff(diff, client)


if __name__ == "__main__":
    main()
