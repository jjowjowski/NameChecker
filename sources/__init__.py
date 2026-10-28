"""Search sources. Each module exposes `NAME` and `find(backfill: bool) -> list[Candidate]`.

main.py calls each source inside its own try/except, so one failing source never
stops the others.
"""

from . import claude_search, gdelt, google_alerts

ALL_SOURCES = [google_alerts, gdelt, claude_search]
