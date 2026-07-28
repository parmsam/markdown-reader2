"""Locally-hosted markdown/PDF read-aloud article library.

Entry point: wires together db.py (library persistence), segmentation.py +
render.py (markdown -> segments/TOC/display HTML), tts.py (Kokoro generation +
disk cache), and pdf_ingest.py (PDF -> markdown), behind a FastHTML app served
on the local network (see LEARNINGS.md / CLAUDE.md for the design rationale).
"""
from __future__ import annotations

import os
import re
import socket
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote

from fasthtml.common import (
    FastHTML, FileResponse, JSONResponse, RedirectResponse, Request, Response, serve,
)

import cache
import components as comp
import db
import pdf_ingest
import tts
import url_ingest
from render import render_document

DB = db.get_db()
STATIC_DIR = Path(__file__).resolve().parent / "static"
PORT = int(os.getenv("PORT", 5001))


def _startup():
    tts.load_model()
    threading.Thread(target=cache.gc_orphaned_audio_cache, args=(DB,), daemon=True).start()


def _get_lan_ip() -> str | None:
    """Best-effort LAN-facing IP via the "UDP connect" trick -- no packets are
    actually sent (UDP connect() just picks a route/local address), this
    just asks the OS which local interface/address it would use to reach an
    external host, which is exactly the address other devices on the LAN
    need to reach this server at."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


app = FastHTML(pico=False, on_startup=_startup)


def _derive_title(markdown: str, fallback: str) -> str:
    m = re.search(r"^#{1,6}\s+(.+)", markdown, re.MULTILINE)
    if m:
        return m.group(1).strip()[:200]
    return fallback


# ---------------------------------------------------------------- static files

@app.get("/static/{fname:path}")
def get_static(fname: str):
    path = STATIC_DIR / fname
    if not path.resolve().is_relative_to(STATIC_DIR.resolve()) or not path.exists():
        return Response(status_code=404)
    # Safe to cache forever: components.py's `?v={_STATIC_VERSION}` query
    # param (fixed per-process) changes on every restart, which is the only
    # time these files change (see LEARNINGS.md's iOS Safari stale-cache entry).
    return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/favicon.ico")
def get_favicon_ico():
    # Browsers/tools probe this fixed path directly regardless of the
    # <link rel="icon"> tag in _head() -- serve the same SVG mark there too
    # so it doesn't 404 (browsers go by content-type/sniffing for favicons,
    # not the ".ico" extension in the URL).
    return get_static("favicon.svg")


# ---------------------------------------------------------------- library

@app.get("/")
def get_library(request: Request):
    # Only worth showing when browsing from the same machine -- if you're
    # already on another device's browser you're already using the LAN URL.
    lan_url = None
    if request.client and request.client.host in ("127.0.0.1", "::1"):
        lan_ip = _get_lan_ip()
        if lan_ip:
            lan_url = f"http://{lan_ip}:{PORT}"
    return comp.library_page(db.list_articles(DB), lan_url=lan_url)


@app.get("/add")
def get_add(url: str = "", text: str = "", error: str = "", autofetch: bool = False):
    # `url` (and optionally `autofetch=1`) let a share action hand off a
    # shared link by opening this page directly -- an iOS Shortcut in the
    # Share Sheet (see README's "Mobile: home screen + sharing links in"), or
    # Android's native
    # Share Target (static/manifest.json's share_target, once this app is
    # added to the home screen). Android apps commonly put the shared link in
    # `text` rather than the dedicated `url` field, so fall back to pulling a
    # URL out of that. `error` round-trips a failed /articles/url attempt so
    # the user sees why, with the URL still filled in instead of retyping it.
    if not url and text:
        m = re.search(r"https?://\S+", text)
        if m:
            url = m.group(0)
    return comp.add_article_page(url=url, error=error, autofetch=autofetch)


@app.post("/articles")
def post_article(title: str = "", markdown: str = ""):
    markdown = markdown.strip()
    if not markdown:
        return RedirectResponse("/add", status_code=303)
    final_title = title.strip() or _derive_title(markdown, "Untitled")
    article = db.create_article(DB, title=final_title, markdown=markdown, source_type="paste")
    return RedirectResponse(f"/article/{article.id}", status_code=303)


@app.post("/articles/url")
def post_article_url(url: str = "", use_page_title: bool = False):
    url = url.strip()
    if not url:
        return RedirectResponse("/add", status_code=303)
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = f"https://{url}"

    def _fail(message: str):
        return RedirectResponse(f"/add?url={quote(url)}&error={quote(message)}", status_code=303)

    try:
        page_title, markdown = url_ingest.fetch_article(url)
    except Exception:
        return _fail("Couldn't fetch that page -- it may be down, or blocking automated readers. "
                      "Try again, or paste the content directly instead.")

    markdown = markdown.strip()
    if not markdown:
        return _fail("Fetched that page, but it had no readable content.")

    final_title = (page_title.strip() if use_page_title else "") or _derive_title(markdown, page_title.strip() or "Untitled")
    article = db.create_article(
        DB, title=final_title, markdown=markdown, source_type="url", original_filename=url,
    )
    return RedirectResponse(f"/article/{article.id}", status_code=303)


@app.post("/articles/upload")
async def post_article_upload(request: Request):
    form = await request.form()
    upload = form.get("file")
    if upload is None or not getattr(upload, "filename", None):
        return RedirectResponse("/add", status_code=303)

    filename = upload.filename
    suffix = Path(filename).suffix.lower()
    raw = await upload.read()
    # Unchecked checkboxes submit no field at all, so absence means "off".
    use_filename_as_title = "use_filename_as_title" in form

    def _title_for(markdown: str) -> str:
        stem = Path(filename).stem
        return stem if use_filename_as_title else _derive_title(markdown, stem)

    if suffix in (".md", ".markdown", ".txt"):
        markdown = raw.decode("utf-8", errors="replace")
        article = db.create_article(
            DB, title=_title_for(markdown),
            markdown=markdown, source_type="markdown_file", original_filename=filename,
        )
        return RedirectResponse(f"/article/{article.id}", status_code=303)

    if suffix == ".pdf":
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        try:
            markdown = pdf_ingest.convert_pdf_to_markdown(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        article = db.create_article(
            DB, title=_title_for(markdown),
            markdown=markdown, source_type="pdf", original_filename=filename,
        )
        if pdf_ingest.KEEP_ORIGINAL_PDFS:
            pdf_path = db.DATA_DIR / "pdfs" / f"{article.id}.pdf"
            pdf_path.write_bytes(raw)
            db.set_pdf_path(DB, article.id, str(pdf_path))
        return RedirectResponse(f"/article/{article.id}", status_code=303)

    return RedirectResponse("/add", status_code=303)


@app.get("/article/{article_id}")
def get_article(article_id: int):
    article = db.get_article(DB, article_id)
    if article is None:
        return Response("Not found", status_code=404)
    body_html, doc = render_document(article.markdown)
    return comp.article_page(article, body_html, doc.toc)


@app.get("/article/{article_id}/edit")
def get_article_edit(article_id: int):
    article = db.get_article(DB, article_id)
    if article is None:
        return Response("Not found", status_code=404)
    return comp.edit_article_page(article)


@app.post("/article/{article_id}/edit")
def post_article_edit(article_id: int, title: str = "", markdown: str = ""):
    article = db.get_article(DB, article_id)
    if article is None:
        return Response("Not found", status_code=404)
    markdown = markdown.strip()
    if not markdown:
        return RedirectResponse(f"/article/{article_id}/edit", status_code=303)
    db.update_article_markdown(DB, article_id, markdown)
    if title.strip():
        db.get_articles_table(DB).update({"title": title.strip()}, article_id)
    return RedirectResponse(f"/article/{article_id}", status_code=303)


@app.delete("/article/{article_id}")
def delete_article(article_id: int):
    article = db.delete_article(DB, article_id)
    if article is not None:
        cache.delete_article_cache(article.content_hash, DB)
        if article.pdf_path:
            Path(article.pdf_path).unlink(missing_ok=True)
    return Response(status_code=200)


# ---------------------------------------------------------------- TTS API

@app.get("/api/voices")
def get_voices():
    return JSONResponse(tts.VOICES)


def _segment_text_for(article, segment_index: int) -> str | None:
    from segmentation import segment_document
    doc = segment_document(article.markdown)
    if 0 <= segment_index < len(doc.segments):
        return doc.segments[segment_index].text
    return None


@app.get("/api/tts/{article_id}/{segment_index}")
def get_tts_audio(article_id: int, segment_index: int, voice: str = tts.DEFAULT_VOICE, speed: float = tts.DEFAULT_SPEED):
    article = db.get_article(DB, article_id)
    if article is None:
        return Response(status_code=404)
    text = _segment_text_for(article, segment_index)
    if text is None:
        return Response(status_code=404)
    result = tts.get_or_generate(article.content_hash, segment_index, text, voice, speed)
    if result is None:
        return Response(status_code=422)
    return Response(content=result.wav_bytes, media_type="audio/wav")


@app.get("/api/tts/{article_id}/{segment_index}/timings")
def get_tts_timings(article_id: int, segment_index: int, voice: str = tts.DEFAULT_VOICE, speed: float = tts.DEFAULT_SPEED):
    article = db.get_article(DB, article_id)
    if article is None:
        return Response(status_code=404)
    text = _segment_text_for(article, segment_index)
    if text is None:
        return Response(status_code=404)
    result = tts.get_or_generate(article.content_hash, segment_index, text, voice, speed)
    if result is None:
        return JSONResponse({"duration": 0, "word_timings": []}, status_code=422)
    return JSONResponse({"duration": result.duration, "word_timings": result.word_timings})


@app.post("/api/articles/{article_id}/progress")
async def post_progress(article_id: int, request: Request):
    body = await request.json()
    db.update_progress(
        DB, article_id,
        segment_index=int(body.get("segment_index", -1)),
        voice=body.get("voice", tts.DEFAULT_VOICE),
        speed=float(body.get("speed", tts.DEFAULT_SPEED)),
    )
    return JSONResponse({"ok": True})


@app.post("/api/cache/gc")
def post_cache_gc():
    removed = cache.gc_orphaned_audio_cache(DB)
    return JSONResponse({"removed": removed})


if __name__ == "__main__":
    # Explicit port (rather than letting serve() re-read $PORT itself) so it
    # can never diverge from the PORT the LAN-URL banner above was built with.
    serve(reload=False, port=PORT)
