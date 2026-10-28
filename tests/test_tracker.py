import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
import notify  # noqa: E402
from models import Candidate, Mention  # noqa: E402
from sheet import ExistingIndex, _hyperlink, _safe_text  # noqa: E402
from sources.google_alerts import unwrap_google_redirect  # noqa: E402
from urls import normalise_url  # noqa: E402
from verify import Page, mentions_name  # noqa: E402


def test_normalise_url():
    a = normalise_url("https://www.Example.COM/news/Story/?utm_source=x&fbclid=1&id=5#top")
    b = normalise_url("http://example.com/news/Story?id=5&gclid=abc")
    assert a == b == "example.com/news/Story?id=5"
    assert normalise_url("https://example.com/") == "example.com"


def test_name_matching():
    assert mentions_name("Written by JETT GROSHINSKI for the paper")
    assert mentions_name("Groshinski, Jett (2024). A paper.")
    assert mentions_name("Smith, A. and J.\xa0Groshinski")
    assert mentions_name("Jett\nGroshinski said")
    assert not mentions_name("Jett Groshinskiy and Jett Smith")


def test_unwrap_google_redirect():
    wrapped = ("https://www.google.com/url?rct=j&sa=t&url=https://news.example.org/a%3Fb%3D1"
               "&ct=ga&cd=abc&usg=xyz")
    assert unwrap_google_redirect(wrapped) == "https://news.example.org/a?b=1"
    assert unwrap_google_redirect("https://other.org/x") == "https://other.org/x"


def test_existing_index():
    idx = ExistingIndex([
        {"URL": "https://www.site.com/a/", "Title": "Big News!", "Outlet": "The Site", "Status": "Irrelevant"},
    ])
    assert idx.has_url("http://site.com/a?utm_medium=email")
    assert idx.has_title_outlet("big news", "the site")
    assert not idx.has_title_outlet("Big News", "Other Outlet")


def test_sheet_cell_safety():
    assert _safe_text("=IMPORTXML(1)") == "'=IMPORTXML(1)"
    assert _safe_text("Normal title") == "Normal title"
    assert _hyperlink('https://x.com/"a"') == '=HYPERLINK("https://x.com/""a""","https://x.com/""a""")'


def test_telegram_message():
    m = Mention(url="https://e.com/a&b", title="<Title>", outlet="E", published="", sources=[], page_text="")
    msg = notify.build_message([m], "https://sheet")
    assert "1 new mention this week" in msg and "&lt;Title&gt;" in msg and "https://sheet" in msg
    assert "No new mentions" in notify.build_message([], "https://sheet")
    many = notify.build_message([m] * 500, "https://sheet")
    assert len(many) <= 4096 and "more in the sheet" in many


class FakeSource:
    def __init__(self, name, items=None, fail=False):
        self.NAME, self.items, self.fail = name, items or [], fail

    def find(self, backfill):
        if self.fail:
            raise RuntimeError("boom")
        return self.items


def test_dry_run_end_to_end(monkeypatch, capsys, caplog):
    caplog.set_level(logging.INFO)
    pages = {
        "https://a.com/1": Page("https://a.com/1", "Interview with Jett Groshinski", title="Story A", site_name="A News"),
        "https://b.com/2": Page("https://b.com/2", "Nothing relevant here", title="Story B"),
        "https://c.com/3": Page("https://c.com/3", "J. Groshinski wrote", title="Story A", site_name="A News"),
    }

    def fake_fetch(url):
        if url == "https://dead.com/x":
            raise main.FetchError("404")
        return pages[url]

    monkeypatch.setattr(main.sources, "ALL_SOURCES", [
        FakeSource("S1", [Candidate("https://a.com/1", sources=["S1"]), Candidate("https://b.com/2", sources=["S1"])]),
        FakeSource("S2", [Candidate("https://www.a.com/1/?utm_source=x", sources=["S2"]),
                          Candidate("https://c.com/3", sources=["S2"]),
                          Candidate("https://dead.com/x", sources=["S2"]),
                          Candidate("https://old.com/seen", sources=["S2"])]),
        FakeSource("S3", fail=True),
    ])
    monkeypatch.setattr(main, "fetch", fake_fetch)
    monkeypatch.setattr(main, "describe", lambda m: None)

    class FakeSheet:
        def existing(self):
            return ExistingIndex([{"URL": "https://old.com/seen", "Title": "Old", "Outlet": "Old"}])

    monkeypatch.setattr(main, "MentionsSheet", FakeSheet)
    monkeypatch.setenv("GOOGLE_SHEET_ID", "abc")

    assert main.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "1 row(s) would be added" in out
    assert "Story A" in out and "S1, S2" in out
    # found=5 unique URLs; old.com is a sheet duplicate and c.com repeats a.com's title+outlet
    assert "found=5 verified=2 duplicates=2 added=0" in caplog.text
    assert "failed_to_load=1, name_not_found=1" in caplog.text
    assert "sources failed this week: S3" in out
