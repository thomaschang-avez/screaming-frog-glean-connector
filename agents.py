"""
agents.py — AVENUE Z CREWAI TEMPLATE
Verified against CrewAI 1.14.4 | Updated May 2026

ARCHITECTURE:
  - GeminiLLM  → all agent reasoning (cheap, fast, 1M context)
  - Glean tools → all data retrieval (Glean enterprise knowledge graph, internal docs)

Glean is the brain of the company — it holds all internal knowledge.
Gemini reasons over what Glean retrieves.
No OpenAI. Zero client data leaves the enterprise environment.

CUSTOMIZATION CHECKLIST FOR NEW PROJECTS:
  [ ] Replace role, goal, backstory per agent with your use case
  [ ] Replace tools list per agent with the correct tools from tools.py
  [ ] Add/remove build_agent_* functions to match your crew architecture
  [ ] Set max_iter: use 3 for analysis/drafting agents, 5 for research/lookup agents
"""

from __future__ import annotations
import os
import json
from typing import Any, List, Optional
from dotenv import load_dotenv
from crewai import Agent
from crewai.llm import BaseLLM
from pydantic import Field, PrivateAttr
from google import genai
from tools import (
    glean_search,
    glean_read_document,
    web_search,
    post_to_slack,
    # add any custom tools from tools.py here
)

load_dotenv()

# ─────────────────────────────────────────────────────────────────
# GEMINI CONFIG
# ADC authenticates automatically locally
# For Cloud Run: set GEMINI_SERVICE_ACCOUNT env var (see below)
# ─────────────────────────────────────────────────────────────────

GEMINI_PROJECT  = os.environ.get("GEMINI_PROJECT", "vertex-api-test-495415")
GEMINI_LOCATION = os.environ.get("GEMINI_LOCATION", "us-central1")


# ─────────────────────────────────────────────────────────────────
# GEMINI LLM CLASS — COPY UNCHANGED INTO EVERY PROJECT
#
# Replaces GleanLLM as the reasoning engine.
# Glean tools (glean_search, glean_read_document) still handle retrieval.
#
# Available models (May 2026 — do NOT use older names, they are retired):
#   gemini-2.5-flash      → DEFAULT. Best balance of speed/cost/quality.
#   gemini-2.5-flash-lite → Ultra-fast, ultra-cheap. Simple tasks only.
#   gemini-2.5-pro        → Complex multi-step reasoning. Slowest/most expensive.
#
# Cost: ~$0.075 per 1M input tokens (40x cheaper than Claude Sonnet)
# Context: 1M tokens
# ─────────────────────────────────────────────────────────────────

class GeminiLLM(BaseLLM):
    """
    CrewAI LLM adapter routing all agent reasoning through Gemini API via Vertex AI.
    Uses Application Default Credentials (ADC) — no API key needed locally.
    For Cloud Run: set GEMINI_SERVICE_ACCOUNT env var with service account JSON.
    """

    model: str = Field(default="gemini-2.5-flash")
    _client: Any = PrivateAttr()

    def model_post_init(self, __context: Any) -> None:
        """Initialize Gemini client. ADC auto-detects locally."""
        service_account_json = os.environ.get("GEMINI_SERVICE_ACCOUNT")

        if service_account_json:
            # Cloud Run: authenticate via service account JSON env var
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_info(
                json.loads(service_account_json),
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            self._client = genai.Client(
                vertexai=True,
                project=GEMINI_PROJECT,
                location=GEMINI_LOCATION,
                credentials=creds,
            )
        else:
            # Local dev: ADC authenticates automatically
            self._client = genai.Client(
                vertexai=True,
                project=GEMINI_PROJECT,
                location=GEMINI_LOCATION,
            )

    def call(
        self,
        messages: str | list[dict],
        tools: list | None = None,
        callbacks: list | None = None,
        available_functions: dict[str, Any] | None = None,
        **kwargs: Any,  # absorbs from_task, from_agent, response_model (BaseLLM 1.14.4)
    ) -> str:
        """Convert CrewAI messages to Gemini format and return response text."""

        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        # Extract system instruction (Gemini supports it natively via config)
        system_instruction = None
        content_parts: list[str] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_instruction = content
            elif role == "assistant":
                content_parts.append(f"[ASSISTANT]\n{content}")
            else:
                content_parts.append(content)

        # Embed tool descriptions as text (Gemini function calling not used in CrewAI flow)
        if tools:
            tool_descriptions = []
            for t in tools:
                if isinstance(t, dict):
                    func = t.get("function", t)
                    name = func.get("name", "unknown")
                    desc = func.get("description", "")
                    params = func.get("parameters", {})
                    tool_descriptions.append(f"- {name}: {desc}\n  Parameters: {params}")
            if tool_descriptions:
                content_parts.append(
                    "\n[AVAILABLE TOOLS]\n" + "\n".join(tool_descriptions) + "\n\n"
                    "To use a tool, respond with:\n"
                    "Action: <tool_name>\n"
                    "Action Input: <json arguments>\n"
                )

        full_content = "\n\n".join(content_parts)

        # Build Gemini config
        config: dict = {}
        if system_instruction:
            config["system_instruction"] = system_instruction

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=full_content,
                config=config if config else None,
            )
            return response.text

        except Exception as e:
            return f"Error: Gemini API call failed: {e}"

    def get_context_window_size(self) -> int:
        return 1_000_000  # Gemini 2.5 Flash: 1M token context window


def create_gemini_llm(model: str = "gemini-2.5-flash") -> GeminiLLM:
    """
    Factory function — use this in all agent builders.

    Model options:
      "gemini-2.5-flash"      → default, best all-around
      "gemini-2.5-flash-lite" → fastest/cheapest, simple tasks
      "gemini-2.5-pro"        → complex reasoning, slower
    """
    return GeminiLLM(model=model)


# ─────────────────────────────────────────────────────────────────
# AGENT BUILDER FUNCTIONS
# One function per agent. Each returns a configured CrewAI Agent.
#
# Agent fields in CrewAI 1.14.4:
#   required: role, goal, backstory, llm
#   allow_delegation: defaults to False (set explicitly for clarity)
#   verbose: defaults to False (keep False in prod)
#   max_iter: defaults to 25 — override to 3 (analysis/drafting) or 5 (research)
#
# TOOL PATTERN:
#   - Give every agent glean_read_document + glean_search to pull Ave Z knowledge
#   - Add web_search only for agents that need live external data
#   - Max 3 tools per agent — if you need more, split the agent
#
# CONTEXT CHAINING — set in crew.py AFTER building all tasks:
#   task2.context = [task1]     ← NOT inside build functions
# ─────────────────────────────────────────────────────────────────

def build_agent_one(client: Any) -> Agent:
    """
    AGENT 1 — Analysis / Scoring Agent
    Reads client docs from Glean, scores incoming data against value props.
    Gemini reasons over what Glean retrieves.
    max_iter=3: should produce output in one strong pass.
    """
    return Agent(
        role="[AGENT ROLE — e.g. 'Senior PR News Analyst']",
        goal=(
            "[AGENT GOAL — be specific, include pass/fail criteria.]\n"
            f"For {client.name}: score each item 0-10. Only 7+ qualify. "
            "Return max 3. Never force a low-quality item through. "
            "If nothing scores 7+, output NO_QUALIFYING_ANGLES."
        ),
        backstory=(
            "[AGENT BACKSTORY — use real names.]\n"
            "You are a Senior SEO Strategist with deep expertise in technical SEO and enterprise search. "
            "You know immediately what would make a WSJ journalist respond vs delete."
        ),
        tools=[glean_read_document, glean_search],
        llm=create_gemini_llm(),           # Gemini reasons; Glean tools retrieve
        verbose=False,
        allow_delegation=False,
        max_iter=3,
    )


def build_agent_two(client: Any) -> Agent:
    """
    AGENT 2 — Research / List Building Agent
    Searches Glean for contacts, media, enrichment data.
    max_iter=5: may need multiple Glean searches to find all contacts.
    """
    return Agent(
        role="[AGENT ROLE — e.g. 'Media List Builder']",
        goal=(
            "[AGENT GOAL — include exact quality bar with pass/fail criteria.]\n"
            f"For {client.name}: [describe what this agent does and what passes/fails]. "
            "Always find a NAMED person — never just an outlet."
        ),
        backstory=(
            "[AGENT BACKSTORY — e.g. Libbie Wilcox's media list quality standards.]"
        ),
        tools=[glean_search, glean_read_document],
        llm=create_gemini_llm(),
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )


def build_agent_three(client: Any) -> Agent:
    """
    AGENT 3 — Web Supplement / Gap Filler (Optional)
    Runs only when Agent 2 couldn't find enough from Glean.
    max_iter=5: may need multiple web searches.
    Uses gemini-2.5-flash-lite — simple lookup, speed over depth.
    """
    return Agent(
        role="[AGENT ROLE — e.g. 'Web Research Supplement']",
        goal=(
            f"[AGENT GOAL] For {client.name}: supplement gaps from the previous agent. "
            "Do not duplicate work already done."
        ),
        backstory="[AGENT BACKSTORY]",
        tools=[web_search],
        llm=create_gemini_llm(model="gemini-2.5-flash-lite"),  # cheaper for simple lookups
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )


def build_agent_four(client: Any) -> Agent:
    """
    AGENT 4 — Final Output / Pitch Drafter
    Produces the human-facing deliverable. Reads pitchbook from Glean for voice/tone.
    Uses gemini-2.5-pro for highest quality final output.
    max_iter=3: output should be produced in one strong pass.

    IMPORTANT: This agent's output is JSON parsed by crew.py.
    The JSON schema in expected_output (tasks.py) MUST match what crew.py parses.
    """
    return Agent(
        role="[AGENT ROLE — e.g. 'Senior Pitch Drafter']",
        goal=(
            "[AGENT GOAL — final human-facing deliverable. Be specific about format/tone.]\n"
            f"For {client.name}: [describe the output]. "
            "Return ONLY valid JSON. No commentary before or after."
        ),
        backstory=(
            "[AGENT BACKSTORY — e.g. Bristol Jones: 4 paragraphs max, "
            "no fabricated stats, no wire service sources.]"
        ),
        tools=[glean_read_document],
        llm=create_gemini_llm(model="gemini-2.5-pro"),  # best quality for final output
        verbose=False,
        allow_delegation=False,
        max_iter=3,
    )


# ─────────────────────────────────────────────────────────────────
# USAGE IN crew.py
# ─────────────────────────────────────────────────────────────────
#
# from agents import build_agent_one, build_agent_two, build_agent_three, build_agent_four
#
# agent1 = build_agent_one(client)   # gemini-2.5-flash (default)
# agent2 = build_agent_two(client)   # gemini-2.5-flash (default)
# agent3 = build_agent_three(client) # gemini-2.5-flash-lite (fast/cheap)
# agent4 = build_agent_four(client)  # gemini-2.5-pro (best quality)
#
# ENVIRONMENT VARIABLES:
#   GEMINI_PROJECT=vertex-api-test-495415    (already set up)
#   GEMINI_LOCATION=us-central1              (default)
#   GEMINI_SERVICE_ACCOUNT=<json>            (Cloud Run only — not needed locally)
#
# INSTALL:
#   pip install google-cloud-aiplatform      (includes google-genai)
