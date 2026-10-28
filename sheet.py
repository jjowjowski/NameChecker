"""Google Sheet access. Only ever reads existing rows and inserts new ones at the top."""

import json
import logging
import os

import gspread

import config
from models import Mention
from urls import normalise_url, title_outlet_key

log = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class ExistingIndex:
    """What is already in the sheet, for duplicate checks (any status, including Irrelevant)."""

    def __init__(self, rows: list[dict]):
        self.urls = {normalise_url(r.get("URL", "")) for r in rows} - {""}
        self.title_outlets = {title_outlet_key(r.get("Title", ""), r.get("Outlet", "")) for r in rows} - {None}
        self.row_count = len(rows)

    def has_url(self, url: str) -> bool:
        return normalise_url(url) in self.urls

    def has_title_outlet(self, title: str, outlet: str) -> bool:
        key = title_outlet_key(title, outlet)
        return key is not None and key in self.title_outlets

    def add(self, url: str, title: str = "", outlet: str = "") -> None:
        """Record something accepted in this run, so it can't be added twice."""
        self.urls.add(normalise_url(url))
        key = title_outlet_key(title, outlet)
        if key:
            self.title_outlets.add(key)


def sheet_url() -> str:
    return f"https://docs.google.com/spreadsheets/d/{os.environ['GOOGLE_SHEET_ID']}"


def _safe_text(value: str) -> str:
    """Stop web-supplied text (titles etc.) being interpreted as a formula."""
    value = (value or "").replace("\r", " ").strip()
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value


def _hyperlink(url: str) -> str:
    escaped = url.replace('"', '""')
    return f'=HYPERLINK("{escaped}","{escaped}")'


class MentionsSheet:
    def __init__(self):
        creds = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
        client = gspread.service_account_from_dict(creds, scopes=SCOPES)
        self.spreadsheet = client.open_by_key(os.environ["GOOGLE_SHEET_ID"])
        try:
            self.ws = self.spreadsheet.worksheet(config.SHEET_TAB)
        except gspread.WorksheetNotFound:
            log.info("Creating the %r tab", config.SHEET_TAB)
            self.ws = self.spreadsheet.add_worksheet(config.SHEET_TAB, rows=1000, cols=len(config.COLUMNS))
        self._values = self.ws.get_all_values()
        if not self._values or not any(self._values[0]):
            self._create_header()
        self.header = [h.strip() for h in self._values[0]]
        missing = [c for c in ("URL", "Title", "Outlet") if c not in self.header]
        if missing:
            raise RuntimeError(f"The {config.SHEET_TAB!r} tab's header row is missing {missing}")

    def _create_header(self) -> None:
        self.ws.update([config.COLUMNS], "A1")
        self.ws.format("1:1", {"textFormat": {"bold": True}})
        self.ws.freeze(rows=1)
        status_col = config.COLUMNS.index("Status")
        self.spreadsheet.batch_update({"requests": [{
            "setDataValidation": {
                "range": {"sheetId": self.ws.id, "startRowIndex": 1,
                          "startColumnIndex": status_col, "endColumnIndex": status_col + 1},
                "rule": {
                    "condition": {"type": "ONE_OF_LIST",
                                  "values": [{"userEnteredValue": s} for s in config.STATUSES]},
                    "showCustomUi": True,
                    "strict": False,
                },
            }
        }]})
        self._values = [config.COLUMNS]

    def existing(self) -> ExistingIndex:
        rows = [dict(zip(self.header, r)) for r in self._values[1:] if any(c.strip() for c in r)]
        return ExistingIndex(rows)

    def insert(self, mentions: list[Mention], date_found: str) -> None:
        """Insert rows directly under the header, newest first. Existing rows just move down."""
        if not mentions:
            return
        rows = []
        for m in mentions:
            values = {
                "Date found": date_found,
                "Date published": m.published,
                "Title": _safe_text(m.title),
                "Outlet": _safe_text(m.outlet),
                "URL": _hyperlink(m.url),
                "Type": m.type,
                "How I'm mentioned": m.how_mentioned,
                "Brief description": _safe_text(m.description),
                "Source": _safe_text(", ".join(m.sources)),
                "Status": config.DEFAULT_STATUS,
                "Notes": "",
            }
            # Follow the sheet's actual header order, in case columns were rearranged.
            rows.append([values.get(h, "") for h in self.header])
        self.ws.insert_rows(rows, row=2, value_input_option="USER_ENTERED")
