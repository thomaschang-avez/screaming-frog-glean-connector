"""
tasks.py — AVENUE Z CREWAI TEMPLATE
Defines all CrewAI tasks with exact input/output contracts between agents.

Tasks chain via CrewAI's context parameter — each task receives the full
output of the previous task as context. Design output schemas BEFORE writing
agent instructions. Work backwards from what the human needs to see.

CUSTOMIZATION CHECKLIST FOR NEW PROJECTS:
  [ ] Define the FINAL output JSON schema first (what does crew.py parse?)
  [ ] Work backwards — what does each prior task need to output for the next to succeed?
  [ ] Update task descriptions to match your department's standards and language
  [ ] Update expected_output with the exact schema or format you need
  [ ] Chain tasks correctly via context=[task1], context=[task1, task2], etc.
"""

from crewai import Task
from typing import Any, List


# ─────────────────────────────────────────────────────────────────
# TASK 1 — Data Analysis / Scoring
# Input: raw data payload from filters.py (passed as articles_payload string)
# Output: structured JSON of qualifying items with scores
# ─────────────────────────────────────────────────────────────────

def build_task_one(agent: Any, client: Any, data_payload: str) -> Task:
    """
    TASK 1: [Name, e.g. 'Angle Selection', 'Lead Scoring', 'Content Analysis']
    Agent receives the raw data payload and applies scoring/filtering logic.

    UPDATE:
      - description: what exactly should the agent do with the data?
      - expected_output: the EXACT JSON schema agent must produce
    """
    return Task(
        description=(
            f"You are analyzing data for {client.name} ({client.industry}).\n\n"
            f"DATA PAYLOAD:\n{data_payload}\n\n"
            # ── UPDATE BELOW: describe the scoring/analysis rules ──
            "YOUR TASK:\n"
            "1. Review each item in the data payload.\n"
            "2. Score each item 0-10 against [YOUR CRITERIA — e.g. 'the client's value props from their pitchbook'].\n"
            "3. Only items scoring 7 or above qualify. Never force an item below 7.\n"
            "4. Return a maximum of [N] qualifying items.\n"
            "5. If nothing scores 7+, return an empty qualifying_items array. Do not guess.\n\n"
            "HARD REJECT CRITERIA (auto-disqualify regardless of score):\n"
            "- [Add your hard reject rules here, e.g. 'wire service sources']\n"
            "- [e.g. 'items older than 7 days']\n\n"
            "Return your output as valid JSON only. No commentary before or after the JSON."
        ),
        expected_output=(
            """Valid JSON matching this schema exactly:
{
  "qualifying_items": [
    {
      "item_id": "string — unique identifier or URL",
      "score": 9,
      "reason": "string — why this item qualifies, tied to specific criteria",
      "client_angle": "string — how this connects to the client's value prop",
      "talking_point": "string — the key message the client can make"
    }
  ],
  "total_reviewed": 15,
  "total_qualifying": 2,
  "rejection_reasons": {
    "below_threshold": 10,
    "hard_reject": 3
  }
}
If no items qualify, return: {"qualifying_items": [], "total_reviewed": N, "total_qualifying": 0}"""
        ),
        agent=agent,
    )


# ─────────────────────────────────────────────────────────────────
# TASK 2 — Research / List Building
# Input: Task 1 output (qualifying items)
# Output: enriched data with research findings
# ─────────────────────────────────────────────────────────────────

def build_task_two(agent: Any, client: Any, context_tasks: List[Task]) -> Task:
    """
    TASK 2: [Name, e.g. 'Media List Builder', 'Contact Finder', 'Data Enrichment']
    Agent takes qualifying items from Task 1 and finds/enriches data.

    UPDATE:
      - description: what research should the agent do?
      - expected_output: what enriched data format is needed?
    """
    return Task(
        description=(
            f"You are building [RESEARCH OUTPUT TYPE — e.g. 'a media list'] for {client.name}.\n\n"
            "You will receive the qualifying items from the previous task as context.\n\n"
            "YOUR TASK:\n"
            "For each qualifying item, use glean_search and glean_read_document to find:\n"
            "1. [Research target 1 — e.g. 'Named Tier 1 reporters who cover this beat']\n"
            "2. [Research target 2 — e.g. 'Confirmed bylines in the last 90 days']\n"
            "3. [Research target 3 — e.g. 'Contact information from existing media lists']\n\n"
            "QUALITY STANDARDS (these are pass/fail — not guidelines):\n"
            "- [Standard 1 — e.g. 'Always find a NAMED person, never just an outlet']\n"
            "- [Standard 2 — e.g. 'Minimum 2 Tier 1 contacts per item']\n"
            "- [Standard 3 — e.g. 'No opinion columnists, contributors, or trade-only outlets']\n\n"
            "Return valid JSON only."
        ),
        expected_output=(
            """Valid JSON with enriched items:
{
  "enriched_items": [
    {
      "item_id": "string — matches item_id from Task 1",
      "contacts": [
        {
          "name": "string — full name",
          "outlet": "string — publication name",
          "beat": "string — what they cover",
          "email": "string or null",
          "recent_work": "string — recent article confirming beat"
        }
      ],
      "contact_count": 3,
      "source": "glean | web | media_list"
    }
  ]
}"""
        ),
        agent=agent,
        context=context_tasks,
    )


# ─────────────────────────────────────────────────────────────────
# TASK 3 — Supplemental Research (Optional)
# Only include this task if you need a web search fallback agent
# Input: Task 2 output (gaps in research)
# Output: additional findings from web search
# ─────────────────────────────────────────────────────────────────

def build_task_three_supplement(agent: Any, client: Any, context_tasks: List[Task]) -> Task:
    """
    TASK 3 (OPTIONAL): Web Search Supplement
    Only runs if Task 2 found gaps that Glean couldn't fill.
    Copy the pr-newsjacking PR-7s pattern.
    """
    return Task(
        description=(
            f"You are supplementing the research for {client.name} using web search.\n\n"
            "Review the previous task's output. For any items where fewer than 2 contacts were found:\n"
            "1. Use web_search to find additional [CONTACT TYPE — e.g. 'named reporters']\n"
            "2. Verify each result has a confirmed [CRITERIA — e.g. 'byline in last 90 days']\n"
            "3. Add them to the enriched_items output.\n\n"
            "If the previous task already found sufficient contacts for all items, return the existing "
            "output unchanged.\n\n"
            "Return valid JSON only."
        ),
        expected_output=(
            "Valid JSON in the same format as Task 2, with any gaps filled by web research. "
            "Flag each web-sourced contact with source='web' in the contact object."
        ),
        agent=agent,
        context=context_tasks,
    )


# ─────────────────────────────────────────────────────────────────
# TASK 4 — Final Output Generation
# Input: all previous task outputs
# Output: the FINAL human-facing deliverable (pitch, report, message, doc)
# This is what crew.py parses to route to SUCCESS/NO_ANGLES/ERROR states.
# ─────────────────────────────────────────────────────────────────

def build_task_four_final(agent: Any, client: Any, context_tasks: List[Task]) -> Task:
    """
    TASK 4: [Name, e.g. 'Pitch Drafter', 'Report Writer', 'Brief Generator']
    Produces the final deliverable. This output is parsed by crew.py.
    The JSON schema here MUST match what crew.py expects to parse.

    UPDATE:
      - description: exact format, length, tone, what's forbidden
      - expected_output: the EXACT final JSON schema crew.py will parse
    """
    return Task(
        description=(
            f"You are creating the final [DELIVERABLE TYPE — e.g. 'pitch'] for {client.name}.\n\n"
            "Use glean_read_document to read the client pitchbook/strategy doc before writing.\n"
            f"Pitchbook URL: {client.pitchbook_url}\n\n"
            "For each qualifying item from the previous tasks, write:\n"
            "1. [Output section 1 — e.g. '4-paragraph pitch, max 250 words']\n"
            "2. [Output section 2 — e.g. 'Subject line: Re: [headline] — [client] [angle in 5 words]']\n\n"
            "QUALITY RULES (Bristol and Libbie's standards — hard pass/fail):\n"
            "- [Rule 1 — e.g. '4 paragraphs maximum. Shorter is always better.']\n"
            "- [Rule 2 — e.g. 'Match pitchbook tone exactly — brand voice is locked']\n"
            "- [Rule 3 — e.g. 'NEVER fabricate quotes, stats, or claims not in pitchbook']\n"
            "- [Rule 4 — e.g. 'NEVER cite internal documents — external source only']\n\n"
            "Return valid JSON only. This JSON will be parsed automatically — no commentary."
        ),
        expected_output=(
            # ── THIS IS THE SCHEMA crew.py WILL PARSE ──
            # Make sure crew.py's JSON parsing matches this exactly.
            """Valid JSON matching this schema exactly:
{
  "client": "string — client name",
  "run_date": "string — ISO date",
  "qualifying_count": 2,
  "items": [
    {
      "headline": "string — article headline",
      "source_url": "string — article URL",
      "outlet": "string — publication",
      "publish_date": "string — ISO date or null",
      "relevance_score": 9,
      "client_angle": "string — how this connects to client value prop",
      "talking_point": "string — key message",
      "contacts": [
        {
          "name": "string",
          "outlet": "string",
          "beat": "string"
        }
      ],
      "deliverable": {
        "subject_line": "string",
        "body": "string — the full [pitch/report/brief]"
      }
    }
  ]
}
If no items qualified, return: {"client": "...", "run_date": "...", "qualifying_count": 0, "items": []}"""
        ),
        agent=agent,
        context=context_tasks,
    )
