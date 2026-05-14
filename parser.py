"""
parser.py — Screaming Frog X-Point Framework Parser
Reads a Screaming Frog CSV (local file or Google Sheets), runs all 48 X-Point
checks against every row, returns flagged issues sorted by severity.

Usage:
  python3 parser.py --file path/to/export.csv
  python3 parser.py --file path/to/export.csv --client extend
  python3 parser.py --sheet SHEET_ID --client extend
"""

import csv
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

from config import (
    CLIENTS, GOOGLE_CREDENTIALS_PATH, GOOGLE_SCOPES, OUTPUT_DIR,
    SEVERITY_ORDER, XPOINT_CHECKS, CATEGORIES, CRITICAL, HIGH, MEDIUM, LOW,
    SF, ClientConfig, get_client,
)

load_dotenv()


# ─────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────

@dataclass
class Issue:
    check_id: str
    check_name: str
    category: str
    severity: str
    url: str
    detail: str = ""


@dataclass
class ParseResult:
    client_name: str
    crawl_date: str
    total_urls: int
    html_urls: int
    issues: list = field(default_factory=list)

    @property
    def critical_count(self):
        return sum(1 for i in self.issues if i.severity == CRITICAL)

    @property
    def high_count(self):
        return sum(1 for i in self.issues if i.severity == HIGH)

    @property
    def medium_count(self):
        return sum(1 for i in self.issues if i.severity == MEDIUM)

    @property
    def low_count(self):
        return sum(1 for i in self.issues if i.severity == LOW)

    @property
    def issues_by_severity(self):
        return sorted(self.issues, key=lambda i: SEVERITY_ORDER[i.severity])

    @property
    def issues_by_check(self):
        grouped = {}
        for issue in self.issues:
            grouped.setdefault(issue.check_id, []).append(issue)
        return grouped


# ─────────────────────────────────────────────────────────────────
# CSV LOADING
# ─────────────────────────────────────────────────────────────────

def load_csv_from_file(filepath: str) -> list:
    """Load rows from a local Screaming Frog CSV export."""
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def load_csv_from_sheet(sheet_id: str) -> list:
    """Load rows from a Google Sheet (Screaming Frog export uploaded to Sheets)."""
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=GOOGLE_SCOPES)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(sheet_id)

    try:
        ws = sheet.worksheet("Internal All")
    except Exception:
        try:
            ws = sheet.worksheet("Internal - All")
        except Exception:
            ws = sheet.get_worksheet(0)

    rows = ws.get_all_records(default_blank="")
    return rows


def filter_html_rows(rows: list) -> list:
    """Return only HTML page rows — excludes images, CSS, JS, PDFs, etc."""
    html_rows = []
    for row in rows:
        content_type = str(row.get(SF.CONTENT_TYPE, "")).lower()
        if "text/html" in content_type:
            html_rows.append(row)
    return html_rows


# ─────────────────────────────────────────────────────────────────
# VALUE HELPERS
# ─────────────────────────────────────────────────────────────────

def _str(row: dict, col: str) -> str:
    return str(row.get(col, "") or "").strip()


def _int(row: dict, col: str) -> Optional[int]:
    val = _str(row, col)
    if not val:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _float(row: dict, col: str) -> Optional[float]:
    val = _str(row, col)
    if not val:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _is_empty(val: str) -> bool:
    return not val or val.strip() == ""


# ─────────────────────────────────────────────────────────────────
# DUPLICATE DETECTION
# ─────────────────────────────────────────────────────────────────

def _build_duplicate_sets(rows: list) -> dict:
    from collections import Counter
    dup_cols = [SF.TITLE_1, SF.META_DESC_1, SF.H1_1, SF.HASH]
    result = {}
    for col in dup_cols:
        counts = Counter()
        for row in rows:
            val = _str(row, col)
            if val:
                counts[val] += 1
        result[col] = {val for val, cnt in counts.items() if cnt > 1}
    return result


# ─────────────────────────────────────────────────────────────────
# REDIRECT CHAIN DETECTION
# ─────────────────────────────────────────────────────────────────

def _build_redirect_url_set(rows: list) -> set:
    redirect_sources = set()
    for row in rows:
        code = _int(row, SF.STATUS_CODE)
        if code and 300 <= code <= 399:
            redirect_sources.add(_str(row, SF.ADDRESS))
    return redirect_sources


# ─────────────────────────────────────────────────────────────────
# CORE CHECK ENGINE
# ─────────────────────────────────────────────────────────────────

def _check_row(row: dict, duplicate_sets: dict, redirect_sources: set) -> list:
    """Run all X-Point checks against a single row. Returns list of Issues."""
    issues = []
    url = _str(row, SF.ADDRESS)
    fired_categories = {}

    for check in XPOINT_CHECKS:
        col = check.column
        cond = check.condition
        thresh = check.threshold

        flagged = False
        detail = ""

        if cond == "missing":
            val = _str(row, col)
            flagged = _is_empty(val)
            if flagged:
                detail = f"{col} is empty"

        elif cond == "not_missing":
            val = _str(row, col)
            flagged = not _is_empty(val)
            if flagged:
                detail = f"{col} = {val!r}"

        elif cond == "equals":
            if isinstance(thresh, str):
                val = _str(row, col)
                flagged = val == thresh
                detail = f"{col} = {val!r}"
            else:
                val = _int(row, col) if isinstance(thresh, int) else _float(row, col)
                flagged = val is not None and val == thresh
                detail = f"{col} = {val}"

        elif cond == "not_equals":
            val = _str(row, col)
            flagged = val != str(thresh)
            detail = f"{col} = {val!r}"

        elif cond == "greater_than":
            val = _float(row, col)
            flagged = val is not None and val > thresh
            if flagged:
                detail = f"{col} = {val} (threshold: >{thresh})"

        elif cond == "less_than":
            raw = _str(row, col)
            val = _float(row, col)
            flagged = not _is_empty(raw) and val is not None and val < thresh
            if flagged:
                detail = f"{col} = {val} (threshold: <{thresh})"

        elif cond == "between":
            low_t, high_t = thresh
            val = _float(row, col)
            flagged = val is not None and low_t <= val <= high_t
            if flagged:
                detail = f"{col} = {val} (range: {low_t}-{high_t})"

        elif cond == "contains":
            val = _str(row, col).lower()
            flagged = str(thresh).lower() in val
            if flagged:
                detail = f"{col} contains {thresh!r}"

        elif cond == "starts_with":
            val = _str(row, col)
            flagged = val.startswith(str(thresh))
            if flagged:
                detail = f"{col} starts with {thresh!r}"

        elif cond == "duplicate":
            val = _str(row, col)
            flagged = bool(val) and val in duplicate_sets.get(col, set())
            if flagged:
                detail = f"Duplicate {col}: {val[:80]!r}"

        elif cond == "regex":
            val = _str(row, col)
            flagged = bool(re.search(thresh, val))
            if flagged:
                detail = f"{col} matches pattern"

        elif cond == "custom":
            if check.id == "status_4xx_other":
                code = _int(row, SF.STATUS_CODE)
                flagged = code is not None and 400 <= code <= 499 and code != 404
                detail = f"Status code {code}"

            elif check.id == "redirect_chain":
                target = _str(row, SF.REDIRECT_URL)
                if target and target in redirect_sources:
                    flagged = True
                    detail = f"Redirects to {target!r} which is also a redirect"

            elif check.id == "title_same_as_h1":
                title = _str(row, SF.TITLE_1)
                h1 = _str(row, SF.H1_1)
                flagged = bool(title) and bool(h1) and title.lower() == h1.lower()
                if flagged:
                    detail = f"Title = H1 = {title[:60]!r}"

            elif check.id == "long_url":
                val = _str(row, SF.ADDRESS)
                flagged = len(val) > (thresh or 115)
                if flagged:
                    detail = f"URL length {len(val)} chars"

        if not flagged:
            continue

        # Dedup overlapping checks — keep most severe per category
        if check.category in ("performance",):
            dedup_key = f"{check.category}:{col}"
        else:
            dedup_key = check.category

        if dedup_key in fired_categories:
            existing_sev = fired_categories[dedup_key]
            if SEVERITY_ORDER[check.severity] >= SEVERITY_ORDER[existing_sev]:
                continue
            issues = [i for i in issues if not (i.url == url and i.category == check.category and i.check_id != check.id)]

        fired_categories[dedup_key] = check.severity

        issues.append(Issue(
            check_id=check.id,
            check_name=check.name,
            category=check.category,
            severity=check.severity,
            url=url,
            detail=detail,
        ))

    return issues


# ─────────────────────────────────────────────────────────────────
# MAIN PARSE FUNCTION
# ─────────────────────────────────────────────────────────────────

def parse(rows: list, client_name: str = "Unknown") -> ParseResult:
    """Run all X-Point checks against a list of SF export rows."""
    html_rows = filter_html_rows(rows)
    duplicate_sets = _build_duplicate_sets(html_rows)
    redirect_sources = _build_redirect_url_set(rows)

    all_issues = []
    for row in html_rows:
        row_issues = _check_row(row, duplicate_sets, redirect_sources)
        all_issues.extend(row_issues)

    return ParseResult(
        client_name=client_name,
        crawl_date=date.today().isoformat(),
        total_urls=len(rows),
        html_urls=len(html_rows),
        issues=sorted(all_issues, key=lambda i: SEVERITY_ORDER[i.severity]),
    )


# ─────────────────────────────────────────────────────────────────
# SAVE / LOAD RESULT
# ─────────────────────────────────────────────────────────────────

def save_result(result: ParseResult, client_slug: str) -> str:
    """Save ParseResult as JSON to output/ for diff comparison."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = f"{result.crawl_date}_{client_slug}.json"
    filepath = os.path.join(OUTPUT_DIR, filename)
    data = {
        "client_name": result.client_name,
        "crawl_date": result.crawl_date,
        "total_urls": result.total_urls,
        "html_urls": result.html_urls,
        "issues": [
            {
                "check_id": i.check_id,
                "check_name": i.check_name,
                "category": i.category,
                "severity": i.severity,
                "url": i.url,
                "detail": i.detail,
            }
            for i in result.issues
        ],
    }
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    return filepath


def load_result(filepath: str) -> ParseResult:
    """Load a saved ParseResult from JSON."""
    with open(filepath) as f:
        data = json.load(f)
    issues = [
        Issue(
            check_id=i["check_id"],
            check_name=i["check_name"],
            category=i["category"],
            severity=i["severity"],
            url=i["url"],
            detail=i.get("detail", ""),
        )
        for i in data["issues"]
    ]
    return ParseResult(
        client_name=data["client_name"],
        crawl_date=data["crawl_date"],
        total_urls=data["total_urls"],
        html_urls=data["html_urls"],
        issues=issues,
    )


def find_previous_result(client_slug: str, before_date: str) -> Optional[ParseResult]:
    """Find the most recent saved result for a client before a given date."""
    if not os.path.exists(OUTPUT_DIR):
        return None
    matches = []
    for fname in os.listdir(OUTPUT_DIR):
        if fname.endswith(f"_{client_slug}.json"):
            date_str = fname.split("_")[0]
            if date_str < before_date:
                matches.append((date_str, os.path.join(OUTPUT_DIR, fname)))
    if not matches:
        return None
    matches.sort(reverse=True)
    return load_result(matches[0][1])


# ─────────────────────────────────────────────────────────────────
# PRINT SUMMARY
# ─────────────────────────────────────────────────────────────────

def print_summary(result: ParseResult) -> None:
    print(f"\n{'='*60}")
    print(f"  {result.client_name.upper()} — X-POINT AUDIT RESULTS")
    print(f"  Crawl date: {result.crawl_date}")
    print(f"  URLs crawled: {result.total_urls} total | {result.html_urls} HTML pages")
    print(f"{'='*60}")
    print(f"\n  Issues found: {len(result.issues)}")
    print(f"    Critical: {result.critical_count}")
    print(f"    High:     {result.high_count}")
    print(f"    Medium:   {result.medium_count}")
    print(f"    Low:      {result.low_count}")

    if not result.issues:
        print("\n  No issues found.")
        return

    print(f"\n{'─'*60}")
    current_sev = None
    for issue in result.issues_by_severity:
        if issue.severity != current_sev:
            current_sev = issue.severity
            print(f"\n  [{current_sev.upper()}]")
        print(f"    {issue.check_name}")
        print(f"      URL: {issue.url}")
        if issue.detail:
            print(f"      Detail: {issue.detail}")
    print()


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Screaming Frog X-Point Framework Parser")
    ap.add_argument("--file", help="Path to local Screaming Frog CSV export")
    ap.add_argument("--sheet", help="Google Sheets ID of the SF export")
    ap.add_argument("--client", help="Client name or slug")
    ap.add_argument("--save", action="store_true", help="Save result to output/ for diffing")
    args = ap.parse_args()

    if not args.file and not args.sheet:
        print("Error: provide --file or --sheet")
        sys.exit(1)

    client_obj = get_client(args.client) if args.client else None
    client_name = client_obj.name if client_obj else (args.client or "Unknown")
    client_slug = client_obj.slug if client_obj else (args.client or "unknown").lower().replace(" ", "-")

    if args.file:
        print(f"Loading CSV from {args.file}...")
        rows = load_csv_from_file(args.file)
    else:
        print(f"Loading from Google Sheet {args.sheet}...")
        rows = load_csv_from_sheet(args.sheet)

    print(f"Loaded {len(rows)} rows. Running X-Point checks...")

    result = parse(rows, client_name=client_name)
    print_summary(result)

    if args.save:
        path = save_result(result, client_slug)
        print(f"  Saved to: {path}")
