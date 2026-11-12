"""Document parsing service using markitdown and LLM."""

import array
import asyncio
import io
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
import zlib
from pathlib import Path
from collections.abc import Mapping
from typing import Any, BinaryIO, Sequence

import anyio
from markitdown import MarkItDown, UnsupportedFormatException
from pdfminer.ascii85 import ascii85decode, asciihexdecode
from pdfminer.ccitt import CCITTFaxDecoder
from pdfminer.lzw import LZWDecoder
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfdevice import PDFDevice
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import (
    LITERALS_ASCII85_DECODE,
    LITERALS_ASCIIHEX_DECODE,
    LITERALS_CCITTFAX_DECODE,
    LITERALS_DCT_DECODE,
    LITERALS_FLATE_DECODE,
    LITERALS_JBIG2_DECODE,
    LITERALS_JPX_DECODE,
    LITERALS_LZW_DECODE,
    LITERALS_RUNLENGTH_DECODE,
    LITERAL_CRYPT,
    PDFStream,
    apply_png_predictor,
    apply_tiff_predictor,
    int_value,
)
from pdfminer.psparser import PSKeyword, literal_name

from app.llm import complete_json, get_llm_config, get_model_name, get_safe_max_tokens
from app.prompts import PARSE_RESUME_PROMPT
from app.services import ocr as ocr_service
from app.services.tech_terms import canonicalize_tech_terms
from app.prompts.templates import RESUME_SCHEMA_EXAMPLE
from app.schemas import ResumeData

logger = logging.getLogger(__name__)

DOCUMENT_IO_CHUNK_SIZE = 64 * 1024
MAX_DOCX_MEMBERS = 1_024
MAX_UNPACKED_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_EXTRACTED_TEXT_BYTES = 2 * 1024 * 1024
# Decoder row buffers can allocate from dimensions before consuming input.
MAX_PDF_SCANLINE_COLUMNS = 32_768
MAX_PDF_SCANLINE_BYTES = 256 * 1024
DOCUMENT_CONVERSION_WORKERS = 2
DOCUMENT_CONVERSION_TIMEOUT_SECONDS = 120.0
# Legacy binary Word (.doc, OLE2) conversion via a local tool (best effort).
LEGACY_DOC_CONVERSION_TIMEOUT_SECONDS = 60.0
_MACOS_TEXTUTIL_PATH = "/usr/bin/textutil"
_MACOS_LIBREOFFICE_PATH = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
_DOCUMENT_BACKGROUND_WORKERS: set[asyncio.Task[str]] = set()
_DOCUMENT_CONVERSION_LIMITER = anyio.CapacityLimiter(DOCUMENT_CONVERSION_WORKERS)


class DocumentValidationError(ValueError):
    """Raised when uploaded bytes are not a structurally valid document."""


class LegacyDocConversionError(DocumentValidationError):
    """A legacy .doc that needs re-saving as PDF/DOCX (no converter backend).

    Messages are client-safe and actionable, so the router surfaces them
    verbatim (unlike other document-validation failures, which map to a
    generic parse error).
    """


class DocumentResourceLimitError(ValueError):
    """Raised when a valid document exceeds a bounded processing budget."""


_COMPOUND_FILE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")


class _PDFDecodeBudget:
    """Track decoded PDF stream bytes across one parser instance."""

    def __init__(self) -> None:
        self.decoded_bytes = 0

    @property
    def remaining(self) -> int:
        """Return the bytes available to the next decoded stream."""
        return MAX_UNPACKED_DOCUMENT_BYTES - self.decoded_bytes

    def consume(self, size: int) -> None:
        """Charge one decoded stream to the document-wide limit."""
        if size > self.remaining:
            raise DocumentResourceLimitError(
                "Document expanded content exceeds the 16MB limit."
            )
        self.decoded_bytes += size


def _append_pdf_output(output: bytearray, chunk: bytes, limit: int) -> None:
    """Append decoded stream bytes without crossing the remaining budget."""
    if len(chunk) > limit - len(output):
        raise DocumentResourceLimitError(
            "Document expanded content exceeds the 16MB limit."
        )
    output.extend(chunk)


def _decode_flate_bounded(data: bytes, limit: int) -> bytes:
    """Incrementally inflate a stream while enforcing its remaining budget."""
    decoder = zlib.decompressobj()
    output = bytearray()
    for offset in range(0, len(data), DOCUMENT_IO_CHUNK_SIZE):
        pending = data[offset : offset + DOCUMENT_IO_CHUNK_SIZE]
        while pending:
            max_output = min(DOCUMENT_IO_CHUNK_SIZE, limit - len(output) + 1)
            chunk = decoder.decompress(pending, max_output)
            _append_pdf_output(output, chunk, limit)
            pending = decoder.unconsumed_tail
    _append_pdf_output(output, decoder.flush(limit - len(output) + 1), limit)
    if not decoder.eof:
        raise ValueError("Truncated FlateDecode stream")
    return bytes(output)


def _decode_lzw_bounded(data: bytes, limit: int) -> bytes:
    """Decode an LZW stream one emitted code at a time under a byte limit."""
    output = bytearray()
    for chunk in LZWDecoder(io.BytesIO(data)).run():
        _append_pdf_output(output, chunk, limit)
    return bytes(output)


def _decode_run_length_bounded(data: bytes, limit: int) -> bytes:
    """Decode Adobe run-length data without first materializing all output."""
    output = bytearray()
    offset = 0
    while offset < len(data):
        length = data[offset]
        offset += 1
        if length == 128:
            break
        if length < 128:
            end = offset + length + 1
            if end > len(data):
                raise ValueError("Truncated run-length literal")
            _append_pdf_output(output, data[offset:end], limit)
            offset = end
            continue
        if offset >= len(data):
            raise ValueError("Truncated run-length repeat")
        _append_pdf_output(output, bytes([data[offset]]) * (257 - length), limit)
        offset += 1
    return bytes(output)


class _BoundedCCITTFaxDecoder(CCITTFaxDecoder):
    """Collect CCITT rows only while they fit the current stream budget."""

    def __init__(
        self,
        width: int,
        *,
        bytealign: bool,
        reversed_bits: bool,
        limit: int,
    ) -> None:
        super().__init__(width, bytealign=bytealign, reversed=reversed_bits)
        self._chunks: list[bytes] = []
        self._decoded_size = 0
        self._limit = limit

    def output_line(self, y: int, bits: Sequence[int]) -> None:
        """Encode one decoded bitmap row after reserving its output bytes."""
        row_size = (len(bits) + 7) // 8
        if row_size > self._limit - self._decoded_size:
            raise DocumentResourceLimitError(
                "Document expanded content exceeds the 16MB limit."
            )
        row = array.array("B", [0] * row_size)
        source_bits = [1 - bit for bit in bits] if self.reversed else bits
        masks = (128, 64, 32, 16, 8, 4, 2, 1)
        for index, bit in enumerate(source_bits):
            if bit:
                row[index // 8] += masks[index % 8]
        encoded = row.tobytes()
        self._chunks.append(encoded)
        self._decoded_size += len(encoded)

    def close(self) -> bytes:
        """Join already bounded rows into the decoded stream."""
        return b"".join(self._chunks)


def _decode_ccitt_bounded(data: bytes, params: dict[str, Any], limit: int) -> bytes:
    """Decode the CCITT variant supported by pdfminer with bounded output."""
    if params.get("K") != -1:
        raise ValueError("Unsupported CCITT encoding")
    width = int_value(params.get("Columns"))
    if width <= 0:
        raise ValueError("CCITT stream has no positive column count")
    if width > MAX_PDF_SCANLINE_COLUMNS or (width + 7) // 8 > limit:
        raise DocumentResourceLimitError(
            "Document expanded content exceeds the 16MB limit."
        )
    decoder = _BoundedCCITTFaxDecoder(
        width,
        bytealign=bool(params.get("EncodedByteAlign")),
        reversed_bits=bool(params.get("BlackIs1")),
        limit=limit,
    )
    decoder.feedbytes(data)
    return decoder.close()


def _apply_pdf_predictor(data: bytes, params: dict[str, Any]) -> bytes:
    """Apply the same predictor transformations as pdfminer."""
    predictor = int_value(params.get("Predictor", 1))
    if predictor == 1:
        return data
    colors = int_value(params.get("Colors", 1))
    columns = int_value(params.get("Columns", 1))
    bits_per_component = int_value(params.get("BitsPerComponent", 8))
    if colors <= 0 or columns <= 0 or bits_per_component <= 0:
        raise ValueError("PDF predictor dimensions must be positive")
    row_bytes = (colors * columns * bits_per_component + 7) // 8
    if columns > MAX_PDF_SCANLINE_COLUMNS or row_bytes > MAX_PDF_SCANLINE_BYTES:
        raise DocumentResourceLimitError(
            "Document decoder row dimensions exceed the processing limit."
        )
    if predictor == 2:
        return apply_tiff_predictor(colors, columns, bits_per_component, data)
    if predictor >= 10:
        return apply_png_predictor(predictor, colors, columns, bits_per_component, data)
    raise ValueError("Unsupported PDF predictor")


def _decode_pdf_stream(
    data: bytes,
    filters: list[tuple[Any, Any]],
    limit: int,
) -> bytes:
    """Decode every PDF filter while bounding each expansion stage."""
    for filter_name, raw_params in filters:
        params = raw_params if isinstance(raw_params, dict) else {}
        if filter_name in LITERALS_FLATE_DECODE:
            data = _decode_flate_bounded(data, limit)
        elif filter_name in LITERALS_LZW_DECODE:
            data = _decode_lzw_bounded(data, limit)
        elif filter_name in LITERALS_ASCII85_DECODE:
            data = ascii85decode(data)
        elif filter_name in LITERALS_ASCIIHEX_DECODE:
            data = asciihexdecode(data)
        elif filter_name in LITERALS_RUNLENGTH_DECODE:
            data = _decode_run_length_bounded(data, limit)
        elif filter_name in LITERALS_CCITTFAX_DECODE:
            data = _decode_ccitt_bounded(data, params, limit)
        elif (
            filter_name in LITERALS_DCT_DECODE
            or filter_name in LITERALS_JBIG2_DECODE
            or filter_name in LITERALS_JPX_DECODE
        ):
            # pdfminer passes already compressed image formats through unchanged.
            pass
        elif filter_name == LITERAL_CRYPT:
            raise ValueError("Encrypted PDF streams are not supported")
        else:
            raise ValueError("Unsupported PDF stream filter")

        if len(data) > limit:
            raise DocumentResourceLimitError(
                "Document expanded content exceeds the 16MB limit."
            )
        if params and "Predictor" in params:
            data = _apply_pdf_predictor(data, params)
            if len(data) > limit:
                raise DocumentResourceLimitError(
                    "Document expanded content exceeds the 16MB limit."
                )
    return data


class _BoundedPDFStream(PDFStream):
    """PDF stream whose decoder charges a request-local shared budget."""

    def __init__(self, stream: PDFStream, budget: _PDFDecodeBudget) -> None:
        super().__init__(stream.attrs, stream.rawdata, stream.decipher)
        self._budget = budget

    def decode(self) -> None:
        """Decode this stream with bounded filter implementations."""
        if self.rawdata is None:
            raise ValueError("PDF stream has no raw data")
        data = self.rawdata
        if self.decipher:
            if self.objid is None or self.genno is None:
                raise ValueError("Encrypted PDF stream is missing an object ID")
            data = self.decipher(self.objid, self.genno, data, self.attrs)
        decoded = _decode_pdf_stream(data, self.get_filters(), self._budget.remaining)
        self._budget.consume(len(decoded))
        self.data = decoded
        self.rawdata = None


class _BoundedPDFParser(PDFParser):
    """Install bounded streams locally without patching pdfminer globals."""

    def __init__(self, stream: BinaryIO, budget: _PDFDecodeBudget) -> None:
        super().__init__(stream)
        self._budget = budget

    def do_keyword(self, pos: int, token: PSKeyword) -> None:
        """Replace each newly parsed stream with its bounded counterpart."""
        super().do_keyword(pos, token)
        if token is self.KEYWORD_STREAM:
            stream_pos, parsed = self.curstack[-1]
            if isinstance(parsed, PDFStream):
                self.curstack[-1] = (
                    stream_pos,
                    _BoundedPDFStream(parsed, self._budget),
                )


def _validate_pdf_container(path: Path) -> None:
    """Require a readable PDF whose decoded streams fit a shared budget."""
    try:
        with path.open("rb") as stream:
            budget = _PDFDecodeBudget()
            document = PDFDocument(_BoundedPDFParser(stream, budget))
            manager = PDFResourceManager(caching=False)
            interpreter = PDFPageInterpreter(manager, PDFDevice(manager))
            has_pages = False
            for page in PDFPage.create_pages(document):
                has_pages = True
                # Follow the real text consumer's references under the same
                # bounded stream decoder. A forged /Image label on a content
                # or font stream cannot bypass preflight expansion limits.
                interpreter.process_page(page)
            if not has_pages:
                raise ValueError("PDF has no pages")
            seen: set[int] = set()
            for xref in document.xrefs:
                for object_id in xref.get_objids():
                    if object_id in seen:
                        continue
                    seen.add(object_id)
                    value = document.getobj(object_id)
                    if isinstance(value, PDFStream):
                        # Text extraction never decodes image XObjects. Their
                        # optional codecs must not reject otherwise readable text.
                        if literal_name(value.attrs.get("Subtype")) != "Image":
                            value.get_data()
    except DocumentResourceLimitError:
        raise
    except Exception as exc:
        raise DocumentValidationError(
            "The uploaded file is not a valid PDF, DOC, or DOCX document."
        ) from exc


def _validate_docx_container(path: Path) -> None:
    """Require a bounded, readable Office Open XML word-processing package."""
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_DOCX_MEMBERS:
                raise DocumentResourceLimitError(
                    f"Document archive contains more than {MAX_DOCX_MEMBERS} entries."
                )

            names = {member.filename for member in members}
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise DocumentValidationError(
                    "The uploaded file is not a valid PDF, DOC, or DOCX document."
                )

            declared_size = 0
            for member in members:
                if member.flag_bits & 0x1:
                    raise DocumentValidationError(
                        "Encrypted PDF, DOC, or DOCX files are not supported."
                    )
                declared_size += member.file_size
                if declared_size > MAX_UNPACKED_DOCUMENT_BYTES:
                    raise DocumentResourceLimitError(
                        "Document expanded content exceeds the 16MB limit."
                    )

            streamed_size = 0
            for member in members:
                if member.is_dir():
                    continue
                with archive.open(member) as source:
                    while chunk := source.read(DOCUMENT_IO_CHUNK_SIZE):
                        streamed_size += len(chunk)
                        if streamed_size > MAX_UNPACKED_DOCUMENT_BYTES:
                            raise DocumentResourceLimitError(
                                "Document expanded content exceeds the 16MB limit."
                            )
    except DocumentResourceLimitError:
        raise
    except DocumentValidationError:
        raise
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        raise DocumentValidationError(
            "The uploaded file is not a valid PDF, DOC, or DOCX document."
        ) from exc


def _validate_doc_container(path: Path) -> None:
    """Validate the fixed compound-file header used by legacy Word documents."""
    try:
        with path.open("rb") as stream:
            header = stream.read(512)
    except OSError as exc:
        raise DocumentValidationError(
            "The uploaded file is not a valid PDF, DOC, or DOCX document."
        ) from exc

    sector_shift = int.from_bytes(header[30:32], "little") if len(header) >= 32 else -1
    mini_sector_shift = (
        int.from_bytes(header[32:34], "little") if len(header) >= 34 else -1
    )
    if (
        len(header) != 512
        or header[:8] != _COMPOUND_FILE_SIGNATURE
        or header[28:30] != b"\xfe\xff"
        or sector_shift not in (9, 12)
        or mini_sector_shift != 6
        or header[34:40] != b"\x00" * 6
    ):
        raise DocumentValidationError(
            "The uploaded file is not a valid PDF, DOC, or DOCX document."
        )

    major_version = int.from_bytes(header[26:28], "little")
    file_size = path.stat().st_size
    sector_size = 1 << sector_shift
    # WPS Office appends a non-CFB trailer (signature/watermark metadata, seen
    # in the wild at 153 bytes) after the final sector. Floor division keeps
    # every pointer check on the sector-aligned base; the trailing partial
    # sector is ignored, exactly as textutil/LibreOffice ignore it.
    sector_count = file_size // sector_size - 1
    fat_sector_count = int.from_bytes(header[44:48], "little")
    first_directory_sector = int.from_bytes(header[48:52], "little")
    difat_entries = [
        int.from_bytes(header[offset : offset + 4], "little")
        for offset in range(76, 512, 4)
    ]
    inline_fat_sectors = [entry for entry in difat_entries if entry < 0xFFFFFFFA]
    if (
        major_version not in (3, 4)
        or (major_version == 3 and sector_shift != 9)
        or (major_version == 4 and sector_shift != 12)
        or file_size < sector_size * 3
        or fat_sector_count < 1
        or fat_sector_count > sector_count
        or first_directory_sector >= sector_count
        or len(inline_fat_sectors) < min(fat_sector_count, len(difat_entries))
        or any(entry >= sector_count for entry in inline_fat_sectors)
    ):
        raise DocumentValidationError(
            "The uploaded file is not a valid PDF, DOC, or DOCX document."
        )


# Real container signatures hidden behind a legacy ``.doc`` filename. Files
# saved by WPS/Word/Google Docs (or renamed in the file manager) frequently
# carry a .doc extension while their bytes are OOXML, RTF or Word HTML.
_ZIP_LOCAL_FILE_SIGNATURE = b"PK\x03\x04"
_RTF_SIGNATURE = b"{\\rtf"


def _sniff_legacy_doc_format(path: Path) -> str:
    """Identify the real container behind a ``.doc`` filename.

    Returns ``"ole2"`` for a genuine binary Word document, ``"docx"`` for an
    OOXML package, ``"rtf"`` / ``"html"`` for those text formats, and
    ``"unknown"`` for anything unrecognised.
    """
    try:
        with path.open("rb") as stream:
            header = stream.read(512)
    except OSError as exc:
        raise DocumentValidationError(
            "The uploaded file is not a valid PDF, DOC, or DOCX document."
        ) from exc

    if header[:8] == _COMPOUND_FILE_SIGNATURE:
        return "ole2"
    if header[:4] == _ZIP_LOCAL_FILE_SIGNATURE:
        return "docx"
    # RTF/HTML may carry a UTF-8 BOM or leading whitespace before the marker.
    stripped = header.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if stripped.startswith(_RTF_SIGNATURE):
        return "rtf"
    if stripped.startswith(b"<!doctype") or stripped.startswith(b"<html"):
        return "html"
    return "unknown"


def _validate_extracted_text(text: str) -> None:
    """Bound prompt-bound UTF-8 text without allocating another full-size copy."""
    extracted_bytes = 0
    for offset in range(0, len(text), DOCUMENT_IO_CHUNK_SIZE):
        chunk = text[offset : offset + DOCUMENT_IO_CHUNK_SIZE]
        extracted_bytes += len(chunk.encode("utf-8"))
        if extracted_bytes > MAX_EXTRACTED_TEXT_BYTES:
            raise DocumentResourceLimitError(
                "Document extracted text exceeds the 2MB processing limit."
            )


# Matches date ranges like "Jan 2020 - Dec 2023", "May 2021 - Present",
# "January 2020 - Current", and single dates like "Jun 2023".
_MD_DATE_RE = re.compile(
    r"(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?"
    r"|Dec(?:ember)?)"
    r"\.?\s+\d{4})"
    r"(?:\s*[-–—]\s*"
    r"(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?"
    r"|Dec(?:ember)?)"
    r"\.?\s+\d{4}"
    r"|Present|Current|Now|Ongoing))?",
    re.IGNORECASE,
)
_MONTH_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?"
    r"|Dec(?:ember)?)",
    re.IGNORECASE,
)


# Numeric date ranges common in Chinese resumes: "2017.09 - 2021.07",
# "2020年6月 - 2023年8月", "2025.07 - 至今", "2020/06 – Present". The month
# (01-12) must not be followed by another day component (so versions such as
# "21.0.1" never match) and the year needs all four digits (rules out "0.6").
_MD_NUMERIC_DATE_RE = re.compile(
    r"\d{4}\s*[年./-]\s*(?:0?[1-9]|1[0-2])(?!\d|[./-]\d)(?:\s*月)?"
    r"(?:\s*[-–—~～]\s*"
    r"(?:\d{4}\s*[年./-]\s*(?:0?[1-9]|1[0-2])(?!\d|[./-]\d)(?:\s*月)?"
    r"|至今|现在|目前|Present|Current|Now|Ongoing))?",
    re.IGNORECASE,
)
_PRESENT_MARKER_RE = re.compile(
    r"至今|现在|目前|Present|Current|Now|Ongoing", re.IGNORECASE
)
# A years field already carrying month precision in numeric form.
_NUMERIC_MONTH_PRECISE_RE = re.compile(
    r"\d{4}\s*[年./-]\s*(?:0?[1-9]|1[0-2])(?!\d|[./-]\d)"
)


def _extract_markdown_dates(markdown: str) -> list[str]:
    """Extract all month-inclusive date ranges from markdown text."""
    return _MD_DATE_RE.findall(markdown)


def _canonical_numeric_date(match_text: str) -> str:
    """Normalize a numeric date match to "YYYY.MM~YYYY.MM|至今"."""
    parts = re.findall(r"(\d{4})\s*[年./-]\s*(\d{1,2})", match_text)
    rendered = [f"{year}.{int(month):02d}" for year, month in parts[:2]]
    if len(rendered) == 1 and _PRESENT_MARKER_RE.search(match_text):
        rendered.append("至今")
    return "~".join(rendered)


def restore_dates_from_markdown(
    parsed_data: dict[str, Any],
    markdown: str,
) -> dict[str, Any]:
    """Patch year-only dates in parsed data with month-inclusive dates from markdown.

    The LLM sometimes drops months during parsing (e.g. "Jun 2020 - Aug 2021"
    becomes "2020 - 2021"). This function extracts all month-inclusive dates
    from the raw markdown and replaces year-only entries where a match exists.
    """

    def date_key(value: str) -> str:
        years = re.findall(r"\d{4}", value)
        if not years:
            return ""
        suffix = "current" if _PRESENT_MARKER_RE.search(value) else ""
        if not suffix and len(years) == 2 and years[0] == years[1]:
            years = years[:1]
        return " - ".join([*years, suffix] if suffix else years)

    occurrences: list[tuple[str, str, str, int]] = []
    lines = markdown.splitlines()
    for line_index, line in enumerate(lines):
        line_context = " ".join(line.casefold().split())
        for match in _MD_DATE_RE.finditer(line):
            full_date = re.sub(r"\s*[-–—]\s*", " - ", match.group(0).strip())
            key = date_key(full_date)
            if key:
                occurrences.append((key, full_date, line_context, line_index))
        for match in _MD_NUMERIC_DATE_RE.finditer(line):
            full_date = _canonical_numeric_date(match.group(0).strip())
            key = date_key(full_date)
            if key:
                occurrences.append((key, full_date, line_context, line_index))
    if not occurrences:
        return parsed_data

    used: set[int] = set()
    patched = 0
    entry_count = sum(
        sum(isinstance(entry, dict) for entry in parsed_data.get(section, []))
        for section in ("workExperience", "education", "personalProjects")
        if isinstance(parsed_data.get(section), list)
    )
    custom_data = parsed_data.get("customSections")
    if isinstance(custom_data, dict):
        entry_count += sum(
            len(section.get("items", []))
            for section in custom_data.values()
            if isinstance(section, dict)
            and section.get("sectionType") == "itemList"
            and isinstance(section.get("items"), list)
        )

    def restore_entry(entry: Any, identity_fields: tuple[str, ...]) -> None:
        nonlocal patched
        if not isinstance(entry, dict):
            return
        years = entry.get("years", "")
        if not isinstance(years, str) or not years or not years.strip():
            empty = True
            key = ""
        elif _MONTH_RE.search(years) or _NUMERIC_MONTH_PRECISE_RE.search(years):
            return
        else:
            empty = False
            key = date_key(years)
        def key_matches(occurrence_key: str) -> bool:
            if empty:
                return True
            if occurrence_key == key:
                return True
            # A year-only value ("2025") matches an ongoing range starting
            # that same year ("2025.07 - 至今" -> "2025 - current").
            return bool(re.fullmatch(r"\d{4}", key)) and occurrence_key == (
                f"{key} - current"
            )

        candidates = [
            index
            for index, occurrence in enumerate(occurrences)
            if key_matches(occurrence[0]) and index not in used
        ]
        if not candidates:
            return
        terms = [
            " ".join(str(entry.get(field, "")).split()).casefold()
            for field in identity_fields
            if str(entry.get(field, "")).strip()
        ]
        scored = []
        for index in candidates:
            line_context = occurrences[index][2]
            line_index = occurrences[index][3]
            matched_terms = 0
            score = 0
            for term in terms:
                term_score = 20 if term in line_context else 0
                for distance in range(1, 6):
                    previous = line_index - distance
                    if previous >= 0 and term in " ".join(
                        lines[previous].casefold().split()
                    ):
                        term_score = max(term_score, 10 - distance)
                for distance in range(1, 4):
                    following = line_index + distance
                    if following < len(lines) and term in " ".join(
                        lines[following].casefold().split()
                    ):
                        term_score = max(term_score, 4 - distance)
                if term_score:
                    matched_terms += 1
                    score += term_score
            scored.append(((matched_terms, score), index))
        best_score = max(score for score, _ in scored)
        best = [index for score, index in scored if score == best_score]
        selected: int | None = None
        if empty:
            # The field carried no date at all: only fill when a unique line
            # contains at least one identity term literally on the date line
            # (score 20 per term). Neighbouring-line fuzz is not enough here,
            # or project entries would steal work/education periods.
            if terms and len(best) == 1 and best_score[1] >= 20:
                selected = best[0]
        elif best_score[0] > 0 and len(best) == 1 and (
            entry_count == 1 or best_score[0] == len(terms)
        ):
            selected = best[0]
        elif len(candidates) == 1 and entry_count == 1:
            selected = candidates[0]
        if selected is None:
            logger.info("Date restoration left ambiguous value unchanged: %s", years)
            return
        entry["years"] = occurrences[selected][1]
        used.add(selected)
        patched += 1

    for section_key, identity_fields in (
        ("workExperience", ("company", "title")),
        ("education", ("institution", "degree")),
        ("personalProjects", ("name", "role")),
    ):
        for entry in parsed_data.get(section_key, []):
            restore_entry(entry, identity_fields)

    custom = parsed_data.get("customSections", {})
    if isinstance(custom, dict):
        for section in custom.values():
            if (
                not isinstance(section, dict)
                or section.get("sectionType") != "itemList"
            ):
                continue
            for item in section.get("items", []):
                restore_entry(item, ("title", "subtitle"))

    if patched:
        logger.info("Restored months in %d date fields from raw markdown", patched)

    return parsed_data


# ---------------------------------------------------------------------------
# Header demographics backfill
# ---------------------------------------------------------------------------
# Chinese resume headers list the basic facts as spaced ``label：value`` pairs
# (markitdown frequently inserts spaces INSIDE the label, e.g. "姓    名：旷武").
# The LLM occasionally leaves these fields empty or strips a parenthetical tag
# such as "(211)", so they are also recovered deterministically from the raw
# markdown. V4 requires header facts verbatim; for the four demographics the
# recovered value therefore wins over a stripped LLM value, while contact
# fields and languages only fill an empty parsed value.

_HEADER_FIELD_LABELS: tuple[tuple[str, str], ...] = (
    ("name", r"姓\s*名"),
    ("gender", r"性\s*别"),
    ("age", r"年\s*龄"),
    ("workYears", r"工\s*作\s*(?:年\s*限|经\s*验|时\s*间)"),
    ("educationLevel", r"(?:最\s*高)?学\s*历"),
    (
        "languages",
        r"(?:外\s*语|语\s*言)\s*(?:水\s*平|能\s*力)|英\s*语\s*水\s*平",
    ),
    (
        "phone",
        r"联\s*系\s*电\s*话|电\s*话|手\s*机\s*号?\s*码?|Cell(?:\s*phone)?|Tel(?:ephone)?",
    ),
    # Starts on a concrete CJK/letter char (no leading \s*) so the column
    # boundary check lands on the character before the label, not in padding.
    ("email", r"(?:电\s*子\s*)?邮\s*(?:箱|件)|E\s*-?\s*[Mm]ail"),
    (
        "title",
        r"求\s*职\s*意\s*向"
        r"|期\s*望\s*(?:职\s*位|岗\s*位|职\s*业)"
        r"|意\s*向\s*(?:职\s*位|岗\s*位|职\s*业)"
        r"|目\s*标\s*岗\s*位",
    ),
    ("location", r"(?:期\s*望|意\s*向|工\s*作)\s*(?:城\s*市|地\s*点)"),
    # Personal-link cells share the header row. Recognizing them is what ends
    # the previous fact's value span: an unrecognized "博客地址：" label used to
    # glue its Markdown link onto workYears ("13年 博客地址：[x](https://…)").
    (
        "website",
        r"博\s*客\s*地\s*址|个\s*人\s*网\s*站|个\s*人\s*主\s*页|个\s*人\s*博\s*客"
        r"|个\s*人\s*网\s*址|主\s*页|博\s*客|网\s*站|网\s*址"
        r"|Website|Web\s*site|Homepage|Blog(?:\s*site)?",
    ),
    ("linkedin", r"领\s*英|Linked\s*[Ii]n"),
    ("github", r"Git\s*[Hh]ub"),
)

_HEADER_LABEL_RE = re.compile(
    r"(?:"
    + "|".join(f"(?P<{field}>{pattern})" for field, pattern in _HEADER_FIELD_LABELS)
    + r")\s*[:：|｜]\s*"
)

_HEADER_BASIC_HEADINGS = ("基本资料", "个人信息", "基本信息", "个人资料", "个人概况")
_HEADER_STOP_HEADINGS = (
    "教育背景",
    "教育经历",
    "教育情况",
    "学历信息",
    "求学履历",
    "工作经历",
    "工作经验",
    "工作履历",
    "从业经历",
    "职业履历",
    "任职经历",
    "职场经历",
    "实习经历",
    "项目经历",
    "项目经验",
    "项目履历",
    "重点项目",
    "专业技能",
    "职业技能",
    "核心技能",
    "专业能力",
    "技能专长",
    "技能清单",
    "个人优势",
    "核心优势",
    "竞争优势",
    "综合优势",
    "个人简介",
    "个人介绍",
    "个人简述",
    "自我介绍",
    "个人总结",
    "自我评价",
    "个人评价",
    "荣誉证书",
    "资质荣誉",
    "资格证书",
    "获奖情况",
    "校园经历",
    "社会实践",
    "兴趣特长",
)
_HEADER_HEADING_RE = re.compile(
    r"^\s*(?:[◆■●★◇▸►#*]{1,2}\s*)?"
    r"(?P<name>"
    + "|".join(_HEADER_BASIC_HEADINGS + _HEADER_STOP_HEADINGS)
    + r")[|｜*\s]*$",
    re.MULTILINE,
)
# A label not found within this many leading characters is assumed to live in
# the body, not the header.
_HEADER_SEARCH_LIMIT = 2000
_LABEL_BOUNDARY_CHARS = " \t\r\n　|｜:："


def _header_demographics_region(markdown: str) -> str:
    """Return the raw span from the first header label to the next section heading.

    Header facts are scanned only inside this region so label words appearing
    in body text (e.g. "电话销售" in a job title) are never treated as facts.
    """
    first: re.Match[str] | None = None
    for candidate in _HEADER_LABEL_RE.finditer(markdown):
        if candidate.start() > _HEADER_SEARCH_LIMIT:
            break
        if candidate.start() == 0 or markdown[candidate.start() - 1] in _LABEL_BOUNDARY_CHARS:
            first = candidate
            break
    if first is None:
        return ""
    for heading in _HEADER_HEADING_RE.finditer(markdown, first.end()):
        if heading.group("name") in _HEADER_STOP_HEADINGS:
            return markdown[first.start() : heading.start()]
    return markdown[first.start() : first.start() + _HEADER_SEARCH_LIMIT]


def _clean_header_value(raw: str) -> str:
    """Trim a header value at the line/cell boundary and fold spacing."""
    line = raw.split("\n", 1)[0]
    line = re.split(r"[|｜]", line)[0]
    line = line.strip(" \t　:：;；,，、")
    return re.sub(r"\s+", " ", line).strip()


# Short header facts whose values must stay single, label-free tokens. When a
# neighboring header cell is glued onto one of them, the pollution always takes
# one of three shapes below (observed in real uploads: workYears
# "13年 博客地址：[fengba.blog.csdn.net](https://…)" and educationLevel
# "本科 学 校： 西安电子科技大学").
_HEADER_FACT_FIELDS: tuple[str, ...] = ("gender", "age", "workYears", "educationLevel")

# Inline Markdown link/image, e.g. "[fengba.blog.csdn.net](https://…)" — the
# URL target is captured so link fields can collapse to it.
_MARKDOWN_INLINE_LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*([^)\s]*)\s*\)")
_BARE_URL_RE = re.compile(r"(?:https?://|www\.)[^\s|｜，,；;）)】\]]+")
# A second "label：" inside a fact value marks the next glued cell. The label
# must follow whitespace (the cell separator) so a value whose own opening
# characters reach a colon ("本科 学 校：…") is cut at the label, not at its
# first character. Spaces inside the label are allowed because markitdown
# splits CJK runs ("学 校").
_EMBEDDED_LABEL_RE = re.compile(r"(?<=\s)[一-鿿A-Za-z][一-鿿A-Za-z\s]{0,11}\s*[:：]")


def sanitize_header_fact_value(value: str) -> str:
    """Drop glued next-cell content from a short header fact value.

    Header facts (gender/age/workYears/educationLevel) are short tokens; an
    inline Markdown link, bare URL, or embedded ``label：`` inside the value
    means another header cell was glued onto it. Everything from the glued
    boundary onward is truncated; the clean prefix survives verbatim. A
    boundary at position 0 is ignored rather than blanking the whole field.
    """
    cut = len(value)
    for pattern in (_MARKDOWN_INLINE_LINK_RE, _BARE_URL_RE, _EMBEDDED_LABEL_RE):
        match = pattern.search(value)
        if match and 0 < match.start() < cut:
            cut = match.start()
    return value[:cut].strip(" \t　:：;；,，、")


def normalize_header_link_value(value: str) -> str:
    """Normalize one personal-link header cell (website/linkedin/github).

    Markdown links collapse to their URL target ("[blog](https://x.com)" →
    "https://x.com"); a bare URL embedded in prose is extracted; plain hosts
    and other text pass through stripped, since the render layer promotes
    bare hosts to "https://…" itself.
    """
    inline = _MARKDOWN_INLINE_LINK_RE.search(value)
    if inline:
        if inline.group(1):
            return inline.group(1).strip()
        # Empty target "[text]()": fall back to the bracket text.
        bracket = re.match(r"!?\[([^\]]*)\]", inline.group(0))
        return bracket.group(1).strip() if bracket else ""
    bare = _BARE_URL_RE.search(value)
    if bare:
        return bare.group(0).rstrip(".,;)）】]")
    return value.strip()


def _extract_header_fields(markdown: str) -> dict[str, str]:
    """Scan the resume header for ``label：value`` demographics."""
    region = _header_demographics_region(markdown)
    if not region:
        return {}
    # First pass: a label only counts when it starts a layout column
    # (preceded by whitespace or a cell border), so label words embedded in a
    # value, e.g. "电话销售" inside a 求职意向, are rejected as spans.
    accepted = [
        match
        for match in _HEADER_LABEL_RE.finditer(region)
        if match.start() == 0 or region[match.start() - 1] in _LABEL_BOUNDARY_CHARS
    ]
    found: dict[str, str] = {}
    for index, match in enumerate(accepted):
        end = accepted[index + 1].start() if index + 1 < len(accepted) else len(region)
        value = _clean_header_value(region[match.end() : end])
        field = match.lastgroup
        if field and value and field not in found:
            found[field] = value
    return found


def _normalize_header_value(field: str, value: str) -> str | list[str]:
    """Normalize one raw header value for its schema field."""
    if field in _HEADER_FACT_FIELDS:
        value = sanitize_header_fact_value(value)
    if field in ("website", "linkedin", "github"):
        return normalize_header_link_value(value)
    if field == "email":
        match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value)
        return match.group(0) if match else ""
    if field == "phone":
        match = re.search(r"\+?\d[\d\s\-()]{5,}\d", value)
        return re.sub(r"\s+", "", match.group(0)) if match else ""
    if field == "languages":
        return [part.strip() for part in re.split(r"[、，,；;/]+", value) if part.strip()]
    if field == "gender":
        match = re.search(r"[男女]", value)
        return match.group(0) if match else value
    if field == "age":
        return re.sub(r"\s*(岁)\s*", r"\1", value).strip()
    return value


def backfill_personal_info_from_markdown(
    parsed_data: dict[str, Any],
    markdown: str,
) -> dict[str, Any]:
    """Recover header demographics from raw markdown label：value pairs.

    For gender/age/workYears/educationLevel the recovered (verbatim) value
    also replaces a stripped LLM value — e.g. source "统招本科(211)" parsed as
    "本科" — so header facts and their qualifiers (211/985/统招/全日制) survive
    regardless of LLM behavior. Glued next-cell content (a personal link or
    embedded "label：" boundary) is truncated from those fact values first.
    name/phone/email/title/location/website/linkedin/github only fill empty
    fields (Markdown links collapse to their URL target); recovered languages
    are unioned into additional.languages.
    """
    extracted = _extract_header_fields(markdown)
    if not extracted:
        return parsed_data

    info = parsed_data.get("personalInfo")
    if not isinstance(info, dict):
        info = {}
        parsed_data["personalInfo"] = info

    patched = 0
    verbatim_fields = _HEADER_FACT_FIELDS
    # Personal links are contact-style facts: they fill an empty field but
    # never replace a value the LLM already extracted.
    for field in (
        "name",
        "phone",
        "email",
        "title",
        "location",
        "website",
        "linkedin",
        "github",
        *verbatim_fields,
    ):
        raw_value = extracted.get(field)
        if not raw_value:
            continue
        value = _normalize_header_value(field, raw_value)
        if not isinstance(value, str) or not value:
            continue
        current = str(info.get(field) or "").strip()
        if field in verbatim_fields:
            if current != value:
                info[field] = value
                patched += 1
        elif not current:
            info[field] = value
            patched += 1

    languages = _normalize_header_value("languages", extracted.get("languages", ""))
    if isinstance(languages, list) and languages:
        additional = parsed_data.get("additional")
        if not isinstance(additional, dict):
            additional = {}
            parsed_data["additional"] = additional
        existing = additional.get("languages")
        if not isinstance(existing, list):
            existing = []
        merged = [*existing]
        for lang in languages:
            if lang not in merged:
                merged.append(lang)
        if len(merged) != len(existing):
            additional["languages"] = merged
            patched += len(merged) - len(existing)

    if patched:
        logger.info("Backfilled %d personal-info field(s) from raw markdown", patched)

    return parsed_data


# ---------------------------------------------------------------------------
# Reverse-chronological ordering of work/education entries
# ---------------------------------------------------------------------------

_EN_MONTH_BY_NAME = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_START_DATE_RE = re.compile(
    r"(" + "|".join(_EN_MONTH_BY_NAME) + r")\s*(\d{4})"
    r"|(\d{4})\s*[.\-/年]\s*(\d{1,2})\s*月?"
    r"|(\d{4})",
    re.IGNORECASE,
)


def _start_date_key(value: Any) -> tuple[int, int]:
    """Return ``(year, month)`` of the FIRST date token in a years string.

    Understands "2018.05 - 2020.11", "2010.09-2014.06", "Jun 2020 - Aug 2021",
    "2020年5月" and plain years. An entry without a parseable date sorts to
    ``(0, 0)`` so it sinks below every dated entry.
    """
    if not isinstance(value, str):
        return (0, 0)
    match = _START_DATE_RE.search(value)
    if not match:
        return (0, 0)
    if match.group(1):  # "Jun 2020" — English month precedes the year
        month = _EN_MONTH_BY_NAME[match.group(1).casefold()]
        return (int(match.group(2)), month)
    if match.group(3):  # "2018.05" / "2020年5月"
        month = int(match.group(4))
        return (int(match.group(3)), month if 1 <= month <= 12 else 0)
    return (int(match.group(5)), 0)


def sort_timeline_sections_newest_first(
    parsed_data: dict[str, Any],
) -> dict[str, Any]:
    """Sort workExperience and education newest-first by START date.

    Stable: entries without a parseable date keep their relative order and
    sink to the end of their section; personalProjects and custom sections
    are untouched.
    """
    for section_key in ("workExperience", "education"):
        entries = parsed_data.get(section_key)
        if not isinstance(entries, list) or len(entries) < 2:
            continue
        parsed_data[section_key] = sorted(
            entries,
            key=lambda entry: _start_date_key(entry.get("years"))
            if isinstance(entry, dict)
            else (0, 0),
            reverse=True,
        )
    return parsed_data


# ---------------------------------------------------------------------------
# Canonical date-period normalization ("yyyy.MM~yyyy.MM" / "yyyy.MM~至今")
# ---------------------------------------------------------------------------

#: Numeric point "2020.06" / "2020/6" / "2020-06" / "2020年6月" (no day part).
_CANON_NUMERIC_POINT_RE = re.compile(
    r"(\d{4})\s*[年./-]\s*(0?[1-9]|1[0-2])(?!\d|[./-]\d)(?:\s*月)?"
)
#: English point "Jan 2020" / "January 2020" (optional trailing dot).
_CANON_EN_POINT_RE = re.compile(
    r"\b(" + "|".join(sorted(_EN_MONTH_BY_NAME, key=len, reverse=True)) + r")\.?\s+(\d{4})",
    re.IGNORECASE,
)
#: Bare four-digit year ("2020"); never adjacent to another date component.
_CANON_BARE_YEAR_RE = re.compile(r"(?<![\d.])(\d{4})(?!\d|[./-]\d)")
#: Open-ended markers all render as Chinese 至今 (canonical for all locales).
_CANON_PRESENT_RE = re.compile(r"至今|现在|目前|Present|Current|Now|Ongoing", re.IGNORECASE)
#: English word connector ("Jan 2020 to Dec 2023"); Chinese 至 also accepted.
_CANON_CONNECTOR_WORD_RE = re.compile(r"\bto\b", re.IGNORECASE)
#: A single trailing parenthesized note ("2020.06~2023.09（实习）") is preserved.
_CANON_TRAILING_NOTE_RE = re.compile(r"^[（(][^（）()]*[)）]\s*$")
_CANON_SKIP_CHARS = frozenset(" \t\r\n\u00a0-–—―~～至")


def _canon_point_text(match: re.Match[str], kind: str) -> tuple[int, int, str]:
    if kind == "en":
        month = _EN_MONTH_BY_NAME[match.group(1).casefold()]
        return (match.start(), match.end(), f"{int(match.group(2)):04d}.{month:02d}")
    if kind == "numeric":
        return (match.start(), match.end(), f"{int(match.group(1)):04d}.{int(match.group(2)):02d}")
    return (match.start(), match.end(), f"{int(match.group(1)):04d}")


def canonicalize_date_period(value: str) -> str:
    """Normalize one ``years`` string to canonical date presentation.

    Output forms: ``"2020.06~2023.09"``, ``"2021.05~至今"``, year-only
    ``"2020~2021"`` and a single point ``"2020.06"`` — tilde connector,
    no spaces, months zero-padded; English month names and every open-ended
    marker (Present/Current/Now/Ongoing/现在/目前) become numeric + 至今.

    Conservative on purpose: values carrying non-date prose (colloquial
    durations like "三年经验", stray words, multiple markers) are returned
    byte-for-byte unchanged, except for one optional trailing parenthesized
    note (e.g. "（实习）"), which is preserved. Idempotent on canonical input.
    """
    if not isinstance(value, str) or not value.strip():
        return value

    # Specific (month-precise) tokens first; bare years fill only unclaimed
    # spans so "2020.06" never yields both a numeric and a year token.
    tokens: list[tuple[int, int, str]] = []
    for match in _CANON_NUMERIC_POINT_RE.finditer(value):
        tokens.append(_canon_point_text(match, "numeric"))
    for match in _CANON_EN_POINT_RE.finditer(value):
        if not any(start < match.end() and match.start() < end for start, end, _ in tokens):
            tokens.append(_canon_point_text(match, "en"))
    for match in _CANON_BARE_YEAR_RE.finditer(value):
        if not any(start < match.end() and match.start() < end for start, end, _ in tokens):
            tokens.append(_canon_point_text(match, "bare"))
    tokens.sort(key=lambda token: token[0])

    present_matches = [
        match
        for match in _CANON_PRESENT_RE.finditer(value)
        if not any(start < match.end() and match.start() < end for start, end, _ in tokens)
    ]

    points = [text for _, _, text in tokens]
    has_present = bool(present_matches)
    if has_present:
        ordered = sorted(tokens + [(m.start(), m.end(), "至今") for m in present_matches],
                         key=lambda token: token[0])
    else:
        ordered = tokens
    if len(present_matches) > 1 or len(points) not in (1, 2) or (has_present and len(points) != 1):
        return value

    # Everything outside date/marker tokens must be connectors/whitespace;
    # one trailing parenthesized note is allowed after the final token.
    note = ""
    cursor = 0
    for index, (start, end, _) in enumerate(ordered):
        gap = value[cursor:start]
        residual = _CANON_CONNECTOR_WORD_RE.sub("", gap)
        if any(char not in _CANON_SKIP_CHARS for char in residual):
            return value
        cursor = end
    tail = value[cursor:].strip()
    if tail:
        if not _CANON_TRAILING_NOTE_RE.fullmatch(tail):
            return value
        note = tail

    if has_present:
        canonical = f"{points[0]}~至今"
    elif len(points) == 2:
        canonical = f"{points[0]}~{points[1]}"
    else:
        canonical = points[0]
    return canonical + note


def normalize_date_periods(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize every ``years`` field (work/education/projects/custom items).

    Mutates the entry dicts in place like the other post-processors; callers
    that need the original preserved deep-copy before calling. Fields that
    cannot be parsed are passed through unchanged.
    """
    for section_key in ("workExperience", "education", "personalProjects"):
        entries = parsed_data.get(section_key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("years"), str):
                entry["years"] = canonicalize_date_period(entry["years"])

    custom = parsed_data.get("customSections")
    if isinstance(custom, dict):
        for section in custom.values():
            if not isinstance(section, dict) or section.get("sectionType") != "itemList":
                continue
            for item in section.get("items", []):
                if isinstance(item, dict) and isinstance(item.get("years"), str):
                    item["years"] = canonicalize_date_period(item["years"])
    return parsed_data


# Sub-labels that may appear INSIDE a work/project item description
# (技术架构：/工作职责：/技术难点及亮点： …). Models occasionally glue such a
# label and its first content line into one row; splitting it restores the
# source layout (label on its own "plain" row, content untouched). Only these
# curated labels are split — normal duty bullets routinely contain a
# mid-sentence colon ("设计并落地……：租户隔离……") and must never be cut.
_SUB_LABEL_CANDIDATES = (
    "技术难点及亮点",
    "技术难度及解决方案",
    "技术架构",
    "系统架构",
    "架构说明",
    "项目背景",
    "项目概述",
    "业务背景",
    "项目描述",
    "项目简介",
    "需求背景",
    "项目概况",
    "项目介绍",
    "工作职责",
    "工作内容",
    "项目职责",
    "个人职责",
    "项目责任",
    "核心职责与成果",
    "项目职责与成果",
    "项目职责和成果",
    "项目职责及成果",
    "工作职责与成果",
    "工作职责和成果",
    "工作职责及成果",
    "个人职责与成果",
    "职责与成果",
    "职责和成果",
    "职责及成果",
    "主要职责",
    "核心职责",
    "核心工作",
    "责任描述",
    "技术栈",
    "技术列表",
    "技术选型",
    "所用技术",
    "技术清单",
    "技术方案",
    "技术亮点",
    "技术难点",
    "难点及亮点",
    "难点与解决",
    "难点与方案",
    "解决方案",
    "项目亮点",
    "项目难点",
    "负责内容",
    "项目成果",
    "个人成果",
    "工作业绩",
    "项目业绩",
    "主要成果",
    "核心成果",
    # Outcome/effectiveness modules are PEERS of 项目亮点 (real resumes carry
    # both in one project: highlight bullets followed by a 项目成效 prose
    # block). They stay verbatim — deliberately NOT in
    # PROJECT_SUB_LABEL_CANONICAL, so they must never be merged into 项目亮点
    # or rendered as a nested numbered head inside it.
    "项目成效",
    "工作成效",
    "实施成效",
    "建设成效",
    "应用成效",
    "业务成效",
    "落地成效",
    "实际成效",
    "量化成效",
    "运营成效",
    "项目效果",
    "实施效果",
    "应用效果",
    "落地效果",
    "运行效果",
    "实际效果",
    "项目角色",
    "担任角色",
)

_INLINE_SUB_LABEL_RE = re.compile(
    r"^\s*(?:\d{1,2}\s*[.、)）．:：]\s*)?"
    r"(" + "|".join(sorted(_SUB_LABEL_CANDIDATES, key=len, reverse=True)) + r")\s*[：:]\s*"
    r"(\S.*)$"
)

# A row that is ONLY a sub-label ("工作职责：" / "项目治理："). This also
# recognizes labels the model knows nothing about, so unplanned sub-modules
# keep their source look: the row renders as a plain label line instead of
# taking a number. The first alternative allows a space/hyphen inside the run
# so latin-prefixed heads rewritten by the model ("CPU 飙升问题：") still
# match. Mirrored by resume_docx._STANDALONE_LABEL_RE and the frontend
# STANDALONE_LABEL_RE — keep the three in sync.
_STANDALONE_SUB_LABEL_RE = re.compile(
    r"^\s*(?:\d{1,2}\s*[.、)）．:：]\s*)?"
    r"(?:[一-鿿A-Za-z][一-鿿A-Za-z0-9/（）() -]{0,11}|[A-Za-z][A-Za-z /-]{0,20})"
    r"\s*[：:]\s*$"
)


# Within PROJECT items, sub-module headings are unified to four canonical
# names: duty groups → 项目职责， highlight/result/difficulty groups →
# 项目亮点， intro/background groups → 项目背景， tech-stack enumerations →
# 技术栈. Projects only — a work-entry "工作职责：" label stays verbatim.
# 项目描述 / 系统架构 / 架构说明 stay verbatim (not in the user-facing alias
# lists) but keep their descriptive, unnumbered layout. The frontend mirrors
# this map at render time so already-stored resumes get the canonical names
# without re-parsing; keep the two in sync.
PROJECT_SUB_LABEL_CANONICAL: dict[str, str] = {
    "项目成果": "项目亮点",
    "个人成果": "项目亮点",
    "技术亮点": "项目亮点",
    "技术难点": "项目亮点",
    "难点与解决": "项目亮点",
    "技术难点及亮点": "项目亮点",
    "工作职责": "项目职责",
    "主要职责": "项目职责",
    "负责内容": "项目职责",
    "核心工作": "项目职责",
    "工作内容": "项目职责",
    # Personal-duty phrasings seen in real uploads ("个人职责：" / "项目责任：")
    # are the same duty module under a different heading.
    "个人职责": "项目职责",
    "项目责任": "项目职责",
    # Combined duty + result headings ("项目职责与成果：" / "核心职责与成果：")
    # open a duty region; they are unified to the canonical 项目职责 name.
    "核心职责与成果": "项目职责",
    # Combined duty + result headings ("项目职责与成果：") open a duty region;
    # they are unified to the canonical 项目职责 name for projects.
    "项目职责与成果": "项目职责",
    "项目职责和成果": "项目职责",
    "项目职责及成果": "项目职责",
    "工作职责与成果": "项目职责",
    "工作职责和成果": "项目职责",
    "工作职责及成果": "项目职责",
    "个人职责与成果": "项目职责",
    "职责与成果": "项目职责",
    "职责和成果": "项目职责",
    "职责及成果": "项目职责",
    "项目概述": "项目背景",
    "业务背景": "项目背景",
    "项目简介": "项目背景",
    "需求背景": "项目背景",
    "项目概况": "项目背景",
    "项目介绍": "项目背景",
    "技术选型": "技术栈",
    "技术架构": "技术栈",
    "所用技术": "技术栈",
    "技术清单": "技术栈",
    "技术列表": "技术栈",
}

# Descriptive (non-duty) sub-labels: project intro/background and tech-stack
# enumerations. When split out of a glued row inside a PROJECT, their content
# row is forced to "plain" so it renders as unnumbered body text (it is
# context, not a duty/highlight point). Mirrors the frontend
# splitProjectPlainPrefix() display rule for already-stored glued rows.
PROJECT_INLINE_PLAIN_LABELS: frozenset[str] = frozenset(
    {
        "项目简介",
        "项目描述",
        "项目概况",
        "项目背景",
        "项目概述",
        "业务背景",
        "需求背景",
        "项目介绍",
        "技术架构",
        "系统架构",
        "架构说明",
        "技术栈",
        "技术列表",
        "技术选型",
        "所用技术",
        "技术清单",
    }
)


def _canonicalize_sub_label(
    label_row: str,
    canonical: Mapping[str, str] | None,
) -> tuple[str, bool]:
    """Rename a standalone label row ("项目成果：") per the canonical map.

    The trailing ASCII/CJK colon (when present) is preserved. Returns
    ``(new_row, changed)``.
    """
    if not canonical:
        return label_row, False
    stripped = label_row.strip()
    if stripped.endswith(("：", ":")):
        core, suffix = stripped[:-1].strip(), stripped[-1]
    else:
        core, suffix = stripped, ""
    target = canonical.get(core)
    if target is None:
        return label_row, False
    new_row = target + suffix
    return new_row, new_row != label_row


def _normalize_item_description_rows(
    description: Any,
    description_styles: Any,
    canonical_labels: Mapping[str, str] | None = None,
    split_descriptive_only: bool = False,
) -> tuple[list[str], list[str]] | None:
    """Restore sub-label rows inside one work/project/custom item.

    Two deterministic repairs, both format-preserving for the content text:

    * a row that is only a sub-label ("工作职责：", including unplanned labels
      the prompt never enumerated) is forced to the ``label`` style so it
      renders bold and without a number regardless of what the model emitted;
    * a curated sub-label glued to its first content line
      ("技术架构：Spring AI …") is split into a bold label row followed by the
      content row with its original style.

    When ``canonical_labels`` is given (project items), label headings are
    additionally renamed per that map (e.g. 项目成果： → 项目亮点：).

    ``split_descriptive_only`` mirrors the frontend read path: glued duty/
    highlight labels stay on one row (only the prefix is canonicalized at
    render), while glued descriptive labels （项目简介/技术栈/…) still split
    into a bold heading plus an unnumbered body content row.
    """
    if not isinstance(description, list):
        return None

    styles = description_styles if isinstance(description_styles, list) else []
    new_description: list[str] = []
    new_styles: list[str] = []
    changed = False

    for index, row in enumerate(description):
        if not isinstance(row, str):
            new_description.append(row)
            new_styles.append(styles[index] if index < len(styles) else "bullet")
            continue

        style = styles[index] if index < len(styles) else "bullet"
        if style not in ("bullet", "plain", "label"):
            style = "bullet"

        standalone = _STANDALONE_SUB_LABEL_RE.match(row)
        if standalone:
            label_row = re.sub(
                r"^\s*(?:\d{1,2}\s*[.、)）．:：]\s*)?", "", row
            ).strip()
            label_row, renamed = _canonicalize_sub_label(label_row, canonical_labels)
            new_description.append(label_row)
            new_styles.append("label")
            if style != "label" or label_row != row or renamed:
                changed = True
            continue

        inline = _INLINE_SUB_LABEL_RE.match(row)
        if inline:
            source_label, content = inline.group(1), inline.group(2).strip()
            if (
                split_descriptive_only
                and source_label not in PROJECT_INLINE_PLAIN_LABELS
            ):
                # Legacy glued duty/highlight row: keep it on one row, the
                # render-time prefix canonicalization handles its display.
                new_description.append(row)
                new_styles.append(style)
                continue
            label = source_label
            if canonical_labels:
                label = canonical_labels.get(label, label)
            new_description.append(f"{label}：")
            new_styles.append("label")
            new_description.append(content)
            # In projects, intro/background/tech-stack content is body text,
            # never a numbered point (even if the model marked the row bullet).
            if canonical_labels and source_label in PROJECT_INLINE_PLAIN_LABELS:
                new_styles.append("plain")
            else:
                new_styles.append(style)
            changed = True
            continue

        # Colon-less label rows ("负责内容") emitted with the label style are
        # not standalone-regex matches but still get the canonical rename.
        if style == "label" and canonical_labels:
            label_row, renamed = _canonicalize_sub_label(row, canonical_labels)
            new_description.append(label_row)
            new_styles.append("label")
            if renamed:
                changed = True
            continue

        # A bare known project sub-label name without a trailing colon
        # ("个人职责" / "项目成果") is a module heading even when a weak model
        # emits it with the plain/bullet style: rename it to the canonical
        # name and promote the row to "label" so the region repair pass sees
        # the module boundary. Only an EXACT whole-row match qualifies, so a
        # content sentence merely containing such a word is never touched.
        if canonical_labels and style != "label":
            bare_core = strip_source_point_marker(row).strip()
            target = canonical_labels.get(bare_core)
            if target is not None:
                new_description.append(target)
                new_styles.append("label")
                changed = True
                continue

        new_description.append(row)
        new_styles.append(style)

    return (new_description, new_styles) if changed else None


# Source-carried point numbering ("1、", "1)", "①", "一、", "• ", "- ").
# Mirrors the frontend POINT_MARKER_RE (components/resume/list-format.ts):
# every rendered list supplies its own numbers, so keeping these prefixes in
# stored content produces double numbering ("1. 1、…"). Keep the two in sync.
_POINT_MARKER_RE = re.compile(
    r"^\s*(?:\d{1,2}\s*[.、)）．:：]"
    r"|[（(]\d{1,2}[)）]"
    r"|[①-⑩]"
    # Glyph markers need no following whitespace ("•Java" is still a bullet);
    # dash markers keep the whitespace requirement to protect minus signs and
    # version ranges like "-30%" / "v1.0-2.0".
    r"|[•·・●▪▸▹◆■]"
    r"|[\-—–]\s+"
    r"|[一二三四五六七八九十]{1,3}\s*[、.．)）])\s*"
)


def strip_source_point_marker(text: Any) -> Any:
    """Remove one leading source numbering/bullet marker from a point."""
    if not isinstance(text, str):
        return text
    return _POINT_MARKER_RE.sub("", text, count=1)


# CJK compatibility-character normalization. PDFs with embedded subset fonts
# (observed via markitdown/pdfminer) extract common Chinese characters as
# Kangxi Radicals (U+2F00–U+2FDF, "⼯" for 工, "⽬" for 目 …) or CJK Radicals
# Supplement glyphs (U+2E80–U+2EF3, "⻓" for 长 …).  Every downstream regex
# (heading detection, sub-label restoration, date repair) then fails to match
# those words. NFKC folds Kangxi codepoints onto unified ideographs; a handful
# fold onto a TRADITIONAL form and need a simplified override, and the
# supplement block has no NFKC mapping at all.
_CJK_COMPAT_SIMPLIFIED_OVERRIDES: dict[str, str] = {
    "⼾": "户",  # NFKC gives traditional 戶
    "⾒": "见",
    "⾙": "贝",
    "⾞": "车",
    "⾧": "长",
    "⾨": "门",
    "⾱": "韦",
    "⾴": "页",
    "⾵": "风",
    "⾶": "飞",
    "⾺": "马",
    "⿂": "鱼",
    "⿃": "鸟",
    "⿄": "卤",
    "⿆": "麦",
    "⿈": "黄",
    "⿑": "齐",
    "⿒": "齿",
    "⿓": "龙",
    "⿔": "龟",
    "⿌": "黾",
    "⾭": "青",  # NFKC gives 靑 (variant form)
}

# CJK Radicals Supplement glyphs that stand for a specific modern simplified
# character when they appear alone in running text (no NFKC mapping).
_CJK_RADICAL_SUPPLEMENT_MAP: dict[str, str] = {
    "⺰": "纟",
    "⻅": "见",
    "⻆": "角",
    "⻈": "讠",
    "⻉": "贝",
    "⻋": "车",
    "⻓": "长",
    "⻔": "门",
    "⻙": "韦",
    "⻚": "页",
    "⻛": "风",
    "⻜": "飞",
    "⻠": "饣",
    "⻢": "马",
    "⻥": "鱼",
    "⻦": "鸟",
    "⻧": "卤",
    "⻨": "麦",
    "⻩": "黄",
    "⻪": "黾",
    "⻬": "齐",
    "⻮": "齿",
    "⻰": "龙",
    "⻳": "龟",
}


def _build_cjk_compat_table() -> dict[int, str]:
    """Kangxi block via NFKC + simplified overrides + supplement glyphs."""
    table: dict[int, str] = {}
    for codepoint in range(0x2F00, 0x2FDF + 1):
        radical = chr(codepoint)
        folded = unicodedata.normalize("NFKC", radical)
        if len(folded) == 1 and folded != radical:
            table[codepoint] = folded
    for radical, replacement in _CJK_COMPAT_SIMPLIFIED_OVERRIDES.items():
        table[ord(radical)] = replacement
    for radical, replacement in _CJK_RADICAL_SUPPLEMENT_MAP.items():
        table[ord(radical)] = replacement
    return table


_CJK_COMPAT_TABLE: dict[int, str] = _build_cjk_compat_table()


def normalize_cjk_compat(text: Any) -> Any:
    """Map radical/compatibility CJK glyphs onto normal simplified characters.

    Non-string values pass through unchanged. Punctuation is deliberately NOT
    normalized (no blanket NFKC): full-width ``：，（）`` must survive because
    the parsing heuristics distinguish them from ASCII equivalents.
    """
    if not isinstance(text, str):
        return text
    return text.translate(_CJK_COMPAT_TABLE)


def normalize_cjk_compat_deep(value: Any) -> Any:
    """Rebuild a nested dict/list with every string leaf compat-normalized.

    Keys are never modified. Non-string scalars pass through unchanged.
    """
    if isinstance(value, str):
        return normalize_cjk_compat(value)
    if isinstance(value, list):
        return [normalize_cjk_compat_deep(item) for item in value]
    if isinstance(value, dict):
        return {
            key: normalize_cjk_compat_deep(item) for key, item in value.items()
        }
    return value


# Markdown emphasis modifiers ("**bold**", "__x__", "*x*", "_x_",
# "`code`", "~~strike~~"). Weak models sometimes copy them through verbatim,
# and the markers can even get split across adjacent fields during JSON
# extraction (observed: educationLevel "统招本科（**985&211)" followed by
# workYears " **5年大型医院项目，3年电商）**", plus a trailing orphan in
# additional.languages). Resume renderers never interpret markdown, so every
# emphasis marker is removed while its enclosed text is kept. Mirrored on the
# frontend display layer (lib/utils/markdown-strip.ts).
_MD_BOLD_STAR_RE = re.compile(r"\*\*\s*([^*]+?)\s*\*\*", re.DOTALL)
_MD_BOLD_UNDER_RE = re.compile(r"__\s*([^_]+?)__", re.DOTALL)
_MD_ITALIC_STAR_RE = re.compile(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])")
_MD_ITALIC_UNDER_RE = re.compile(r"(?<![\w_])_([^_\s][^_]*?)_(?![\w_])")
_MD_CODE_RE = re.compile(r"`+([^`]+?)`+")
_MD_STRIKE_RE = re.compile(r"~~([^~]+?)~~")
_MD_ORPHAN_BOLD_RE = re.compile(r"\*\*|__")
_MD_ORPHAN_STRIKE_RE = re.compile(r"~~")


def strip_markdown_emphasis(text: Any) -> Any:
    """Remove Markdown emphasis modifiers from one string, keeping the text.

    Paired markers are unwrapped first; orphan ``**`` / ``__`` / ``~~``
    fragments (including markers split across fields upstream) are then
    removed. Single ``*`` / ``_`` are only treated as emphasis in matched
    pairs, so "A*", "5*8" and "my_var" stay intact.
    """
    if not isinstance(text, str):
        return text
    text = _MD_BOLD_STAR_RE.sub(r"\1", text)
    text = _MD_BOLD_UNDER_RE.sub(r"\1", text)
    text = _MD_ITALIC_STAR_RE.sub(r"\1", text)
    text = _MD_ITALIC_UNDER_RE.sub(r"\1", text)
    text = _MD_CODE_RE.sub(r"\1", text)
    text = _MD_STRIKE_RE.sub(r"\1", text)
    text = _MD_ORPHAN_BOLD_RE.sub("", text)
    text = _MD_ORPHAN_STRIKE_RE.sub("", text)
    return text


def strip_markdown_emphasis_deep(value: Any) -> Any:
    """Rebuild a nested dict/list with every string leaf emphasis-stripped.

    Keys are never modified. Non-string scalars pass through unchanged.
    """
    if isinstance(value, str):
        return strip_markdown_emphasis(value)
    if isinstance(value, list):
        return [strip_markdown_emphasis_deep(item) for item in value]
    if isinstance(value, dict):
        return {
            key: strip_markdown_emphasis_deep(item) for key, item in value.items()
        }
    return value


# Display list fields that must never contain repeated entries. Index-aligned
# arrays (description / descriptionStyles) are intentionally excluded: their
# positions carry meaning, so a generic collapse would desynchronise them.
_DEDUPABLE_ADDITIONAL_FIELDS = (
    "technicalSkills",
    "certificationsTraining",
    "awards",
    "languages",
)


def dedupe_string_values(values: list[Any]) -> list[Any]:
    """Drop repeated entries from a list of plain strings.

    Comparison is whitespace-insensitive; the first occurrence wins and
    empty strings are preserved. Lists containing non-strings are returned
    untouched.
    """
    if not all(isinstance(item, str) for item in values):
        return values
    seen: set[str] = set()
    deduped: list[str] = []
    for item in values:
        key = item.strip()
        if key:
            if key in seen:
                continue
            seen.add(key)
        deduped.append(item)
    return deduped


def dedupe_resume_lists(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """De-duplicate the rendered string-list fields of parsed resume data.

    Weak extractions repeat the same fact with different formatting
    (observed: additional.languages ["英语四级", "英语四级**"]); once the
    Markdown strip removes the markers the two collapse to one text and
    would otherwise render twice ("外语水平：英语四级、英语四级").
    """
    additional = parsed_data.get("additional")
    if isinstance(additional, dict):
        for field in _DEDUPABLE_ADDITIONAL_FIELDS:
            values = additional.get(field)
            if isinstance(values, list):
                additional[field] = dedupe_string_values(values)

    custom_sections = parsed_data.get("customSections")
    if isinstance(custom_sections, dict):
        for section in custom_sections.values():
            strings = section.get("strings") if isinstance(section, dict) else None
            if isinstance(strings, list):
                section["strings"] = dedupe_string_values(strings)

    return parsed_data


# --- Skill group headers (additional.technicalSkills) ------------------

# Some sources organize 专业技能 as standalone bold group names
# ("AI 大模型", "Java 工程落地能力") followed by detail bullets. Weak models
# keep every source line as one flat technicalSkills string, so the group
# names render as ordinary numbered entries mixed with the details. Storage
# STAYS a flat string list (builder per-row editing, fine-tune region indices
# and diff paths keep their contract); the hierarchy is planned structurally
# at render time. Mirrored by planSkillGroupHeaders() in
# components/resume/list-format.ts and consumed by the DOCX exporter — keep
# the three in sync.
_SKILL_GROUP_HEAD_MAX_LEN = 14
_SKILL_GROUP_HEAD_PUNCT_RE = re.compile(r"[，。；！？、,.!?;：:]")
_SKILL_GROUP_MIN_HEADS = 2
_SKILL_DETAIL_MIN_LEN = 16
_SKILL_DETAIL_PUNCT_RE = re.compile(r"[。；！？!?;：:]")


def _is_skill_group_head(row: Any) -> bool:
    """Shape-only test for a standalone skill group heading row.

    A head is a SHORT line without sentence/enumeration/colon punctuation:
    "AI 大模型" / "Java 工程落地能力" qualify, while detail sentences
    ("精通 RAG 全链路：…") do not. An optional TRAILING colon is tolerated
    (the render layer trims it); a colon followed by content disqualifies the
    row, as do enumeration commas, sentence punctuation, URLs and source list
    markers. Whether a head-shaped row actually OPENS a group is decided
    structurally by :func:`plan_skill_group_heads`.
    """
    if not isinstance(row, str):
        return False
    text = strip_source_point_marker(row).strip()
    if text.endswith(("：", ":")):
        text = text[:-1].strip()
    if not text or len(text) > _SKILL_GROUP_HEAD_MAX_LEN:
        return False
    if _SKILL_GROUP_HEAD_PUNCT_RE.search(text):
        return False
    if _BARE_URL_RE.fullmatch(text):
        return False
    return True


def _is_skill_detail_row(row: Any) -> bool:
    """A skill detail entry: long prose, or any line carrying colon/sentence
    punctuation — everything a short group heading is not."""
    if not isinstance(row, str):
        return False
    text = row.strip()
    if not text or _is_skill_group_head(text):
        return False
    return len(text) >= _SKILL_DETAIL_MIN_LEN or bool(
        _SKILL_DETAIL_PUNCT_RE.search(text)
    )


def plan_skill_group_heads(skills: Any) -> set[int]:
    """Return the indices of standalone skill group heading rows.

    Structural gates, mirroring the project nested-head planner:

    * a head must be followed by a detail-shaped row, so flat bare-name lists
      such as ``["Java", "Kotlin", "Spring Boot"]`` never qualify (every
      successor is itself head-shaped);
    * two heads cannot be adjacent — a head next to another head is a peer;
    * at least :data:`_SKILL_GROUP_MIN_HEADS` heads must qualify across the
      whole list, so an isolated short row amid detail entries keeps its
      ordinary numbering.

    An empty set means "ungrouped": renderers fall back to their existing
    flat behavior, so ungrouped resumes render byte-identically. Tolerates
    non-list input (returns an empty set).
    """
    if not isinstance(skills, list):
        return set()
    texts = [skill.strip() if isinstance(skill, str) else "" for skill in skills]
    total = len(texts)
    qualified: set[int] = set()
    for index, text in enumerate(texts):
        if not _is_skill_group_head(text):
            continue
        next_index = index + 1
        if next_index >= total or not _is_skill_detail_row(texts[next_index]):
            continue
        prev_index = index - 1
        if prev_index >= 0 and _is_skill_group_head(texts[prev_index]):
            continue
        qualified.add(index)
    if len(qualified) < _SKILL_GROUP_MIN_HEADS:
        return set()
    return qualified


def strip_markdown_formatting(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """Deterministic pass: strip leaked Markdown modifiers from every field.

    Rendered string lists are also de-duplicated, since marker removal can
    collapse entries that differed only by formatting.
    """
    for key, value in list(parsed_data.items()):
        parsed_data[key] = strip_markdown_emphasis_deep(value)
    dedupe_resume_lists(parsed_data)
    return parsed_data


def strip_source_point_numbering(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """Strip source-carried numbering from list fields after LLM extraction.

    Applies to description rows (work/projects/custom itemLists), skills,
    certifications, awards, languages, and custom stringList entries.
    Prose fields (summary, custom text blocks) are untouched; the renderer
    strips per line there. Runs AFTER sub-label normalization, which knows
    how to split a numbered label row ("1、工作职责：…").
    """
    for section_key in ("workExperience", "personalProjects"):
        entries = parsed_data.get(section_key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("description"), list):
                entry["description"] = [
                    strip_source_point_marker(row) for row in entry["description"]
                ]

    additional = parsed_data.get("additional")
    if isinstance(additional, dict):
        for field in (
            "technicalSkills",
            "certificationsTraining",
            "awards",
            "languages",
        ):
            values = additional.get(field)
            if isinstance(values, list):
                additional[field] = [strip_source_point_marker(v) for v in values]

    custom_sections = parsed_data.get("customSections")
    if isinstance(custom_sections, dict):
        for section in custom_sections.values():
            if not isinstance(section, dict):
                continue
            if isinstance(section.get("strings"), list):
                section["strings"] = [
                    strip_source_point_marker(value) for value in section["strings"]
                ]
            items = section.get("items")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and isinstance(item.get("description"), list):
                        item["description"] = [
                            strip_source_point_marker(row) for row in item["description"]
                        ]

    return parsed_data


def reconcile_custom_section_shapes(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """Move custom-section content into the container matching sectionType.

    Weak extractions declare a custom section's type but fill the wrong
    content container (observed: a stringList 「其它」 section whose two link
    entries were placed in ``items`` while ``strings`` stayed null; every
    template renders a stringList from ``strings`` only, so the entries were
    invisible and diagnosis flagged the block as title-without-content).
    The stranded entries are migrated rather than dropped:

    * stringList with no strings + content-bearing items -> ``strings``
      built from the item titles (source markers stripped, blanks dropped),
      items cleared;
    * itemList with no items + content-bearing strings -> ``items``
      synthesized as ``{"id": n, "title": value}`` (mirrors the Pydantic
      string->item coercion in schemas.models.CustomSection), strings cleared.

    Sections whose declared container already holds content are untouched,
    so a second run over healed data is a no-op.
    """
    custom_sections = parsed_data.get("customSections")
    if not isinstance(custom_sections, dict):
        return parsed_data

    migrated_sections = 0
    for section in custom_sections.values():
        if not isinstance(section, dict):
            continue
        section_type = section.get("sectionType")
        items = section.get("items")
        strings = section.get("strings")
        has_items = isinstance(items, list) and any(
            isinstance(item, dict) and str(item.get("title") or "").strip()
            for item in items
        )
        has_strings = isinstance(strings, list) and any(
            isinstance(value, str) and value.strip() for value in strings
        )

        if section_type == "stringList" and not has_strings and has_items:
            migrated: list[str] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                if not title:
                    continue
                cleaned = strip_source_point_marker(title)
                cleaned = cleaned.strip() if isinstance(cleaned, str) else title
                if cleaned:
                    migrated.append(cleaned)
            if migrated:
                section["strings"] = migrated
                section["items"] = None
                migrated_sections += 1
        elif section_type == "itemList" and not has_items and has_strings:
            clean_strings = [
                value.strip()
                for value in strings
                if isinstance(value, str) and value.strip()
            ]
            synthesized = [
                {"id": index, "title": value}
                for index, value in enumerate(clean_strings, start=1)
            ]
            if synthesized:
                section["items"] = synthesized
                section["strings"] = None
                migrated_sections += 1

    if migrated_sections:
        logger.info(
            "Reconciled %d custom section(s) whose content container "
            "did not match their declared sectionType",
            migrated_sections,
        )
    return parsed_data


# ---------------------------------------------------------------------------
# Text hygiene: trim rows, collapse whitespace runs, drop blank rows/styles
# in lockstep, no blank lines inside text blocks, unified list-point endings.
# ---------------------------------------------------------------------------

#: Terminal punctuation stripped from LIST points (bullet rows and rendered
#: string lists). Plain prose keeps its sentence punctuation; nothing is ever
#: added. Conservative: only the trailing run is removed.
_LIST_TRAILING_PUNCT_RE = re.compile(r"[。.；;！？!?]+[ 　\t]*$")
#: Runs of horizontal whitespace (tab, NBSP, ideographic space) collapse to
#: one ASCII space; newline runs are handled via line splitting.
_WHITESPACE_RUN_RE = re.compile(r"[ \t\u00a0\u3000]+")
_VALID_DESCRIPTION_STYLES = frozenset({"bullet", "plain", "label"})


def _hygiene_clean_row(row: str) -> str:
    """Trim one line and collapse its internal horizontal whitespace runs."""
    return _WHITESPACE_RUN_RE.sub(" ", row).strip()


def _hygiene_strip_list_ending(row: str) -> str:
    """Remove terminal sentence punctuation from one list point."""
    return _LIST_TRAILING_PUNCT_RE.sub("", row).rstrip()


def _hygiene_description(entry: dict[str, Any]) -> None:
    """Trim/drop description rows in lockstep with descriptionStyles.

    Blank rows and their style are removed together by INDEX (a positional
    filter alone would shift every later bullet/plain setting onto its
    neighbour). Bullet rows additionally lose trailing sentence punctuation;
    plain and label rows are only trimmed.
    """
    descriptions = entry.get("description")
    if not isinstance(descriptions, list):
        return
    raw_styles = entry.get("descriptionStyles")
    styles = raw_styles if isinstance(raw_styles, list) else None

    kept_descriptions: list[Any] = []
    kept_styles: list[str] = []
    for index, raw_row in enumerate(descriptions):
        if not isinstance(raw_row, str):
            # Defensive: keep non-string rows (schema validation reports them).
            kept_descriptions.append(raw_row)
            if styles is not None and index < len(styles):
                kept_styles.append(styles[index])
            continue
        row = _hygiene_clean_row(raw_row)
        if not row:
            continue
        style = styles[index] if styles is not None and index < len(styles) else "bullet"
        if style not in _VALID_DESCRIPTION_STYLES:
            style = "bullet"
        if style == "bullet":
            row = _hygiene_strip_list_ending(row)
            if not row:
                continue
        kept_descriptions.append(row)
        if styles is not None:
            kept_styles.append(style)

    entry["description"] = kept_descriptions
    if styles is not None:
        entry["descriptionStyles"] = kept_styles


def _hygiene_text_block(value: Any, *, strip_list_endings: bool) -> Any:
    """Outer-strip a text block; trim every line and drop blank lines."""
    if not isinstance(value, str):
        return value
    cleaned_lines: list[str] = []
    for raw_line in value.splitlines():
        line = _hygiene_clean_row(raw_line)
        if not line:
            continue
        if strip_list_endings:
            line = _hygiene_strip_list_ending(line)
            if not line:
                continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def _hygiene_string_list(values: Any) -> Any:
    """Trim rendered string-list entries, drop blanks, unify endings."""
    if not isinstance(values, list):
        return values
    cleaned: list[Any] = []
    for value in values:
        if not isinstance(value, str):
            cleaned.append(value)
            continue
        row = _hygiene_strip_list_ending(_hygiene_clean_row(value))
        if row:
            cleaned.append(row)
    return cleaned


def _hygiene_header_fields(entry: dict[str, Any], fields: tuple[str, ...]) -> None:
    """Trim outer whitespace from header string fields only."""
    for field in fields:
        value = entry.get(field)
        if isinstance(value, str):
            entry[field] = value.strip()


def normalize_text_hygiene(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """Deterministic presentation hygiene for parsed resume data.

    Format-consistency rules enforced here: no blank description rows (removed
    in lockstep with their styles), no runs of whitespace, no blank lines in
    summary/custom text blocks, no blank string-list entries, no stray outer
    whitespace in header fields, and no trailing sentence punctuation on list
    points (bullet rows, rendered string arrays, summary/self-evaluation
    lines). Plain prose rows and non-selfeval text blocks keep their own
    punctuation; punctuation is never added.
    """
    # Summary is rendered as one-number-per-line list points.
    parsed_data["summary"] = _hygiene_text_block(
        parsed_data.get("summary", ""), strip_list_endings=True
    )

    personal_info = parsed_data.get("personalInfo")
    if isinstance(personal_info, dict):
        _hygiene_header_fields(
            personal_info,
            (
                "name",
                "title",
                "email",
                "phone",
                "location",
                "gender",
                "age",
                "workYears",
                "educationLevel",
                "website",
                "linkedin",
                "github",
            ),
        )
        # Self-heal glued header cells from pre-fix uploads (e.g. workYears
        # "13年 博客地址：[blog](https://…)", educationLevel "本科 学 校： …")
        # and resolve Markdown links stored verbatim in personal-link fields.
        # Idempotent, so repeated GETs leave already-clean values untouched.
        for fact_field in _HEADER_FACT_FIELDS:
            fact_value = personal_info.get(fact_field)
            if isinstance(fact_value, str):
                personal_info[fact_field] = sanitize_header_fact_value(fact_value)
        for link_field in ("website", "linkedin", "github"):
            link_value = personal_info.get(link_field)
            if isinstance(link_value, str) and link_value:
                personal_info[link_field] = normalize_header_link_value(link_value)

    work_entries = parsed_data.get("workExperience")
    if isinstance(work_entries, list):
        for entry in work_entries:
            if isinstance(entry, dict):
                _hygiene_header_fields(entry, ("title", "company", "department", "location"))
                _hygiene_description(entry)

    education_entries = parsed_data.get("education")
    if isinstance(education_entries, list):
        for entry in education_entries:
            if isinstance(entry, dict):
                _hygiene_header_fields(
                    entry, ("institution", "degree", "description")
                )

    project_entries = parsed_data.get("personalProjects")
    if isinstance(project_entries, list):
        for entry in project_entries:
            if isinstance(entry, dict):
                _hygiene_header_fields(entry, ("name", "role", "scale", "github", "website"))
                _hygiene_description(entry)

    additional = parsed_data.get("additional")
    if isinstance(additional, dict):
        for field in _DEDUPABLE_ADDITIONAL_FIELDS:
            additional[field] = _hygiene_string_list(additional.get(field))

    custom_sections = parsed_data.get("customSections")
    if isinstance(custom_sections, dict):
        for key, section in custom_sections.items():
            if not isinstance(section, dict):
                continue
            section_type = section.get("sectionType")
            if section_type == "itemList":
                _hygiene_header_fields(section, ("title",))
                for item in section.get("items", []):
                    if isinstance(item, dict):
                        _hygiene_header_fields(item, ("title", "subtitle", "location"))
                        _hygiene_description(item)
            elif section_type == "stringList":
                section["strings"] = _hygiene_string_list(section.get("strings"))
            elif section_type == "text":
                section["text"] = _hygiene_text_block(
                    section.get("text", ""),
                    strip_list_endings=key in _SELF_EVALUATION_KEYS,
                )
                _hygiene_header_fields(section, ("title",))

    return parsed_data


# Clause boundaries used when a weak extraction returns one big prose blob
# where the resume actually lists several points. Chinese full-width
# punctuation only — an ASCII "." must never split versions ("JDK 21.0.1"),
# dates ("2020.09") or decimals; an ASCII ";" inside code-like text inside a
# 项目职责 row is rarer than the Chinese semicolon but still accepted.
_BLOB_CLAUSE_RE = re.compile(r"[；;。]")

# customSections keys that identify the self-evaluation family. Mirrors the
# diagnosis checker's key fallbacks (a displayName 自我评价/个人评价 always
# parses to key self_evaluation; the extras cover legacy records).
_SELF_EVALUATION_KEYS: frozenset[str] = frozenset(
    {
        "self_evaluation",
        "self_eval",
        "self_appraisal",
        "selfassessment",
    }
)


def _split_blob_line(line: str) -> list[str]:
    """Split one text line at Chinese clause boundaries into list points.

    A line without a boundary (or ending with just one) is returned verbatim,
    so already-point-per-line content is byte-for-byte unchanged. Boundary
    punctuation is dropped from the produced points (the renderer numbers
    them) and any residual source point marker is stripped per segment.
    """
    stripped = line.strip()
    if not stripped:
        return []
    segments = [segment.strip() for segment in _BLOB_CLAUSE_RE.split(stripped)]
    segments = [segment for segment in segments if segment]
    if len(segments) <= 1:
        return [stripped]
    points: list[str] = []
    for segment in segments:
        cleaned = strip_source_point_marker(segment)
        cleaned = cleaned.strip() if isinstance(cleaned, str) else ""
        if cleaned:
            points.append(cleaned)
    return points or [stripped]


def _split_text_blob_into_points(text: Any) -> tuple[str, bool]:
    """Split a self-evaluation text blob, one point per output line."""
    if not isinstance(text, str):
        return text, False
    points: list[str] = []
    for line in text.split("\n"):
        points.extend(_split_blob_line(line))
    if not points:
        return text, False
    split_text = "\n".join(points)
    return split_text, split_text != text.strip()


def split_blob_text_sections(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """Split large prose blobs into ordered-list points.

    Two user-visible cases:

    * self-evaluation custom text blocks (自我评价 / 个人评价 / 个人总结 …):
      a paragraph separated by ；/。 becomes ``"\\n"``-joined points, which the
      renderer displays as an ordered list;
    * project 项目职责 descriptions: rows inside the 职责 label region are
      split at the same boundaries, each segment inheriting the row style.
      Rows outside a duty region (项目背景 / 技术栈 / 项目亮点 …) are never
      split, and resumes without label rows are left untouched because the
      duty region cannot be located safely.
    """
    custom_sections = parsed_data.get("customSections")
    if isinstance(custom_sections, dict):
        for key, section in custom_sections.items():
            if key not in _SELF_EVALUATION_KEYS or not isinstance(section, dict):
                continue
            if section.get("sectionType") != "text" or not isinstance(section.get("text"), str):
                continue
            split_text, changed = _split_text_blob_into_points(section["text"])
            if changed:
                section["text"] = split_text

    projects = parsed_data.get("personalProjects")
    if isinstance(projects, list):
        for project in projects:
            if not isinstance(project, dict) or not isinstance(project.get("description"), list):
                continue
            description = project["description"]
            styles = project.get("descriptionStyles")
            styles = styles if isinstance(styles, list) else []
            in_duty_region = False
            new_description: list[Any] = []
            new_styles: list[str] = []
            changed = False
            for index, row in enumerate(description):
                style = styles[index] if index < len(styles) else "bullet"
                if style not in ("bullet", "plain", "label"):
                    style = "bullet"
                if style == "label":
                    in_duty_region = "职责" in str(row)
                    new_description.append(row)
                    new_styles.append(style)
                    continue
                if in_duty_region and isinstance(row, str):
                    points = _split_blob_line(row)
                    if len(points) > 1:
                        changed = True
                    new_description.extend(points)
                    new_styles.extend([style] * len(points))
                else:
                    new_description.append(row)
                    new_styles.append(style)
            if changed:
                project["description"] = new_description
                project["descriptionStyles"] = new_styles

    return parsed_data


_PROJECT_HEADER_FIELD_RE = re.compile(
    r"^\s*(?:\d{1,2}\s*[.、)）．:：]\s*)?"
    r"(?P<label>项目规模|团队规模|项目角色|担任角色)\s*[：:]\s*(?P<value>.+?)\s*$"
)


def extract_project_header_fields(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """Move inline 项目规模/项目角色 rows into the project header fields.

    Source resumes sometimes write "项目规模：20人团队" or "项目角色：核心开发"
    as description rows. Such rows belong in ``scale`` / ``role`` (rendered on
    the project header line); only fill an EMPTY header field, never overwrite
    what the model extracted. Mutates and returns ``parsed_data``.
    """
    projects = parsed_data.get("personalProjects")
    if not isinstance(projects, list):
        return parsed_data

    for project in projects:
        if not isinstance(project, dict):
            continue
        description = project.get("description")
        if not isinstance(description, list) or not description:
            continue
        styles = project.get("descriptionStyles")
        if not isinstance(styles, list):
            styles = []

        kept_rows: list[Any] = []
        kept_styles: list[Any] = []
        changed = False
        for index, row in enumerate(description):
            match = _PROJECT_HEADER_FIELD_RE.match(row) if isinstance(row, str) else None
            field: str | None = None
            if match:
                label = match.group("label")
                field = "scale" if "规模" in label else "role"
            current = project.get(field, "") if field else None
            value = match.group("value").strip() if match else ""
            if field and isinstance(current, str) and not current.strip() and value:
                project[field] = value
                changed = True
                continue
            kept_rows.append(row)
            kept_styles.append(styles[index] if index < len(styles) else "bullet")

        if changed:
            project["description"] = kept_rows
            project["descriptionStyles"] = kept_styles

    return parsed_data


# A standalone org-unit line weak models file as a plain work description row
# ("全球资金部" / "云计算集成部" / "保险事业群" / "平台研发中心" / "Payments
# Department"). Tight gate: short, no sentence punctuation, ends with a known
# organization suffix. Mirrored by the frontend renderer (work-department.ts),
# which repairs the same shape in already-stored resumes.
_WORK_DEPARTMENT_LINE_RE = re.compile(
    r"^\s*"
    r"(?:"
    r"[一-鿿][一-鿿A-Za-z0-9（）()·&/+\- ]{0,13}"
    r"(?:事业部|事业群|部门|条线|分院|大区|办公室|中心|团队|小组|[部组室科处])"
    r"|[A-Za-z0-9][A-Za-z0-9 &/+\-]{1,28}(?:Department|Dept\.?|Division|Team|Group)"
    r")"
    r"(?:[（(][^（）()]{1,12}[）)])?"
    r"\s*$"
)
_WORK_DEPARTMENT_SENTENCE_PUNCT_RE = re.compile(r"[。．.，,；;：:！!？?、…]")


def _looks_like_department_line(row: Any) -> bool:
    """True for a short standalone org-unit line ("研发部", "Payments Team")."""
    if not isinstance(row, str):
        return False
    text = row.strip()
    if len(text) < 2:
        return False
    if _WORK_DEPARTMENT_SENTENCE_PUNCT_RE.search(text):
        return False
    return bool(_WORK_DEPARTMENT_LINE_RE.match(text))


def promote_work_departments(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """Move a leading plain department row into the work ``department`` field.

    Chinese source resumes often list the org unit on its own line under the
    company ("武汉软通动力 / 全球资金部"); weak models file it as a "plain"
    description row instead of ``department``. The parse prompt asks for the
    field directly; this pass is the deterministic safety net, mirroring
    :func:`extract_project_header_fields`: only fill an EMPTY field, only the
    FIRST description row, and only when that row is styled "plain" and looks
    like a standalone department line. Mutates and returns ``parsed_data``.
    """
    works = parsed_data.get("workExperience")
    if not isinstance(works, list):
        return parsed_data

    for work in works:
        if not isinstance(work, dict):
            continue
        current = work.get("department")
        if isinstance(current, str) and current.strip():
            continue
        description = work.get("description")
        if not isinstance(description, list) or not description:
            continue
        styles = work.get("descriptionStyles")
        styles = styles if isinstance(styles, list) else []
        first_style = styles[0] if styles else "bullet"
        first_row = description[0]
        if first_style == "plain" and _looks_like_department_line(first_row):
            work["department"] = first_row.strip()
            work["description"] = description[1:]
            if styles:
                work["descriptionStyles"] = styles[1:]

    return parsed_data


def normalize_item_sub_labels(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """Preserve in-item sub-modules across work/projects/custom itemLists.

    Runs after LLM extraction as a deterministic safety net (same layer as
    date restoration and demographics backfill): the parse prompt asks for
    sub-label fidelity, but weak models merge labels into content or number
    label rows. Unplanned sub-modules (tables, grids, free-form blocks the
    schema has no field for) stay exactly where the source had them, inside
    the item's description rows.
    """
    # Canonical sub-label naming applies to PROJECT items only; work entries
    # and custom itemLists keep their source labels verbatim.
    item_sections: list[tuple[Any, Mapping[str, str] | None]] = [
        (parsed_data.get("workExperience"), None),
        (parsed_data.get("personalProjects"), PROJECT_SUB_LABEL_CANONICAL),
    ]
    custom_sections = parsed_data.get("customSections")
    if isinstance(custom_sections, dict):
        item_sections.extend(
            (
                section.get("items"),
                None,
            )
            for section in custom_sections.values()
            if isinstance(section, dict)
        )

    for entries, canonical_labels in item_sections:
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            normalized = _normalize_item_description_rows(
                entry.get("description"),
                entry.get("descriptionStyles"),
                canonical_labels,
            )
            if normalized is not None:
                entry["description"], entry["descriptionStyles"] = normalized

    return parsed_data


# Project sub-label cores whose rows are descriptive body text (unnumbered)
# rather than numbered duty/highlight points. Mirrors the frontend's
# PROJECT_DESCRIPTIVE_LABELS in components/resume/list-format.ts.
_PROJECT_REGION_PLAIN_CORES: frozenset[str] = frozenset(
    {
        "项目背景",
        "技术栈",
        "项目描述",
        "系统架构",
        "架构说明",
    }
)
_PROJECT_REGION_BULLET_CORES: frozenset[str] = frozenset({"项目职责", "项目亮点"})


# Every canonical project sub-label name (rename map keys + the four target
# names); a bare label row with one of these cores is a heading even without
# its trailing colon.
_PROJECT_KNOWN_LABEL_CORES: frozenset[str] = (
    frozenset(PROJECT_SUB_LABEL_CANONICAL)
    | _PROJECT_REGION_PLAIN_CORES
    | _PROJECT_REGION_BULLET_CORES
)


def _project_heading_kind(row: Any) -> str | None:
    """Classify a project heading row: "plain"/"bullet" region, "other" or None.

    A known sub-label name (colon-terminated "技术栈：" or bare "项目职责")
    opens a region. Any other standalone label ("难点/方案/效果：") stays a
    heading but CLOSES the known region so free-form content under it keeps
    its stored style. A label-styled content paragraph returns None so the
    caller can demote it.
    """
    if not isinstance(row, str):
        return None
    text = row.strip()
    core = text[:-1].strip() if text.endswith(("：", ":")) else text
    if core in _PROJECT_REGION_PLAIN_CORES:
        return "plain"
    if core in _PROJECT_REGION_BULLET_CORES:
        return "bullet"
    if (
        core in _PROJECT_KNOWN_LABEL_CORES
        or _STANDALONE_SUB_LABEL_RE.match(text) is not None
    ):
        return "other"
    return None


# Bare (colon-less) sub-headings that GROUP the duty/highlight points below
# them, e.g. "架构演进与技术债务治理" on its own bold line followed by bullet
# rows. The source prints them without a number and without a colon; weak
# models store them as short plain/label/bullet rows interleaved with the
# points. Qualified heads are numbered level-1 by the renderer and their
# details become 1.1/1.2 sub-points. The shape predicate + structural planner
# are mirrored in resume_docx.py (_is_nested_head_shaped /
# _plan_nested_group_heads) and the frontend (looksLikeNestedGroupHead /
# planNestedGroupHeads in list-format.ts) — keep the three in sync.
_NESTED_GROUP_HEAD_MAX_LEN = 16
_NESTED_GROUP_HEAD_PUNCT_RE = re.compile(r"[，。；！？、,.!?;：:]")
# A real grouping structure contains at least this many head groups; an
# isolated short row amid normal points is a peer point, never a head.
_NESTED_GROUP_MIN_HEADS = 2


def _is_nested_head_shaped(row: Any, style: str) -> bool:
    """Shape-only test for a bare bold group heading (no successor check).

    True for short (<=16 chars), unnumbered, colon-less rows without
    sentence/enumeration punctuation. The weak model may store such a head
    as ``plain``, ``label`` OR ``bullet``, so all three styles are eligible;
    the structural decision (the row actually opens a head group) lives in
    :func:`_plan_nested_group_heads`.
    """
    if style not in ("plain", "label", "bullet"):
        return False
    if not isinstance(row, str) or _POINT_MARKER_RE.match(row):
        return False
    text = row.strip()
    if not text or text.endswith(("：", ":")):
        return False
    if len(text) > _NESTED_GROUP_HEAD_MAX_LEN:
        return False
    return not _NESTED_GROUP_HEAD_PUNCT_RE.search(text)


def _plan_nested_group_heads(
    description: Sequence[Any],
    styles: Sequence[str],
    heading_kinds: Sequence[str | None],
) -> set[int]:
    """Find bare group-heading row indices inside duty/highlight (bullet) spans.

    A head-shaped row qualifies only when:

    * the next content row in the same span is a DETAIL-shaped row — a head
      always owns at least one point, and two adjacent head-shaped rows are
      peer points rather than head+head;
    * the previous content row in the span is not head-shaped (no adjacent
      heads);
    * the span holds at least :data:`_NESTED_GROUP_MIN_HEADS` qualified heads
      — an isolated short row ("技术方案设计" above one long bullet, or a
      short point sandwiched between long points) stays an ordinary point.

    The rule is structural rather than style-based so it generalizes across
    every project upload regardless of how the weak model styled the heads.
    """

    def style_at(index: int) -> str:
        return styles[index] if index < len(styles) else "bullet"

    span_heads: list[set[int]] = []
    current: set[int] = set()
    in_bullet_span = False

    def close_span() -> None:
        nonlocal current
        if current:
            span_heads.append(current)
            current = set()

    for index, row in enumerate(description):
        kind = heading_kinds[index] if index < len(heading_kinds) else None
        if kind == "bullet":
            # Duty/highlight module label opens a fresh bullet span.
            close_span()
            in_bullet_span = True
            continue
        if kind in ("plain", "other"):
            # Background/tech label or an unplanned standalone heading ends
            # the known bullet span.
            close_span()
            in_bullet_span = False
            continue
        if not in_bullet_span or not _is_nested_head_shaped(row, style_at(index)):
            continue
        next_index = index + 1
        if next_index >= len(description):
            continue
        # A heading row next means a module/span boundary: no detail follows.
        if heading_kinds[next_index] is not None:
            continue
        if _is_nested_head_shaped(
            description[next_index], style_at(next_index)
        ):
            continue  # adjacent head-shaped rows: peer points, not a head
        prev_index = index - 1
        if (
            prev_index >= 0
            and heading_kinds[prev_index] is None
            and _is_nested_head_shaped(
                description[prev_index], style_at(prev_index)
            )
        ):
            continue  # no head directly after another head
        current.add(index)
    close_span()

    qualified: set[int] = set()
    for heads in span_heads:
        if len(heads) >= _NESTED_GROUP_MIN_HEADS:
            qualified.update(heads)
    return qualified


def repair_project_label_regions(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """Force description-row styles to match the sub-label region they sit in.

    Weak models mislabel project rows in two observed ways: tech-stack /
    background entries are emitted with the ``label`` or ``bullet`` style
    (rendering each "Java"/"Kafka" row as a bold heading or a numbered point),
    and a whole duty/achievement paragraph is glued onto a ``label`` row
    ("负责整体架构：……。"), rendering the prose as a bold heading.

    Repair (projects only): a standalone sub-label row opens a region —
    技术栈/项目背景-family rows are ``plain`` body text, 项目职责/项目亮点 rows
    are ``bullet`` points; an unplanned standalone label ("难点/方案/效果：")
    closes the known region so free-form content keeps its stored style. A
    ``label``-styled row that is NOT heading-shaped (long prose, no trailing
    colon) is demoted to its region's content style. Content before the first
    heading inherits that heading's region only when it is descriptive (the
    glued-intro case), never bullet.
    """
    projects = parsed_data.get("personalProjects")
    if not isinstance(projects, list):
        return parsed_data

    for project in projects:
        if not isinstance(project, dict) or not isinstance(
            project.get("description"), list
        ):
            continue
        normalized = _normalize_item_description_rows(
            project.get("description"),
            project.get("descriptionStyles"),
            PROJECT_SUB_LABEL_CANONICAL,
            split_descriptive_only=True,
        )
        if normalized is not None:
            project["description"], project["descriptionStyles"] = normalized

        description: list[Any] = project["description"]
        styles_in = project.get("descriptionStyles")
        styles: list[str] = styles_in if isinstance(styles_in, list) else []

        heading_kinds: list[str | None] = []
        for row in description:
            heading_kinds.append(_project_heading_kind(row))
        if not any(kind in ("plain", "bullet") for kind in heading_kinds):
            continue
        # Region of the first known heading; only pre-heading intro prose
        # adopts it (and then only a plain region — never bullet).
        first_region = next(
            kind for kind in heading_kinds if kind in ("plain", "bullet")
        )

        # Structural pass: decide which bare rows are nested group heads
        # BEFORE coercing region styles, so head-shaped bullets survive.
        nested_head_indices = _plan_nested_group_heads(
            description, styles, heading_kinds
        )

        new_styles: list[str] = []
        region: str | None = None
        changed = False
        for index, row in enumerate(description):
            style = styles[index] if index < len(styles) else "bullet"
            if style not in ("bullet", "plain", "label"):
                style = "bullet"
            heading_kind = heading_kinds[index]
            if heading_kind in ("plain", "bullet"):
                region = heading_kind
                new_styles.append("label")
                if style != "label":
                    changed = True
                continue
            if heading_kind == "other":
                # Unplanned standalone heading: keep it bold and stop applying
                # the previous known region to what follows.
                region = None
                new_styles.append("label")
                if style != "label":
                    changed = True
                continue
            if region == "bullet" and index in nested_head_indices:
                # A bare bold sub-heading grouping the following points
                # ("架构演进与技术债务治理" above two duty bullets, even when
                # the weak model stored it as a bullet) stays bold instead of
                # being coerced into a point; the renderer turns it into a
                # level-1 numbered head with 1.1/1.2 sub-points.
                new_styles.append("label")
                if style != "label":
                    changed = True
                continue
            if style == "label":
                # Label-styled prose that is not a standalone heading is a
                # mislabeled content row. Before the first heading, only a
                # descriptive region claims it (avoids numbering an intro).
                target = region if region is not None else (
                    first_region if first_region == "plain" else None
                )
                if target is not None:
                    new_styles.append(target)
                    changed = True
                else:
                    new_styles.append("label")
                continue
            if region is not None and style != region:
                new_styles.append(region)
                changed = True
            else:
                new_styles.append(style)

        if changed:
            project["descriptionStyles"] = new_styles

    return parsed_data


# --- Project tech-stack region repair ----------------------------------

# A whole description row that is ONLY a URL: a bare link ("https://…",
# "www.…") or a single Markdown link ("[Forest](https://…)"). Rows that merely
# contain a URL alongside prose fail the full-row gate and stay in the body.
def _extract_standalone_url_row(row: Any) -> str | None:
    """Return the URL when a tech-stack row is a standalone link, else None."""
    if not isinstance(row, str):
        return None
    text = row.strip()
    if not text:
        return None
    markdown_match = _MARKDOWN_INLINE_LINK_RE.fullmatch(text)
    if markdown_match:
        target = markdown_match.group(1).strip()
        return target or None
    bare_match = _BARE_URL_RE.fullmatch(text)
    if bare_match:
        return bare_match.group(0).rstrip(".,;)）】]、，。；;：:!?！？")
    return None


# github.com hosts (incl. subdomains such as gist.github.com) map to the
# project github field; every other standalone URL is the project website.
_GITHUB_HOST_RE = re.compile(r"(?:^|\.)github\.com$", re.IGNORECASE)


def _project_url_target_field(url: str) -> str:
    """Pick the project header field ("github"/"website") for a standalone URL."""
    rest = url.strip()
    if "://" in rest:
        rest = rest.split("://", 1)[1]
    elif rest.lower().startswith("www."):
        rest = rest[4:]
    host = rest.split("/", 1)[0].split(":", 1)[0]
    return "github" if _GITHUB_HOST_RE.match(host.lower()) else "website"


def _is_tech_stack_label_row(row: Any) -> bool:
    """True for a standalone 技术栈 heading row, with or without a trailing colon."""
    if not isinstance(row, str):
        return False
    text = row.strip()
    core = text[:-1].strip() if text.endswith(("：", ":")) else text
    return core == "技术栈"


# Structured tech-stack category row ("后端：Java 8、Spring Boot",
# "数据库：MySQL、Redis"): a short category prefix, a colon and non-empty
# content. Mirrors TECH_STACK_CATEGORY_RE in resume_docx.py and
# components/resume/list-format.ts — keep the three in sync. A region with
# such rows renders as an ordered list (one number per category row), so its
# rows must stay separate; pure-name stacks are the ones we join.
_TECH_STACK_CATEGORY_RE = re.compile(
    r"^[一-鿿A-Za-z][一-鿿A-Za-z0-9/（）() -]{0,10}[：:]\s*\S"
)
_CATEGORY_SENTENCE_RE = re.compile(r"[。；！？!?;]")


def _is_tech_stack_category_row(row: str) -> bool:
    """Whether a tech-stack row is a structured category enumeration.

    Mirrors resume_docx._is_tech_stack_category_row / the frontend
    isTechStackCategoryRow(): the short-colon shape minus sentence punctuation
    and glued known sub-module names.
    """
    # A standalone URL matches the short-colon shape by accident ("https://…"
    # parses as the prefix "https" + a colon); it is a link, never a
    # 分类：… enumeration row — URL rows are classified separately (lifted to
    # the website/github header fields, or joined into a flat stack when they
    # cannot be routed). Mirrored by the scheme-prefix guards in the two render
    # predicates — keep the three in sync.
    if _extract_standalone_url_row(row) is not None:
        return False
    if not _TECH_STACK_CATEGORY_RE.search(row) or _CATEGORY_SENTENCE_RE.search(row):
        return False
    core = re.sub(r"[：:].*$", "", row).strip()
    return core not in _PROJECT_KNOWN_LABEL_CORES


def repair_project_tech_stack_rows(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """Join split 技术栈 enumeration rows and lift standalone URL rows.

    Weak models split one source line ("技术栈：Java、Kotlin、…") into one plain
    row per token and file a standalone project URL line ("https://…") as the
    last tech-stack row instead of the project's website/github header field.
    The split rows also defeat the renderer's inline join: an "https:" row
    matches its inline-disqualifier shape, so the whole stack prints one token
    per line. Runs after region repair (the 技术栈 label is canonical and its
    followers are plain) and after source-number stripping, so rows carry no
    list markers anymore:

    * a follower row that IS a standalone URL is moved into an EMPTY github
      (github.com hosts) or website field. Existing field values and fields
      filled by an earlier URL row are never overwritten — an unroutable URL
      stays in the body;
    * a FLAT name stack (no structured "分类：…" category rows) is joined into
      ONE plain row with the Chinese enumeration comma 、 — the recognized
      技术栈 label is Chinese-context, so even all-ASCII token stacks follow
      zh typography (the user-visible expectation for Chinese resumes);
    * a structured category stack keeps one row per category — its ordered
      per-category list rendering depends on the row boundaries.

    Only 技术栈 regions are touched; a region whose followers are all URLs is
    left verbatim (no orphan label, no dropped information), and an
    already-repaired stack is a no-op, so the pass is idempotent. Mutates and
    returns ``parsed_data``.
    """
    projects = parsed_data.get("personalProjects")
    if not isinstance(projects, list):
        return parsed_data

    for project in projects:
        if not isinstance(project, dict) or not isinstance(
            project.get("description"), list
        ):
            continue
        description: list[Any] = project["description"]
        styles_in = project.get("descriptionStyles")
        styles: list[Any] = styles_in if isinstance(styles_in, list) else []

        new_rows: list[Any] = []
        new_styles: list[str] = []
        # Fields filled by THIS pass, so a second URL targeting the same field
        # is kept in the body instead of overwriting the first winner.
        filled_fields: set[str] = set()
        changed = False
        pos = 0
        total = len(description)

        while pos < total:
            row = description[pos]
            style = styles[pos] if pos < len(styles) else "bullet"
            if not _is_tech_stack_label_row(row):
                new_rows.append(row)
                new_styles.append(style if style in _VALID_DESCRIPTION_STYLES else "bullet")
                pos += 1
                continue

            # The region ends at the next heading row (known sub-label or any
            # label-styled row); everything before it belongs to 技术栈.
            region_end = pos + 1
            while region_end < total:
                candidate = description[region_end]
                candidate_style = (
                    styles[region_end] if region_end < len(styles) else "bullet"
                )
                if candidate_style == "label" or _project_heading_kind(candidate) is not None:
                    break
                region_end += 1

            # Surviving body rows as (original position, stripped text); URL
            # rows routed to a header field are consumed instead.
            body_sources: list[tuple[int, str]] = []
            url_fills: list[tuple[str, str]] = []
            for follower_pos in range(pos + 1, region_end):
                follower = description[follower_pos]
                url = _extract_standalone_url_row(follower)
                if url is None:
                    body_sources.append(
                        (
                            follower_pos,
                            follower.strip() if isinstance(follower, str) else str(follower),
                        )
                    )
                    continue
                field = _project_url_target_field(url)
                current = project.get(field)
                field_occupied = field in filled_fields or (
                    isinstance(current, str) and bool(current.strip())
                )
                if field_occupied:
                    # Never overwrite: the URL stays visible inside the stack.
                    body_sources.append(
                        (
                            follower_pos,
                            follower.strip() if isinstance(follower, str) else str(follower),
                        )
                    )
                else:
                    url_fills.append((field, url))
                    # Reserve the field for the rest of THIS scan so a second
                    # URL targeting the same field stays in the body instead
                    # of overwriting the first winner when fills are applied.
                    filled_fields.add(field)

            # A recognized 技术栈 heading keeps its explicit stored style; a
            # missing or invalid entry synthesizes the canonical "label" style
            # rather than the body-row "bullet" default used below.
            label_style = (
                style
                if pos < len(styles) and style in _VALID_DESCRIPTION_STYLES
                else "label"
            )

            if not body_sources:
                # Degenerate all-URL region: keep every row verbatim so the
                # 技术栈 heading is never orphaned and no data is dropped.
                for keep_pos in range(pos, region_end):
                    new_rows.append(description[keep_pos])
                    if keep_pos == pos:
                        new_styles.append(label_style)
                        continue
                    keep_style = styles[keep_pos] if keep_pos < len(styles) else "bullet"
                    new_styles.append(
                        keep_style if keep_style in _VALID_DESCRIPTION_STYLES else "bullet"
                    )
                pos = region_end
                continue

            body_rows = [text for _, text in body_sources]
            structured = any(_is_tech_stack_category_row(text) for text in body_rows)

            if structured:
                # Category enumeration: keep one plain row per category; only
                # the consumed URL rows disappear.
                emitted_rows: list[Any] = [row]
                emitted_styles = [label_style]
                for source_pos, text in body_sources:
                    source_style = (
                        styles[source_pos] if source_pos < len(styles) else "plain"
                    )
                    emitted_rows.append(text)
                    emitted_styles.append(
                        source_style if source_style in _VALID_DESCRIPTION_STYLES else "plain"
                    )
            elif len(body_rows) >= 2:
                # Flat name stack: merge into one inline-wrapped plain line.
                # The recognized 技术栈 label is Chinese-context, so Chinese
                # enumeration typography applies even when every token is an
                # ASCII tech name ("Java、Kotlin") — this is the zh-resume
                # expectation. The render-time joinInlineBodyRows() / DOCX
                # _join_inline_body_rows() helpers instead pick ", " for
                # all-ASCII bodies because they have no label context; the
                # single stored row produced here already carries its
                # separator verbatim, so their fallback never re-joins it.
                emitted_rows = [row, "、".join(body_rows)]
                emitted_styles = [label_style, "plain"]
            else:
                # One surviving body row (URL rows may still have been
                # consumed): tech-stack content is always unnumbered body.
                emitted_rows = [row, body_rows[0]]
                emitted_styles = [label_style, "plain"]

            original_rows = description[pos:region_end]
            original_styles = [
                styles[index] if index < len(styles) else "bullet"
                for index in range(pos, region_end)
            ]
            if url_fills or emitted_rows != original_rows or emitted_styles != original_styles:
                changed = True
            new_rows.extend(emitted_rows)
            new_styles.extend(emitted_styles)

            for field, url in url_fills:
                # Occupancy was reserved during the scan, so each field appears
                # at most once here and this write only fills an empty field.
                project[field] = url

            pos = region_end

        if changed:
            project["description"] = new_rows
            project["descriptionStyles"] = new_styles

    return parsed_data


# --- Inline credentials inside education descriptions ------------------
# Chinese resumes frequently print awards and certificates INSIDE the
# education block, e.g.
#   "2017.10-2021.06 天津大学仁爱学院 计算机科学与技术 本科
#    奖项：国家励志奖学金、杯全国软件和信息技术三等奖。
#    证书：PMP项目管理证书。"
# Weak models glue these lines into education.description — which renders in
# the single major cell of the fixed education row. The labels below re-route
# each segment to additional.awards / certificationsTraining; the major cell
# keeps only the specialization text.
_EDU_MAJOR_LABEL_CORES: tuple[str, ...] = ("专业方向", "主修专业", "专业名称", "专业")
_EDU_AWARD_LABEL_CORES: tuple[str, ...] = (
    "奖项名称",
    "获奖情况",
    "获奖名称",
    "获奖记录",
    "荣誉奖项",
    "荣誉称号",
    "荣誉证书",
    "奖项",
    "获奖",
    "荣誉",
    "奖励",
    "Awards",
    "Award",
    "Honors",
    "Honours",
    "Honor",
)
_EDU_CERT_LABEL_CORES: tuple[str, ...] = (
    "资格证书",
    "资格认证",
    "资质证书",
    "职业资格",
    "证书名称",
    "认证证书",
    "资质",
    "认证",
    "证书",
    "执照",
    "Certifications",
    "Certification",
    "Certificates",
    "Certificate",
    "Qualifications",
    "Qualification",
    "Licenses",
    "License",
    "Licences",
    "Licence",
)
# Labels that mix the two kinds on one line ("荣誉证书：校三好学生、PMP证书。");
# items are then routed individually by keyword.
_EDU_MIXED_LABEL_CORES: frozenset[str] = frozenset(
    {"荣誉证书", "资质荣誉", "荣誉资质"}
)
# Extra award/cert cores shared with the work/project list-region pass below.
_EXTRA_AWARD_LABEL_CORES: tuple[str, ...] = (
    "所获荣誉",
    "个人荣誉",
    "荣誉表彰",
    "获奖荣誉",
    "所获奖励",
)
_EXTRA_CERT_LABEL_CORES: tuple[str, ...] = (
    "执业资格",
    "职业证书",
    "专业证书",
    "技能证书",
)
# Language-proficiency label cores, shared by the education string pass and
# the work/project list-region pass. The bare 语言 core stays last: inside the
# free-text education regex it carries 编程/开发-family lookbehinds so
# "编程语言：Java" cannot match; list rows are row-anchored and naturally safe.
_EDU_LANG_LABEL_CORES: tuple[str, ...] = (
    "语言能力",
    "外语能力",
    "语言水平",
    "外语水平",
    "英语水平",
    "英语能力",
    "语言情况",
    "掌握语言",
    "Languages",
    "Language",
    "语言",
    "外语",
)
_EDU_CERT_ITEM_HINT_RE = re.compile(r"证书|认证|资格|资质|执照")
_EDU_LABEL_ALT = "|".join(
    sorted(
        _EDU_MAJOR_LABEL_CORES
        + _EDU_AWARD_LABEL_CORES
        + _EXTRA_AWARD_LABEL_CORES
        + _EDU_CERT_LABEL_CORES
        + _EXTRA_CERT_LABEL_CORES
        + tuple(_EDU_MIXED_LABEL_CORES),
        key=len,
        reverse=True,
    )
)
# Language alternatives form their own group: multi-char cores first, the
# bare 语言 core last with fixed-width negative lookbehinds (编程语言 /
# 开发语言 / 脚本语言 / …). All are two CJK chars wide, as re requires.
_EDU_LANG_LABEL_ALT = "|".join(
    sorted(
        (core for core in _EDU_LANG_LABEL_CORES if core != "语言"),
        key=len,
        reverse=True,
    )
)
_EDU_LABEL_ALT = (
    _EDU_LABEL_ALT
    + "|"
    + _EDU_LANG_LABEL_ALT
    + r"|(?<!编程)(?<!开发)(?<!脚本)(?<!程序)(?<!设计)(?<!计算)语言"
)
# ASCII labels need a lookbehind so "Rewards:" cannot match "Awards:" in its
# middle; CJK labels are naturally bounded by non-ASCII characters.
_EDU_SEGMENT_LABEL_RE = re.compile(rf"(?<![A-Za-z0-9])({_EDU_LABEL_ALT})\s*[：:]")
_EDU_CREDENTIAL_CLAUSE_RE = re.compile(r"[；;。\n，,]+")
_EDU_CREDENTIAL_ITEM_TAIL = "。.；;，,、 \t"

# Item-level routing hints. These are used INSIDE an explicit credential label
# region only (never on free description rows), so broad tokens like 奖/英语
# stay safe. Strong certificate words/acronyms win over the other two buckets,
# so a PMP line inside a 语言： region still lands in certificationsTraining.
_MISFILE_CERT_ITEM_HINT_RE = re.compile(
    r"PMP|CPA|CFA|ACCA|AWS|Azure|Google\s*Cloud|OCI|ITIL|CKA|"
    r"Licen[cs]e|Certified|"
    r"证书|认证|资格|资质|执照|执业|结业证",
    re.IGNORECASE,
)
_MISFILE_LANG_ITEM_HINT_RE = re.compile(
    r"英语|日语|韩语|法语|德语|俄语|西班牙语|葡萄牙语|意大利语|阿拉伯语|泰语|越南语|"
    r"印尼语|马来语|粤语|普通话|汉语|中文|外语|口语|口译|笔译|"
    r"雅思|IELTS|托福|TOEFL|GRE|GMAT|SAT|TESOL|TEFL|CATTI|"
    r"CET|大学英语|专四|专八|四级|六级|八级|N[1-5](?![0-9])|"
    r"English|Japanese|Korean|French|German|Spanish|Mandarin|Cantonese",
    re.IGNORECASE,
)
_MISFILE_AWARD_ITEM_HINT_RE = re.compile(
    r"奖|荣誉|荣获|获奖|奖学金|冠军|亚军|季军|金奖|银奖|铜奖|表彰|勋章|"
    r"标兵|三好|优秀|先进|奖章|立功|嘉奖|"
    r"Dean'?s List|Cum Laude|Magna|Summa|Prize|Scholarship|Fellowship|"
    r"Medal|Honor Roll|Recognition|Champion|Runner[- ]?up|"
    r"Awards?|Honou?rs",
    re.IGNORECASE,
)


def _route_credential_item(region_kind: str, item: str) -> tuple[str, bool]:
    """Route one credential item to its ``additional`` bucket.

    Returns ``(bucket_name, evidenced)``. ``evidenced`` means the item carries
    a keyword for the bucket it lands in; callers use that as a conservative
    gate so a labeled block full of unrelated duty prose stays untouched.
    Items without any hint default to their region's bucket unevidenced
    (mixed/award regions default to awards, mirroring the education pass).
    """
    if _MISFILE_CERT_ITEM_HINT_RE.search(item):
        return "certificationsTraining", True
    has_lang = bool(_MISFILE_LANG_ITEM_HINT_RE.search(item))
    has_award = bool(_MISFILE_AWARD_ITEM_HINT_RE.search(item))
    if has_lang and has_award:
        return ("languages", True) if region_kind == "language" else ("awards", True)
    if has_lang:
        return "languages", True
    if has_award:
        return "awards", True
    if region_kind == "language":
        return "languages", False
    if region_kind == "cert":
        return "certificationsTraining", False
    return "awards", False


def _edu_label_kind(label_core: str) -> str:
    """Classify an education inline label core as major/award/cert/language/mixed."""
    if label_core in _EDU_MAJOR_LABEL_CORES:
        return "major"
    if label_core in _EDU_MIXED_LABEL_CORES:
        return "mixed"
    if label_core in _EDU_LANG_LABEL_CORES:
        return "language"
    if label_core in _EDU_CERT_LABEL_CORES or label_core in _EXTRA_CERT_LABEL_CORES:
        return "cert"
    return "award"


def _split_credential_items(segment: str) -> list[str]:
    """Split one credential segment into trimmed individual items.

    Clause punctuation (``；。,``/newlines) is split first so a source number
    attached to the second clause ("…；2、校三好学生") can be stripped before
    splitting on ``、`` — otherwise the ``、`` of the marker "2、" would leave
    a bare "2" item.
    """
    items: list[str] = []
    for clause in _EDU_CREDENTIAL_CLAUSE_RE.split(segment):
        clause_text = strip_source_point_marker(clause.strip())
        if not isinstance(clause_text, str):
            continue
        for part in clause_text.split("、"):
            item = strip_source_point_marker(part.strip())
            if not isinstance(item, str):
                continue
            item = item.strip(_EDU_CREDENTIAL_ITEM_TAIL)
            if item:
                items.append(item)
    return items


def _extract_education_credentials_text(
    text: str,
) -> tuple[str, list[str], list[str], list[str]] | None:
    """Split an education ``description`` into (major, awards, certs, languages).

    Returns ``None`` when the text contains no recognized inline label, so
    callers can leave unrecognized descriptions byte-identical.
    """
    matches = list(_EDU_SEGMENT_LABEL_RE.finditer(text))
    if not matches:
        return None

    major_parts: list[str] = []
    awards: list[str] = []
    certs: list[str] = []
    languages: list[str] = []
    leading = text[: matches[0].start()].strip()
    if leading:
        major_parts.append(leading)

    for index, match in enumerate(matches):
        segment_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = text[match.end() : segment_end].strip()
        kind = _edu_label_kind(match.group(1))
        if kind == "major":
            content = content.strip("。.；;，,、 \t")
            if content:
                major_parts.append(content)
            continue
        for item in _split_credential_items(content):
            if kind == "award":
                awards.append(item)
            elif kind == "cert":
                certs.append(item)
            elif kind == "language":
                # Strong certificate words ("英语六级证书") still win.
                bucket, _ = _route_credential_item("language", item)
                if bucket == "certificationsTraining":
                    certs.append(item)
                else:
                    languages.append(item)
            elif _EDU_CERT_ITEM_HINT_RE.search(item):
                certs.append(item)
            else:
                awards.append(item)

    return " ".join(major_parts).strip(), awards, certs, languages


def extract_education_credentials(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """Move inline 奖项/证书 segments out of education descriptions.

    The education row renders ``description`` in a single major cell; award
    and certificate lines glued into it by weak models must instead join
    ``additional.awards`` / ``additional.certificationsTraining`` (which the
    prompt already mandates regardless of an independent section heading).
    Entries already present in those arrays are de-duplicated by the final
    de-dupe pass, so running this twice is a no-op.
    """
    education = parsed_data.get("education")
    if not isinstance(education, list):
        return parsed_data

    additional = parsed_data.get("additional")
    if not isinstance(additional, dict):
        additional = None

    for entry in education:
        if not isinstance(entry, dict):
            continue
        description = entry.get("description")
        if not isinstance(description, str) or not description:
            continue
        extracted = _extract_education_credentials_text(description)
        if extracted is None:
            continue
        major, awards, certs, languages = extracted
        if not awards and not certs and not languages and major == description.strip():
            continue
        entry["description"] = major
        if not awards and not certs and not languages:
            continue
        if additional is None:
            additional = {}
            parsed_data["additional"] = additional
        for field, items in (
            ("awards", awards),
            ("certificationsTraining", certs),
            ("languages", languages),
        ):
            if not items:
                continue
            values = additional.get(field)
            if not isinstance(values, list):
                values = []
            values.extend(items)
            additional[field] = values

    return parsed_data


# --- Misfiled credential regions in work/project list descriptions --------
#
# Weak models file labeled award / certificate / language blocks inside the
# list-shaped workExperience / personalProjects descriptions:
#
#   ["奖项：", "国家奖学金", "校优秀学生干部", "工作职责：", …]   # block
#   ["奖项：国家奖学金、PMP项目管理证书。", …]                   # glued row
#
# The lists render as numbered points, so the pass moves items into
# additional.awards / certificationsTraining / languages and deletes BOTH the
# row and its descriptionStyles entry. Conservative by design: only an
# explicit credential label opens a region, every moved item must carry a
# keyword for its target bucket (the evidence gate), and a region longer than
# six rows without another label as boundary is abandoned — unlabeled duty
# prose ("负责年会奖品采购", "持有 PMP 证书的轮岗") is never touched.
_MISFILE_AWARD_LABEL_CORES: tuple[str, ...] = (
    _EDU_AWARD_LABEL_CORES + _EXTRA_AWARD_LABEL_CORES
)
_MISFILE_CERT_LABEL_CORES: tuple[str, ...] = _EDU_CERT_LABEL_CORES + _EXTRA_CERT_LABEL_CORES
_MISFILE_MIXED_CORES: frozenset[str] = _EDU_MIXED_LABEL_CORES
_MISFILE_REGION_MAX_ROWS = 6


def _misfile_label_kind(core: str) -> str:
    """Classify a list-row credential label core (mixed wins overlaps)."""
    if core in _MISFILE_MIXED_CORES:
        return "mixed"
    if core in _EDU_LANG_LABEL_CORES:
        return "language"
    if core in _MISFILE_CERT_LABEL_CORES:
        return "cert"
    return "award"


# De-duplicated cores, longest first so "语言能力" wins over bare "语言".
_MISFILE_LABEL_CORES_SORTED: tuple[str, ...] = tuple(
    sorted(
        set(
            _MISFILE_AWARD_LABEL_CORES
            + _MISFILE_CERT_LABEL_CORES
            + tuple(_MISFILE_MIXED_CORES)
            + _EDU_LANG_LABEL_CORES
        ),
        key=len,
        reverse=True,
    )
)
_MISFILE_LABEL_KIND: dict[str, str] = {
    core: _misfile_label_kind(core) for core in _MISFILE_LABEL_CORES_SORTED
}
# Match credential labels anywhere in a row. The preceding-char lookbehind
# keeps "编程语言：Java" / "获奖证书：" (证书 preceded by 奖) unrecognized; the
# first match in a row must start at the row start (checked by callers), so a
# mid-sentence "Languages:" in an English duty line never opens a region.
_MISFILE_INLINE_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9一-鿿])("
    + "|".join(_MISFILE_LABEL_CORES_SORTED)
    + r")\s*[：:]"
)


def _misfiled_row_kind(row: Any, style: Any) -> str | None:
    """Classify a description row that opens a credential region.

    A label with trailing content ("奖项：国家奖学金") counts in every style.
    A standalone label ("奖项：") also counts in every style — stored resumes
    may carry bullet/plain styled labels. A bare heading without a colon
    ("奖项") counts only when the model styled that row as ``label``.
    """
    if not isinstance(row, str):
        return None
    text = strip_source_point_marker(row)
    if not isinstance(text, str):
        return None
    text = text.strip()
    match = _MISFILE_INLINE_LABEL_RE.match(text)
    if match is None:
        if style == "label" and text in _MISFILE_LABEL_KIND:
            return _MISFILE_LABEL_KIND[text]
        return None
    return _MISFILE_LABEL_KIND[match.group(1)]


def _split_inline_credential_row(row: Any) -> list[tuple[str, list[str]]] | None:
    """Split a glued credential row into ``(kind, items)`` segments.

    ``奖项：国家奖学金、PMP证书。 证书：AWS 认证`` → two segments. Returns
    ``None`` unless the (marker-stripped) row starts with a credential label.
    """
    if not isinstance(row, str):
        return None
    text = strip_source_point_marker(row)
    if not isinstance(text, str):
        return None
    text = text.strip()
    matches = list(_MISFILE_INLINE_LABEL_RE.finditer(text))
    if not matches or matches[0].start() != 0:
        return None
    segments: list[tuple[str, list[str]]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = text[match.end() : end].strip()
        items = _split_credential_items(content) if content else []
        segments.append((_MISFILE_LABEL_KIND[match.group(1)], items))
    return segments


def _segments_evidenced(segments: list[tuple[str, list[str]]]) -> bool:
    """Gate for glued rows: every non-empty segment has >=1 item and every
    item carries a keyword for its routed bucket."""
    saw_item = False
    for kind, items in segments:
        if not items:
            continue
        saw_item = True
        for item in items:
            _, evidenced = _route_credential_item(kind, item)
            if not evidenced:
                return False
    return saw_item


def _extract_misfiled_from_rows(
    rows: list[Any], styles: list[Any]
) -> tuple[list[Any], list[Any], dict[str, list[str]]] | None:
    """Scan one entry's description rows for misfiled credential regions.

    Returns ``(kept_rows, kept_styles, routed_items)`` or ``None`` when
    nothing moved. ``routed_items`` keys are awards / certificationsTraining
    / languages.
    """
    delete: set[int] = set()
    routed: dict[str, list[str]] = {
        "awards": [],
        "certificationsTraining": [],
        "languages": [],
    }
    changed = False
    index = 0
    while index < len(rows):
        style = styles[index] if index < len(styles) else "bullet"
        kind = _misfiled_row_kind(rows[index], style)
        if kind is None:
            index += 1
            continue

        segments = _split_inline_credential_row(rows[index])
        if segments is not None and any(items for _, items in segments):
            # Glued row ("奖项：A、B。"), possibly multi-segment.
            if _segments_evidenced(segments):
                delete.add(index)
                for segment_kind, items in segments:
                    for item in items:
                        bucket, _ = _route_credential_item(segment_kind, item)
                        routed[bucket].append(item)
                changed = True
            index += 1
            continue

        # Standalone block label: slurp following content rows until the next
        # label-shaped boundary. One content row = one credential item (list
        # bullets are one item per row); internal punctuation is NOT split,
        # so a duty sentence can never fragment into fake credentials.
        content_indices: list[int] = []
        cursor = index + 1
        abandoned = False
        while cursor < len(rows):
            candidate = rows[cursor]
            if not isinstance(candidate, str):
                break
            candidate_style = styles[cursor] if cursor < len(styles) else "bullet"
            if _misfiled_row_kind(candidate, candidate_style) is not None:
                break
            if candidate_style == "label" or _STANDALONE_SUB_LABEL_RE.match(
                candidate.strip()
            ):
                break
            content_indices.append(cursor)
            cursor += 1
            if len(content_indices) > _MISFILE_REGION_MAX_ROWS:
                abandoned = True
                break

        if abandoned or not content_indices:
            # Over-long region: keep the label and resume behind it so later
            # glued credential rows can still be found independently.
            index += 1
            continue

        planned: list[tuple[int, str, str]] = []
        accepted = True
        for content_index in content_indices:
            raw = strip_source_point_marker(rows[content_index])
            if not isinstance(raw, str):
                accepted = False
                break
            item = raw.strip().strip(_EDU_CREDENTIAL_ITEM_TAIL).strip()
            if not item:
                accepted = False
                break
            bucket, evidenced = _route_credential_item(kind, item)
            if not evidenced:
                accepted = False
                break
            planned.append((content_index, item, bucket))

        if not accepted:
            index += 1
            continue

        delete.add(index)
        for content_index, item, bucket in planned:
            delete.add(content_index)
            routed[bucket].append(item)
        changed = True
        index = cursor

    if not changed:
        return None

    kept_rows = [row for row_index, row in enumerate(rows) if row_index not in delete]
    kept_styles = [
        (styles[row_index] if row_index < len(styles) else "bullet")
        for row_index in range(len(rows))
        if row_index not in delete
    ]
    return kept_rows, kept_styles, routed


def extract_misfiled_credentials(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """Move labeled award/cert/language regions out of work/project descriptions.

    Only ``workExperience`` / ``personalProjects`` list descriptions are
    scanned, and only explicit credential labels (block or glued) trigger a
    move — unlabeled rows are never touched. Running twice is a no-op (the
    labels are gone; the final de-dupe pass folds pre-existing duplicates).
    Mutates and returns ``parsed_data``.
    """
    for section in ("workExperience", "personalProjects"):
        entries = parsed_data.get(section)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            description = entry.get("description")
            if not isinstance(description, list) or not description:
                continue
            styles = entry.get("descriptionStyles")
            if not isinstance(styles, list):
                styles = []
            try:
                extracted = _extract_misfiled_from_rows(description, styles)
            except Exception:  # pragma: no cover - heuristic never breaks parse
                logger.warning("Misfiled-credential pass failed on %s entry", section, exc_info=True)
                continue
            if extracted is None:
                continue
            kept_rows, kept_styles, routed = extracted
            entry["description"] = kept_rows
            entry["descriptionStyles"] = kept_styles

            additional = parsed_data.get("additional")
            if not isinstance(additional, dict):
                additional = {}
                parsed_data["additional"] = additional
            for field, items in routed.items():
                if not items:
                    continue
                values = additional.get(field)
                if not isinstance(values, list):
                    values = []
                values.extend(items)
                additional[field] = values

    return parsed_data


_NON_CONTENT_RESUME_KEYS = frozenset(
    {
        "id",
        "sectionType",
        "descriptionStyles",
        "isDefault",
        "isVisible",
        "order",
        "key",
        "displayName",
    }
)
# Depth guard against self-referential or pathological LLM output.  Recursion
# starts at depth 0 on a *top-level section value*, so the deepest user-visible
# value the real ``ResumeData`` schema can produce sits at depth 5:
#
#   customSections(0) -> CustomSection(1) -> items(2) -> CustomSectionItem(3)
#       -> description(4) -> bullet string(5)
#
# Every other content section is shallower: workExperience / personalProjects
# bottom out at depth 3 (list -> Experience -> description -> bullet),
# education and additional at depth 2, personalInfo at depth 1, summary at
# depth 0.  Values are still inspected at depth 9 (the cut-off is ``>= 10``),
# so the limit leaves four full levels of headroom over the schema maximum.
# Nothing that validates as ``ResumeData`` can be misjudged empty here;
# anything deeper is malformed LLM output rather than a resume.  Raise this
# only if the schema itself grows deeper -- see the boundary tests in
# tests/unit/test_parser.py::TestMeaningfulResumeContent.
_MAX_RESUME_CONTENT_RECURSION = 10


def _has_meaningful_resume_value(
    value: Any,
    *,
    depth: int = 0,
    filter_structural_keys: bool = True,
) -> bool:
    """Return whether a value contains non-structural, user-visible text.

    Custom-section identifiers are dictionary keys rather than schema fields,
    so their values are checked without filtering the identifier itself.  Once
    inside a section, normal structural-key filtering resumes.
    """
    if depth >= _MAX_RESUME_CONTENT_RECURSION:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(
            _has_meaningful_resume_value(item, depth=depth + 1) for item in value
        )
    if isinstance(value, dict):
        return any(
            (not filter_structural_keys or key not in _NON_CONTENT_RESUME_KEYS)
            and _has_meaningful_resume_value(item, depth=depth + 1)
            for key, item in value.items()
        )
    return False


def has_meaningful_resume_content(resume_data: Any) -> bool:
    """Return whether parsed resume data contains any user-facing content.

    ``ResumeData`` intentionally defaults most fields to empty strings/lists.
    That is useful for the builder, but it also means an LLM response such as
    ``{}`` validates successfully.  Treating that response as a parsed resume
    produces a blank PDF and makes every downstream tailoring request operate
    on empty data.
    """

    if not isinstance(resume_data, dict):
        return False

    content_sections = (
        "personalInfo",
        "summary",
        "workExperience",
        "education",
        "personalProjects",
        "additional",
        "customSections",
    )
    return any(
        _has_meaningful_resume_value(
            resume_data.get(section),
            filter_structural_keys=section != "customSections",
        )
        for section in content_sections
    )


def _legacy_doc_backend() -> str | None:
    """Locate a local tool able to read legacy binary Word (.doc) files.

    markitdown only handles PDF and OOXML (.docx); OLE2 ``.doc`` needs an
    external converter. Prefer LibreOffice (cross-platform), then the macOS
    built-in ``textutil``.
    """
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        return soffice
    if sys.platform == "darwin":
        if os.path.isfile(_MACOS_LIBREOFFICE_PATH) and os.access(
            _MACOS_LIBREOFFICE_PATH, os.X_OK
        ):
            return _MACOS_LIBREOFFICE_PATH
        if os.path.isfile(_MACOS_TEXTUTIL_PATH) and os.access(_MACOS_TEXTUTIL_PATH, os.X_OK):
            return _MACOS_TEXTUTIL_PATH
    return None


def _run_soffice_to_text(executable: str, doc_path: Path) -> str:
    """Convert a legacy document to plain text with a headless LibreOffice."""
    with tempfile.TemporaryDirectory(prefix="docconvert-") as outdir:
        # A private user profile avoids colliding with an interactive instance.
        profile_url = Path(outdir, "profile").resolve().as_uri()
        completed = subprocess.run(
            [
                executable,
                f"-env:UserInstallation={profile_url}",
                "--headless",
                "--convert-to",
                "txt:Text",
                "--outdir",
                outdir,
                str(doc_path),
            ],
            capture_output=True,
            timeout=LEGACY_DOC_CONVERSION_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode != 0:
            logger.error(
                "LibreOffice legacy .doc conversion failed (rc=%s): %s",
                completed.returncode,
                completed.stderr.decode("utf-8", errors="replace")[:500],
            )
            raise LegacyDocConversionError(
                "Failed to parse the legacy Word (.doc) file. "
                "Please re-save it as PDF or DOCX in Word and upload again."
            )
        produced = Path(outdir, f"{doc_path.stem}.txt")
        if not produced.is_file():
            logger.error("LibreOffice produced no text file for legacy .doc upload")
            raise LegacyDocConversionError(
                "Failed to parse the legacy Word (.doc) file. "
                "Please re-save it as PDF or DOCX in Word and upload again."
            )
        return produced.read_text(encoding="utf-8", errors="replace")


def _run_textutil_to_text(executable: str, doc_path: Path) -> str:
    """Convert a legacy document to plain text with macOS textutil."""
    completed = subprocess.run(
        [executable, "-convert", "txt", "-stdout", str(doc_path)],
        capture_output=True,
        timeout=LEGACY_DOC_CONVERSION_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        logger.error(
            "textutil legacy .doc conversion failed (rc=%s): %s",
            completed.returncode,
            completed.stderr.decode("utf-8", errors="replace")[:500],
        )
        raise LegacyDocConversionError(
            "Failed to parse the legacy Word (.doc) file. "
            "Please re-save it as PDF or DOCX in Word and upload again."
        )
    return completed.stdout.decode("utf-8", errors="replace")


def _convert_legacy_doc(doc_path: Path) -> str:
    """Extract text from a legacy OLE2 Word (.doc) file via a local tool.

    Raises ``LegacyDocConversionError`` (client-safe message, details logged)
    when no converter backend is available or conversion fails.
    """
    executable = _legacy_doc_backend()
    if executable is None:
        logger.error("Legacy .doc upload rejected: no local converter backend installed")
        raise LegacyDocConversionError(
            "Legacy binary Word (.doc) is not supported on this server. "
            "Please open the file in Word and save it as PDF or DOCX, then upload again."
        )
    try:
        if os.path.basename(executable) == "textutil":
            text = _run_textutil_to_text(executable, doc_path)
        else:
            text = _run_soffice_to_text(executable, doc_path)
    except subprocess.TimeoutExpired:
        logger.error(
            "Legacy .doc conversion timed out after %.0fs",
            LEGACY_DOC_CONVERSION_TIMEOUT_SECONDS,
        )
        raise LegacyDocConversionError(
            "Parsing the legacy Word (.doc) file timed out. "
            "Please re-save it as PDF or DOCX in Word and upload again."
        ) from None
    return text


# Extraction signature of an embedded-subset font whose glyphs pdfminer (the
# markitdown PDF backend) cannot decode: dropped character runs leave long
# space gaps ("2017.09 - 2021.07" -> "    .  -    . "), and the characters it
# can partially map surface as Kangxi/radical codepoints (⼯/⻓/…).
_GLYPH_LOSS_GAP_RE = re.compile(r"[ \t]{4,}")
# Date range with its digits dropped: "2017.09 - 2021.07" -> "   .  -    . ".
_GLYPH_LOSS_DATE_RE = re.compile(r"[ \t]{2,}\.[ \t]*-[ \t]{0,3}\.")
_GLYPH_LOSS_RADICAL_RE = re.compile(r"[⺀-⻳⼀-⿕]")
_PDFIUM_MIN_CJK_RATIO = 0.6


def _shows_glyph_loss(text: str) -> bool:
    """Heuristic: markitdown/pdfminer output likely dropped glyph runs."""
    if _GLYPH_LOSS_GAP_RE.search(text) or _GLYPH_LOSS_DATE_RE.search(text):
        return True
    return len(_GLYPH_LOSS_RADICAL_RE.findall(text)) >= 10


def _extract_pdf_text_pdfium(content: bytes) -> str | None:
    """Extract PDF text with pypdfium2 (better embedded-subset coverage).

    Returns ``None`` when the optional dependency is missing or extraction
    fails; the caller then keeps the markitdown output. pypdfium2 can reorder
    sidebar/right-rail content, so this is a recovery path, never the primary.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None
    try:
        document = pdfium.PdfDocument(content)
        try:
            pages: list[str] = []
            for page in document:
                text_page = page.get_textpage()
                try:
                    pages.append(text_page.get_text_range())
                finally:
                    text_page.close()
        finally:
            document.close()
    except Exception:
        logger.exception("pypdfium2 recovery extraction failed")
        return None
    text = normalize_cjk_compat("\n".join(pages))
    return text if text.strip() else None


def _recover_glyph_loss(content: bytes, text: str) -> str:
    """Swap in pypdfium2 text when markitdown output shows dropped glyphs.

    The replacement must keep at least 60% of the CJK characters and contain
    more ASCII digits (dates, levels such as P7, versions such as JDK 21.0.1)
    than the damaged text; otherwise the markitdown output wins because its
    reading order (in-line tech stacks) is usually better.
    """
    if not _shows_glyph_loss(text):
        return text
    recovered = _extract_pdf_text_pdfium(content)
    if recovered is None:
        return text

    def cjk_count(value: str) -> int:
        return sum(1 for ch in value if "一" <= ch <= "鿿")

    def digit_count(value: str) -> int:
        return sum(1 for ch in value if ch.isdigit())

    if cjk_count(recovered) < _PDFIUM_MIN_CJK_RATIO * cjk_count(text):
        logger.info(
            "pypdfium2 recovery rejected: too few CJK characters (%d vs %d)",
            cjk_count(recovered),
            cjk_count(text),
        )
        return text
    if digit_count(recovered) <= digit_count(text):
        logger.info("pypdfium2 recovery rejected: no extra digit content")
        return text
    logger.info(
        "Recovered PDF text with pypdfium2 after markitdown glyph loss "
        "(digits %d -> %d)",
        digit_count(text),
        digit_count(recovered),
    )
    return recovered


def _ocr_fallback(content: bytes, text: str) -> str:
    """Recover a text-less PDF via the optional offline OCR extra.

    Every failure path (extra not installed, rendering/inference error, no
    recognised text) returns the original (empty) extraction so the router
    keeps emitting the existing 422 instead of turning OCR trouble into 500s.
    """
    if not ocr_service.is_ocr_available():
        logger.info(
            "PDF text layer is empty; install the optional 'ocr' extra to "
            "recognise scanned or outline-only PDFs automatically"
        )
        return text
    try:
        recovered = ocr_service.ocr_pdf(content)
    except Exception:
        logger.exception("OCR fallback failed for a text-less PDF")
        return text
    if not recovered.strip():
        logger.info("OCR fallback recognised no text in the text-less PDF")
        return text
    _validate_extracted_text(recovered)
    logger.info(
        "Recovered %d characters from a text-less PDF via OCR", len(recovered)
    )
    return recovered


def _parse_document_sync(content: bytes, filename: str) -> str:
    """Validate and convert a document inside a bounded worker thread."""
    suffix = Path(filename).suffix.lower()
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(content)
        if suffix == ".pdf":
            _validate_pdf_container(tmp_path)
        elif suffix == ".doc":
            sniffed_format = _sniff_legacy_doc_format(tmp_path)
            if sniffed_format == "ole2":
                _validate_doc_container(tmp_path)
            elif sniffed_format == "docx":
                # Mislabeled OOXML package: markitdown infers the converter
                # from the extension, so re-suffix before its DOCX path.
                docx_path = tmp_path.with_suffix(".docx")
                tmp_path.rename(docx_path)
                tmp_path = docx_path
                suffix = ".docx"
                _validate_docx_container(tmp_path)
            elif sniffed_format in ("rtf", "html"):
                # The local legacy converter (textutil/LibreOffice) sniffs
                # content and reads RTF/HTML directly; a server without a
                # converter gets the actionable LegacyDocConversionError.
                text = normalize_cjk_compat(_convert_legacy_doc(tmp_path))
                _validate_extracted_text(text)
                return text
            else:
                raise DocumentValidationError(
                    "The uploaded file is not a valid PDF, DOC, or DOCX document."
                )
        elif suffix == ".docx":
            _validate_docx_container(tmp_path)
        md = MarkItDown()
        try:
            result = md.convert(str(tmp_path))
        except UnsupportedFormatException:
            # markitdown has no converter for OLE2 legacy Word (.doc).
            if suffix != ".doc":
                raise
            text = normalize_cjk_compat(_convert_legacy_doc(tmp_path))
            _validate_extracted_text(text)
            return text
        text = result.text_content
        if not isinstance(text, str):
            raise DocumentValidationError(
                "The uploaded file is not a valid PDF, DOC, or DOCX document."
            )
        if suffix == ".pdf":
            if not text.strip():
                # Scanned PDFs and glyph-as-outline PDFs have no text layer.
                text = _ocr_fallback(content, text)
            else:
                # Damaged text layer (missing digits, radical glyphs): run on
                # the raw markitdown output while the glyph-loss signature is
                # still visible (normalization would erase the radicals).
                text = _recover_glyph_loss(content, text)
        # Embedded-subset fonts can yield Kangxi/radical glyphs (⼯→should be
        # 工): normalize before any heuristic or the LLM sees the text.
        text = normalize_cjk_compat(text)
        _validate_extracted_text(text)
        return text
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def _validate_parsed_resume(result: dict[str, Any]) -> dict[str, Any]:
    """Validate that parsed output is a schema-valid, non-empty resume."""
    parsed_data = ResumeData.model_validate(result).model_dump()
    if not has_meaningful_resume_content(parsed_data):
        raise ValueError("LLM returned an empty structured resume.")
    return parsed_data


async def parse_document(content: bytes, filename: str) -> str:
    """Convert a bounded PDF/DOC/DOCX without blocking the request event loop.

    Args:
        content: Raw file bytes
        filename: Original filename for extension detection

    Returns:
        Markdown text content
    """
    deadline = asyncio.get_running_loop().time() + DOCUMENT_CONVERSION_TIMEOUT_SECONDS
    borrower = object()
    # Queued requests still belong to their caller. Only an admitted conversion
    # can outlive cancellation; abandoned queues never retain file bytes or run.
    await asyncio.wait_for(
        _DOCUMENT_CONVERSION_LIMITER.acquire_on_behalf_of(borrower),
        timeout=DOCUMENT_CONVERSION_TIMEOUT_SECONDS,
    )

    async def run_admitted_worker() -> str:
        try:
            return await anyio.to_thread.run_sync(
                _parse_document_sync, content, filename, abandon_on_cancel=False
            )
        finally:
            _DOCUMENT_CONVERSION_LIMITER.release_on_behalf_of(borrower)

    worker = asyncio.create_task(run_admitted_worker())
    try:
        return await asyncio.wait_for(
            asyncio.shield(worker),
            timeout=max(0.0, deadline - asyncio.get_running_loop().time()),
        )
    except (asyncio.CancelledError, TimeoutError):
        # Threads cannot be killed safely. Return on the caller's deadline while
        # the worker retains its limiter slot and owns its tempfile until done.
        _DOCUMENT_BACKGROUND_WORKERS.add(worker)

        def consume_result(done: asyncio.Task[str]) -> None:
            _DOCUMENT_BACKGROUND_WORKERS.discard(done)
            if not done.cancelled():
                try:
                    done.result()
                except Exception:
                    logger.exception(
                        "Document conversion failed after request cancellation"
                    )

        worker.add_done_callback(consume_result)
        raise


async def parse_resume_to_json(markdown_text: str) -> dict[str, Any]:
    """Parse resume markdown to structured JSON using LLM.

    After LLM parsing, patches any year-only dates with month-inclusive
    dates extracted from the raw markdown, backfills empty/stripped
    header demographics (gender, age, work years, education level incl.
    tags such as "(211)", contact facts, languages) from label：value
    pairs in the raw markdown, and promotes a standalone org-unit line
    ("全球资金部") misfiled as a plain description row into the work
    department field. This ensures these facts are never lost
    regardless of LLM behavior.

    Args:
        markdown_text: Resume content in markdown format

    Returns:
        Structured resume data matching ResumeData schema
    """
    if not markdown_text or not markdown_text.strip():
        raise ValueError("Resume content is empty after text extraction.")

    prompt = PARSE_RESUME_PROMPT.format(
        schema=RESUME_SCHEMA_EXAMPLE,
        resume_text=markdown_text,
    )

    config = get_llm_config()
    model_name = get_model_name(config)
    result = await complete_json(
        prompt=prompt,
        system_prompt="You are a JSON extraction engine. Output only valid JSON, no explanations.",
        max_tokens=get_safe_max_tokens(model_name, config=config),
        retries=3,
        response_validator=_validate_parsed_resume,
    )

    # Normalize radical glyphs (⼯→工, ⻓→长, …) FIRST: PDF extraction can
    # emit them for embedded-subset fonts, and they would defeat every regex
    # (headings, sub-labels, dates) in the pipeline below.
    result = normalize_cjk_compat_deep(result)

    # Remove leaked Markdown emphasis markers ("**x**"/"`x`"/"~~x~~" and
    # orphan fragments) from every field FIRST, so markers cannot defeat the
    # date/sub-label/header regexes below.
    result = strip_markdown_formatting(result)

    # Patch dates: restore months the LLM may have dropped
    result = restore_dates_from_markdown(result, markdown_text)

    # Canonicalize every years field: yyyy.MM, "~" connector, 至今 for
    # open-ended periods (numeric months for every resume, incl. English).
    result = normalize_date_periods(result)

    # Patch header demographics: fill empty fields / restore verbatim tags
    # such as "(211)" the LLM may have dropped from the source header.
    result = backfill_personal_info_from_markdown(result, markdown_text)

    # Reverse-chronological work/education order, regardless of LLM ordering.
    result = sort_timeline_sections_newest_first(result)

    # Promote inline 项目规模/项目角色 rows into the project header fields.
    result = extract_project_header_fields(result)

    # Restore in-item sub-label rows (技术架构：/工作职责：/…), including
    # unplanned sub-modules, so their source formatting survives weak models.
    result = normalize_item_sub_labels(result)

    # Align every project row style with its sub-label region: tech-stack
    # entries stay unnumbered body rows, duty/achievement prose glued to a
    # bold label row is demoted to a bullet point.
    result = repair_project_label_regions(result)

    # Move inline 奖项/证书 segments glued into education descriptions into
    # additional.awards / certificationsTraining; the major cell keeps only
    # the specialization text.
    result = extract_education_credentials(result)

    # Same for labeled award/cert/language regions trapped inside the
    # list-shaped work/project descriptions (rows + styles removed in sync).
    result = extract_misfiled_credentials(result)

    # Strip source-carried list numbering ("1、"/"①"/"•"): the renderer owns
    # list numbers, so keeping them would double-number every list.
    result = strip_source_point_numbering(result)

    # Join per-token 技术栈 rows back into one plain line and lift standalone
    # project URL rows into the empty website/github header fields. Runs after
    # region repair and marker stripping so followers are plain, marker-free.
    result = repair_project_tech_stack_rows(result)

    # Repair custom sections whose content landed in the wrong container
    # (stringList entries stored as items, or vice versa): the render layer
    # only reads the container matching sectionType, so mismatches hide the
    # content and leave a title-only block.
    result = reconcile_custom_section_shapes(result)

    # Move a standalone org-unit line ("全球资金部") wrongly filed as a plain
    # description row into the work entry's department field; the renderer
    # repeats the same repair for already-stored resumes.
    result = promote_work_departments(result)

    # Weak models sometimes return a self-evaluation paragraph or a project
    # 项目职责 row as one long ；/。-separated blob; split them into separate
    # points so the renderer shows an ordered list, not a paragraph.
    result = split_blob_text_sections(result)

    # Canonical casing for curated technical terms (java→Java …) BEFORE
    # hygiene/dedupe so rows that only differed by casing collapse together.
    result = canonicalize_tech_terms(result)

    # Presentation hygiene: trim rows, collapse whitespace runs, drop blank
    # rows/styles in lockstep and blank lines in text blocks, and unify list
    # point endings (no trailing 。.；; on bullets / rendered lists). Runs
    # AFTER structural splits/repairs so newly created rows are cleaned too,
    # but BEFORE dedupe, which can collapse rows that hygiene makes equal.
    result = normalize_text_hygiene(result)

    # Source-number stripping can collapse list entries that differed only by
    # their marker ("1、英语四级" / "英语四级"); drop the now-duplicate rows.
    result = dedupe_resume_lists(result)

    # Validate against schema
    return _validate_parsed_resume(result)
