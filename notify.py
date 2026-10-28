"""Telegram notification."""

import html
import logging
import os

import requests

from models import Mention

log = logging.getLogger(__name__)
MAX_LEN = 4000  # Telegram's limit is 4096 characters


def build_message(mentions: list[Mention], sheet_link: str, failed_sources: list[str] = ()) -> str:
    link = f'<a href="{html.escape(sheet_link)}">Open the sheet</a>'
    if failed_sources:
        link = f"⚠️ These sources failed this week: {html.escape(', '.join(failed_sources))}\n{link}"
    if not mentions:
        return f"No new mentions this week (the tracker ran).\n{link}"

    noun = "mention" if len(mentions) == 1 else "mentions"
    lines = [f"<b>{len(mentions)} new {noun} this week</b>", ""]
    footer = f"\n{link}"
    for i, m in enumerate(mentions):
        line = f'• <a href="{html.escape(m.url)}">{html.escape(m.title or m.url)}</a> ({html.escape(m.outlet)})'
        more = f"…and {len(mentions) - i} more in the sheet"
        if len("\n".join(lines + [line, more])) + len(footer) > MAX_LEN:
            lines.append(more)
            break
        lines.append(line)
    return "\n".join(lines) + footer


def send(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": os.environ["TELEGRAM_CHAT_ID"],
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"Telegram API error {resp.status_code}: {resp.text[:300]}")
