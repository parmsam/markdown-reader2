"""Best-effort, read-only check against GitHub's releases API for a newer
tagged version than the one currently running.

Deliberately does *not* offer any way to apply an update from the app: this
server has no authentication (see CLAUDE.md), so anything that could pull code
or restart the process would be a remote-triggerable action for any device on
the LAN, not just you. This module only ever tells you a newer version
exists -- updating is still a manual `git pull` + restart.

Never makes a blocking network call from a request handler: get_available_update()
always returns instantly from an in-memory cache, kicking off a background
refresh (at most one at a time) when that cache is stale.
"""
from __future__ import annotations

import threading
import time

import httpx

REPO = "parmsam/markdown-reader2"
CHECK_INTERVAL_SECONDS = 6 * 60 * 60  # how often to re-hit the GitHub API
_TIMEOUT_SECONDS = 3.0

_lock = threading.Lock()
_state = {"latest": None, "checked_at": 0.0, "checking": False}


def _parse_version(v: str) -> tuple[int, ...]:
    parts = []
    for p in v.lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _fetch_latest_tag() -> str | None:
    try:
        resp = httpx.get(
            f"https://api.github.com/repos/{REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
            timeout=_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json().get("tag_name")
    except Exception:
        # Network hiccup, rate limit, no releases yet, etc -- an update check
        # must never break the app it's checking on behalf of.
        return None


def _refresh():
    tag = _fetch_latest_tag()
    with _lock:
        _state["checked_at"] = time.time()
        _state["checking"] = False
        if tag is not None:
            _state["latest"] = tag


def _maybe_start_refresh() -> None:
    with _lock:
        stale = (time.time() - _state["checked_at"]) > CHECK_INTERVAL_SECONDS
        if not stale or _state["checking"]:
            return
        _state["checking"] = True
    threading.Thread(target=_refresh, daemon=True).start()


def get_available_update(current_version: str) -> str | None:
    """Returns the latest release's version (e.g. "1.1.0") if newer than
    current_version, else None. Safe to call on every page load."""
    _maybe_start_refresh()
    with _lock:
        latest = _state["latest"]
    if latest is None:
        return None
    latest_clean = latest.lstrip("vV")
    if _parse_version(latest_clean) > _parse_version(current_version):
        return latest_clean
    return None


def release_url(version: str) -> str:
    return f"https://github.com/{REPO}/releases/tag/v{version}"
