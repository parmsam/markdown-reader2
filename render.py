"""Server-side markdown -> display HTML, per block, wired to the same segment
indices segmentation.py produces for TTS/highlighting.

There's no client-side markdown parser in this app (no React/build step) -- the
whole document is rendered once, server-side, per article view. Each rendered
element carries `data-seg`/`data-type` for every Segment it corresponds to, so
static/player.js only ever needs to look up `[data-seg="N"]` in the DOM; it never
parses markdown or manages a virtual DOM itself.

Every segment type renders its `raw_text` (markdown intact -- bold/links/code/etc
survive) through markdown-it-py's inline renderer; only the code block's fenced
content is shown verbatim/escaped rather than markdown-rendered. Paragraph and
blockquote segments are one sentence each (see segmentation.py), so this is a
per-sentence inline render, not a whole-block one. Paragraph segments additionally
carry `data-words` (derived from the plain, stripped `text` -- not `raw_text`) so
the player can swap in per-word spans only while that segment is the active one,
then restore the original (nicely-formatted) HTML afterward.
"""
from __future__ import annotations

import html
import json
import re
from itertools import groupby

from markdown_it import MarkdownIt
from markdown_it.rules_inline.state_inline import Delimiter, StateInline

from segmentation import Segment, SegmentedDocument, segment_document

# html_block/html_inline disabled: this app has no authentication (see
# CLAUDE.md/README.md), so any device on the LAN can add content, and PDF/
# pasted content is not a trusted input. CommonMark's default `html=True`
# passes raw HTML straight through into the page unescaped -- a stored-XSS
# vector (e.g. a pasted "<script>...</script>" would execute for anyone
# viewing the article). Disabling these two rules makes markdown-it-py
# escape raw HTML as literal text instead, while leaving normal markdown
# (bold/links/code/etc) fully intact.
_md = MarkdownIt("commonmark").disable("html_block").disable("html_inline")


def _mark_tokenize(state: StateInline, silent: bool) -> bool:
    """Parse Obsidian-style ==highlighted text== into a <mark> span.

    markdown-it-py's "commonmark" preset ships a `strikethrough` rule for
    ~~text~~ but doesn't enable it; this is that same rule (doubled-delimiter,
    balance_pairs-based, so bold/italic can nest inside) ported from '~' to
    '=' and 's'/<s> to 'mark'/<mark>, since there's no "mark" plugin in
    markdown-it-py or mdit_py_plugins to reuse.
    """
    start = state.pos
    ch = state.src[start]
    if silent or ch != "=":
        return False

    scanned = state.scanDelims(state.pos, True)
    length = scanned.length
    if length < 2:
        return False

    if length % 2:
        token = state.push("text", "", 0)
        token.content = ch
        length -= 1

    i = 0
    while i < length:
        token = state.push("text", "", 0)
        token.content = ch + ch
        state.delimiters.append(
            Delimiter(
                marker=ord(ch),
                length=0,
                token=len(state.tokens) - 1,
                end=-1,
                open=scanned.can_open,
                close=scanned.can_close,
            )
        )
        i += 2

    state.pos += scanned.length
    return True


def _mark_postprocess_delims(state: StateInline, delimiters: list[Delimiter]) -> None:
    lone_markers = []
    for start_delim in delimiters:
        if start_delim.marker != ord("=") or start_delim.end == -1:
            continue
        end_delim = delimiters[start_delim.end]

        token = state.tokens[start_delim.token]
        token.type = "mark_open"
        token.tag = "mark"
        token.nesting = 1
        token.markup = "=="
        token.content = ""

        token = state.tokens[end_delim.token]
        token.type = "mark_close"
        token.tag = "mark"
        token.nesting = -1
        token.markup = "=="
        token.content = ""

        if (
            state.tokens[end_delim.token - 1].type == "text"
            and state.tokens[end_delim.token - 1].content == "="
        ):
            lone_markers.append(end_delim.token - 1)

    while lone_markers:
        i = lone_markers.pop()
        j = i + 1
        while j < len(state.tokens) and state.tokens[j].type == "mark_close":
            j += 1
        j -= 1
        if i != j:
            state.tokens[i], state.tokens[j] = state.tokens[j], state.tokens[i]


def _mark_postprocess(state: StateInline) -> None:
    _mark_postprocess_delims(state, state.delimiters)
    for meta in state.tokens_meta:
        if meta and "delimiters" in meta:
            _mark_postprocess_delims(state, meta["delimiters"])


_md.inline.ruler.before("emphasis", "mark", _mark_tokenize)
_md.inline.ruler2.before("emphasis", "mark", _mark_postprocess)

def _renders_safely_as_inline_markdown(raw_sentence: str) -> bool:
    """A sentence is one half of a sentence-boundary split over the *raw* block
    text (see segmentation.py). If an emphasis/code span happens to straddle
    that sentence boundary (e.g. one `*...*` run wrapping two full sentences),
    each half only gets one of the pair of delimiter characters -- markdown-it
    can't recognize an unmatched single "*"/"_"/"`" as a real emphasis marker,
    so it just prints it literally, which looks broken (a stray visible
    asterisk) rather than merely plain. Rather than trying to detect and
    reconstruct cross-sentence spans, treat an odd count of any delimiter
    character as a sign this sentence isn't self-contained markdown and fall
    back to safe plain text for just that sentence."""
    for delim in ("**", "__", "=="):
        if raw_sentence.count(delim) % 2 != 0:
            return False
    # Count single '*'/'_' not already accounted for by the doubled forms above
    singles = re.sub(r"\*\*|__", "", raw_sentence)
    if singles.count("*") % 2 != 0 or singles.count("_") % 2 != 0:
        return False
    if raw_sentence.count("`") % 2 != 0:
        return False
    return True


def _render_inline_or_plain(seg: Segment) -> str:
    if _renders_safely_as_inline_markdown(seg.raw_text):
        return _md.renderInline(seg.raw_text)
    return html.escape(seg.text)


_HEADING_PREFIX_RE = re.compile(r"^#{1,6}\s+")
_LIST_MARKER_RE = re.compile(r"^([-*+]\s+|\d+\.\s+)")
_ORDERED_MARKER_RE = re.compile(r"^\d+\.\s")
_CODE_FENCE_RE = re.compile(r"^```(\w*)\n(.*?)\n?```$", re.DOTALL)


def _attr(s: str) -> str:
    return html.escape(s, quote=True)


def _render_heading(seg: Segment) -> str:
    inline = _md.renderInline(_HEADING_PREFIX_RE.sub("", seg.raw_text))
    level = seg.level or 1
    return f'<h{level} data-seg="{seg.index}" data-type="heading">{inline}</h{level}>'


def _render_code(seg: Segment) -> str:
    m = _CODE_FENCE_RE.match(seg.raw_text)
    lang, content = (m.group(1), m.group(2)) if m else ("", seg.raw_text)
    lang_class = f' class="language-{_attr(lang)}"' if lang else ""
    return (
        f'<div data-seg="{seg.index}" data-type="code">'
        f'<pre><code{lang_class}>{html.escape(content)}</code></pre>'
        f'</div>'
    )


def _render_list(segs: list[Segment]) -> str:
    ordered = bool(_ORDERED_MARKER_RE.match(segs[0].raw_text))
    tag = "ol" if ordered else "ul"
    items = []
    for seg in segs:
        inline = _md.renderInline(_LIST_MARKER_RE.sub("", seg.raw_text, count=1))
        items.append(f'<li data-seg="{seg.index}" data-type="listitem">{inline}</li>')
    return f"<{tag}>" + "".join(items) + f"</{tag}>"


def _render_blockquote(segs: list[Segment]) -> str:
    spans = [
        f'<span data-seg="{seg.index}" data-type="blockquote">{_render_inline_or_plain(seg)}</span>'
        for seg in segs
    ]
    return "<blockquote>" + " ".join(spans) + "</blockquote>"


def _render_paragraph(segs: list[Segment]) -> str:
    spans = []
    for seg in segs:
        words = re.findall(r"\S+", seg.text)
        words_json = _attr(json.dumps(words))
        inline = _render_inline_or_plain(seg)
        spans.append(
            f'<span data-seg="{seg.index}" data-type="paragraph" data-words="{words_json}">'
            f"{inline}</span>"
        )
    return "<p>" + " ".join(spans) + "</p>"


def render_document(markdown: str) -> tuple[str, SegmentedDocument]:
    """Render markdown to display HTML with data-seg attributes, alongside the
    SegmentedDocument used to drive playback/TOC. Both come from the same
    segment_document() call so they can never disagree with each other."""
    doc = segment_document(markdown)
    segs_by_block: dict[int, list[Segment]] = {
        block_index: list(segs)
        for block_index, segs in groupby(doc.segments, key=lambda s: s.block_index)
    }

    blocks_html = []
    for block_index, raw_block in enumerate(doc.blocks):
        segs = segs_by_block.get(block_index)
        if not segs:
            # Nothing spoken for this block (thematic break, raw HTML block) --
            # still render it visually via plain markdown-it-py block rendering,
            # just with no data-seg (never highlighted, never clickable-to-jump).
            blocks_html.append(_md.render(raw_block))
            continue

        seg_type = segs[0].type
        if seg_type == "heading":
            blocks_html.append(_render_heading(segs[0]))
        elif seg_type == "code":
            blocks_html.append(_render_code(segs[0]))
        elif seg_type == "listitem":
            blocks_html.append(_render_list(segs))
        elif seg_type == "blockquote":
            blocks_html.append(_render_blockquote(segs))
        elif seg_type == "paragraph":
            blocks_html.append(_render_paragraph(segs))
    return "\n".join(blocks_html), doc
