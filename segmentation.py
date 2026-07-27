"""Markdown -> reading-order segments + table of contents, in a single pass.

Ported from the proven, bug-fixed Python segmenter in v1's markdown-to-audio
skill (strip_markdown/has_speakable_content/split_sentences/segment_markdown),
combined with the richer typed structure of v1's TypeScript textSegmenter.ts.

v1 computed segments (for TTS) and the table of contents separately, as two
independent passes over the same markdown that happened to agree on heading
order by construction of the source text rather than by any actual link
between them. A heading segment that got filtered out (e.g. because it was
empty after stripping) could silently desync the two passes. Here, a
TocEntry is only ever created inside the same branch, at the same moment,
that its corresponding heading Segment is appended -- so a TocEntry can
never reference a heading that doesn't exist in `segments`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Segment:
    index: int
    text: str          # stripped plain text, sent to TTS
    raw_text: str       # original markdown source for this segment (for display)
    type: str           # "heading" | "paragraph" | "listitem" | "blockquote" | "code"
    level: int | None   # heading level 1-6, else None
    block_index: int    # which top-level block (split on blank lines) this came from


@dataclass
class TocEntry:
    level: int
    text: str
    segment_index: int


@dataclass
class SegmentedDocument:
    segments: list[Segment] = field(default_factory=list)
    toc: list[TocEntry] = field(default_factory=list)
    # Raw (trimmed) text of every non-empty block, indexed by block_index -- including
    # blocks with NO segments (thematic breaks, raw HTML), so render.py can fall back
    # to plain markdown rendering for those without re-deriving the block split itself.
    blocks: list[str] = field(default_factory=list)


def strip_markdown(text: str) -> str:
    """Strip markdown formatting down to plain speakable text."""
    # Unescape CommonMark backslash-escapes (e.g. marker-pdf emits "\_\_\_\_" for
    # signature/blank lines) before the emphasis regexes below, so escaped runs of
    # punctuation don't survive as literal backslashes in the narrated text.
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!>~])", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"==(.+?)==", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    text = re.sub(r"!\[.*?\]\(.+?\)", "", text)
    # These four strip a block-level marker (heading/blockquote/list) only when
    # it's at the very start of the text being processed -- anchored to "^",
    # not a global unanchored match. Unanchored, they'd eat any coincidental
    # "* "/"- "/"> " substring appearing anywhere in ordinary prose (e.g. "3 *
    # 4 = 12" silently becoming "3 4 = 12", or "5 > 3" becoming "5 3") -- a
    # real bug inherited verbatim from v1 that a test caught while working on
    # something unrelated (see LEARNINGS.md).
    text = re.sub(r"^#{1,6}\s+", "", text)
    text = re.sub(r"^>\s+", "", text)
    text = re.sub(r"^[-*+]\s+", "", text)
    text = re.sub(r"^\d+\.\s+", "", text)
    return text.strip()


def has_speakable_content(text: str) -> bool:
    """True if text has at least one letter or digit -- filters out lines that are
    pure punctuation/underscores (e.g. signature-line placeholders like "____")."""
    return bool(re.search(r"[A-Za-z0-9]", text))


def split_sentences(text: str) -> list[str]:
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z"\']|$)', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    return sentences if sentences else [text]


def _sentence_pairs(raw_block: str, plain_whole: str) -> list[tuple[str, str]]:
    """Pair each sentence's plain (TTS/word-highlighting) text with its raw
    (markdown-preserving, for display) text.

    The two are split independently: `plain_whole` (already fully stripped of
    markdown) via the proven approach, `raw_block` (markdown intact) so
    render.py can show real formatting. They're paired by index, which holds
    as long as both splits agree on sentence count -- true in the vast
    majority of real text, since the sentence-boundary regex only looks at
    `.!?` + whitespace + a capital letter, which markdown syntax elsewhere
    doesn't interfere with. If they ever disagree (some markdown construct
    that itself looks like a sentence boundary), raw_text falls back to the
    plain text for every sentence in this block -- this can only lose rich
    formatting for that block, never misattribute one sentence's raw markup
    to a different sentence, and never affects `text` (the field TTS and
    word-highlighting actually use), which is always computed the
    old/proven way regardless."""
    plain_sentences = split_sentences(plain_whole)
    raw_sentences = split_sentences(raw_block)
    if len(plain_sentences) != len(raw_sentences):
        raw_sentences = plain_sentences
    return list(zip(plain_sentences, raw_sentences))


_HEADING_RE = re.compile(r"^(#{1,6})\s")
_THEMATIC_BREAK_RE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")
_HTML_BLOCK_RE = re.compile(r"^<")
_CODE_FENCE_RE = re.compile(r"^```")
_BLOCKQUOTE_RE = re.compile(r"^>")
_LIST_ITEM_RE = re.compile(r"^[-*+]\s|^\d+\.\s")


def segment_document(markdown: str) -> SegmentedDocument:
    doc = SegmentedDocument()
    # Normalize CRLF/CR to LF before anything else. The block splitter below
    # requires two literal consecutive "\n" characters; "\r\n\r\n" (what
    # browsers submit for a <textarea>'s content, and what many
    # Windows-authored files already contain) never matches that, so an
    # un-normalized CRLF document collapses into a single giant unsplit block
    # instead of being segmented at all. Normalizing here (not just at the
    # point content is saved) means content already stored with CRLF renders
    # correctly on next view too, with no migration needed.
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n{2,}", markdown)
    block_index = 0

    for block in blocks:
        trimmed = block.strip()
        if not trimmed:
            continue
        doc.blocks.append(trimmed)

        if _HTML_BLOCK_RE.match(trimmed):
            pass  # HTML block -- nothing to read aloud
        elif _THEMATIC_BREAK_RE.match(trimmed):
            pass  # thematic break (horizontal rule) -- nothing to read aloud
        elif (m := _HEADING_RE.match(trimmed)):
            level = len(m.group(1))
            plain = strip_markdown(trimmed)
            if plain and has_speakable_content(plain):
                idx = len(doc.segments)
                doc.segments.append(Segment(
                    index=idx, text=plain, raw_text=trimmed,
                    type="heading", level=level, block_index=block_index,
                ))
                doc.toc.append(TocEntry(level=level, text=plain, segment_index=idx))
        elif _CODE_FENCE_RE.match(trimmed):
            idx = len(doc.segments)
            doc.segments.append(Segment(
                index=idx, text="code block", raw_text=trimmed,
                type="code", level=None, block_index=block_index,
            ))
        elif _BLOCKQUOTE_RE.match(trimmed):
            # strip_markdown()'s own ">" removal only strips a single leading
            # marker (anchored to the very start of the string, not per-line --
            # see its docstring), so a multi-line blockquote's later lines would
            # keep their "> " prefix if left to strip_markdown alone. Remove all
            # of them here first (MULTILINE), then strip_markdown only has
            # inline formatting left to handle.
            raw_no_prefix = re.sub(r"^>\s?", "", trimmed, flags=re.MULTILINE)
            plain_whole = strip_markdown(raw_no_prefix)
            for plain_sentence, raw_sentence in _sentence_pairs(raw_no_prefix, plain_whole):
                plain_sentence = plain_sentence.strip()
                raw_sentence = raw_sentence.strip()
                if plain_sentence and has_speakable_content(plain_sentence):
                    idx = len(doc.segments)
                    doc.segments.append(Segment(
                        index=idx, text=plain_sentence, raw_text=raw_sentence,
                        type="blockquote", level=None, block_index=block_index,
                    ))
        elif _LIST_ITEM_RE.match(trimmed):
            for line in trimmed.split("\n"):
                plain = strip_markdown(line)
                if plain and has_speakable_content(plain):
                    idx = len(doc.segments)
                    doc.segments.append(Segment(
                        index=idx, text=plain, raw_text=line,
                        type="listitem", level=None, block_index=block_index,
                    ))
        else:
            plain_whole = strip_markdown(trimmed)
            for plain_sentence, raw_sentence in _sentence_pairs(trimmed, plain_whole):
                plain_sentence = plain_sentence.strip()
                raw_sentence = raw_sentence.strip()
                if plain_sentence and has_speakable_content(plain_sentence):
                    idx = len(doc.segments)
                    doc.segments.append(Segment(
                        index=idx, text=plain_sentence, raw_text=raw_sentence,
                        type="paragraph", level=None, block_index=block_index,
                    ))

        block_index += 1

    return doc
