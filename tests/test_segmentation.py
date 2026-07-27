import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from segmentation import segment_document, strip_markdown, has_speakable_content


def test_thematic_break_skipped():
    doc = segment_document("Some text.\n\n---\n\nMore text.")
    texts = [s.text for s in doc.segments]
    assert "---" not in texts
    assert texts == ["Some text.", "More text."]


def test_backslash_escapes_unescaped():
    # Escaped punctuation runs (marker-pdf emits "\_\_\_\_" for signature/blank
    # lines) must never surface literal backslashes in narrated text. The
    # emphasis-stripping regexes that run afterward may still collapse long
    # underscore runs (they can't distinguish a placeholder from _emphasis_),
    # but that's harmless here since has_speakable_content() drops pure
    # punctuation/underscore segments regardless of exact character count.
    assert "\\" not in strip_markdown(r"\_\_\_\_")
    doc = segment_document(r"Signature: \_\_\_\_")
    assert "\\" not in doc.segments[0].text
    assert doc.segments[0].text.startswith("Signature:")


def test_pure_punctuation_segment_dropped():
    assert not has_speakable_content("____")
    doc = segment_document("____\n\nReal content here.")
    assert len(doc.segments) == 1
    assert doc.segments[0].text == "Real content here."


def test_heading_becomes_segment_and_toc_entry_together():
    doc = segment_document("# Title\n\nBody text.")
    assert len(doc.segments) == 2
    assert doc.segments[0].type == "heading"
    assert len(doc.toc) == 1
    assert doc.toc[0].segment_index == 0
    assert doc.toc[0].text == doc.segments[0].text


def test_toc_never_references_a_filtered_heading():
    # A heading made only of punctuation/underscores has no speakable content and
    # must be filtered from both segments AND the toc, in lockstep, by construction.
    doc = segment_document("# ____\n\n# Real Heading\n\nBody text.")
    assert len(doc.toc) == 1
    assert doc.toc[0].text == "Real Heading"
    referenced = doc.segments[doc.toc[0].segment_index]
    assert referenced.type == "heading"
    assert referenced.text == "Real Heading"


def test_every_toc_entry_points_at_a_matching_heading_segment():
    doc = segment_document(
        "# H1\n\nIntro paragraph.\n\n## H2\n\nMore text.\n\n### H3\n\nEnd."
    )
    for entry in doc.toc:
        seg = doc.segments[entry.segment_index]
        assert seg.type == "heading"
        assert seg.text == entry.text
        assert seg.level == entry.level


def test_code_block_narrates_as_code_block_but_keeps_raw_text():
    doc = segment_document("```python\nprint('hi')\n```")
    assert len(doc.segments) == 1
    seg = doc.segments[0]
    assert seg.type == "code"
    assert seg.text == "code block"
    assert "print" in seg.raw_text


def test_multi_sentence_paragraph_splits_into_multiple_segments():
    doc = segment_document("First sentence. Second sentence. Third one.")
    assert len(doc.segments) == 3
    assert all(s.type == "paragraph" for s in doc.segments)


def test_list_items_each_become_a_segment():
    doc = segment_document("- one\n- two\n- three")
    assert len(doc.segments) == 3
    assert all(s.type == "listitem" for s in doc.segments)


def test_blockquote_splits_into_sentences():
    doc = segment_document("> First. Second.")
    assert len(doc.segments) == 2
    assert all(s.type == "blockquote" for s in doc.segments)


def test_html_block_produces_no_segment():
    doc = segment_document("<div>raw html</div>\n\nReal paragraph.")
    assert len(doc.segments) == 1
    assert doc.segments[0].text == "Real paragraph."


def test_crlf_line_endings_still_segment_correctly():
    # Real bug: block-splitting uses "\n{2,}", which never matches inside
    # "\r\n\r\n" (there's an \r between the two \n's) -- an un-normalized CRLF
    # document (what a browser's <textarea> submits, and what some
    # Windows-authored files already contain) used to collapse into a single
    # giant unsplit block instead of being segmented at all.
    crlf_doc = "# Title\r\n\r\nFirst paragraph.\r\n\r\n## Section\r\n\r\nSecond paragraph."
    doc = segment_document(crlf_doc)
    assert len(doc.segments) == 4
    assert len(doc.toc) == 2
    assert doc.segments[0].type == "heading"
    assert doc.segments[0].text == "Title"


def test_paragraph_sentence_preserves_inline_markdown_in_raw_text():
    # raw_text must keep inline formatting (bold/links/etc) intact -- only
    # `text` (the plain TTS/word-highlighting copy) should be stripped --
    # so render.py can display real formatting instead of flattening every
    # paragraph to plain text.
    doc = segment_document("This is *italic* and **bold** text. Second sentence.")
    assert doc.segments[0].raw_text == "This is *italic* and **bold** text."
    assert doc.segments[0].text == "This is italic and bold text."


def test_blockquote_sentence_preserves_inline_markdown_in_raw_text():
    doc = segment_document("> A **bold** quote. Second sentence.")
    assert doc.segments[0].raw_text == "A **bold** quote."
    assert doc.segments[0].text == "A bold quote."


def test_strip_markdown_does_not_eat_literal_marker_characters_mid_prose():
    # Real bug (inherited from v1): unanchored "[-*+]\s+"/">\s+"/etc regexes
    # would strip ANY "* "/"- "/"> " substring anywhere in prose, not just a
    # genuine leading marker -- e.g. "3 * 4" silently became "3 4".
    assert strip_markdown("The result is 3 * 4 = 12.") == "The result is 3 * 4 = 12."
    assert strip_markdown("5 > 3 is true.") == "5 > 3 is true."
    assert strip_markdown("cost - benefit analysis") == "cost - benefit analysis"


def test_multiline_blockquote_strips_every_line_prefix():
    doc = segment_document("> Line one.\n> Line two.")
    assert len(doc.segments) == 2
    assert doc.segments[0].text == "Line one."
    assert doc.segments[1].text == "Line two."
    assert ">" not in doc.segments[0].text
    assert ">" not in doc.segments[1].text
