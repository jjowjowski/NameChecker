"""Google Alerts RSS (actually Atom) feed.

The feed only ever holds Google's most recent alert items (roughly the last 20),
so a backfill run simply takes everything currently in it.
"""

import logging
import os
import time
from urllib.parse import parse_qs, urlsplit

import feedparser
import requests
from bs4 import BeautifulSoup

import config
from models import Candidate
from urls import domain_of

NAME = "Google Alerts"
log = logging.getLogger(__name__)


def unwrap_google_redirect(url: str) -> str:
    """Turn https://www.google.com/url?...&url=<real>&... into <real>."""
    parts = urlsplit(url)
    if (parts.hostname or "").endswith("google.com") and parts.path == "/url":
        qs = parse_qs(parts.query)
        for key in ("url", "q"):
            if qs.get(key):
                return qs[key][0]
    return url


def _plain(html: str) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)


def find(backfill: bool) -> list[Candidate]:
    feed_url = os.getenv("GOOGLE_ALERTS_RSS_URL", "").strip()
    if not feed_url:
        log.warning("GOOGLE_ALERTS_RSS_URL is not set; skipping Google Alerts")
        return []

    resp = requests.get(feed_url, timeout=config.HTTP_TIMEOUT, headers={"User-Agent": config.USER_AGENT})
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"could not parse feed: {feed.bozo_exception}")

    out = []
    for entry in feed.entries:
        link = entry.get("link") or ""
        if not link and entry.get("links"):
            link = entry.links[0].get("href", "")
        url = unwrap_google_redirect(link)
        if not url:
            continue
        published = ""
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        if stamp:
            published = time.strftime("%Y-%m-%d", stamp)
        out.append(
            Candidate(
                url=url,
                title=_plain(entry.get("title", "")),
                outlet=domain_of(url),
                published=published,
                sources=[NAME],
            )
        )
    return out
