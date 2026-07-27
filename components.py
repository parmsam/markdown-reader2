"""FT (FastHTML component) builders for every page in the app.

Kept separate from app.py so route handlers stay thin: each route calls one of
these builders and returns the result.
"""
from __future__ import annotations

from fasthtml.common import (
    A, Body, Blockquote, Button, Details, Div, Form, H1, H2, Head, Html, Input,
    Label, Link, Main, NotStr, Nav, Option, P, Script, Select, Span, Style,
    Summary, Textarea, Title,
)

from tts import VOICES, DEFAULT_VOICE, DEFAULT_SPEED

SPEEDS = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]


def _head(title: str):
    return Head(
        Title(title),
        Link(rel="stylesheet", href="/static/style.css"),
        Script(src="/static/player.js", defer=True),
        Script(src="/static/library.js", defer=True),
    )


def _nav():
    return Nav(
        A("Library", href="/", cls="nav-link"),
        A("+ Add article", href="/add", cls="nav-link nav-add"),
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
        _head("Library — Markdown Reader"),
        Body(_nav(), Main(H1("Library"), body, cls="container"), data_theme="auto"),
    )


def _article_row(a) -> Div:
    resume_pct = ""
    if a.last_segment_index is not None and a.last_segment_index >= 0:
        resume_pct = Span("in progress", cls="badge badge-progress")
    filename_span = Span(a.original_filename, cls="article-filename") if a.original_filename else ""
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


def add_article_page() -> Html:
    paste_form = Form(
        Label("Title (optional)", Input(name="title", type="text", placeholder="Derived from content if left blank")),
        Label("Markdown", Textarea(name="markdown", rows=16, placeholder="Paste or write markdown here...", required=True)),
        Button("Add to library", type="submit", cls="btn btn-primary"),
        method="post",
        action="/articles",
        cls="add-form",
    )
    upload_form = Form(
        Label("File (.md, .markdown, .txt, or .pdf)", Input(name="file", type="file", accept=".md,.markdown,.txt,.pdf", required=True)),
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
    return Html(
        _head("Add article — Markdown Reader"),
        Body(
            _nav(),
            Main(
                H1("Add an article"),
                Details(Summary("Paste markdown"), paste_form, open=True),
                Details(Summary("Upload a file"), upload_form),
                cls="container",
            ),
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
        _head(f"Edit {article.title or 'Untitled'} — Markdown Reader"),
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


def toc_sidebar(toc: list) -> Nav:
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
    return Nav(H2("Contents"), *items, cls="toc-sidebar")


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
            Div(*speed_buttons, cls="speed-row", id="speed-row"),
            Select(*voice_options, id="voice-select"),
            cls="player-controls",
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
        _head(f"{article.title or 'Untitled'} — Markdown Reader"),
        Body(
            _nav(),
            Div(
                toc_sidebar(toc),
                Main(
                    Div(
                        Div(
                            H1(article.title or "Untitled"),
                            Span(article.original_filename, cls="article-filename")
                            if article.original_filename else "",
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
