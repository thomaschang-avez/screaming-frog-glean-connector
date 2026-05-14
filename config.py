"""
config.py — Screaming Frog X-Point Framework Parser
Loads credentials, defines 20 clients, and maps SF columns to SEO checks.
No CrewAI — plain Python.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────────
# CREDENTIALS (from .env)
# ─────────────────────────────────────────────────────────────────

GLEAN_API_TOKEN = os.environ["GLEAN_API_TOKEN"]
GLEAN_INSTANCE = os.environ["GLEAN_INSTANCE"]
GLEAN_SERVER_URL = os.environ["GLEAN_SERVER_URL"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
GOOGLE_CREDENTIALS_PATH = os.environ.get("GOOGLE_CREDENTIALS_PATH", "google-credentials.json")

GLEAN_ACT_AS = os.environ.get("GLEAN_ACT_AS", "you@yourcompany.com")

# ─────────────────────────────────────────────────────────────────
# SLACK CHANNELS
# ─────────────────────────────────────────────────────────────────

ERROR_CHANNEL = os.environ.get("ERROR_CHANNEL", "YOUR_ERROR_CHANNEL_ID")
TEST_CHANNEL = os.environ.get("TEST_CHANNEL", "YOUR_TEST_CHANNEL_ID")
USE_TEST_CHANNEL = os.environ.get("USE_TEST_CHANNEL", "true").lower() == "true"

# ─────────────────────────────────────────────────────────────────
# GOOGLE SHEETS AUTH
# ─────────────────────────────────────────────────────────────────

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# ─────────────────────────────────────────────────────────────────
# OUTPUT — previous run results stored here for diffing
# ─────────────────────────────────────────────────────────────────

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

# ─────────────────────────────────────────────────────────────────
# CLIENT CONFIG
# ─────────────────────────────────────────────────────────────────

@dataclass
class ClientConfig:
    name: str
    url: str
    sheet_id: str               # Google Sheets ID for this client's SF export
    output_channel_id: str      # Slack channel for results

    @property
    def slug(self) -> str:
        return self.name.lower().replace(" ", "-").replace("&", "and")


# Add your clients here.
# sheet_id: Google Sheets ID with Screaming Frog "Internal - All" export
# output_channel_id: Slack channel to post results to
CLIENTS: list[ClientConfig] = [
    ClientConfig("Client A",  "client-a.com",  "YOUR_SHEET_ID", "YOUR_SLACK_CHANNEL_ID"),
    ClientConfig("Client B",  "client-b.com",  "YOUR_SHEET_ID", "YOUR_SLACK_CHANNEL_ID"),
    ClientConfig("Client C",  "client-c.com",  "YOUR_SHEET_ID", "YOUR_SLACK_CHANNEL_ID"),
    # Add more clients following the same pattern
]


def get_client(name: str) -> ClientConfig | None:
    name_lower = name.lower()
    for c in CLIENTS:
        if c.name.lower() == name_lower or c.slug == name_lower:
            return c
    return None


# ─────────────────────────────────────────────────────────────────
# SCREAMING FROG COLUMN NAMES ("Internal - All" export)
# ─────────────────────────────────────────────────────────────────

class SF:
    ADDRESS = "Address"
    CONTENT_TYPE = "Content Type"
    STATUS_CODE = "Status Code"
    STATUS = "Status"
    INDEXABILITY = "Indexability"
    INDEXABILITY_STATUS = "Indexability Status"
    TITLE_1 = "Title 1"
    TITLE_1_LENGTH = "Title 1 Length"
    TITLE_1_PIXEL = "Title 1 Pixel Width"
    META_DESC_1 = "Meta Description 1"
    META_DESC_1_LENGTH = "Meta Description 1 Length"
    META_DESC_1_PIXEL = "Meta Description 1 Pixel Width"
    H1_1 = "H1-1"
    H1_2 = "H1-2"
    H2_1 = "H2-1"
    H2_2 = "H2-2"
    META_ROBOTS_1 = "Meta Robots 1"
    X_ROBOTS_TAG_1 = "X-Robots-Tag 1"
    META_REFRESH_1 = "Meta Refresh 1"
    CANONICAL = "Canonical Link Element 1"
    SIZE = "Size (bytes)"
    WORD_COUNT = "Word Count"
    TEXT_RATIO = "Text Ratio"
    CRAWL_DEPTH = "Crawl Depth"
    LINK_SCORE = "Link Score"
    INLINKS = "Unique Inlinks"
    OUTLINKS = "Unique Outlinks"
    EXTERNAL_OUTLINKS = "Unique External Outlinks"
    HASH = "Hash"
    RESPONSE_TIME = "Response Time"
    REDIRECT_URL = "Redirect URL"
    REDIRECT_TYPE = "Redirect Type"


# ─────────────────────────────────────────────────────────────────
# SEVERITY LEVELS
# ─────────────────────────────────────────────────────────────────

CRITICAL = "Critical"
HIGH = "High"
MEDIUM = "Medium"
LOW = "Low"

SEVERITY_ORDER = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3}

# ─────────────────────────────────────────────────────────────────
# X-POINT FRAMEWORK CHECK CATEGORIES
# ─────────────────────────────────────────────────────────────────

CATEGORIES = {
    "status_codes": "HTTP Status Codes",
    "crawlability": "Crawlability & Indexation",
    "redirects": "Redirects",
    "titles": "Page Titles",
    "meta_desc": "Meta Descriptions",
    "headings": "Headings",
    "content": "Content Quality",
    "canonicals": "Canonicalization",
    "performance": "Performance",
    "url_structure": "URL Structure",
    "links": "Internal Linking",
    "security": "Security",
}

# ─────────────────────────────────────────────────────────────────
# X-POINT CHECK DEFINITION
# ─────────────────────────────────────────────────────────────────

@dataclass
class XPointCheck:
    id: str
    name: str
    category: str       # key from CATEGORIES
    severity: str       # CRITICAL / HIGH / MEDIUM / LOW
    column: str         # SF column to evaluate
    condition: str      # see list below
    threshold: object = None
    description: str = ""
    # Conditions:
    #   missing         — column is empty/null
    #   not_missing     — column has a value
    #   equals          — column == threshold
    #   not_equals      — column != threshold
    #   greater_than    — numeric > threshold
    #   less_than       — numeric < threshold
    #   between         — threshold = (low, high) inclusive
    #   contains        — string contains threshold (case-insensitive)
    #   starts_with     — string starts with threshold
    #   duplicate       — value appears >1 time across all rows
    #   regex           — matches regex pattern in threshold
    #   custom          — special logic in parser (see check id)

# ─────────────────────────────────────────────────────────────────
# X-POINT FRAMEWORK CHECKS (Screaming Frog subset)
# Overlapping severity checks (e.g. slow + very_slow) — parser
# deduplicates per URL, keeping only the most severe match.
# ─────────────────────────────────────────────────────────────────

XPOINT_CHECKS: list[XPointCheck] = [

    # ── STATUS CODES ──────────────────────────────────────────────

    XPointCheck("status_5xx", "5xx Server Error", "status_codes", CRITICAL,
                SF.STATUS_CODE, "between", (500, 599)),
    XPointCheck("status_404", "404 Not Found", "status_codes", CRITICAL,
                SF.STATUS_CODE, "equals", 404),
    XPointCheck("status_4xx_other", "4xx Client Error (non-404)", "status_codes", HIGH,
                SF.STATUS_CODE, "custom", None,
                "Matches 400-499 excluding 404"),

    # ── REDIRECTS ─────────────────────────────────────────────────

    XPointCheck("redirect_302", "302 Temporary Redirect", "redirects", MEDIUM,
                SF.STATUS_CODE, "equals", 302),
    XPointCheck("redirect_chain", "Redirect Chain Detected", "redirects", HIGH,
                SF.REDIRECT_URL, "custom", None,
                "Redirect target is itself a redirect"),

    # ── CRAWLABILITY & INDEXATION ─────────────────────────────────

    XPointCheck("non_indexable", "Non-Indexable Page", "crawlability", HIGH,
                SF.INDEXABILITY, "equals", "Non-Indexable"),
    XPointCheck("blocked_robots", "Blocked by Robots.txt", "crawlability", CRITICAL,
                SF.INDEXABILITY_STATUS, "equals", "Blocked by Robots.txt"),
    XPointCheck("noindex_meta", "Noindex in Meta Robots", "crawlability", HIGH,
                SF.META_ROBOTS_1, "contains", "noindex"),
    XPointCheck("noindex_xrobots", "Noindex in X-Robots-Tag", "crawlability", HIGH,
                SF.X_ROBOTS_TAG_1, "contains", "noindex"),
    XPointCheck("nofollow_meta", "Nofollow in Meta Robots", "crawlability", MEDIUM,
                SF.META_ROBOTS_1, "contains", "nofollow"),
    XPointCheck("meta_refresh", "Meta Refresh Redirect", "crawlability", MEDIUM,
                SF.META_REFRESH_1, "not_missing", None),

    # ── PAGE TITLES ───────────────────────────────────────────────

    XPointCheck("missing_title", "Missing Title Tag", "titles", CRITICAL,
                SF.TITLE_1, "missing", None),
    XPointCheck("title_too_long", "Title Over 60 Characters", "titles", MEDIUM,
                SF.TITLE_1_LENGTH, "greater_than", 60),
    XPointCheck("title_too_short", "Title Under 30 Characters", "titles", MEDIUM,
                SF.TITLE_1_LENGTH, "less_than", 30),
    XPointCheck("title_pixel_overflow", "Title Exceeds SERP Pixel Width (580px)", "titles", HIGH,
                SF.TITLE_1_PIXEL, "greater_than", 580),
    XPointCheck("duplicate_title", "Duplicate Title Tag", "titles", HIGH,
                SF.TITLE_1, "duplicate", None),
    XPointCheck("title_same_as_h1", "Title Identical to H1", "titles", LOW,
                SF.TITLE_1, "custom", None,
                "Title 1 == H1-1"),

    # ── META DESCRIPTIONS ─────────────────────────────────────────

    XPointCheck("missing_meta_desc", "Missing Meta Description", "meta_desc", HIGH,
                SF.META_DESC_1, "missing", None),
    XPointCheck("meta_desc_too_long", "Meta Description Over 160 Characters", "meta_desc", MEDIUM,
                SF.META_DESC_1_LENGTH, "greater_than", 160),
    XPointCheck("meta_desc_too_short", "Meta Description Under 70 Characters", "meta_desc", MEDIUM,
                SF.META_DESC_1_LENGTH, "less_than", 70),
    XPointCheck("meta_desc_pixel_overflow", "Meta Description Exceeds Pixel Width (990px)", "meta_desc", HIGH,
                SF.META_DESC_1_PIXEL, "greater_than", 990),
    XPointCheck("duplicate_meta_desc", "Duplicate Meta Description", "meta_desc", HIGH,
                SF.META_DESC_1, "duplicate", None),

    # ── HEADINGS ──────────────────────────────────────────────────

    XPointCheck("missing_h1", "Missing H1 Tag", "headings", CRITICAL,
                SF.H1_1, "missing", None),
    XPointCheck("multiple_h1", "Multiple H1 Tags", "headings", HIGH,
                SF.H1_2, "not_missing", None),
    XPointCheck("missing_h2", "Missing H2 Tag", "headings", MEDIUM,
                SF.H2_1, "missing", None),
    XPointCheck("duplicate_h1", "Duplicate H1 Across Pages", "headings", MEDIUM,
                SF.H1_1, "duplicate", None),

    # ── CONTENT QUALITY ───────────────────────────────────────────

    XPointCheck("no_content", "Zero Word Count", "content", CRITICAL,
                SF.WORD_COUNT, "equals", 0),
    XPointCheck("thin_content", "Thin Content (Under 200 Words)", "content", HIGH,
                SF.WORD_COUNT, "between", (1, 199)),
    XPointCheck("low_word_count", "Low Word Count (200-300)", "content", MEDIUM,
                SF.WORD_COUNT, "between", (200, 300)),
    XPointCheck("low_text_ratio", "Low Text-to-HTML Ratio (Under 10%)", "content", MEDIUM,
                SF.TEXT_RATIO, "less_than", 10),
    XPointCheck("excessive_content", "Excessively Long Page (Over 5000 Words)", "content", LOW,
                SF.WORD_COUNT, "greater_than", 5000),

    # ── CANONICALIZATION ──────────────────────────────────────────

    XPointCheck("missing_canonical", "Missing Canonical Tag", "canonicals", HIGH,
                SF.CANONICAL, "missing", None),
    XPointCheck("canonicalized_away", "Canonicalized to Different URL", "canonicals", MEDIUM,
                SF.INDEXABILITY_STATUS, "equals", "Canonicalised"),
    XPointCheck("duplicate_hash", "Duplicate Page Content (Same Hash)", "canonicals", HIGH,
                SF.HASH, "duplicate", None),

    # ── PERFORMANCE ───────────────────────────────────────────────

    XPointCheck("very_slow_response", "Very Slow Response (Over 3s)", "performance", CRITICAL,
                SF.RESPONSE_TIME, "greater_than", 3.0),
    XPointCheck("slow_response", "Slow Response (Over 1s)", "performance", HIGH,
                SF.RESPONSE_TIME, "greater_than", 1.0),
    XPointCheck("very_large_page", "Very Large Page (Over 5MB)", "performance", CRITICAL,
                SF.SIZE, "greater_than", 5_242_880),
    XPointCheck("large_page", "Large Page (Over 3MB)", "performance", HIGH,
                SF.SIZE, "greater_than", 3_145_728),

    # ── URL STRUCTURE ─────────────────────────────────────────────

    XPointCheck("uppercase_url", "Uppercase Characters in URL", "url_structure", MEDIUM,
                SF.ADDRESS, "regex", r"https?://[^?#]*[A-Z]"),
    XPointCheck("underscore_url", "Underscores in URL Path", "url_structure", LOW,
                SF.ADDRESS, "regex", r"https?://[^?#]*_"),
    XPointCheck("long_url", "URL Over 115 Characters", "url_structure", MEDIUM,
                SF.ADDRESS, "custom", 115,
                "len(Address) > 115"),
    XPointCheck("url_parameters", "URL Contains Query Parameters", "url_structure", MEDIUM,
                SF.ADDRESS, "contains", "?"),
    XPointCheck("very_deep_page", "Very Deep Page (Over 5 Clicks)", "url_structure", HIGH,
                SF.CRAWL_DEPTH, "greater_than", 5),
    XPointCheck("deep_page", "Deep Page (Over 3 Clicks)", "url_structure", MEDIUM,
                SF.CRAWL_DEPTH, "greater_than", 3),

    # ── INTERNAL LINKING ──────────────────────────────────────────

    XPointCheck("orphan_page", "Orphan Page (Zero Inlinks)", "links", HIGH,
                SF.INLINKS, "equals", 0),
    XPointCheck("low_inlinks", "Low Internal Links (Only 1)", "links", MEDIUM,
                SF.INLINKS, "equals", 1),
    XPointCheck("excessive_outlinks", "Excessive Outlinks (Over 100)", "links", MEDIUM,
                SF.OUTLINKS, "greater_than", 100),

    # ── SECURITY ──────────────────────────────────────────────────

    XPointCheck("http_url", "Non-HTTPS URL", "security", HIGH,
                SF.ADDRESS, "starts_with", "http://"),
]

# ─────────────────────────────────────────────────────────────────
# LOOKUP INDEXES
# ─────────────────────────────────────────────────────────────────

CHECKS_BY_ID: dict[str, XPointCheck] = {c.id: c for c in XPOINT_CHECKS}

CHECKS_BY_CATEGORY: dict[str, list[XPointCheck]] = {}
for _check in XPOINT_CHECKS:
    CHECKS_BY_CATEGORY.setdefault(_check.category, []).append(_check)

# ─────────────────────────────────────────────────────────────────
# VALIDATION — python3 config.py
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("SCREAMING FROG X-POINT FRAMEWORK — CONFIG VALIDATION")
    print("=" * 60)

    pending = sum(1 for c in CLIENTS if c.sheet_id == "PENDING")
    print(f"\n  {len(CLIENTS)} clients configured ({len(CLIENTS) - pending} ready, {pending} pending):\n")
    for c in CLIENTS:
        tag = "READY" if c.sheet_id != "PENDING" else "PENDING"
        print(f"  [{tag:>7}]  {c.name:<35} {c.url}")

    print(f"\n  {len(XPOINT_CHECKS)} X-Point checks across {len(CATEGORIES)} categories:\n")
    for cat_key, cat_name in CATEGORIES.items():
        checks = CHECKS_BY_CATEGORY.get(cat_key, [])
        if not checks:
            continue
        by_sev = {}
        for c in checks:
            by_sev[c.severity] = by_sev.get(c.severity, 0) + 1
        parts = []
        for sev in [CRITICAL, HIGH, MEDIUM, LOW]:
            if sev in by_sev:
                parts.append(f"{by_sev[sev]}{sev[0]}")
        print(f"  {cat_name:<30} {len(checks):>2} checks  ({'/'.join(parts)})")

    totals = {}
    for c in XPOINT_CHECKS:
        totals[c.severity] = totals.get(c.severity, 0) + 1
    print(f"\n  Severity totals: ", end="")
    print(" | ".join(f"{sev}: {totals.get(sev, 0)}" for sev in [CRITICAL, HIGH, MEDIUM, LOW]))

    print(f"\n  Credentials:")
    print(f"    Glean:  {'loaded' if GLEAN_API_TOKEN else 'MISSING'}")
    print(f"    Slack:  {'loaded' if SLACK_BOT_TOKEN else 'MISSING'}")
    print(f"    Google: {'found' if os.path.exists(GOOGLE_CREDENTIALS_PATH) else 'MISSING'}")
    print(f"    Mode:   {'TEST' if USE_TEST_CHANNEL else 'PRODUCTION'}")
    print()
