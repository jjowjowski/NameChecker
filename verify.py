"""Fetch a candidate page and confirm the name really appears in its text."""

import io
import json
import logging
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

import config

log = logging.getLogger(__name__)
MAX_BYTES = 15 * 1024 * 1024
MAX_PDF_PAGES = 40


def name_pattern(variants: list[str]) -> re.Pattern:
    """Case-insensitive regex matching any variant, with flexible whitespace.

    "J. Groshinski" becomes \\bJ\\.\\s+Groshinski\\b, so it also matches across a
    line break or a non-breaking space.
    """
    parts = []
    for v in variants:
        tokens = [re.escape(t) for t in v.split()]
        if not tokens:
            continue
        body = r"\s+".join(tokens)
        start = r"\b" if re.match(r"\w", v) else ""
        end = r"\b" if re.search(r"\w$", v) else ""
        parts.append(start + body + end)
    return re.compile("|".join(parts), re.IGNORECASE)


NAME_RE = name_pattern(config.NAME_VARIANTS)


@dataclass
class Page:
    final_url: str
    text: str
    title: str = ""
    site_name: str = ""
    published: str = ""


class FetchError(Exception):
    pass


def _meta(soup: BeautifulSoup, *keys: str) -> str:
    for key in keys:
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def _json_ld_date(soup: BeautifulSoup) -> str:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if isinstance(item.get("datePublished"), str):
                    return item["datePublished"]
                stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
    return ""


def _iso_date(value: str) -> str:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", value or "")
    return "-".join(m.groups()) if m else ""


def _parse_html(raw: bytes, encoding: str | None) -> tuple[str, str, str, str]:
    soup = BeautifulSoup(raw, "html.parser", from_encoding=encoding)
    title = _meta(soup, "og:title", "twitter:title")
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
    site = _meta(soup, "og:site_name", "application-name")
    published = _iso_date(
        _meta(soup, "article:published_time", "citation_publication_date", "citation_date",
              "dc.date", "DC.date.issued", "date", "pubdate")
        or _json_ld_date(soup)
        or (soup.find("time", datetime=True) or {}).get("datetime", "")
    )
    # citation_* tags appear on academic pages; prefer their journal as the outlet.
    site = _meta(soup, "citation_journal_title") or site
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    # Attribute text too: author names on some sites live only in meta tags.
    meta_bits = " ".join(
        m.get("content", "") for m in soup.find_all("meta") if m.get("name", "").lower() in
        ("author", "citation_author", "dc.creator", "description", "og:description")
    )
    return f"{text} {meta_bits}".strip(), title, site, published


def _parse_pdf(raw: bytes) -> tuple[str, str]:
    reader = PdfReader(io.BytesIO(raw))
    pages = [p.extract_text() or "" for p in reader.pages[:MAX_PDF_PAGES]]
    title = ""
    if reader.metadata and reader.metadata.title:
        title = str(reader.metadata.title).strip()
    return " ".join(pages), title


def fetch(url: str) -> Page:
    try:
        resp = requests.get(
            url,
            timeout=config.HTTP_TIMEOUT,
            headers={"User-Agent": config.USER_AGENT, "Accept-Language": "en"},
            stream=True,
        )
        resp.raise_for_status()
        raw = resp.raw.read(MAX_BYTES, decode_content=True)
    except requests.RequestException as e:
        raise FetchError(str(e)) from e

    ctype = resp.headers.get("Content-Type", "").lower()
    if "pdf" in ctype or raw[:5] == b"%PDF-":
        try:
            text, title = _parse_pdf(raw)
        except Exception as e:
            raise FetchError(f"could not read PDF: {e}") from e
        return Page(final_url=resp.url, text=text, title=title)
    if "html" in ctype or "xml" in ctype or not ctype:
        text, title, site, published = _parse_html(raw, resp.encoding if "charset" in ctype else None)
        return Page(final_url=resp.url, text=text, title=title, site_name=site, published=published)
    if ctype.startswith("text/"):
        return Page(final_url=resp.url, text=raw.decode(resp.encoding or "utf-8", "replace"))
    raise FetchError(f"unsupported content type {ctype!r}")


def mentions_name(text: str) -> bool:
    return bool(NAME_RE.search(text.replace("\xa0", " ")))


def excerpt_for_claude(text: str, limit: int = config.DESCRIBE_TEXT_CHARS) -> str:
    """The start of the page plus the passages around each mention, within `limit` chars."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    snippets = []
    for m in list(NAME_RE.finditer(text))[:8]:
        snippets.append(text[max(0, m.start() - 600): m.end() + 600])
    around = "\n…\n".join(snippets)
    head = text[: max(1000, limit - len(around) - 10)]
    return (head + "\n…\n" + around)[:limit]
