"""PDF -> Markdown conversion via marker-pdf.

marker-pdf is a secondary/best-effort feature (per the user's explicit call): it
OCRs and parses layout, so it's heavier and has previously conflicted with the TTS
stack's `transformers` dependency (v1 commit 981c169). `marker.*` is imported lazily,
inside the function body, so importing this module -- and therefore starting the
app -- never pays marker's import cost or risks an import-time failure unless a PDF
is actually uploaded.

Conversion happens once, at add-to-library time; the resulting markdown is stored
and never reconverted on subsequent reads.
"""
from __future__ import annotations

KEEP_ORIGINAL_PDFS = True


def convert_pdf_to_markdown(pdf_path: str) -> str:
    """Convert a PDF file on disk to markdown text. Tries the current marker-pdf API
    first, falling back to the older API shape (marker-pdf's public API has changed
    across major versions before)."""
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.output import text_from_rendered

        models = create_model_dict()
        converter = PdfConverter(artifact_dict=models)
        rendered = converter(pdf_path)
        text, _, _ = text_from_rendered(rendered)
        return text
    except ImportError:
        try:
            from marker.convert import convert_single_pdf
            from marker.models import load_all_models

            model_lst = load_all_models()
            full_text, _, _ = convert_single_pdf(pdf_path, model_lst)
            return full_text
        except Exception as e:
            raise RuntimeError(f"marker-pdf API not available: {e}") from e
