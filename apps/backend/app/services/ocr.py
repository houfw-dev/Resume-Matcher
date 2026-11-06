"""Optional offline OCR fallback for PDFs without a text layer.

Two kinds of résumé PDFs yield zero extractable text:

1. scanned / image-only PDFs (a picture of a page), and
2. PDFs whose fonts were converted to vector outlines by design tools
   (the content stream draws glyph bezier curves and contains no text
   operators or font objects at all).

markitdown/pdfminer return an empty document for both, and without this
module the upload is rejected as "image-based or scanned". When the
optional ``ocr`` extra is installed (``pypdfium2`` +
``rapidocr-onnxruntime``), the parser renders pages to bitmaps and runs
offline PP-OCR recognition (bundled Simplified Chinese + English models;
no network access, no API key).

The heavy libraries are imported lazily, so a default install keeps
working without them — callers then see the legacy empty-text 422.
"""

import io
import logging
import threading
from importlib.util import find_spec
from typing import Any

logger = logging.getLogger(__name__)

OCR_DPI = 200
OCR_MAX_PAGES = 10
_REQUIRED_MODULES = ("pypdfium2", "rapidocr_onnxruntime", "numpy")

_engine: Any | None = None
_engine_lock = threading.Lock()
# ONNX inference + full-page bitmap decode is memory-heavy; serialise OCR
# jobs so two concurrent conversions cannot spike memory together.
_ocr_lock = threading.Lock()


class OcrUnavailableError(RuntimeError):
    """The optional OCR dependencies are not installed."""


def is_ocr_available() -> bool:
    """Report whether the optional ``ocr`` extra is importable."""
    return all(find_spec(name) is not None for name in _REQUIRED_MODULES)


def _get_engine() -> Any:
    """Return the process-wide RapidOCR engine, creating it on first use."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from rapidocr_onnxruntime import RapidOCR

                logger.info("Initialising offline RapidOCR engine")
                _engine = RapidOCR(show_log=False)
    return _engine


def _render_page_images(content: bytes) -> list[Any]:
    """Render the first ``OCR_MAX_PAGES`` PDF pages to RGB numpy arrays."""
    import numpy as np
    import pypdfium2 as pdfium

    images: list[Any] = []
    pdf = pdfium.PdfDocument(io.BytesIO(content))
    try:
        page_count = len(pdf)
        rendered = min(page_count, OCR_MAX_PAGES)
        for index in range(rendered):
            page = pdf[index]
            try:
                bitmap = page.render(scale=OCR_DPI / 72.0)
                images.append(np.asarray(bitmap.to_pil()))
            finally:
                page.close()
        if page_count > OCR_MAX_PAGES:
            logger.warning(
                "OCR: document has %d pages; recognising only the first %d",
                page_count,
                OCR_MAX_PAGES,
            )
    finally:
        pdf.close()
    return images


def _recognize_lines(engine: Any, image: Any) -> list[str]:
    """Run one rendered page and return its recognised text lines."""
    result, _elapsed = engine(image)
    if not result:
        return []
    lines: list[str] = []
    for item in result:
        # Each result row is [quad_points, text, confidence].
        if len(item) >= 2 and isinstance(item[1], str):
            line = item[1].strip()
            if line:
                lines.append(line)
    return lines


def ocr_pdf(content: bytes) -> str:
    """Recognise a text-less PDF and return page-joined plain text.

    Returns ``""`` when recognition finds nothing. Raises
    ``OcrUnavailableError`` without the optional dependencies; rendering or
    inference errors propagate so the parser can log them and fall back to
    the empty-text rejection.
    """
    if not is_ocr_available():
        raise OcrUnavailableError(
            "Install the optional 'ocr' extra to recognise scanned PDFs."
        )
    pages: list[str] = []
    with _ocr_lock:
        for index, image in enumerate(_render_page_images(content)):
            lines = _recognize_lines(_get_engine(), image)
            logger.info("OCR page %d: %d lines", index + 1, len(lines))
            if lines:
                pages.append("\n".join(lines))
    return "\n\n".join(pages).strip()
