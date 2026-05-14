# Screaming Frog Glean Connector

SEO audit pipeline for multi-client agencies. Parses Screaming Frog "Internal - All" CSV exports, evaluates 48 checks across a structured X-Point SEO Framework, diffs new issues against the previous crawl, posts per-client Slack alerts, and indexes results into Glean enterprise search.

## Architecture

```
Screaming Frog CSV export ("Internal - All")
  → parser.py      Map SF columns to 48 X-Point Framework checks
  → diff.py        Compare vs previous snapshot (new / resolved / unchanged)
  → slack_alert.py Post summary to client's Slack channel
  → glean_push.py  Index structured audit into Glean
```

## X-Point Framework — 48 checks across 12 categories

| Category | Examples |
|---|---|
| Redirects | Redirect chains, loops, 3xx to non-200 |
| Status Codes | 4xx, 5xx, soft 404s |
| Titles & Meta | Missing, duplicate, too long/short |
| Headings | Missing H1, multiple H1s, empty headings |
| Content | Thin pages, duplicate content |
| Page Speed | Large page size, uncompressed resources |
| Canonical | Missing, self-referencing, cross-domain |
| Hreflang | Missing, incorrect |
| Schema | Present/absent structured data |
| Internal Linking | Orphaned pages, broken internal links |
| Images | Missing alt text, oversized images |
| Structured Data | JSON-LD validation |

Checks are severity-weighted: **critical** · **warning** · **opportunity**

## Diff output

For each client run, the diff produces:
- **New issues** — appeared since last crawl
- **Resolved issues** — fixed since last crawl  
- **Unchanged** — still open, bucketed by severity
- **Score delta** — weighted total vs previous run

## Usage

```bash
# Single client — parse, diff, alert, push to Glean
python3 main.py --file ~/Downloads/internal_all.csv --client "Client A" --save --push --alert

# All clients (reads each from configured Google Sheet)
python3 main.py --all

# Dry run — validate config and parsing only
python3 main.py --dry-run
```

## Setup

```bash
cp .env.example .env
pip install -r requirements.txt
```

Configure clients in `config.py` — each needs a Google Sheets ID (where Screaming Frog exports are stored) and a Slack channel ID for results.

## Stack

- Python — parsing, diffing, orchestration
- Google Sheets API — crawl data storage per client
- Glean Indexing API — enterprise search indexing
- Slack API — per-client result alerts

## Files

| File | Purpose |
|---|---|
| `config.py` | Client list, credentials, X-Point check definitions |
| `parser.py` | Maps Screaming Frog CSV columns to 48 framework checks |
| `filters.py` | Severity filtering and issue bucketing |
| `diff.py` | New vs resolved vs unchanged issue comparison |
| `slack_alert.py` | Per-client Slack alert formatting and delivery |
| `glean_push.py` | Indexes audit results into Glean |
| `agents.py` | CrewAI agents for AI-assisted issue analysis |
| `tasks.py` | Task definitions for the agent pipeline |
| `crew.py` | Pipeline orchestration |
| `tools.py` | Glean search tools for agent use |
| `main.py` | Entry point |
