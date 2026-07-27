"""FT (FastHTML component) builders for every page in the app.

Kept separate from app.py so route handlers stay thin: each route calls one of
these builders and returns the result.
"""
from __future__ import annotations

import time

from fasthtml.common import (
    A, Audio, Body, Blockquote, Button, Details, Div, Form, H1, H2, Head, Html,
    Img, Input, Label, Link, Main, Meta, NotStr, Nav, Option, P, Script, Select,
    Span, Style, Summary, Textarea, Title,
)

from tts import VOICES, DEFAULT_VOICE, DEFAULT_SPEED

APP_NAME = "Lector"
SPEEDS = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]

# Cache-busting query param for static assets, fixed at process start. Static
# files are served with a far-future Cache-Control (see app.py's get_static),
# so this is what forces phones/browsers to fetch the new player.js/style.css
# after an edit + restart instead of silently keeping a stale cached copy
# (bit us in practice: iOS Safari cached player.js across a fix that needed
# it, see LEARNINGS.md).
_STATIC_VERSION = str(int(time.time()))

# A ~0.1s silent WAV, played (looped) on first touch/click on iOS. iOS Safari
# puts pages that only use the Web Audio API into the "ambient" audio session
# category, which is muted by the hardware ring/silent switch; playing *any*
# HTML <audio> element flips the page into the "playback" category for the
# rest of the session, so our AudioBufferSourceNode-based playback is audible
# even with the switch flipped to silent. See player.js's unlockAudio().
SILENT_WAV_DATA_URI = (
    "data:audio/wav;base64,"
    + "UklGRmQGAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YUAGAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
)


def _head(title: str):
    return Head(
        # Sets data-theme on <html> from localStorage *before* the stylesheet
        # loads, so a saved light/dark choice applies on first paint instead
        # of flashing the system-default theme first. Kept inline (not
        # deferred) and ordered before the Link below for that reason --
        # static/theme.js (deferred) owns the toggle button's click handling.
        Script(NotStr(
            "(function(){try{"
            "var t=localStorage.getItem('theme');"
            "if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t);"
            "}catch(e){}})();"
        )),
        Meta(charset="utf-8"),
        Meta(name="viewport", content="width=device-width, initial-scale=1, viewport-fit=cover"),
        Title(title),
        Link(rel="icon", type="image/svg+xml", href=f"/static/favicon.svg?v={_STATIC_VERSION}"),
        Link(rel="apple-touch-icon", href=f"/static/apple-touch-icon.png?v={_STATIC_VERSION}"),
        Link(rel="stylesheet", href=f"/static/style.css?v={_STATIC_VERSION}"),
        Script(src=f"/static/player.js?v={_STATIC_VERSION}", defer=True),
        Script(src=f"/static/library.js?v={_STATIC_VERSION}", defer=True),
        Script(src=f"/static/theme.js?v={_STATIC_VERSION}", defer=True),
        Script(src=f"/static/upload.js?v={_STATIC_VERSION}", defer=True),
    )


def _nav():
    return Nav(
        A(
            Img(src=f"/static/favicon.svg?v={_STATIC_VERSION}", alt="", width="22", height="22", cls="brand-logo"),
            Span(APP_NAME, cls="brand-name"),
            href="/", cls="nav-link nav-brand",
        ),
        A("+ Add article", href="/add", cls="nav-link nav-add"),
        Button(
            id="theme-toggle", cls="theme-toggle", type="button",
            title="Toggle light/dark theme", aria_label="Toggle light/dark theme",
        ),
        cls="topnav",
    )


def library_page(articles: list) -> Html:
    if not articles:
        body = Div(
            P("Your library is empty."),
            A("Add your first article", href="/add", cls="btn btn-primary"),
            cls="empty-state",
        )
    else:
        rows = [_article_row(a) for a in articles]
        body = Div(*rows, cls="article-list")

    return Html(
        _head(f"Library — {APP_NAME}"),
        Body(_nav(), Main(H1("Library"), body, cls="container")),
    )


def _source_label(a):
    """original_filename doubles as the source URL for source_type == "url"
    articles, so render it as a link there instead of plain text."""
    if not a.original_filename:
        return ""
    if a.source_type == "url":
        return A(a.original_filename, href=a.original_filename, cls="article-filename", target="_blank", rel="noopener noreferrer")
    return Span(a.original_filename, cls="article-filename")


def _article_row(a) -> Div:
    resume_pct = ""
    if a.last_segment_index is not None and a.last_segment_index >= 0:
        resume_pct = Span("in progress", cls="badge badge-progress")
    filename_span = _source_label(a)
    return Div(
        Div(
            A(a.title or "Untitled", href=f"/article/{a.id}", cls="article-title"),
            Span(a.source_type, cls="badge"),
            resume_pct,
            filename_span,
            cls="article-row-main",
        ),
        Div(
            Span(a.created_at[:10] if a.created_at else "", cls="article-date"),
            Button(
                "Delete",
                cls="btn btn-danger btn-sm",
                data_delete_id=str(a.id),
            ),
            cls="article-row-meta",
        ),
        cls="article-row",
    )


def add_article_page(url: str = "", error: str = "", autofetch: bool = False) -> Html:
    url_form = Form(
        Label(
            "Page URL",
            Input(
                name="url", type="url", value=url,
                placeholder="https://example.com/some-article",
                required=True, autocapitalize="off", autocorrect="off", spellcheck="false",
                autofocus=bool(url) or None,
            ),
        ),
        Label(
            Input(name="use_page_title", type="checkbox", checked=True),
            " Use the page's title",
            cls="checkbox-label",
        ),
        Button("Fetch & add", type="submit", cls="btn btn-primary"),
        P(
            "Fetched with defuddle.md, falling back to Jina AI's reader if that fails.",
            cls="form-hint",
        ),
        method="post",
        action="/articles/url",
        id="url-add-form",
        cls="add-form",
    )
    paste_form = Form(
        Label("Title (optional)", Input(name="title", type="text", placeholder="Derived from content if left blank")),
        Label("Markdown", Textarea(name="markdown", rows=16, placeholder="Paste or write markdown here...", required=True)),
        Button("Add to library", type="submit", cls="btn btn-primary"),
        method="post",
        action="/articles",
        cls="add-form",
    )
    upload_form = Form(
        Label(
            "File (.md, .markdown, .txt, or .pdf)",
            Div(
                Input(name="file", type="file", accept=".md,.markdown,.txt,.pdf", required=True),
                Span("Drop a file here, or tap to browse", cls="file-drop-hint"),
                Span("", cls="file-drop-name", hidden=True),
                cls="file-dropzone",
            ),
        ),
        Label(
            Input(name="use_filename_as_title", type="checkbox", checked=True),
            " Use file name as title",
            cls="checkbox-label",
        ),
        Button("Upload", type="submit", cls="btn btn-primary"),
        method="post",
        action="/articles/upload",
        enctype="multipart/form-data",
        cls="add-form",
    )
    error_banner = Div(error, cls="add-error") if error else ""
    autofetch_script = (
        Script(NotStr(
            "document.getElementById('url-add-form').submit();"
        ))
        if autofetch and url and not error else ""
    )
    return Html(
        _head(f"Add article — {APP_NAME}"),
        Body(
            _nav(),
            Main(
                H1("Add an article"),
                error_banner,
                Details(Summary("Add from a link"), url_form, open=True),
                Details(Summary("Paste markdown"), paste_form, open=not url),
                Details(Summary("Upload a file"), upload_form),
                cls="container",
            ),
            autofetch_script,
        ),
    )


def edit_article_page(article) -> Html:
    form = Form(
        Label("Title", Input(name="title", type="text", value=article.title or "")),
        Label("Markdown", Textarea(article.markdown, name="markdown", rows=20, required=True)),
        Button("Save changes", type="submit", cls="btn btn-primary"),
        method="post",
        action=f"/article/{article.id}/edit",
        cls="add-form",
    )
    return Html(
        _head(f"Edit {article.title or 'Untitled'} — {APP_NAME}"),
        Body(
            _nav(),
            Main(
                H1(f"Edit: {article.title or 'Untitled'}"),
                P(
                    "Saving will reset your reading progress for this article and "
                    "regenerate audio on next play (edited content gets a fresh cache).",
                    cls="edit-note",
                ),
                form,
                cls="container",
            ),
        ),
    )


def toc_sidebar(toc: list):
    if not toc:
        return Nav(cls="toc-sidebar")
    items = [
        Button(
            entry.text,
            cls=f"toc-entry toc-level-{entry.level}",
            data_jump=str(entry.segment_index),
        )
        for entry in toc
    ]
    # A <details> rather than a plain <nav>: on desktop it's styled to look
    # identical to the old always-expanded sidebar, but on narrow screens
    # player.js collapses it at load, so a long table of contents doesn't
    # push the article itself below the fold -- tapping "Contents"
    # expands/collapses it like the add-article forms' <details> already do.
    # The entries are wrapped in their own .toc-list flex column rather than
    # relying on <details> to lay out its own children: modern browsers wrap
    # everything after <summary> in an internal anonymous box, so a `display:
    # flex` on the <details> itself only flexes [summary, that one wrapper]
    # -- the buttons inside it then fell back to native inline-block flow
    # and packed side-by-side like wrapped text instead of stacking.
    return Details(Summary("Contents"), Div(*items, cls="toc-list"), open=True, cls="toc-sidebar")


def player_bar(voice: str, speed: float) -> Div:
    speed_buttons = [
        Button(
            f"{s}x",
            cls="speed-btn" + (" active" if s == speed else ""),
            data_speed=str(s),
        )
        for s in SPEEDS
    ]
    voice_options = [
        Option(f"{v['name']} ({v['language']})", value=v["id"], selected=(v["id"] == voice))
        for v in VOICES
    ]
    return Div(
        Div(cls="progress-bar", id="progress-bar"),
        Div(
            Button("⏮", id="btn-skip-back", title="Previous sentence (←)"),
            Button("▶", id="btn-play-pause", title="Play/Pause (Space)"),
            Button("⏹", id="btn-stop", title="Stop"),
            Button("⏭", id="btn-skip-forward", title="Next sentence (→)"),
            cls="transport-row",
        ),
        Div(
            Div(*speed_buttons, cls="speed-row", id="speed-row"),
            Select(*voice_options, id="voice-select"),
            cls="settings-row",
        ),
        id="player-bar",
        cls="player-bar",
    )


def article_page(article, body_html: str, toc: list) -> Html:
    resume_banner = Div(
        Span("Continue from where you left off?"),
        Button("Resume", id="btn-resume", cls="btn btn-sm btn-primary"),
        Button("Dismiss", id="btn-dismiss-resume", cls="btn btn-sm"),
        id="resume-banner",
        cls="resume-banner",
        style="display:none",
    )
    voice = article.last_voice or DEFAULT_VOICE
    speed = article.last_speed or DEFAULT_SPEED
    return Html(
        _head(f"{article.title or 'Untitled'} — {APP_NAME}"),
        Body(
            _nav(),
            Div(
                toc_sidebar(toc),
                Main(
                    Div(
                        Div(
                            H1(article.title or "Untitled"),
                            _source_label(article),
                        ),
                        A("Edit", href=f"/article/{article.id}/edit", cls="btn btn-sm"),
                        cls="reader-header",
                    ),
                    resume_banner,
                    Div(NotStr(body_html), id="doc-body", cls="doc-body"),
                    cls="container reader-main",
                ),
                cls="reader-layout",
            ),
            player_bar(voice, speed),
            Audio(
                id="ios-audio-unlock",
                src=SILENT_WAV_DATA_URI,
                loop=True,
                playsinline=True,
                preload="auto",
                style="display:none",
            ),
            Script(
                NotStr(
                    f"window.ARTICLE_ID = {article.id};\n"
                    f"window.LAST_SEGMENT_INDEX = {article.last_segment_index if article.last_segment_index is not None else -1};\n"
                    f"window.INITIAL_VOICE = {voice!r};\n"
                    f"window.INITIAL_SPEED = {speed!r};\n"
                )
            ),
            cls="has-player-bar",
        ),
    )
