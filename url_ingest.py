"""URL -> Markdown ingestion via defuddle.md, falling back to Jina AI's Reader.

Both are free hosted content-extraction services (no API key, no scraping
code of our own): defuddle.md returns YAML frontmatter (title, source, ...)
followed by clean markdown; r.jina.ai (https://r.jina.ai/{url}) returns a
short plain-text header (Title:/URL Source:/Markdown Content:) followed by
its own markdown extraction. Falling back to Jina covers pages defuddle can't
handle (its own downtime, sites it doesn't parse well) since the two services
have independent extraction pipelines.
"""
from __future__ import annotations

import re

import httpx

TIMEOUT = 30.0

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_JINA_TITLE_RE = re.compile(r"\ATitle:\s*(.*)\n")


class UrlIngestError(Exception):
    pass


def _defuddle(url: str) -> tuple[str, str]:
    stripped = re.sub(r"^https?://", "", url)
    resp = httpx.get(f"https://defuddle.md/{stripped}", timeout=TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    raw = resp.text.strip()
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        raise UrlIngestError("defuddle.md response had no frontmatter")
    title = ""
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "title":
            title = value.strip().strip('"')
            break
    body = raw[m.end():].strip()
    if not body:
        raise UrlIngestError("defuddle.md returned empty content")
    return title, body


def _jina(url: str) -> tuple[str, str]:
    resp = httpx.get(f"https://r.jina.ai/{url}", timeout=TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    raw = resp.text.strip()
    title_match = _JINA_TITLE_RE.match(raw)
    title = title_match.group(1).strip() if title_match else ""
    marker = "Markdown Content:"
    idx = raw.find(marker)
    body = raw[idx + len(marker):].strip() if idx != -1 else raw
    if not body:
        raise UrlIngestError("r.jina.ai returned empty content")
    return title, body


def fetch_article(url: str) -> tuple[str, str]:
    """Fetch `url` and return (title, markdown), title may be "". Tries
    defuddle.md first, falls back to Jina's reader if that raises for any
    reason (bad status, timeout, no frontmatter, empty body)."""
    try:
        return _defuddle(url)
    except Exception:
        return _jina(url)
