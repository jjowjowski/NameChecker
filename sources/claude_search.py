"""Claude API with the server-side web search tool.

Asks a cheap model to search for pages containing the exact name and to reply
with only a JSON list of {"url", "title"}. Everything it returns is verified by
fetching the page later, so a made-up or wrong URL just gets dropped.

Cost per run: the web searches (billed per search, capped by max_uses) plus a
small number of Haiku tokens.
"""

import json
import logging
import os
import re

import anthropic

import config
from models import Candidate
from urls import domain_of

NAME = "Claude web search"
MAX_CONTINUATIONS = 3
log = logging.getLogger(__name__)


def _prompt(backfill: bool) -> str:
    names = " OR ".join(f'"{v}"' for v in config.NAME_VARIANTS)
    when = (
        "Find as many as you can, from any date."
        if backfill
        else "Focus on pages published or updated in the last two weeks."
    )
    return (
        f"Use web search to find web pages that mention the person named {names} "
        f"(exact name, any of those spellings). {when} Ignore pages about other "
        "people with a similar name.\n\n"
        "Reply with ONLY a JSON array and nothing else, like:\n"
        '[{"url": "https://example.com/page", "title": "Page title"}]\n'
        "Use [] if you find nothing. Only include URLs that appeared in your search results."
    )


def _parse_json_list(text: str) -> list[dict]:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict) and isinstance(d.get("url"), str)]


def find(backfill: bool) -> list[Candidate]:
    if not os.getenv("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY is not set; skipping Claude web search")
        return []

    client = anthropic.Anthropic()
    max_uses = config.CLAUDE_SEARCH_MAX_USES_BACKFILL if backfill else config.CLAUDE_SEARCH_MAX_USES
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}]
    messages = [{"role": "user", "content": _prompt(backfill)}]

    response = None
    for _ in range(MAX_CONTINUATIONS + 1):
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=config.CLAUDE_SEARCH_MAX_TOKENS,
            output_config={"effort": "low"},
            tools=tools,
            messages=messages,
        )
        if response.stop_reason != "pause_turn":
            break
        # The server-side search loop paused; send the turn back and it resumes.
        messages = [messages[0], {"role": "assistant", "content": response.content}]

    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined the search request: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        log.warning("Claude search hit max_tokens; the URL list may be truncated")

    text = "".join(b.text for b in response.content if b.type == "text")
    items = _parse_json_list(text)
    if not items and text.strip() not in ("", "[]"):
        log.warning("Could not parse Claude's reply as a JSON list: %r", text[:300])

    return [
        Candidate(
            url=item["url"].strip(),
            title=str(item.get("title") or "").strip(),
            outlet=domain_of(item["url"]),
            sources=[NAME],
        )
        for item in items
        if item["url"].startswith(("http://", "https://"))
    ]
