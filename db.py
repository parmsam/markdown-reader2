"""Article library persistence: one sqlite table, via fastlite (fasthtml.common.Database).

Segments/TOC are deliberately NOT stored here -- they're cheap, pure functions of
`markdown` (see segmentation.py) recomputed on every view. Storing a second,
derived copy is exactly the kind of two-sources-of-truth drift that caused a real
bug in v1 (see CLAUDE.md). Only generated TTS audio is expensive enough to cache
(see cache.py), and that cache is keyed off content_hash below, not off this table.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastlite import Database

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)
(DATA_DIR / "pdfs").mkdir(exist_ok=True)
(DATA_DIR / "audio_cache").mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "library.db"


def normalize_newlines(markdown: str) -> str:
    """Browsers submit a <textarea>'s content with CRLF line endings regardless
    of what was typed/loaded into it, and some uploaded files already use CRLF.
    Normalizing at write time keeps stored markdown -- and therefore every
    downstream consumer (segmentation, rendering, the edit textarea) -- LF-only.
    segmentation.py normalizes too (defense in depth for anything already
    stored with CRLF), but doing it here means content stays clean going
    forward instead of relying on that alone."""
    return markdown.replace("\r\n", "\n").replace("\r", "\n")


def content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db(path: str | Path = DB_PATH) -> Database:
    db = Database(path)
    db.t.articles.create(
        {
            "id": int,
            "title": str,
            "markdown": str,
            "content_hash": str,
            "source_type": str,           # "paste" | "markdown_file" | "pdf" | "url"
            "original_filename": str,     # also holds the source URL when source_type == "url"
            "pdf_path": str,
            "created_at": str,
            "updated_at": str,
            "last_segment_index": int,    # -1 = no progress yet
            "last_voice": str,
            "last_speed": float,
        },
        pk="id",
        if_not_exists=True,
    )
    return db


Article = None  # populated by get_articles_table() below, once the db is open


def get_articles_table(db: Database):
    global Article
    articles = db.t.articles
    if Article is None:
        Article = articles.dataclass()
    return articles


def create_article(
    db: Database,
    *,
    title: str,
    markdown: str,
    source_type: str,
    original_filename: str | None = None,
    pdf_path: str | None = None,
) -> "Article":
    articles = get_articles_table(db)
    markdown = normalize_newlines(markdown)
    now = _now()
    return articles.insert(
        title=title,
        markdown=markdown,
        content_hash=content_hash(markdown),
        source_type=source_type,
        original_filename=original_filename,
        pdf_path=pdf_path,
        created_at=now,
        updated_at=now,
        last_segment_index=-1,
        last_voice=None,
        last_speed=None,
    )


def list_articles(db: Database) -> list["Article"]:
    articles = get_articles_table(db)
    return list(articles(order_by="-created_at"))


def get_article(db: Database, article_id: int) -> "Article | None":
    articles = get_articles_table(db)
    try:
        return articles[article_id]
    except Exception:
        return None


def update_article_markdown(db: Database, article_id: int, markdown: str) -> None:
    articles = get_articles_table(db)
    markdown = normalize_newlines(markdown)
    articles.update(
        {
            "markdown": markdown,
            "content_hash": content_hash(markdown),
            "updated_at": _now(),
            "last_segment_index": -1,
        },
        article_id,
    )


def set_pdf_path(db: Database, article_id: int, pdf_path: str) -> None:
    articles = get_articles_table(db)
    articles.update({"pdf_path": pdf_path}, article_id)


def update_progress(db: Database, article_id: int, *, segment_index: int, voice: str, speed: float) -> None:
    articles = get_articles_table(db)
    articles.update(
        {"last_segment_index": segment_index, "last_voice": voice, "last_speed": speed},
        article_id,
    )


def delete_article(db: Database, article_id: int) -> "Article | None":
    articles = get_articles_table(db)
    article = get_article(db, article_id)
    if article is None:
        return None
    articles.delete(article_id)
    return article


def all_content_hashes(db: Database) -> set[str]:
    articles = get_articles_table(db)
    return {row["content_hash"] for row in articles.rows}
