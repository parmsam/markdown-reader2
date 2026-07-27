"""Disk cache for generated TTS audio.

Layout: data/audio_cache/{content_hash}/{segment_index:05d}__{voice}__{speed}.wav
                                          (+ a matching .json for duration/word_timings)

Keyed by the *content hash of the article's markdown*, not by article id. Editing an
article changes its content_hash, so a new (empty) cache namespace is used
automatically on next playback -- stale audio can never be served, by construction,
with no explicit invalidation step required. The old namespace just becomes an
orphan (nothing references it any more) until gc_orphaned_audio_cache() sweeps it.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from db import DATA_DIR, all_content_hashes

AUDIO_CACHE_DIR = DATA_DIR / "audio_cache"
AUDIO_CACHE_DIR.mkdir(exist_ok=True)


def _speed_key(speed: float) -> str:
    return f"{speed:.2f}"


def cache_dir(content_hash: str) -> Path:
    d = AUDIO_CACHE_DIR / content_hash
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_paths(content_hash: str, segment_index: int, voice: str, speed: float) -> tuple[Path, Path]:
    """Return (wav_path, json_path) for a given cache key. Does not create them.

    NOTE: build filenames via string concatenation, not Path.with_suffix() -- the
    speed component (e.g. "1.00") itself contains a dot, which with_suffix() would
    misparse as an existing suffix and silently truncate (turning "...1.00" into
    "...1.wav", losing the fractional part and colliding different speeds).
    """
    stem = f"{segment_index:05d}__{voice}__{_speed_key(speed)}"
    d = AUDIO_CACHE_DIR / content_hash
    return d / f"{stem}.wav", d / f"{stem}.json"


def read_cached_timings(json_path: Path) -> dict | None:
    if not json_path.exists():
        return None
    try:
        return json.loads(json_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def write_cache(wav_path: Path, json_path: Path, wav_bytes: bytes, meta: dict) -> None:
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    wav_path.write_bytes(wav_bytes)
    json_path.write_text(json.dumps(meta))


def delete_article_cache(content_hash: str, db) -> None:
    """Delete a content_hash's cache directory, unless another article still shares it."""
    if content_hash in all_content_hashes(db):
        return  # another article still references this exact content
    d = AUDIO_CACHE_DIR / content_hash
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def gc_orphaned_audio_cache(db) -> int:
    """Delete any cached content_hash directory not referenced by any current article.
    Returns the number of directories removed."""
    referenced = all_content_hashes(db)
    removed = 0
    if not AUDIO_CACHE_DIR.exists():
        return 0
    for entry in AUDIO_CACHE_DIR.iterdir():
        if entry.is_dir() and entry.name not in referenced:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed
