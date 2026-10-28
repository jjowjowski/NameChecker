# Mentions tracker

A small Python job that runs once a week on Railway. It finds new web pages that mention
**Jett Groshinski**, checks each page really contains the name, adds new ones to a Google
Sheet, and sends a Telegram message with a link to the sheet.

## How a run works

1. **Read the sheet.** Every existing row's URL, title and outlet is loaded, whatever its
   Status. A row you mark *Irrelevant* stays there, so its URL is never added again.
2. **Search three sources.** Each is its own module in `sources/`, so if one fails the
   others still run (the Telegram message says which source failed):
   - `google_alerts.py`: your Google Alert's RSS feed. Google's redirect links are unwrapped to the real article URL.
   - `gdelt.py`: the GDELT DOC 2.0 API (free, no key), exact phrase, past 2 weeks.
   - `claude_search.py`: Claude (Haiku 5.5, a cheap model) with the web search tool, asked to return only a JSON list of URLs and titles.
3. **Skip duplicates.** URLs are normalised before comparing: lowercase domain, no
   `http(s)://` or `www.`, no `utm_*`, `fbclid` or `gclid` parameters, no trailing slash. A
   page is also a duplicate if its title and outlet match an existing row, which catches
   the same article syndicated at a different URL.
4. **Verify.** Each remaining page (HTML or PDF) is downloaded and kept only if one of the
   name variants appears in its text (case-insensitive). Pages that fail to load are
   skipped and logged.
5. **Describe.** Claude reads each kept page and fills in *Type*, *How I'm mentioned* and a
   1–2 sentence paraphrased *Brief description*.
6. **Write and notify.** New rows go in at the top of the sheet with Status `New`. Existing
   rows are never edited or deleted; they just move down. Then the Telegram message is sent:
   "X new mentions this week" with each title and outlet, or "No new mentions this week" so
   you know it ran.

Every run logs its counts to stdout, for example:
`Run complete: found=14 verified=5 duplicates=8 added=3 (failed_to_load=1, name_not_found=4, ...)`.
Here `verified` counts pages that contain the name. `added` is lower when a verified page
turns out to repeat an existing title and outlet.

**First run = backfill.** If the sheet has no rows yet, the run searches as far back as
each source allows: everything in the Alerts feed (Google keeps about the last 20 items),
GDELT's full 3-month window, and a broader Claude search. You can force this later with
`--backfill`.

### Name variants

They live in `NAME_VARIANTS` in `config.py`:

```python
NAME_VARIANTS = ["Jett Groshinski", "Groshinski, Jett", "J. Groshinski"]
```

Add to that list, or set `EXTRA_NAME_VARIANTS` on Railway (separated by semicolons, since
variants can contain commas).

## Files

| File | What it does |
|---|---|
| `main.py` | Entry point; runs the steps above. Flags: `--dry-run`, `--backfill`, `--scheduled` |
| `config.py` | Name variants, columns, model, search windows |
| `sources/` | One module per source |
| `verify.py` | Fetches pages, extracts text and metadata, matches the name |
| `urls.py` | URL and title normalisation for duplicate checks |
| `describe.py` | Claude classification and description |
| `sheet.py` | Google Sheet read and insert |
| `notify.py` | Telegram message |
| `railway.toml` | Railway cron schedule and start command |
| `.env.example` | Every environment variable |
| `tests/` | `pytest` tests (no network needed) |

## Setup

### 1. Google service account and sheet

1. Go to <https://console.cloud.google.com/>, then create or pick a project.
2. **APIs & Services → Library** → enable the **Google Sheets API**.
3. **IAM & Admin → Service Accounts → Create service account.** Give it any name (e.g.
   `mentions-tracker`). It needs no project roles, so skip that step.
4. Open the new account → **Keys → Add key → Create new key → JSON.** A `.json` file
   downloads. Treat it like a password and don't commit it.
5. Create a Google Sheet (any name). Click **Share** and share it with the service account's
   email (the `client_email` in the JSON, like `mentions-tracker@project.iam.gserviceaccount.com`)
   as **Editor**.
6. Copy the sheet ID from its URL: `https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit`.
7. Set the env vars:
   - `GOOGLE_SHEET_ID` = that ID
   - `GOOGLE_SERVICE_ACCOUNT_JSON` = the entire contents of the JSON key file. Railway
     accepts multi-line values. For a local `.env`, put it on one line:
     `python -c "import json;print(json.dumps(json.load(open('key.json'))))"`.

On the first run the script creates the **Mentions** tab, writes the header, makes it bold,
freezes it, and adds a New/Reviewed/Irrelevant dropdown to the Status column. If a
*Mentions* tab already exists with headers, it is left as is; columns are matched by
header name.

### 2. Google Alert RSS feed

1. Go to <https://www.google.com/alerts>, signed in to Google.
2. Type `"Jett Groshinski"` (with the quotes) into the box, then click **Show options**:
   - How often: **As-it-happens** (the feed keeps a limited number of items, so this avoids missing any)
   - Sources: Automatic · Language: Any · Region: Any Region · How many: **All results**
   - **Deliver to: RSS feed**
3. Click **Create Alert**.
4. On the Alerts page, click the RSS icon next to the alert and copy that URL into
   `GOOGLE_ALERTS_RSS_URL`. (Optionally add more alerts, e.g. `"Groshinski, Jett"`. Only one
   feed URL is read, so keep the main one.)

### 3. Telegram bot

1. In Telegram, message **@BotFather** and send `/newbot`. Choose a name and a username
   ending in `bot`. BotFather replies with a token like `123456789:AA...`. That is
   `TELEGRAM_BOT_TOKEN`.
2. Open a chat with your new bot and send it any message (bots can't message you first).
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser. Find
   `"chat":{"id":123456789,...}`. That number is `TELEGRAM_CHAT_ID`.

### 4. Anthropic API key

Create a key at <https://console.anthropic.com/> → **API keys** and set `ANTHROPIC_API_KEY`.
Without it, the Claude search source is skipped and rows get no description.

Cost: each weekly run does up to 5 web searches (10 on a backfill; web search is billed per
search) plus a few small Haiku calls, one per new page. That is cents per run.

### 5. Try it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill it in
set -a; source .env; set +a
python main.py --dry-run
```

`--dry-run` reads the sheet (if credentials are set) and runs the searches, page checks and
Claude descriptions. It then prints the rows it would add and the Telegram message, without
writing to the sheet or sending anything.

Run the tests with `pip install pytest && pytest`.

### 6. Deploy on Railway

1. Push this repo to GitHub.
2. In Railway: **New Project → Deploy from GitHub repo** → pick the repo. Railway detects
   Python from `requirements.txt` and reads `railway.toml`.
3. In the service's **Variables** tab, add everything from `.env.example`.
4. Check **Settings → Deploy**: the start command should be `python main.py --scheduled`
   and the cron schedule `0 20,21 * * 0`, both coming from `railway.toml`. The service has
   no web server and exits after each run, which is what a Railway cron service expects.
5. To test it on Railway right away, temporarily set the start command to
   `python main.py --dry-run` and the cron schedule to a few minutes from now (in UTC),
   check the logs, then put both back. Without `--scheduled` the script runs whatever the
   time. With `--scheduled` it exits unless it is 9am in NZ.

#### Why the schedule fires twice

Railway cron runs in UTC, and Monday 9:00 in New Zealand is Sunday 20:00 UTC during NZDT
(UTC+13, late September to early April) but Sunday 21:00 UTC during NZST (UTC+12). One
fixed UTC time would be an hour off for half the year, so the job is triggered at both
20:00 and 21:00 UTC on Sundays. `--scheduled` makes the script check the actual
`Pacific/Auckland` time and only do the work in the run that lands in the 9 o'clock hour.
The other run exits in a second or two. No schedule changes are needed when the clocks
change.

## Sheet columns

| Column | Filled by |
|---|---|
| Date found | Date of the run (NZ time) |
| Date published | Page metadata, else the source's date (GDELT's is when it first saw the article), else blank |
| Title, Outlet | Page metadata (`og:title`, `og:site_name`, journal name), else the source's, else the domain |
| URL | Clickable link |
| Type | News / Op-ed / Academic / Organisation site / Social / Other (Claude) |
| How I'm mentioned | Author / Co-author / Quoted / Named / Other (Claude) |
| Brief description | 1–2 sentences paraphrased by Claude |
| Source | Which source(s) found it |
| Status | `New`. Change it to `Reviewed` or `Irrelevant` yourself |
| Notes | Yours |

## Limits

- Sites that block scripts (some paywalls, LinkedIn, X) usually fail to load and are
  skipped and logged. If something important is skipped, add it to the sheet by hand;
  the tracker then treats it as a duplicate.
- The weekly GDELT search covers 2 weeks, so a missed week is covered by the next run.
  If the job is down for longer, run it once with `--backfill`.
