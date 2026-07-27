"""Locally-hosted markdown/PDF read-aloud article library.

Entry point: wires together db.py (library persistence), segmentation.py +
render.py (markdown -> segments/TOC/display HTML), tts.py (Kokoro generation +
disk cache), and pdf_ingest.py (PDF -> markdown), behind a FastHTML app served
on the local network (see LEARNINGS.md / CLAUDE.md for the design rationale).
"""
from __future__ import annotations

import re
import tempfile
import threading
from pathlib import Path

from fasthtml.common import (
    FastHTML, FileResponse, JSONResponse, RedirectResponse, Request, Response, serve,
)

import cache
import components as comp
import db
import pdf_ingest
import tts
from render import render_document

DB = db.get_db()
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _startup():
    tts.load_model()
    threading.Thread(target=cache.gc_orphaned_audio_cache, args=(DB,), daemon=True).start()


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
    return FileResponse(path)


# ---------------------------------------------------------------- library

@app.get("/")
def get_library():
    return comp.library_page(db.list_articles(DB))


@app.get("/add")
def get_add():
    return comp.add_article_page()


@app.post("/articles")
def post_article(title: str = "", markdown: str = ""):
    markdown = markdown.strip()
    if not markdown:
        return RedirectResponse("/add", status_code=303)
    final_title = title.strip() or _derive_title(markdown, "Untitled")
    article = db.create_article(DB, title=final_title, markdown=markdown, source_type="paste")
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
    serve(reload=False)
