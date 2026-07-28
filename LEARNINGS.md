# LEARNINGS.md

Design decisions and lessons learned while building this, for future
maintenance. See `CLAUDE.md` for the architecture map and `README.md` for
setup/usage.

## Real bugs found via actual usage (not just tests) -- CRLF collapsed segmentation

A real user document ("edit after upload doesn't work correctly... it changes
the rendering") turned out to have two compounding causes, both found by
inspecting the actual stored data and re-running `segmentation.py` against it
directly, not by reasoning abstractly:

1. **CRLF line endings collapse the entire document into one segment.**
   `segment_document()`'s block splitter is `re.split(r"\n{2,}", markdown)`,
   which requires two *literal consecutive* `\n` characters. `\r\n\r\n` has an
   `\r` between the two `\n`s, so it never matches -- an un-normalized CRLF
   document (which is exactly what a browser submits for a `<textarea>`'s
   value, regardless of what was typed into it, per the HTML spec, and what
   some Windows-authored files already contain) collapses into a single giant
   unsplit block. The user's real article went from 62 correctly-segmented
   TTS/highlight units down to **1** after being round-tripped through the
   edit form once. Fixed in two places, deliberately redundant: `segmentation.py`
   normalizes CRLF/CR to LF at the top of `segment_document()` (so content
   already stored with CRLF renders correctly immediately, with **no migration
   needed**), and `db.py`'s `normalize_newlines()` normalizes at write time in
   `create_article`/`update_article_markdown` (so stored content stays clean
   going forward instead of relying solely on read-time normalization).
2. **`strip_markdown()`'s block-marker regexes were unanchored.** `[-*+]\s+`,
   `\d+\.\s+`, `>\s+`, `#{1,6}\s+` are meant to strip a single leading marker
   (list bullet, blockquote, heading), but without a `^` anchor they match
   that pattern *anywhere* in the string -- "3 * 4 = 12" silently became "3 4 =
   12", "5 > 3" became "5 3". This bug was inherited verbatim from v1 (both
   the TypeScript and the Python CLI skill have the same unanchored regexes)
   and had gone unnoticed until a test written for an unrelated fix caught it.
   Fixed by anchoring all four to `^` (single match at the start of whatever
   fragment is passed in, matching their actual intent).

**Lesson:** when a bug report mentions "rendering changed" or similar vague
symptoms, pull the actual stored data and run the pure functions against it
directly (`segment_document(real_markdown)`) before guessing at causes from
the code alone -- the segment count (62 -> 1) immediately pointed at block
splitting rather than any of several more speculative theories (inline
markdown loss, TOC drift, etc.) that turned out to be real but secondary.

## Paragraph/blockquote formatting: preserve markdown in `raw_text`, but carefully

Initially, paragraph and blockquote segments only ever displayed their plain,
fully-stripped `text` (matching v1's carried-forward behavior, see below) --
so bold/italic/links never rendered even when the source had them. Fixed by
splitting sentences from the *raw* (markdown-intact) block for `raw_text`,
which `render.py` renders through `markdown-it-py`'s inline renderer, while
`text` (used for TTS and word-highlighting) is still computed the old,
proven-safe way: `strip_markdown()` on the *whole block first*, then split
into sentences. These two splits are independent (`segmentation.py`'s
`_sentence_pairs()`) and only paired together when they agree on sentence
count; if they ever disagree, `raw_text` falls back to the plain `text` for
every sentence in that block. This guarantees `text` is never affected by the
richer `raw_text` path, and a raw fragment can never be misattributed to the
wrong sentence.

**Real regression found while implementing this** (via the same real user
document): a single `*…*` emphasis run wrapping *two full sentences* gets
split in half by sentence-boundary splitting -- each half keeps only one of
the two `*` delimiters. Rendering an unmatched delimiter as standalone
markdown doesn't fail, it just prints the stray `*` literally, which looks
more broken than the old flatten-everything-to-plain-text behavior. Fixed
with `render.py`'s `_renders_safely_as_inline_markdown()`: before rendering a
sentence's `raw_text` as markdown, check that `**`/`__`/backtick counts are
even and single `*`/`_` counts are even; if not, render the (guaranteed-clean)
`text` field instead, escaped, for that one sentence. A false positive here
(a genuine literal odd-count character, e.g. "3 * 4 = 12") just means that
one sentence renders as plain text instead of attempting markdown -- safe
either way, since there's no actual emphasis to lose in that case.

## No CDN dependencies -- htmx was never actually wired up, and that's fine

The Delete button originally used `hx-delete`/`hx-confirm` attributes, but
FastHTML's `htmx=True` default only auto-injects the htmx `<script>` tag into
its *own* auto-generated page wrapper -- which never applies here, since every
page in this app returns a fully custom `Html(Head(...), Body(...))` tree
(see `components.py`'s `_head()`). Nothing was including htmx.js at all, so
the attributes were inert and Delete silently did nothing.

Rather than add the missing `<script src="https://cdn.jsdelivr.net/.../htmx.js">`
tag, Delete was reimplemented as ~15 lines of plain `fetch()` in
`static/library.js`. This app's whole premise is running fully on-device with
no cloud dependency (see README's tech-stack table) -- depending on a CDN for
one button's confirm-and-delete behavior would silently break the moment the
LAN has no internet access, which directly contradicts that premise. If a
future feature genuinely needs htmx-style partial-page swaps, wire up
`hx-boost`/htmx deliberately (and bundle htmx.js as a local static file rather
than relying on FastHTML's CDN default) rather than assuming the framework's
defaults are already wired in -- they aren't, once you bypass its automatic
page wrapper.

## Why this exists: v1 was a desktop app, not a web app

`../markdown-reader` (v1) already built almost this exact feature set, but as a
Tauri 2 desktop app (Rust + React/TypeScript) that only ever holds one document
in memory -- no library, no persistence beyond a localStorage resume-position
hack keyed by a content hash. It also had segmentation logic duplicated in two
places (TypeScript in the app, Python in a CLI skill), which drifted: a real bug
(thematic breaks read aloud literally, backslash-escapes surviving into
narration, punctuation-only lines being narrated) was fixed in the Python CLI
skill first and had to be manually re-applied to the TypeScript version later
(v1 commit `4053f7c`). Moving to a single Python web app removes the
duplication entirely -- there is now exactly one segmentation module used by
every code path.

## Unified segmentation + TOC in one pass

v1's TypeScript segmenter computed the TTS segment list and the table of
contents as two independent passes over the same markdown. They happened to
agree on heading order because both walk headings in document order over the
same source -- but that agreement was coincidental, not structural. A heading
segment that got filtered out (e.g. it was empty after stripping) could silently
desync the two passes.

`segmentation.py`'s `segment_document()` fixes this by construction: a
`TocEntry` is only ever appended inside the exact same `if plain and
has_speakable_content(plain):` branch that appends its corresponding heading
`Segment`, in the same loop iteration. A `TocEntry` referencing a
nonexistent/filtered heading is now structurally impossible, not just
empirically rare. `tests/test_segmentation.py` pins this guarantee directly
(`test_toc_never_references_a_filtered_heading`), not just the individual
ported bug fixes.

## Why generated audio is cached to disk, keyed by content hash

This app is a persistent library, not an ephemeral single-document viewer like
v1 -- the same article gets replayed, potentially from multiple devices on the
LAN. Regenerating audio via Kokoro every single time (as v1's per-request Tauri
subprocess did) wastes real time (a first Kokoro call is several seconds; MLX
JIT-compiles the graph on first use per process).

The cache key is `sha256(article.markdown)` + segment index + voice + speed --
**not** article id. This means editing an article's content automatically
invalidates its old cached audio with zero explicit invalidation code: the hash
changes, so playback lands in a fresh, empty cache directory. The old directory
becomes an orphan (referenced by no article row) rather than actively wrong,
and `cache.gc_orphaned_audio_cache()` sweeps orphans on startup, on demand, and
synchronously when an article is deleted.

**Real bug hit during this pass:** the cache path builder originally used
`Path(...).with_suffix(".wav")` on a base path that already contained a `.` from
the speed component (e.g. `..._1.00`). `Path.with_suffix()` treats `.00` as an
*existing* suffix and replaces it, silently truncating `..._1.00` into
`..._1.wav` -- which meant speed `1.0` and speed `1.5` (`..._1.50` -> `..._1.wav`)
collided onto the *same* cache file. Playing back at a different speed would
have silently served audio generated at the wrong speed. Fixed by building
filenames via plain string concatenation instead of `Path.with_suffix()`. Any
future change to the cache filename scheme should avoid `with_suffix()`/
`with_name()` on a stem that can itself contain a literal dot.

## Why Kokoro generation is serialized behind one global lock

Kokoro/MLX uses the machine's shared GPU/ANE resource. Rather than reason about
MLX's thread-safety under concurrent `model.generate()` calls, `tts.py` holds
one process-wide `threading.Lock` for the entire "check cache -> generate if
missing -> write cache" critical section. The practical cost: lookahead
prefetch for upcoming segments waits behind whatever is currently generating.
For a single-user LAN app this is invisible in practice; it would need
rethinking only if this ever became a genuinely multi-user concurrent service.

## Word timing is estimated, not real forced alignment

Kokoro (via `mlx_audio.tts`) does not expose per-word timestamps through its
public API -- `model.generate()` yields whole-segment audio chunks. There is a
per-*phoneme* frame-count array (`pred_dur`) inside the decoder, but mapping
that back to word boundaries reliably would be a much larger undertaking than
this project needs. `tts.estimate_word_timings()` instead distributes a
segment's real (measured) duration across words proportionally to character
count, with small multipliers for trailing `.!?` and `,;:` to approximate
natural pauses, then rescales so the total matches the actual audio duration.
This is a deliberate approximation carried over from v1's CLI skills -- good
enough for smooth-looking highlighting, not sample-accurate.

## Client-side player: the generation-counter race guard is load-bearing

`static/player.js` ports v1's `usePlayer.ts` design almost directly, including
a monotonic `gen` counter incremented on every play/pause/stop/skip/jump/
speed/voice change. Every scheduled `setTimeout` and every `await` continuation
checks `gen !== myGen` before touching shared state. Without this, a user who
rapidly skips or changes speed/voice leaves behind stale timers/fetches from
the *previous* session that can resurrect highlighting or restart audio after
the user has already moved on. Do not remove or "simplify" this guard when
touching `player.js` -- it's the fix for a real class of bug, not defensive
boilerplate.

**Real bug hit during this pass (more serious than it looks):** the original
`fetchSegment()` used a plain `Set` to track "already loading" indices and
`return`ed immediately (resolving with nothing) if a fetch for that index was
already in flight. `playSegment()` relies on `await fetchSegment(index)`
actually waiting for the result before checking the cache -- but since
lookahead prefetch (`startSession`'s and `playSegment`'s own `for` loops) fires
`fetchSegment()` for the same index moments before `playSegment` awaits it,
the *second* call's guard saw "already loading," returned instantly, and
`playSegment` checked an empty cache immediately afterward. Every segment was
therefore treated as "failed to generate" and skipped, and an entire document
would silently blaze through in milliseconds with no audio and no highlighting
-- with **zero console errors**, because nothing ever actually threw. This was
only caught by manually instrumenting `playSegment()` and watching real browser
state over time; a `console.error` audit alone would have missed it since the
"skip a segment that failed to generate" path is a legitimate, silent code path
by design (used for segments that really do fail Kokoro's decoder even after
the retry/bisect fallback).

Fixed by replacing the `Set` with a `Map<index, Promise>`: a second caller for
the same in-flight index now gets and awaits the *same* promise instead of a
fire-and-forget no-op. If you touch the prefetch/fetch logic again, preserve
this: any "is this already happening" guard for async work that other code
paths might `await` must hand back the actual in-flight promise, not just a
boolean-shaped bail-out.

## PDF support is intentionally best-effort, not core

marker-pdf (OCR + layout parsing) was chosen over a lighter alternative
(`pymupdf4llm`, which only reads a PDF's embedded text layer) specifically
*because* the user explicitly said PDF is a secondary feature and they're
willing to pre-convert externally as a manual fallback if marker-pdf's
dependency chain (`transformers`/`surya-ocr`, shared with `mlx-audio`) breaks
again the way it did in v1 (commit `981c169`). `pdf_ingest.py` lazily imports
`marker.*` inside the function body specifically so that a marker-pdf import
failure can never take down the rest of the app (paste/markdown-upload/
playback) -- it only surfaces when a PDF is actually uploaded.

## Server-side rendering avoids a second markdown parser

There's no client-side build step (no React/Vite) and therefore no client-side
markdown parser. `render.py` renders the whole article once, server-side, per
`GET /article/{id}`, using `markdown-it-py` (already a transitive dependency of
the environment, added as an explicit one here). Headings, code blocks, and
list items map one segment to one raw markdown line/block, so they get full
inline-markdown rendering (bold/links survive). Paragraphs and blockquotes can
split one block into multiple sentence-level segments; matching v1's actual
(not idealized) behavior, those render as plain escaped-text spans rather than
through the markdown renderer, since `split_sentences()` operates on already-
stripped plain text and there's no reliable way back to the original markdown
span for one sentence within a run of prose. A fix (rendering each sentence's
inline HTML separately) is possible but has its own edge case -- a bold/link run
spanning a sentence boundary would render oddly split -- and wasn't needed for
this pass.

## Environment: pinned to Python 3.12, not the system's 3.14

The system's default Python (3.14, Framework install) is what v1's Tauri
sidecar hardcodes and what the CLI skills assume. `spacy` (a hard dependency of
`misaki`, which Kokoro's English G2P pipeline requires) has no published wheels
for `cp314` as of this build -- only up to `cp313`. Rather than fight that, this
project's `.python-version` pins `3.12`, which has full wheel coverage for the
entire stack (`mlx`, `mlx-audio`, `torch`, `spacy`, `marker-pdf`). If a future
`uv sync` fails with a "no wheel for this platform" error on `spacy` or a
similar heavy dependency, check whether the pinned Python version has moved
forward faster than that dependency's wheel availability, rather than assuming
the dependency itself is broken.

Full misaki runtime dependency list that had to be made explicit in
`pyproject.toml` (none of these are transitively pulled in by `mlx-audio`
alone): `num2words`, `phonemizer-fork` (provides the `phonemizer` import name --
note the PyPI package name and the importable module name differ), `spacy`,
`espeakng-loader`, and the `en_core_web_sm` spaCy model itself, which isn't on
PyPI in installable form and has to be pulled from its GitHub wheel release
directly (`en_core_web_sm @ https://github.com/explosion/spacy-models/...`).

## iOS Safari: silent on the ring/mute switch, and a stale-JS red herring

Playback worked fine on the same Mac serving the app, but was completely
silent on an iPhone on the same LAN (page loaded fine, TTS fetches succeeded).
Root cause: `player.js` only ever uses the raw Web Audio API
(`AudioBufferSourceNode` -> `ctx.destination`), never an HTML `<audio>`/
`<video>` element. iOS Safari puts pages like that into the "ambient" audio
session category, which the hardware ring/silent switch mutes -- this is
independent of in-app/system volume and throws no error, so it looks
identical to "nothing is happening." Fixed by adding a hidden, looping, silent
`<audio>` element (`components.py`'s `SILENT_WAV_DATA_URI`, a tiny inline data
URI so no extra network request) and playing it on the page's first
`pointerdown`/`keydown` (`player.js`'s `unlockAudio()`) -- playing *any* real
`<audio>` element flips the whole page into the "playback" category for the
rest of the session, after which the existing `AudioBufferSourceNode` output
becomes audible with the switch on silent too.

First test of the fix looked like it hadn't worked -- because it hadn't been
tested yet: the phone was still showing the pre-fix `player.js` from Safari's
cache. `/static/*` had no `Cache-Control` header at all, so browsers fall back
to caching heuristics that can easily keep an old JS file around across a
same-URL redeploy. A closed-tab/fresh-load retest immediately confirmed the
real fix worked. Now fixed at the root: `app.py`'s `get_static()` sends
`Cache-Control: public, max-age=31536000, immutable`, and `components.py`
appends `?v={_STATIC_VERSION}` (a timestamp fixed at process start) to every
static asset URL -- so a restart always busts the cache, and between restarts
the far-future header lets the browser skip the network entirely.

**Lesson:** "does the fix work" and "am I actually testing the fix" are
separate questions on iOS Safari specifically -- always rule out a stale
cached asset (closed tab / private tab / cache-busted URL) before concluding
a fix didn't work, especially for anything under `static/`.

## `display: flex` on a `<details>` element doesn't flex its real children

Made the TOC sidebar collapsible on mobile by changing `toc_sidebar()` from a
plain `<nav>` to `<details><summary>Contents</summary>...entries...</details>`,
reusing `.toc-sidebar`'s existing `display: flex; flex-direction: column`.
Desktop rendering broke: entries after a certain point started packing
side-by-side instead of stacking, looking like text wrapping mid-sentence.
Root cause verified with a headless-browser bounding-box dump (`getBoundingClientRect()`
on every `.toc-entry`, comparing x/y across items) rather than guessing from
the CSS: modern browsers render everything after a `<details>`'s `<summary>`
inside one internal anonymous box. Setting `display: flex` on the `<details>`
itself only flexes *that box* (as one item, alongside the summary) -- the
buttons inside it fall back to their native `inline-block` flow and wrap like
words in a paragraph, which is why short entries (e.g. "On using AI",
"Domains") ended up on the same line while longer ones didn't. Fixed by never
letting `<details>` lay out real content directly: entries are wrapped in an
explicit `Div(*items, cls="toc-list")`, and the flex column rules moved onto
`.toc-list` instead of `.toc-sidebar`. `.toc-sidebar` now only owns sizing/
position/overflow; `<details>`/`<summary>` are just the disclosure chrome
around it.

**Lesson:** if `<details>` needs to do anything beyond default disclosure
behavior (flex/grid layout of its content, animation, etc.), give the content
its own wrapper element and style that -- don't style the `<details>` itself
and assume its children behave like normal flex/grid items.

## Nested/wrapped list items: every line was treated as its own item

`segmentation.py`'s list branch turned *every line* of a list block into its
own Segment/`<li>`, with no concept of an item spanning more than one line.
Two real breakages followed: an indented sub-bullet ("  - child") kept its
marker as literal text -- `_LIST_ITEM_LINE_RE`'s marker match requires
position 0, so leading indentation meant it just wasn't recognized as a
marker at all -- and a plain wrapped continuation line (no marker, no blank
line before it) became a bogus extra bullet instead of part of the item
above it. Fixed by grouping lines into items *before* creating segments: a
line starting with a marker begins a new item, any other line attaches to
whichever item is currently being built. Added `Segment.list_depth` (indent
width // 2, a heuristic like the rest of this segmenter) so `render.py` can
rebuild genuine nested `<ul>`/`<ol>` markup (a `<li>` stays open, deeper
items nest inside it, popped via a small depth-tracking stack) instead of a
flat list of `<li>`s -- deciding ordered-vs-unordered per depth level rather
than once for the whole list, so mixed nesting (numbered list with bulleted
sub-items) renders correctly too.

**Lesson:** this segmenter's other "one block -> N segments" branches
(blockquote, paragraph) already had a real per-item grouping step
(`_sentence_pairs`) before creating segments; the list branch was the one
place still naively mapping "one line -> one segment" 1:1, which is exactly
where multi-line items broke. When adding a new per-item block type, group
into logical items *first*, then segment each -- don't assume a source
line is a reasonable unit on its own.

## Folders: a path string on each article, not a folders table

`articles.folder` is a single nullable TEXT column holding a "/"-joined path
("Notes/Work"), not a foreign key into a separate `folders` table with
parent/child rows. This means a folder only exists at all by virtue of at
least one article currently pointing at that path -- `db.list_folders()`
just does `SELECT DISTINCT folder`, and `library_page`'s nested `<details>`
tree (`_build_folder_tree`) is rebuilt from that on every render. The
tradeoff: an empty folder can't be "kept around" with zero articles in it
(there's nothing to persist it), and `rename_folder()` has to walk and
rewrite every affected article's `folder` column (a prefix-match update)
rather than changing one row. Chosen anyway because it needed no schema
beyond one column, no join to compute a library listing, and "empty folder
you're deliberately keeping around for later" isn't something this app's
actual use case (organizing articles you already have) needs.

Existing `data/library.db` files predate this column, and this app has no
migration framework -- `db.get_db()` checks `articles.columns` and calls
`.add_column("folder", str)` itself if missing, rather than assuming
`if_not_exists=True` on `.create()` (which only handles a table not existing
yet at all, never a column added to one that already does).

## Folder upload: relative paths only survive a hand-built multipart request

`<input type=file webkitdirectory multiple>` gives the browser's JS each
picked file's directory location via `file.webkitRelativePath`
("MyNotes/sub/note.md") -- but that's a JS-only File property. A plain
`<form>` submission of that input sends the server only each file's bare
basename in the multipart Content-Disposition filename; the relative path
never crosses the wire. static/upload.js's folder-upload handler works
around this by intercepting the form's `submit`, building the `FormData` by
hand, and passing `file.webkitRelativePath` as `FormData.append`'s third
(filename-override) argument for every file -- that value *is* preserved
through to Starlette's `UploadFile.filename` server-side, which
`post_articles_upload_folder` (app.py) then splits back into directory path
+ basename to reconstruct the folder structure.

**Lesson:** if a file input's metadata beyond the raw bytes matters
server-side (relative path, capture timestamp, whatever), check whether a
plain native form submission actually transmits it before building UI
around the assumption that it does -- several File/`<input>` properties are
JS-visible-only and need an explicit fetch()+FormData workaround to reach
the server at all.

## A list right after other content, no blank line, all became one paragraph

Found via a user's real document: a bold "label" line directly above its
bullets with no blank line between them (`**What this covers:**` then
`- one` on the very next line -- a very common way people actually write
markdown). `segment_document()`'s block splitter only splits on a *blank*
line, so the label and the whole list stayed one block; classification only
looks at the block's first line, which here is the label, not a marker --
so everything fell into the paragraph branch, spoken and rendered as one
run-on paragraph with literal "- " characters instead of a heading-like line
plus a real bulleted list. CommonMark handles this ("a list can interrupt a
paragraph") but this segmenter's classification never had a notion of
"the block *starts* as something else but a list begins partway through."

Fixed with a pre-pass, `_split_prose_and_list()`: if a line with an
*un-indented* marker appears after the first line of a block, split there --
everything before is its own block, the marker onward is its own (list)
block. Deliberately checks the strict `_LIST_ITEM_RE` (column 0 only), not
the indentation-tolerant `_LIST_ITEM_LINE_RE` used inside the list branch
itself -- using the tolerant one here was the first attempt, and it broke
nested lists: an indented sub-item is *not* a new list interrupting
something else, it's a continuation of the list already underway, and
splitting there fed each half through independent `.strip()`s that silently
ate the leading indentation encoding its nesting depth. Caught immediately
by the existing nested-list tests -- exactly why those were worth having
beyond the bug they were originally written for.

**Lesson:** when a heuristic needs to distinguish "a new thing starting" from
"a continuation of the thing already in progress," reuse of a
continuation-tolerant regex for the *starting* check is an easy way to
conflate the two. Keep the strict and tolerant variants distinct and use
each only for the question it actually answers.

## Document-wide playhead: estimated, not exact, and why

The player generates and plays audio one segment at a time, lazily -- there
is no whole-document duration to know without either generating every
segment upfront (slow for a long article, defeats the point of lazy
generation) or estimating. The playhead's elapsed/total time labels are a
word-count-based estimate (`~150wpm / speed`) per segment, refined to the
*real* duration the moment each segment actually gets generated --
`recordRealDuration()` also back-calibrates the words/sec rate itself from
that real data, so later not-yet-generated estimates get more accurate as
you listen, without ever touching a segment's own real duration once known.
A voice/speed change invalidates every real duration (they were measured at
the old one), so `resetDurationEstimates()` -- called alongside the existing
`cacheMap.clear()` in `setSpeed()`/`setVoice()` -- reverts every segment back
to a fresh estimate rather than leaving stale real numbers in the total.

First cut kept the seek bar scoped to the current segment only, reasoning
that a document-wide scrubber would mean seeking to an arbitrary *time*,
which implies generating a not-yet-heard sentence's audio on the spot at
some precise mid-sentence offset. Revisited: "jump to a chunk" doesn't
actually require that precision -- landing on the nearest *segment*
(`segmentIndexAtTime()`, walking cumulative `segmentDurations` rather than
segment count so it roughly tracks actual speaking time) and calling the
already-existing `jumpTo()` is exactly what clicking a TOC entry or a
paragraph in the document already does, on-demand generation included. So
there are two bars now: `#doc-seek` (document-wide, coarse -- jumps to the
nearest segment on release) above `#playhead-seek` (the original, current-
segment-only, sample-accurate scrub). Each with its own elapsed/duration
labels -- four numbers total, since collapsing them into one pair asking
"elapsed/total" to mean two different scales at once (document position
via the numbers, segment position via the bar) read as inconsistent.

**Debugging note:** verifying this against real playback was blocked by the
sandboxed headless-Chromium test environment's `AudioContext.currentTime`
not advancing in real time (confirmed with a bare `new AudioContext()` and
zero app code -- 1.5s of wall-clock time produced ~0.005s of audio-clock
time). Not a code bug: a previously-committed, previously-verified-working
version of this same player showed the identical stall when tested in the
same session. When live audio timing can't be exercised, verify the pure
calculation logic in isolation (a plain Node script reimplementing the
formulas, no browser needed) instead of concluding the feature is broken.

## Per-folder sort: inherited by default, one SQL query isn't enough

Each folder can now have its own sort, independent of its siblings, that
falls back to its nearest ancestor's own sort (and ultimately the global
"Sort by") when unset -- not "every folder defaults to the global setting,"
but a real inheritance chain, so setting a parent folder's sort also affects
any child that hasn't overridden it itself.

Storing the override needed an actual table (`folder_sort`, path -> sort key)
-- the first time a folder has a real row anywhere, since otherwise (per
`list_folders`'s docstring) a folder only exists implicitly via articles'
`folder` field. Both `rename_folder` and `delete_folder` needed the exact
same prefix-rewrite/prefix-delete treatment already applied to articles
extended to this table too, or a renamed/deleted folder would silently leave
behind an orphaned override under its old path.

The bigger implication: `db.list_articles(sort=...)` runs one `ORDER BY` for
the whole library, which can only ever express *one* order -- fine when
every folder shares the global sort, not sufficient once folders can
disagree with each other. `components.py` now does two passes: the DB query
still provides a reasonable default top-to-bottom order, but
`_render_folder_node` re-sorts each folder's own direct articles in Python
(`_sort_articles`, one function mirroring `db.py`'s `SORT_OPTIONS` per
criterion) using that folder's own *effective* (inherited-or-overridden)
sort, and passes that effective sort down as the inherited default for its
children. Folder ordering among siblings uses the same effective-sort value
at whatever level they're siblings at, via the already-existing
`_sorted_folder_entries`.

**Lesson:** "sort the whole page" and "let different parts of the page sort
independently" are different enough problems that the second one usually
can't be satisfied by parameterizing the same one-query mechanism the first
one uses -- it needs its own pass over already-fetched data instead.

## Kebab menus: preventDefault() cancels a popovertarget button's own popover

Collapsed the article-row (move/delete) and folder-header (sort/rename/
delete) actions behind a single "⋯" button each, using the native Popover
API (`popover` + `popovertarget`) rather than a hand-rolled dropdown --
click-outside dismissal, Escape-to-close, and top-layer stacking all come
free. A folder's kebab button lives inside its `<summary>`, which meant the
same problem every other interactive element in a folder header already
had: a click there also toggles the `<details>` open/closed.

The existing fix for that (used for Rename/Delete/the sort `<select>`) was
`event.preventDefault()` in a delegated click listener. Tried the same thing
here first -- and it broke the popover: `preventDefault()` on a
`popovertarget` button's click cancels *that* button's own default action
(showing its popover) exactly the same way it cancels `<summary>`'s toggle,
since both are driven by the same click event. Confirmed with a minimal
isolated repro (a bare `<details>`/`<summary>`/popovertarget-button page,
no app code) before trusting it: `preventDefault()` -> popover stays
closed; `stopPropagation()` alone -> `<details>` doesn't toggle *and* the
popover opens, because it only stops the click from bubbling up to
`<summary>`, without touching the click's default action at all.

**Lesson:** "prevent an unwanted side effect of a click" and "prevent that
click from doing anything else" are different asks -- `preventDefault()`
answers the second one (cancels *every* default action tied to that event,
not just the one you're thinking about), `stopPropagation()` answers the
first (only keeps the event from reaching handlers on ancestors). Reach for
`preventDefault()` out of habit and you can silently break a *different*
default action on the same element you didn't mean to touch -- worth an
isolated repro when a fix like this doesn't behave as expected, rather than
guessing further from inside the full app.

## Folder delete: reversed from "safe" (ungroup) to Finder-style (destructive)

`db.delete_folder()` originally only cleared `folder` on every article
inside the folder, moving them back to the library root -- deliberately, by
design: since a folder is just a path string (see "Folders: a path string on
each article" above), the reasoning was that "deleting" one could only ever
mean dissolving the grouping, never destroying content, and the docstring
said so explicitly.

That reasoning was correct about the implementation but wrong about what
"Delete" on a folder should mean to someone using the app: after clicking
Delete on a real folder of 78 articles expecting them gone, the user got
them back at the root instead -- silently no data loss, but not what "Delete"
means anywhere else (Finder, Explorer, this app's own article-row Delete).
Confirmed via explicit follow-up that they wanted the destructive behavior,
not the safe one, and that it should apply going forward as the *default*
Delete, not a separate second option next to a preserved safe one.

`db.delete_folder()` was replaced with `db.get_articles_in_folder()` (read-
only lookup) + `db.clear_folder_sort_overrides()`; `post_folder_delete` in
app.py now loops the folder's articles through the same per-article cleanup
`DELETE /article/{id}` already used (db row + `cache.delete_article_cache` +
pdf file), so a folder's "container" is destroyed the same way single
articles always were -- there's no longer a code path where "delete" on
anything in this app means "keep the content, lose the label." The confirm()
dialog now names the article count and says "permanently delete," replacing
the old "will NOT be deleted" wording.

**Lesson:** "safe by design" is a property of an implementation, not
automatically the right product decision -- a delete that silently
downgrades to a no-op-on-content because the underlying data model makes
that easy is still a surprise if it doesn't match the verb's meaning
everywhere else in the app. When a real usage incident reveals the gap,
prefer changing the default to match user expectation (with a clear, count-
specific confirm dialog for the newly-real risk) over keeping the safe
behavior and bolting a second "actually delete" option next to it -- one
unambiguous Delete beats two similarly-named buttons with different blast
radii.
