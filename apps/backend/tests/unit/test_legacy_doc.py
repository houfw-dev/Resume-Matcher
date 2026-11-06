"""Unit tests for the legacy binary Word (.doc, OLE2) conversion fallback.

markitdown has no converter for OLE2 ``.doc`` files; the parser falls back to a
local LibreOffice or macOS textutil invocation. Every test here stubs
``subprocess`` so the suite stays deterministic and platform-independent.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from markitdown import UnsupportedFormatException

from app.services import parser
from app.services.parser import (
    DocumentValidationError,
    LegacyDocConversionError,
    _convert_legacy_doc,
    _legacy_doc_backend,
    _parse_document_sync,
)

OLE_HEADER = bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 64


# ---------------------------------------------------------------------------
# Backend discovery
# ---------------------------------------------------------------------------


def test_backend_none_without_any_local_tool() -> None:
    with patch("app.services.parser.shutil.which", return_value=None), patch(
        "app.services.parser.sys.platform", "linux"
    ):
        assert _legacy_doc_backend() is None


def test_backend_prefers_soffice_on_path() -> None:
    with patch(
        "app.services.parser.shutil.which",
        side_effect=lambda name: "/usr/bin/soffice" if name == "soffice" else None,
    ):
        assert _legacy_doc_backend() == "/usr/bin/soffice"


def test_backend_falls_back_to_macos_textutil() -> None:
    def fake_isfile(path: str) -> bool:
        return path == parser._MACOS_TEXTUTIL_PATH

    with patch("app.services.parser.shutil.which", return_value=None), patch(
        "app.services.parser.sys.platform", "darwin"
    ), patch("app.services.parser.os.path.isfile", side_effect=fake_isfile), patch(
        "app.services.parser.os.access", return_value=True
    ):
        assert _legacy_doc_backend() == "/usr/bin/textutil"


def test_backend_none_on_macos_without_textutil() -> None:
    with patch("app.services.parser.shutil.which", return_value=None), patch(
        "app.services.parser.sys.platform", "darwin"
    ), patch("app.services.parser.os.path.isfile", return_value=False):
        assert _legacy_doc_backend() is None


# ---------------------------------------------------------------------------
# Conversion: textutil
# ---------------------------------------------------------------------------


def test_textutil_success_returns_decoded_stdout() -> None:
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="简历正文 甲公司".encode("utf-8"), stderr=b""
    )
    with patch("app.services.parser._legacy_doc_backend", return_value="/usr/bin/textutil"), patch(
        "app.services.parser.subprocess.run", return_value=completed
    ) as run:
        text = _convert_legacy_doc(Path("/tmp/resume.doc"))

    assert "简历正文" in text
    argv = run.call_args.args[0]
    assert argv[:2] == ["/usr/bin/textutil", "-convert"]
    assert "txt" in argv and "-stdout" in argv


def test_textutil_nonzero_exit_raises_validation_error() -> None:
    completed = subprocess.CompletedProcess(
        args=[], returncode=1, stdout=b"", stderr=b"bad document"
    )
    with patch("app.services.parser._legacy_doc_backend", return_value="/usr/bin/textutil"), patch(
        "app.services.parser.subprocess.run", return_value=completed
    ):
        with pytest.raises(LegacyDocConversionError, match="PDF or DOCX"):
            _convert_legacy_doc(Path("/tmp/resume.doc"))


def test_textutil_timeout_raises_validation_error() -> None:
    with patch("app.services.parser._legacy_doc_backend", return_value="/usr/bin/textutil"), patch(
        "app.services.parser.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="textutil", timeout=60),
    ):
        with pytest.raises(LegacyDocConversionError, match="timed out"):
            _convert_legacy_doc(Path("/tmp/resume.doc"))


# ---------------------------------------------------------------------------
# Conversion: LibreOffice
# ---------------------------------------------------------------------------


def _fake_soffice_run(monkeypatch_text: str = "converted"):
    """Build a subprocess.run stand-in that writes LibreOffice's outdir file."""

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        outdir = argv[argv.index("--outdir") + 1]
        source = Path(argv[-1])
        Path(outdir, f"{source.stem}.txt").write_text(monkeypatch_text, encoding="utf-8")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    return fake_run


def test_soffice_success_reads_outdir_text(tmp_path: Path) -> None:
    doc = tmp_path / "resume.doc"
    doc.write_bytes(OLE_HEADER)
    with patch(
        "app.services.parser._legacy_doc_backend",
        return_value="/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ), patch(
        "app.services.parser.subprocess.run", side_effect=_fake_soffice_run("项目经验正文")
    ) as run:
        text = _convert_legacy_doc(doc)

    assert "项目经验正文" in text
    argv = run.call_args.args[0]
    assert "--headless" in argv and "txt:Text" in argv
    # A private user profile avoids colliding with an interactive LibreOffice.
    assert any(arg.startswith("-env:UserInstallation=") for arg in argv)


def test_soffice_without_output_file_raises(tmp_path: Path) -> None:
    doc = tmp_path / "resume.doc"
    doc.write_bytes(OLE_HEADER)
    with patch(
        "app.services.parser._legacy_doc_backend", return_value="/usr/bin/soffice"
    ), patch(
        "app.services.parser.subprocess.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b""),
    ):
        with pytest.raises(LegacyDocConversionError, match="PDF or DOCX"):
            _convert_legacy_doc(doc)


def test_convert_without_backend_raises_actionable_error(tmp_path: Path) -> None:
    doc = tmp_path / "resume.doc"
    doc.write_bytes(OLE_HEADER)
    with patch("app.services.parser._legacy_doc_backend", return_value=None):
        with pytest.raises(LegacyDocConversionError, match="PDF or DOCX") as exc_info:
            _convert_legacy_doc(doc)
    assert "Legacy binary Word (.doc)" in str(exc_info.value)
    assert isinstance(exc_info.value, DocumentValidationError)


# ---------------------------------------------------------------------------
# Wired into _parse_document_sync
# ---------------------------------------------------------------------------


def test_parse_document_sync_uses_fallback_for_ole_doc(tmp_path: Path) -> None:
    doc = tmp_path / "resume.doc"
    doc.write_bytes(OLE_HEADER)
    with patch("app.services.parser._validate_doc_container"), patch.object(
        parser.MarkItDown, "convert", side_effect=UnsupportedFormatException("")
    ), patch(
        "app.services.parser._convert_legacy_doc", return_value="旧版 Word 简历正文"
    ) as fallback:
        text = _parse_document_sync(OLE_HEADER, "resume.doc")
    assert "旧版 Word 简历正文" in text
    fallback.assert_called_once()


def test_parse_document_sync_does_not_fallback_for_non_doc(tmp_path: Path) -> None:
    # A PDF that markitdown cannot identify must surface the original failure
    # instead of invoking the .doc-only fallback.
    pdf_bytes = b"%PDF-1.4\n" + b"\x00" * 128
    with patch("app.services.parser._validate_pdf_container"), patch.object(
        parser.MarkItDown, "convert", side_effect=UnsupportedFormatException("")
    ), patch("app.services.parser._convert_legacy_doc") as fallback:
        with pytest.raises(UnsupportedFormatException):
            _parse_document_sync(pdf_bytes, "resume.pdf")
    fallback.assert_not_called()
