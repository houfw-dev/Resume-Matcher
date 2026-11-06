"""Deterministic tests for the optional OCR fallback (no OCR deps required).

The real pypdfium2/rapidocr libraries are an optional extra, so every test
stubs the rendering/recognition seams. The tests must still fail if the
fallback composition (availability gating, page order/join, page cap,
empty-result handling) breaks.
"""

import logging
import sys
import types

import pytest

from app.services import ocr


class _FakeEngine:
    """Records inputs and returns scripted per-page result rows."""

    def __init__(self, pages: list[list[tuple[str, float]]] | None = None) -> None:
        self.calls: list[object] = []
        self.pages = pages or []

    def __call__(self, image: object) -> tuple[list[list[object]], float]:
        self.calls.append(image)
        rows = self.pages[len(self.calls) - 1] if len(self.calls) <= len(self.pages) else []
        return ([[None, text, score] for text, score in rows], 1.23)


def test_ocr_pdf_requires_optional_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr, "is_ocr_available", lambda: False)
    with pytest.raises(ocr.OcrUnavailableError):
        ocr.ocr_pdf(b"%PDF-fake")


def test_is_ocr_available_reflects_find_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr, "find_spec", lambda name: None)
    assert ocr.is_ocr_available() is False
    monkeypatch.setattr(ocr, "find_spec", lambda name: object())
    assert ocr.is_ocr_available() is True


def test_ocr_pdf_joins_pages_and_lines_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ocr, "is_ocr_available", lambda: True)
    monkeypatch.setattr(ocr, "_render_page_images", lambda content: ["IMG-1", "IMG-2"])
    engine = _FakeEngine(
        [
            [("第一页 第一行", 0.99), ("  ", 0.50), ("第一页 第二行", 0.98)],
            [("第二页 第一行", 0.97)],
        ]
    )
    monkeypatch.setattr(ocr, "_get_engine", lambda: engine)

    text = ocr.ocr_pdf(b"%PDF-fake")

    assert engine.calls == ["IMG-1", "IMG-2"]
    assert text == "第一页 第一行\n第一页 第二行\n\n第二页 第一行"


def test_ocr_pdf_blank_recognition_returns_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ocr, "is_ocr_available", lambda: True)
    monkeypatch.setattr(ocr, "_render_page_images", lambda content: ["IMG"])
    monkeypatch.setattr(ocr, "_get_engine", lambda: _FakeEngine([[]]))
    assert ocr.ocr_pdf(b"%PDF-fake") == ""


def test_ocr_pdf_render_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr, "is_ocr_available", lambda: True)

    def _boom(content: bytes) -> list[object]:
        raise ValueError("corrupt pdf")

    monkeypatch.setattr(ocr, "_render_page_images", _boom)
    with pytest.raises(ValueError, match="corrupt pdf"):
        ocr.ocr_pdf(b"%PDF-fake")


class _FakePage:
    def __init__(self, index: int, closed: list[int]) -> None:
        self.index = index
        self.closed = closed

    def render(self, scale: float) -> "_FakeBitmap":
        assert scale == ocr.OCR_DPI / 72.0
        return _FakeBitmap(self.index)

    def close(self) -> None:
        self.closed.append(self.index)


class _FakeBitmap:
    def __init__(self, index: int) -> None:
        self.index = index

    def to_pil(self) -> str:
        return f"PIL-{self.index}"


class _FakePdf:
    def __init__(self, page_count: int, closed_pages: list[int]) -> None:
        self.page_count = page_count
        self.closed_pages = closed_pages

    def __len__(self) -> int:
        return self.page_count

    def __getitem__(self, index: int) -> _FakePage:
        return _FakePage(index, self.closed_pages)

    def close(self) -> None:
        pass


def _install_fake_pdfium(
    monkeypatch: pytest.MonkeyPatch, page_count: int, closed_pages: list[int]
) -> None:
    fake_pdfium = types.ModuleType("pypdfium2")
    fake_pdfium.PdfDocument = lambda stream: _FakePdf(page_count, closed_pages)
    fake_numpy = types.ModuleType("numpy")
    fake_numpy.asarray = lambda image: f"ARRAY-{image}"
    monkeypatch.setitem(sys.modules, "pypdfium2", fake_pdfium)
    monkeypatch.setitem(sys.modules, "numpy", fake_numpy)


def test_render_page_images_caps_page_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the first OCR_MAX_PAGES are rendered and each page is closed."""
    closed_pages: list[int] = []
    _install_fake_pdfium(
        monkeypatch, ocr.OCR_MAX_PAGES + 3, closed_pages
    )

    images = ocr._render_page_images(b"%PDF-fake")

    assert images == [f"ARRAY-PIL-{i}" for i in range(ocr.OCR_MAX_PAGES)]
    assert closed_pages == list(range(ocr.OCR_MAX_PAGES))


def test_render_page_images_warns_when_truncating(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _install_fake_pdfium(monkeypatch, 2, [])
    monkeypatch.setattr(ocr, "OCR_MAX_PAGES", 0)

    with caplog.at_level(logging.WARNING):
        images = ocr._render_page_images(b"%PDF-fake")

    assert images == []
    assert "first 0" in caplog.text
