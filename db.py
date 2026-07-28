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
            "folder": str,                # "/"-joined path ("Notes/Work"), None/"" = no folder
            "created_at": str,
            "updated_at": str,
            "last_segment_index": int,    # -1 = no progress yet
            "last_voice": str,
            "last_speed": float,
        },
        pk="id",
        if_not_exists=True,
    )
    # `if_not_exists=True` above only creates the table on a first run --
    # it doesn't add new columns to an already-existing one (this app has no
    # migration framework), so an existing data/library.db from before the
    # "folder" column existed needs it added explicitly.
    articles = db.t.articles
    if "folder" not in {c.name for c in articles.columns}:
        articles.add_column("folder", str)
    return db


Article = None  # populated by get_articles_table() below, once the db is open


def get_articles_table(db: Database):
    global Article
    articles = db.t.articles
    if Article is None:
        Article = articles.dataclass()
    return articles


def normalize_folder(folder: str | None) -> str | None:
    """Normalize a "/"-joined folder path: trims whitespace around each
    segment, drops empty segments (so leading/trailing/repeated slashes and
    stray spaces around "/" collapse away), and returns None for an empty or
    root path -- the one canonical form `folder` is ever stored/compared in."""
    if not folder:
        return None
    segments = [s.strip() for s in folder.split("/")]
    segments = [s for s in segments if s]
    return "/".join(segments) if segments else None


def create_article(
    db: Database,
    *,
    title: str,
    markdown: str,
    source_type: str,
    original_filename: str | None = None,
    pdf_path: str | None = None,
    folder: str | None = None,
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
        folder=normalize_folder(folder),
        created_at=now,
        updated_at=now,
        last_segment_index=-1,
        last_voice=None,
        last_speed=None,
    )


def list_folders(db: Database) -> list[str]:
    """Distinct folder paths currently in use, sorted. Folders only exist
    implicitly via articles' `folder` field (no separate folders table), so
    one that's lost all its articles (moved or deleted) simply stops
    appearing -- there's nothing further to clean up."""
    articles = get_articles_table(db)
    folders = {row["folder"] for row in articles.rows if row["folder"]}
    return sorted(folders)


def set_article_folder(db: Database, article_id: int, folder: str | None) -> None:
    articles = get_articles_table(db)
    articles.update({"folder": normalize_folder(folder)}, article_id)


def delete_folder(db: Database, path: str) -> int:
    """Remove a folder (and any of its sub-folders) by clearing `folder` on
    every article inside it -- moves them back to the root library rather
    than deleting them. There's no separate "delete the articles too" path:
    a folder is just a path string on an article (see list_folders'
    docstring), not a real container, so "deleting" it can only ever mean
    dissolving the grouping, never destroying content. Returns the number
    of articles moved."""
    path = normalize_folder(path)
    if not path:
        return 0
    articles = get_articles_table(db)
    updated = 0
    for row in list(articles.rows):
        folder = row["folder"]
        if folder == path or (folder and folder.startswith(path + "/")):
            articles.update({"folder": None}, row["id"])
            updated += 1
    return updated


def rename_folder(db: Database, old_path: str, new_path: str) -> int:
    """Rename a folder, cascading to every descendant sub-folder path too
    (e.g. renaming "Notes" to "Journal" also turns "Notes/Work" into
    "Journal/Work"). Returns the number of articles updated."""
    old_path = normalize_folder(old_path)
    new_path = normalize_folder(new_path)
    if not old_path or not new_path or old_path == new_path:
        return 0
    articles = get_articles_table(db)
    updated = 0
    for row in list(articles.rows):
        folder = row["folder"]
        if folder == old_path:
            new_folder = new_path
        elif folder and folder.startswith(old_path + "/"):
            new_folder = new_path + folder[len(old_path):]
        else:
            continue
        articles.update({"folder": new_folder}, row["id"])
        updated += 1
    return updated


SORT_OPTIONS = {
    "recent": ("Recently added", "-created_at"),
    "oldest": ("Oldest first", "created_at"),
    "title_asc": ("Title (A-Z)", "title COLLATE NOCASE"),
    "title_desc": ("Title (Z-A)", "title COLLATE NOCASE DESC"),
}
DEFAULT_SORT = "recent"


def list_articles(db: Database, sort: str = DEFAULT_SORT) -> list["Article"]:
    articles = get_articles_table(db)
    _, order_by = SORT_OPTIONS.get(sort, SORT_OPTIONS[DEFAULT_SORT])
    return list(articles(order_by=order_by))


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
