# CLAUDE.md

Architecture reference for working on this project. See also `README.md` (tech
stack, setup, usage) and `LEARNINGS.md` (why things are built the way they are).

## What this is

A FastHTML web app, run as a single long-lived Python process on your local
network, that maintains a personal library of markdown/PDF articles and reads
them aloud with Kokoro TTS (via `mlx-audio`, Apple Silicon only), with real-time
sentence/word highlighting, a table of contents, and full playback controls.

This is a rewrite of `../markdown-reader` (a Tauri 2 desktop app) as a network-
accessible Python web app with a real persistent library, consolidating logic
that used to be duplicated across TypeScript (the app) and Python (CLI skills)
into one codebase. See `LEARNINGS.md` for the full rationale.

## Module map

```
app.py            FastHTML routes + startup. Thin: every handler calls into one
                   of the modules below and returns FT components / a Response.
db.py             sqlite (via fastlite's Database) persistence for the article
                   library. One table: articles. CRUD helpers only -- no
                   business logic.
segmentation.py   Pure functions: markdown string -> (Segment list, TocEntry
                   list), in a single pass. No I/O, no DB, no TTS. This is the
                   one place block-classification / sentence-splitting logic
                   lives (see LEARNINGS.md for why that matters).
render.py         segmentation.py's output -> display HTML (data-seg/data-type/
                   data-words attributes baked in). No parsing logic of its own
                   beyond markdown-it-py inline/block rendering.
tts.py            Kokoro model singleton (loaded once, at app startup), audio
                   generation with retry/bisect fallback, word-timing
                   estimation, and the cache-aware get_or_generate() entrypoint.
                   This is the ONLY module that imports mlx_audio or calls
                   the model.
cache.py          Disk cache path scheme + orphan GC for generated audio.
pdf_ingest.py     marker-pdf wrapper. Lazily imports marker.* inside the
                   function body -- importing this module must never cost
                   marker's (heavy, occasionally fragile) import chain unless a
                   PDF is actually being converted.
components.py     FT (FastHTML component) builders for every page. No routing,
                   no business logic -- pure view functions taking plain data.
static/player.js  The entire client-side player. No build step, no framework --
                   plain browser JS talking to app.py's JSON/audio endpoints.
static/style.css  Layout + theme (light/dark via prefers-color-scheme and a
                   data-theme override) + highlighting classes.
```

## Data flow for a single "play a segment" request

1. Browser already has the article's segment list baked into the DOM as
   `data-seg`/`data-type`/`data-words` attributes (rendered server-side by
   `render.py` when the article page loaded -- the browser never parses
   markdown itself).
2. `static/player.js` requests `GET /api/tts/{article_id}/{segment_index}` (raw
   WAV bytes) and `GET /api/tts/{article_id}/{segment_index}/timings` (JSON) in
   parallel.
3. `app.py`'s handlers re-derive the segment's plain text via
   `segmentation.segment_document(article.markdown)` (cheap, deterministic --
   never persisted) and call `tts.get_or_generate(content_hash, segment_index,
   text, voice, speed)`.
4. `tts.get_or_generate` checks `cache.py`'s disk cache first
   (`data/audio_cache/{content_hash}/{segment:05d}__{voice}__{speed:.2f}.{wav,json}`).
   On a miss, it acquires the global generation lock, loads the Kokoro model
   (already loaded at startup -- this is just a reference), generates audio
   (with retry/bisect on the known MLX decoder bug), estimates word timings,
   writes the cache files, and returns.
5. `player.js` decodes the WAV via Web Audio's `decodeAudioData`, plays it via
   an `AudioBufferSourceNode`, and schedules word-highlight callbacks against
   the timings JSON.

## Content-hash-keyed cache -- the one invariant to preserve

The audio cache is keyed by `sha256(article.markdown)`, not by article id.
**Never** change this to key by article id alone -- the entire cache
invalidation story (stale audio can never be served after an edit) depends on
the hash changing whenever the content changes. If you add a feature that
mutates `articles.markdown`, make sure it goes through
`db.update_article_markdown()` (which recomputes `content_hash` and resets
`last_segment_index`), not a raw `UPDATE`.

## Adding a new segment type or block type

Everything branches on `Segment.type` in exactly three places, and they must
stay in sync:
1. `segmentation.py`'s `segment_document()` -- where the type is assigned.
2. `render.py`'s `render_document()` -- how that type is displayed.
3. `static/player.js` -- whether that type gets word-level highlighting
   (currently paragraph only) and whether it's skipped during playback
   (currently code only).

## Known constraints (see LEARNINGS.md for the "why")

- Word timings are estimated (character-length weighted), not real forced
  alignment -- Kokoro/mlx-audio doesn't expose per-word timestamps.
- Segmentation is regex/heuristic-based, ported from v1, not a real CommonMark
  AST walk -- unusual constructs (tables, nested lists in blockquotes) may
  segment imperfectly.
- All Kokoro generation is serialized behind one global `threading.Lock` in
  `tts.py` -- fine for single-user LAN use, would need rethinking for
  multi-user concurrent load.
- `render.py`'s markdown-it-py instance has `html_block`/`html_inline`
  disabled -- raw HTML in an article is escaped as literal text, not passed
  through. Do not re-enable this: there's no authentication, so any device on
  the LAN can add content, making raw HTML passthrough a stored-XSS vector.
- Stored markdown is always LF-only (`db.normalize_newlines()` at write time,
  `segmentation.segment_document()` again at read time as defense in depth --
  see LEARNINGS.md for the CRLF bug this fixes). Never bypass
  `db.create_article`/`db.update_article_markdown` to write `articles.markdown`
  directly.
- No authentication -- anyone on your LAN who can reach the port can view/add/
  delete library articles. Acceptable for a personal local-network tool; do not
  expose this port beyond your LAN.
