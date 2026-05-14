"""
main.py — SCREAMING FROG ZOS
Full pipeline entry point. Parse → Save → Glean → Slack. One command.

Usage:
  python3 main.py --file ~/Downloads/export.csv --client extend
  python3 main.py --file ~/Downloads/export.csv --client extend --save
  python3 main.py --file ~/Downloads/export.csv --client extend --save --alert
  python3 main.py --file ~/Downloads/export.csv --client extend --save --push --alert
  python3 main.py --dry-run
"""

import os
import sys
import json
import argparse
import traceback
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

REQUIRED_ENV_VARS = [
    "GLEAN_API_TOKEN",
    "GLEAN_SERVER_URL",
    "GLEAN_INSTANCE",
    "SLACK_BOT_TOKEN",
]


# ─────────────────────────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────────────────────────

def validate_env() -> bool:
    missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        print(f"❌ Missing env vars: {', '.join(missing)}")
        print("   Check your .env file.")
        return False
    return True


# ─────────────────────────────────────────────────────────────────
# DRY RUN
# ─────────────────────────────────────────────────────────────────

def dry_run():
    from config import CLIENTS, XPOINT_CHECKS, USE_TEST_CHANNEL, TEST_CHANNEL
    print("\n" + "=" * 60)
    print("  SCREAMING FROG ZOS — DRY RUN")
    print("=" * 60)
    print(f"\n  {len(CLIENTS)} clients configured:")
    for c in CLIENTS:
        status = "READY" if c.sheet_id != "PENDING" else "PENDING"
        print(f"  [{status:>7}]  {c.name:<35} {c.url}")
    print(f"\n  {len(XPOINT_CHECKS)} X-Point checks loaded")
    print(f"  Mode: {'TEST → ' + TEST_CHANNEL if USE_TEST_CHANNEL else 'PRODUCTION'}")
    print(f"\n  Output directory: output/")
    snapshots = list(Path("output").glob("*.json")) if Path("output").exists() else []
    snapshots = [s for s in snapshots if "_diff" not in s.name]
    print(f"  Existing snapshots: {len(snapshots)}")
    for s in sorted(snapshots):
        print(f"    {s.name}")
    print()


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("  AVENUE Z — SCREAMING FROG ZOS PIPELINE")
    print("=" * 60 + "\n")

    parser = argparse.ArgumentParser(description="Screaming Frog ZOS Pipeline")
    parser.add_argument("--file", help="Path to Screaming Frog CSV export")
    parser.add_argument("--client", help="Client name or slug (e.g. extend)")
    parser.add_argument("--save", action="store_true", help="Save snapshot to output/")
    parser.add_argument("--push", action="store_true", help="Push snapshot to Glean")
    parser.add_argument("--alert", action="store_true", help="Post Slack alert after run")
    parser.add_argument("--dry-run", action="store_true", help="Validate config only")
    args = parser.parse_args()

    if not validate_env():
        sys.exit(1)

    if args.dry_run:
        dry_run()
        return

    if not args.file:
        print("❌ --file is required. Example:")
        print('   python3 main.py --file ~/Downloads/export.csv --client extend --save --push --alert')
        sys.exit(1)

    if not args.client:
        print("❌ --client is required. Example: --client extend")
        sys.exit(1)

    # ── STEP 1: Parse ──
    print(f"  [1/4] Parsing CSV: {args.file}")
    try:
        from parser import load_csv_from_file, filter_html_rows, parse, save_result, print_summary
        rows = load_csv_from_file(args.file)
        html_rows = filter_html_rows(rows)
        result = parse(html_rows, client_name=args.client)
        print_summary(result)
    except Exception as e:
        print(f"  ❌ Parse failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    # ── STEP 2: Save snapshot ──
    snapshot_path = None
    if args.save:
        print(f"  [2/4] Saving snapshot...")
        try:
            client_slug = args.client.lower().replace(" ", "-")
            snapshot_path = save_result(result, client_slug)
            print(f"  Saved to: {snapshot_path}")
        except Exception as e:
            print(f"  ❌ Save failed: {e}")
            traceback.print_exc()
    else:
        print(f"  [2/4] Skipping save (use --save to persist snapshot)")

    # ── STEP 3: Push to Glean ──
    if args.push:
        if not snapshot_path:
            print(f"  [3/4] Skipping Glean push — no snapshot saved (use --save with --push)")
        else:
            print(f"  [3/4] Pushing to Glean...")
            try:
                from glean_push import push_snapshot
                snapshot_data = json.loads(Path(snapshot_path).read_text())
                push_snapshot(snapshot_data)
            except Exception as e:
                print(f"  ❌ Glean push failed: {e}")
                traceback.print_exc()
    else:
        print(f"  [3/4] Skipping Glean push (use --push to index in ZOS)")

    # ── STEP 4: Slack alert ──
    if args.alert:
        print(f"  [4/4] Sending Slack alert...")
        try:
            from slack_alert import send_alert
            client_slug = args.client.lower()

            # Try diff first (if 2+ snapshots exist), else first-run format
            from diff import find_snapshots, load_snapshot, diff_snapshots
            snapshots = find_snapshots(client_slug)
            if len(snapshots) >= 2:
                old = load_snapshot(snapshots[-2])
                new = load_snapshot(snapshots[-1])
                diff = diff_snapshots(old, new)
                send_alert(client_slug, diff=diff)
            else:
                # First run — use snapshot format
                if snapshot_path:
                    snapshot_data = json.loads(Path(snapshot_path).read_text())
                    send_alert(client_slug, snapshot=snapshot_data)
                else:
                    print("  ⚠️  No snapshot to alert on — use --save with --alert")
        except Exception as e:
            print(f"  ❌ Slack alert failed: {e}")
            traceback.print_exc()
    else:
        print(f"  [4/4] Skipping Slack alert (use --alert to notify team)")

    print()
    print("  ✅ Pipeline complete.")
    print()
    print("  Next run commands:")
    client_slug = args.client.lower()
    print(f"    Full run:  python3 main.py --file ~/Downloads/export.csv --client {client_slug} --save --push --alert")
    print(f"    Diff only: python3 diff.py --client {client_slug}")
    print(f"    Alert only: python3 slack_alert.py --client {client_slug}")
    print(f"    Glean only: python3 glean_push.py --client {client_slug}")
    print()


if __name__ == "__main__":
    main()
