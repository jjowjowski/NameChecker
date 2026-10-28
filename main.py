"""Mentions tracker: find new web pages that mention the name, add them to a Google
Sheet, and send a Telegram summary.

    python main.py              # normal run
    python main.py --dry-run    # print what would be added; no sheet writes, no Telegram
    python main.py --backfill   # search as far back as each source allows
    python main.py --scheduled  # what the Railway cron runs (see railway.json)
"""

import argparse
import html
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import config
import notify
import sources
from describe import describe
from models import Candidate, Mention
from sheet import ExistingIndex, MentionsSheet, sheet_url
from urls import normalise_url
from verify import FetchError, fetch, mentions_name

log = logging.getLogger("mentions")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="print what would be added; don't write to the sheet or Telegram")
    p.add_argument("--backfill", action="store_true", help="search as far back as each source allows (automatic on the first run)")
    p.add_argument("--scheduled", action="store_true",
                   help=f"exit unless it is {config.SCHEDULED_LOCAL_HOUR}:00-{config.SCHEDULED_LOCAL_HOUR}:59 in {config.TIMEZONE}")
    return p.parse_args(argv)


def collect(backfill: bool) -> tuple[list[Candidate], list[str]]:
    """Run every source, merging results that point at the same URL."""
    merged: dict[str, Candidate] = {}
    failed = []
    for source in sources.ALL_SOURCES:
        try:
            found = source.find(backfill)
        except Exception as e:
            log.exception("Source %s failed: %s", source.NAME, e)
            failed.append(source.NAME)
            continue
        log.info("%s: %d candidates", source.NAME, len(found))
        for c in found:
            key = normalise_url(c.url)
            if not key:
                continue
            if key not in merged:
                merged[key] = c
                continue
            existing = merged[key]
            existing.sources += [s for s in c.sources if s not in existing.sources]
            existing.title = existing.title or c.title
            existing.published = existing.published or c.published
    return list(merged.values()), failed


def _fetch(candidate: Candidate):
    try:
        return candidate, fetch(candidate.url), None
    except FetchError as e:
        return candidate, None, e


def run(args) -> int:
    tz = ZoneInfo(config.TIMEZONE)
    now = datetime.now(tz)
    if args.scheduled and now.hour != config.SCHEDULED_LOCAL_HOUR:
        # The cron fires at two UTC times to cover NZ daylight saving (see railway.toml);
        # only the one that lands at 9am NZ time does any work.
        log.info("It's %s in NZ, not the %d:00 slot; exiting (this is the other daylight-saving trigger).",
                 now.strftime("%H:%M"), config.SCHEDULED_LOCAL_HOUR)
        return 0

    # 1. What's already in the sheet.
    sheet = None
    try:
        sheet = MentionsSheet()
        existing = sheet.existing()
    except Exception as e:
        if not args.dry_run:
            raise
        log.warning("Dry run: could not read the sheet (%s); treating it as empty", e)
        existing = ExistingIndex([])

    backfill = args.backfill or existing.row_count == 0
    if backfill:
        log.info("Backfill run: searching as far back as each source allows")

    # 2. Search.
    candidates, failed_sources = collect(backfill)
    found = len(candidates)

    duplicates = 0
    to_check = []
    for c in candidates:
        if existing.has_url(c.url):
            duplicates += 1
        else:
            to_check.append(c)

    # 3. Verify: fetch each page (in parallel) and look for the name.
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_fetch, to_check))

    verified = failed_fetch = no_name = 0
    new_mentions: list[Mention] = []
    for c, page, err in results:
        if err:
            failed_fetch += 1
            log.warning("Skipped (failed to load): %s — %s", c.url, err)
            continue
        if not mentions_name(page.text):
            no_name += 1
            log.info("Dropped (name not in page): %s", c.url)
            continue
        verified += 1
        m = Mention(
            url=c.url,
            title=page.title or c.title or c.url,
            outlet=page.site_name or c.outlet,
            published=page.published or c.published,
            sources=c.sources,
            page_text=page.text,
        )
        # Check again now we know the real URL, title and outlet (catches redirects,
        # syndicated copies, and the same page found twice in this run).
        if existing.has_url(page.final_url) or existing.has_title_outlet(m.title, m.outlet):
            duplicates += 1
            log.info("Duplicate of an existing row: %s", c.url)
            continue
        existing.add(c.url, m.title, m.outlet)
        existing.add(page.final_url)
        new_mentions.append(m)

    # 4. Describe with Claude, newest first.
    for m in new_mentions:
        describe(m)
    new_mentions.sort(key=lambda m: m.published or "", reverse=True)

    # 5. Write and notify.
    date_found = now.strftime("%Y-%m-%d")
    if args.dry_run:
        print(f"\n--- DRY RUN: {len(new_mentions)} row(s) would be added ---")
        for m in new_mentions:
            print(f"\n{m.title}\n  Outlet: {m.outlet}\n  URL: {m.url}\n  Published: {m.published or '?'}"
                  f"\n  Type: {m.type} | Mentioned as: {m.how_mentioned} | Source: {', '.join(m.sources)}"
                  f"\n  Description: {m.description or '-'}")
        link = sheet_url() if os.getenv("GOOGLE_SHEET_ID") else "(sheet link)"
        print("\n--- Telegram message that would be sent ---\n" + notify.build_message(new_mentions, link, failed_sources))
        added = 0
    else:
        sheet.insert(new_mentions, date_found)
        added = len(new_mentions)

    log.info(
        "Run complete: found=%d verified=%d duplicates=%d added=%d (failed_to_load=%d, name_not_found=%d, failed_sources=%s)",
        found, verified, duplicates, added, failed_fetch, no_name, failed_sources or "none",
    )

    if not args.dry_run:
        try:
            notify.send(notify.build_message(new_mentions, sheet_url(), failed_sources))
        except Exception as e:
            log.error("Telegram notification failed: %s", e)
            return 1
    return 0


def main(argv=None) -> int:
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs every request at INFO; keep the run log readable.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = parse_args(argv)
    try:
        return run(args)
    except Exception as e:
        log.exception("Run failed")
        if not args.dry_run:
            try:
                notify.send(html.escape(f"⚠️ Mentions tracker failed: {type(e).__name__}: {e}"[:4000]))
            except Exception:
                log.exception("Could not send the failure message to Telegram either")
        return 1


if __name__ == "__main__":
    sys.exit(main())
