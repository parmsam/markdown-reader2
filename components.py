"""FT (FastHTML component) builders for every page in the app.

Kept separate from app.py so route handlers stay thin: each route calls one of
these builders and returns the result.
"""
from __future__ import annotations

import time

from fasthtml.common import (
    A, Audio, Body, Blockquote, Button, Datalist, Details, Div, Form, H1, H2,
    Head, Html, Img, Input, Label, Link, Main, Meta, NotStr, Nav, Option, P,
    Script, Select, Span, Style, Summary, Textarea, Title,
)

from tts import VOICES, DEFAULT_VOICE, DEFAULT_SPEED

APP_NAME = "Lector"
SPEEDS = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5]

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
        # Web App Manifest (name/icons/display/share_target) -- Android's
        # equivalent of the apple-touch-icon/apple-mobile-web-app-* pair
        # below, plus what lets "Add to Home Screen" register this app as a
        # native Share Target (see README's "Share from your phone").
        Link(rel="manifest", href=f"/static/manifest.json?v={_STATIC_VERSION}"),
        # Address-bar/status-bar tint. Static default here for pre-JS paint;
        # theme.js keeps this in sync with the effective (system or manually
        # toggled) theme afterward.
        Meta(name="theme-color", id="theme-color-meta", content="#ffffff"),
        Meta(name="apple-mobile-web-app-capable", content="yes"),
        Meta(name="apple-mobile-web-app-title", content=APP_NAME),
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


def _build_folder_tree(articles: list) -> tuple[list, dict]:
    """Split articles into (root_articles, tree): root_articles have no
    folder (rendered directly, unlabeled -- so a library that's never used
    folders looks exactly like it did before this feature existed); tree is
    a nested dict keyed by path segment, {"path": "A/B", "articles": [...],
    "children": {...}}, one level per "/" in `folder`. There's no separate
    folders table (see db.py's list_folders docstring), so this tree is
    rebuilt from the articles' own `folder` values every render -- cheap at
    personal-library scale, and it means a folder can never exist here
    without also being reachable via at least one real article."""
    root_articles = []
    tree: dict = {}
    for a in articles:
        if not a.folder:
            root_articles.append(a)
            continue
        level = tree
        node = None
        path_so_far = []
        for seg in a.folder.split("/"):
            path_so_far.append(seg)
            node = level.setdefault(seg, {"path": "/".join(path_so_far), "articles": [], "children": {}})
            level = node["children"]
        node["articles"].append(a)
    return root_articles, tree


def _count_descendants(children: dict) -> int:
    return sum(len(n["articles"]) + _count_descendants(n["children"]) for n in children.values())


def _render_folder_node(name: str, node: dict, all_folders: list[str]) -> Details:
    total = len(node["articles"]) + _count_descendants(node["children"])
    rows = [_article_row(a, all_folders) for a in node["articles"]]
    children = [
        _render_folder_node(child_name, child, all_folders)
        for child_name, child in sorted(node["children"].items())
    ]
    return Details(
        Summary(
            Span(f"\U0001F4C1 {name}", cls="folder-name"),
            Span(f"({total})", cls="folder-count"),
            Button("Rename", type="button", cls="btn btn-sm folder-rename-btn", data_folder_path=node["path"]),
        ),
        Div(*rows, cls="article-list") if rows else "",
        *children,
        open=True,
        cls="folder-group",
    )


def library_page(articles: list, lan_url: str | None = None, notice: str | None = None) -> Html:
    if not articles:
        body = Div(
            P("Your library is empty."),
            A("Add your first article", href="/add", cls="btn btn-primary"),
            cls="empty-state",
        )
    else:
        all_folders = sorted({a.folder for a in articles if a.folder})
        root_articles, tree = _build_folder_tree(articles)
        parts = []
        if root_articles:
            parts.append(Div(*[_article_row(a, all_folders) for a in root_articles], cls="article-list"))
        parts.extend(_render_folder_node(name, node, all_folders) for name, node in sorted(tree.items()))
        body = Div(*parts)

    # Only rendered when app.py detects the request came from localhost --
    # the point is giving you something to copy onto another device (phone,
    # tablet) without having to go dig it out of the terminal that ran
    # start.sh.
    lan_banner = (
        Div(
            Span("On your network: ", cls="lan-banner-label"),
            A(lan_url, href=lan_url, cls="lan-url-link"),
            Button("Copy", type="button", cls="btn btn-sm", id="copy-lan-url", data_url=lan_url),
            cls="lan-banner",
        )
        if lan_url else ""
    )
    notice_banner = Div(notice, cls="notice-banner") if notice else ""

    return Html(
        _head(f"Library — {APP_NAME}"),
        Body(_nav(), Main(H1("Library"), lan_banner, notice_banner, body, cls="container")),
    )


def _source_label(a):
    """original_filename doubles as the source URL for source_type == "url"
    articles, so render it as a link there instead of plain text."""
    if not a.original_filename:
        return ""
    if a.source_type == "url":
        return A(a.original_filename, href=a.original_filename, cls="article-filename", target="_blank", rel="noopener noreferrer")
    return Span(a.original_filename, cls="article-filename")


def _folder_move_form(a, all_folders: list[str]) -> Form:
    options = [Option("— No folder —", value="", selected=not a.folder)]
    options += [Option(f, value=f, selected=(a.folder == f)) for f in all_folders]
    options.append(Option("+ New folder…", value="__new__"))
    return Form(
        Select(*options, cls="folder-select", title="Move to folder"),
        Input(type="hidden", name="folder", value=a.folder or ""),
        method="post",
        action=f"/article/{a.id}/move",
        cls="folder-move-form",
    )


def _article_row(a, all_folders: list[str] | None = None) -> Div:
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
            _folder_move_form(a, all_folders or []),
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


def _folder_field() -> Label:
    return Label(
        "Folder (optional)",
        Input(name="folder", type="text", list="folder-datalist", placeholder="e.g. Notes/Work"),
    )


def add_article_page(url: str = "", error: str = "", autofetch: bool = False, folders: list[str] | None = None) -> Html:
    folder_datalist = Datalist(*[Option(value=f) for f in (folders or [])], id="folder-datalist")
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
        _folder_field(),
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
        _folder_field(),
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
        _folder_field(),
        Button("Upload", type="submit", cls="btn btn-primary"),
        method="post",
        action="/articles/upload",
        enctype="multipart/form-data",
        cls="add-form",
    )
    folder_upload_form = Form(
        Label(
            "Folder",
            Div(
                Input(name="folder_files", type="file", webkitdirectory=True, multiple=True, required=True, id="folder-upload-input"),
                Span("Tap to choose a folder", cls="file-drop-hint"),
                Span("", cls="file-drop-name", hidden=True),
                cls="file-dropzone",
            ),
        ),
        Label(
            "Folder name in library (optional)",
            Input(name="folder_prefix", type="text", list="folder-datalist", id="folder-prefix-input",
                  placeholder="Auto-filled from the picked folder's name"),
        ),
        Button("Upload folder", type="submit", cls="btn btn-primary"),
        P(
            "Subfolders are preserved. Unsupported files (anything but "
            ".md/.markdown/.txt/.pdf) are skipped.",
            cls="form-hint",
        ),
        method="post",
        action="/articles/upload-folder",
        enctype="multipart/form-data",
        id="folder-upload-form",
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
                folder_datalist,
                Details(Summary("Add from a link"), url_form, open=True),
                Details(Summary("Paste markdown"), paste_form, open=not url),
                Details(Summary("Upload a file"), upload_form),
                Details(Summary("Upload a folder"), folder_upload_form),
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
        Div(
            Span(
                "0:00", id="doc-elapsed", cls="playhead-time",
                title="Elapsed across the whole article",
            ),
            Input(
                type="range", id="doc-seek", min="0", max="0", step="0.01", value="0",
                cls="doc-seek", disabled=True,
                aria_label="Jump to a sentence anywhere in the article",
                title="Drag to jump to a sentence anywhere in the article",
            ),
            Span(
                "0:00", id="doc-duration", cls="playhead-time",
                title="Estimated total article duration (refines as more of it is generated)",
            ),
            cls="playhead-row",
        ),
        Div(
            Span(
                "0:00", id="playhead-elapsed", cls="playhead-time",
                title="Elapsed in this sentence",
            ),
            Input(
                type="range", id="playhead-seek", min="0", max="0", step="0.01", value="0",
                cls="playhead-seek", disabled=True, aria_label="Seek within current sentence",
                title="Seek within the current sentence",
            ),
            Span(
                "0:00", id="playhead-duration", cls="playhead-time",
                title="Duration of this sentence",
            ),
            cls="playhead-row",
        ),
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
                        Div(
                            Button(
                                "\U0001F3A7 Audio only", id="audio-only-toggle", type="button",
                                cls="btn btn-sm", title="Hide the article text, just show playback",
                            ),
                            A("Edit", href=f"/article/{article.id}/edit", cls="btn btn-sm"),
                            cls="reader-header-actions",
                        ),
                        cls="reader-header",
                    ),
                    resume_banner,
                    Div(
                        Div("Nothing playing yet", id="now-playing-text"),
                        id="now-playing-panel",
                    ),
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
