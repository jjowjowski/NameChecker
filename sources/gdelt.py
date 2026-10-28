"""GDELT DOC 2.0 API: free, no key. Exact-phrase search over recent news.

The DOC API only searches a rolling 3-month window, so that is the backfill limit.
GDELT asks for no more than one request every 5 seconds, so variants are queried
one at a time with a pause in between.
"""

import logging
import time
from datetime import datetime

import requests

import config
from models import Candidate
from urls import domain_of

NAME = "GDELT"
API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
log = logging.getLogger(__name__)


def _query(phrase: str, timespan: str) -> list[dict]:
    params = {
        "query": f'"{phrase}"',
        "mode": "ArtList",
        "format": "json",
        "maxrecords": 250,
        "sort": "DateDesc",
        "timespan": timespan,
    }
    resp = requests.get(API_URL, params=params, timeout=60, headers={"User-Agent": config.USER_AGENT})
    resp.raise_for_status()
    if not resp.text.strip():
        return []  # GDELT returns an empty body when nothing matches
    try:
        data = resp.json()
    except ValueError:
        # Errors (e.g. "phrase too short") come back as plain text with HTTP 200.
        raise RuntimeError(f"GDELT returned non-JSON for {phrase!r}: {resp.text[:200]!r}")
    return data.get("articles") or []


def _date(seendate: str) -> str:
    try:
        return datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def find(backfill: bool) -> list[Candidate]:
    timespan = config.GDELT_TIMESPAN_BACKFILL if backfill else config.GDELT_TIMESPAN
    out = []
    errors = 0
    for i, phrase in enumerate(config.NAME_VARIANTS):
        if i:
            time.sleep(6)
        try:
            articles = _query(phrase, timespan)
        except Exception as e:  # one bad variant shouldn't lose the others
            log.warning("GDELT query for %r failed: %s", phrase, e)
            errors += 1
            continue
        for a in articles:
            url = a.get("url")
            if not url:
                continue
            out.append(
                Candidate(
                    url=url,
                    title=a.get("title", ""),
                    outlet=a.get("domain") or domain_of(url),
                    # seendate is when GDELT first saw the article: close to, not
                    # exactly, the publish date. Page metadata overrides it later.
                    published=_date(a.get("seendate", "")),
                    sources=[NAME],
                )
            )
    if errors == len(config.NAME_VARIANTS):
        raise RuntimeError("every GDELT query failed")
    return out
