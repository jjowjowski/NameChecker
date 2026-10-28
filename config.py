"""Settings for the mentions tracker.

Edit NAME_VARIANTS to track more spellings of the name. Every variant is used to
verify pages, and the search sources query each one.
"""

import os

# The first entry is the "main" name used in messages and Claude prompts.
NAME_VARIANTS = [
    "Jett Groshinski",
    "Groshinski, Jett",
    "J. Groshinski",
]

# You can add variants without a code change by setting EXTRA_NAME_VARIANTS to a
# semicolon-separated list (semicolons, because variants can contain commas).
NAME_VARIANTS += [v.strip() for v in os.getenv("EXTRA_NAME_VARIANTS", "").split(";") if v.strip()]

TIMEZONE = "Pacific/Auckland"
# With --scheduled, the run only goes ahead if it is this hour in TIMEZONE (see railway.json).
SCHEDULED_LOCAL_HOUR = 9

SHEET_TAB = "Mentions"
COLUMNS = [
    "Date found",
    "Date published",
    "Title",
    "Outlet",
    "URL",
    "Type",
    "How I'm mentioned",
    "Brief description",
    "Source",
    "Status",
    "Notes",
]
TYPES = ["News", "Op-ed", "Academic", "Organisation site", "Social", "Other"]
MENTION_KINDS = ["Author", "Co-author", "Quoted", "Named", "Other"]
STATUSES = ["New", "Reviewed", "Irrelevant"]
DEFAULT_STATUS = "New"

# A cheap model for both the web search and the per-page descriptions.
CLAUDE_MODEL = "claude-haiku-5-5"
CLAUDE_SEARCH_MAX_TOKENS = 2048
CLAUDE_DESCRIBE_MAX_TOKENS = 1024
CLAUDE_SEARCH_MAX_USES = 5
CLAUDE_SEARCH_MAX_USES_BACKFILL = 10

# How far back each source looks on a normal weekly run.
GDELT_TIMESPAN = "2weeks"
# GDELT's DOC API only covers a rolling 3 months, so that is the backfill limit.
GDELT_TIMESPAN_BACKFILL = "3months"

HTTP_TIMEOUT = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
# Characters of page text sent to Claude for the description.
DESCRIBE_TEXT_CHARS = 8000
