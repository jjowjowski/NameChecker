"""URL and text normalisation used for duplicate checks."""

import re
import string
from urllib.parse import parse_qsl, urlencode, urlsplit

TRACKING_PARAMS = {"fbclid", "gclid"}


def normalise_url(url: str) -> str:
    """Reduce a URL to a comparable key.

    Lowercases the domain, drops http/https and "www.", removes utm_*, fbclid and
    gclid parameters, the fragment, and trailing slashes. The path keeps its case,
    because some sites have case-sensitive paths.
    """
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    query.sort()
    path = parts.path.rstrip("/")
    key = host + path
    if query:
        key += "?" + urlencode(query)
    return key.rstrip("/")


_PUNCT = re.compile(f"[{re.escape(string.punctuation)}‘’“”–—…]")


def normalise_text(text: str) -> str:
    """Lowercase, strip punctuation and collapse whitespace (for title/outlet matching)."""
    text = _PUNCT.sub(" ", (text or "").lower())
    return " ".join(text.split())


def title_outlet_key(title: str, outlet: str) -> tuple[str, str] | None:
    t, o = normalise_text(title), normalise_text(outlet)
    if not t or not o:
        return None
    return (t, o)


def domain_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host
