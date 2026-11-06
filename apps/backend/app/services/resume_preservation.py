"""Deterministic preservation at the final AI-authored resume seam."""

from __future__ import annotations

import copy
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any

GROUNDING_REVIEW_CODE = "GROUNDING_REVIEW_REQUIRED"
_GROUNDING_REVIEW_THRESHOLD = 0.45

# Han range for detecting an elaboration boundary directly after a skill name
# ("Redis缓存" elaborates "Redis") and for CJK-adjacent token matching.
_CJK_CHAR_RE = re.compile(r"[㐀-䶿一-鿿]")
_ANY_DIGIT_RE = re.compile(r"\d")

# Canonical sub-module labels the diff flow may inject when a project lacks a
# 技术栈 / 项目亮点 region. An inserted label row is structural boilerplate (the
# parser canonically produces exactly these), not a content claim, so it is
# approved structurally whenever row insertion is active.
_SKILL_DETAIL_SEPARATORS = "：:·|（(［[\\-—、,，/；;"
_INJECTED_STACK_LABELS = (
    "技术栈",
    "技术选型",
    "技术架构",
    "所用技术",
    "tech stack",
    "technology stack",
    "technologies",
)
_INJECTED_HIGHLIGHT_LABELS = (
    "项目亮点",
    "项目成果",
    "技术亮点",
    "project highlights",
    "key highlights",
    "highlights",
)
_INJECTED_LABEL_NORMS: set[str] = {
    " ".join(label.casefold().split())
    for label in _INJECTED_STACK_LABELS + _INJECTED_HIGHLIGHT_LABELS
}

# Broader label vocabulary used to locate sub-module regions when re-deriving
# insert_row approvals at confirm time. Mirrors the parser/improver label sets;
# OTHER labels terminate a stack/highlight region without opening one.
_REGION_STACK_LABEL_NORMS = {
    " ".join(label.casefold().split()) for label in _INJECTED_STACK_LABELS
} | {
    " ".join(label.casefold().split())
    for label in (
        "技术选型",
        "技术架构",
        "所用技术",
        "技术清单",
        "技术列表",
        "系统架构",
        "架构说明",
        "technologies",
    )
}
_REGION_HIGHLIGHT_LABEL_NORMS = {
    " ".join(label.casefold().split()) for label in _INJECTED_HIGHLIGHT_LABELS
} | {
    " ".join(label.casefold().split())
    for label in (
        "项目成果",
        "技术难点",
        "难点与解决",
        "技术难点及亮点",
    )
}
_REGION_OTHER_LABEL_NORMS = {
    " ".join(label.casefold().split())
    for label in (
        "项目职责",
        "工作职责",
        "主要职责",
        "负责内容",
        "核心工作",
        "工作内容",
        "职责",
        "responsibilities",
        "duties",
        "项目背景",
        "项目概述",
        "业务背景",
        "项目简介",
        "需求背景",
        "项目概况",
        "项目介绍",
        "项目描述",
        "background",
        "overview",
        "description",
    )
}


def _skill_detail_boundary(tail: str) -> bool:
    """Whether text immediately after a bare skill name starts an elaboration."""
    if not tail:
        return False
    if tail[0].isspace():
        return True
    return tail[0] in _SKILL_DETAIL_SEPARATORS or bool(_CJK_CHAR_RE.match(tail[0]))


_TERM_BOUNDARY_CHARS = frozenset(
    "：:·|（(［[\\-—、,，/；;）)】]。.！!？?\"'“”‘’<>《》「」 "
)


def _is_term_boundary(ch: str) -> bool:
    """Whether ``ch`` may bound a technology name inside a longer line.

    Mirrors improver boundary semantics: adjacent CJK characters count as
    boundaries ("熟练掌握Redis核心" names Redis), while "RedisExporter" does not.
    """
    if not ch or ch.isspace() or ch in _TERM_BOUNDARY_CHARS:
        return True
    return bool(_CJK_CHAR_RE.match(ch))


def _term_appears_bounded(needle: str, haystack: str) -> bool:
    """Boundary-aware term presence (case-insensitive) inside ``haystack``."""
    needle = needle.strip().casefold()
    haystack = haystack.casefold()
    if not needle:
        return False
    start = 0
    while True:
        pos = haystack.find(needle, start)
        if pos == -1:
            return False
        before = haystack[pos - 1] if pos > 0 else ""
        after_pos = pos + len(needle)
        after = haystack[after_pos] if after_pos < len(haystack) else ""
        if _is_term_boundary(before) and _is_term_boundary(after):
            return True
        start = pos + 1


def _skill_entry_covers(source_item: str, candidate_item: str) -> bool:
    """Whether ``candidate_item`` is the source skill or its elaboration.

    "Redis" is covered by "Redis：高可用缓存设计……" (prefix elaboration) and by
    a proficiency-positioned rewrite such as "熟练掌握 Redis 核心数据结构……"
    (name embedded as a whole term); an unrelated entry such as
    "RedisExporter" is not (no term boundary after the bare name).
    """
    source_norm = _normalized(source_item)
    candidate_norm = _normalized(candidate_item)
    if not source_norm:
        return False
    if candidate_norm == source_norm:
        return True
    if candidate_norm.startswith(source_norm) and _skill_detail_boundary(
        candidate_norm[len(source_norm) :]
    ):
        return True
    # Proficiency-first sentence rewrites name the bare technology mid-line.
    # Only single-technology source entries qualify: a category row such as
    # "后端：Java、Kafka" must not count as covered by one sentence about Kafka.
    if any(sep in source_norm for sep in ("、", "：", ":", "，", ",", ";", "；")):
        return False
    return _term_appears_bounded(source_norm, candidate_norm)


def skill_entry_covers(source_item: str, candidate_item: str) -> bool:
    """Public form of :func:`_skill_entry_covers` for cross-module safety nets."""
    return _skill_entry_covers(source_item, candidate_item)


def _row_approval_matches(row_norm: str, approved: set[str]) -> bool:
    """Fuzzy membership for pre-approved rows (AI-phrase scrubbing may edit text).

    Exact normalized match, an injected sub-module label, or high token-set
    overlap with an approved row. Pure substring containment is intentionally
    not enough: a replaced bullet that merely mentions an approved tech must
    still pass the ordinary grounding gates.
    """
    if not row_norm:
        return False
    # Label rows carry a trailing colon ("技术栈：") but the canonical label set
    # stores bare cores ("技术栈"), so compare on the stripped core too.
    label_core = row_norm.rstrip("：:").strip()
    if label_core in _INJECTED_LABEL_NORMS:
        return True
    if not approved:
        return False
    if row_norm in approved:
        return True
    row_tokens = _tokens(row_norm)
    if not row_tokens:
        return False
    for approved_row in approved:
        approved_tokens = _tokens(approved_row)
        if not approved_tokens:
            continue
        overlap = len(row_tokens & approved_tokens) / len(
            row_tokens | approved_tokens
        )
        if overlap >= 0.8:
            return True
    return False

# Source row styles that survive a row merge. "label" is a structural
# sub-module heading （技术栈：/项目亮点：/工作职责： …) that drives bold
# rendering, per-region numbering restart and unnumbered body blocks;
# dropping it flattened every region into one continuous numbered list.
# Merged styles are always taken from the SOURCE row, so widening this set
# cannot let a candidate inject label styles. Appended rows stay "bullet".
_PRESERVED_DESCRIPTION_STYLES = frozenset({"bullet", "plain", "label"})

_ENTRY_FIELDS: dict[str, tuple[str, ...]] = {
    "workExperience": ("company", "title"),
    "education": ("institution", "degree"),
    "personalProjects": ("name", "role"),
    "customItems": ("title", "subtitle"),
}
_PROTECTED_FIELDS: dict[str, tuple[str, ...]] = {
    "workExperience": ("id", "title", "company", "location", "years"),
    "education": ("id", "institution", "degree", "years"),
    "personalProjects": ("id", "name", "role", "years", "github", "website"),
    "customItems": ("id", "title", "subtitle", "location", "years"),
}
# Date-point comparison used to distinguish presentation-only rewrites of
# "years" (e.g. "2016 年 06 月 - 2020 年 09 月" -> "2016.06 - 2020.09")
# from real date edits. Mirrors the numeric/CJK/English forms recognised by
# parser.py's restore_dates_from_markdown — keep the two in sync.
_DATE_ENGLISH_MONTHS: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_DATE_ENGLISH_MONTH_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?"
    r"|Dec(?:ember)?)\.?\s+(\d{4})",
    re.IGNORECASE,
)
# Numeric/CJK points: "2017.09", "2017/9", "2017-09", "2017年09月". The
# trailing guard rejects day components ("2017.09.01") so only year-month
# points are captured here.
_DATE_NUMERIC_RE = re.compile(
    r"(\d{4})\s*[年./-]\s*(0?[1-9]|1[0-2])(?!\d|[./-]\d)(?:\s*月)?"
)
_DATE_BARE_YEAR_RE = re.compile(r"\d{4}")
_DATE_PRESENT_RE = re.compile(
    r"至今|现在|目前|Present|Current|Now|Ongoing", re.IGNORECASE
)


def _date_points(value: Any) -> tuple[tuple[tuple[int, int | None], ...], bool] | None:
    """Parse a years string into ordered ``(year, month)`` points + present flag.

    Returns ``None`` when the string carries no recognisable date point.
    Month precision is preserved in the tuple, so "2016 - 2020" and
    "2016.06 - 2020.09" produce different results.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    points: list[tuple[int, int | None]] = []
    claimed_year_spans: list[tuple[int, int]] = []
    for match in _DATE_ENGLISH_MONTH_RE.finditer(value):
        month = _DATE_ENGLISH_MONTHS[match.group(1)[:3].lower()]
        points.append((int(match.group(2)), month))
        claimed_year_spans.append(match.span(2))
    for match in _DATE_NUMERIC_RE.finditer(value):
        points.append((int(match.group(1)), int(match.group(2))))
        claimed_year_spans.append(match.span(1))
    for match in _DATE_BARE_YEAR_RE.finditer(value):
        if any(start <= match.start() < end for start, end in claimed_year_spans):
            continue
        points.append((int(match.group(0)), None))
    if not points:
        return None
    present = bool(_DATE_PRESENT_RE.search(value))
    return tuple(points), present


def _is_format_only_date_change(source_years: Any, candidate_years: Any) -> bool:
    """Whether two years strings differ only in presentation, never meaning.

    Accepts e.g. "2016 年 06 月 - 2020 年" vs "2016.06 - 2020.09"; rejects
    month precision loss/gain, changed dates, point-count changes and
    present-marker mismatches — those stay protected from the model.
    """
    if not isinstance(source_years, str) or not isinstance(candidate_years, str):
        return False
    if source_years.strip() == candidate_years.strip():
        return False
    source_points = _date_points(source_years)
    candidate_points = _date_points(candidate_years)
    if source_points is None or candidate_points is None:
        return False
    return source_points == candidate_points


_TOKEN_RE = re.compile(r"[\w+#./-]+", re.UNICODE)
_NUMBER_RE = re.compile(
    r"(?<![\w.])(?P<currency>[$€£])?(?P<number>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?P<unit>thousand|million|billion|percent|times|ms|gb|mb|tb|[kmb%x]))?"
    r"(?![A-Za-z])",
    re.IGNORECASE,
)
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "the",
        "to",
        "using",
        "with",
    }
)

# Award/grade levels and rankings in Arabic or Chinese numerals:
# 二等奖 / 第一名 / 三级 / 2等. A swap such as 二等奖 -> 三等奖 bypasses the
# Arabic-numeral filter, so levels get a dedicated line-level guard.
_RANK_RE = re.compile(r"([0-9零〇一二三四五六七八九十百千两]+)\s*(等|名|级|甲)")


def _rank_claims(text: str) -> Counter[str]:
    """Extract level/ranking claims ("二等", "一名", "三级") from a line."""
    return Counter(
        f"{match.group(1)}{match.group(2)}"
        for match in _RANK_RE.finditer(str(text or ""))
    )


def _rank_mutated(source: str, candidate: str) -> bool:
    """Whether a level/ranking was changed or invented.

    Deleting the whole phrase (candidate carries no rank claim) is NOT a
    mutation: a relocation flow may legitimately move the line elsewhere.
    """
    candidate_ranks = _rank_claims(candidate)
    return bool(candidate_ranks) and _rank_claims(source) != candidate_ranks


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _identity(entry: dict[str, Any], section: str) -> tuple[str, ...]:
    entry_id = entry.get("id")
    if isinstance(entry_id, int) and entry_id != 0:
        return ("id", str(entry_id))
    return (
        "fields",
        *(_normalized(entry.get(field)) for field in _ENTRY_FIELDS[section]),
    )


def _field_identity(entry: dict[str, Any], section: str) -> tuple[str, ...] | None:
    identity = tuple(_normalized(entry.get(field)) for field in _ENTRY_FIELDS[section])
    return identity if any(identity) else None


def _matching_source_index(
    candidate: dict[str, Any],
    source_entries: list[dict[str, Any]],
    available: set[int],
    section: str,
) -> int | None:
    candidate_id = candidate.get("id")
    if isinstance(candidate_id, int) and candidate_id != 0:
        for index in sorted(available):
            if source_entries[index].get("id") == candidate_id:
                return index

    candidate_identity = _field_identity(candidate, section)
    if candidate_identity is None:
        return None
    matches = [
        index
        for index in sorted(available)
        if _field_identity(source_entries[index], section) == candidate_identity
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    candidate_description = candidate.get("description")
    candidate_text = (
        " ".join(str(row) for row in candidate_description)
        if isinstance(candidate_description, list)
        else str(candidate_description or "")
    )
    return max(
        matches,
        key=lambda index: (
            _similarity(
                " ".join(
                    str(row)
                    for row in source_entries[index].get("description", [])
                )
                if isinstance(source_entries[index].get("description"), list)
                else str(source_entries[index].get("description") or ""),
                candidate_text,
            ),
            -index,
        ),
    )


def _tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in _TOKEN_RE.findall(text)
        if len(token) > 1 and token.casefold() not in _STOP_WORDS
    }


def _similarity(left: str, right: str) -> float:
    left_normalized = _normalized(left)
    right_normalized = _normalized(right)
    if left_normalized == right_normalized:
        return 1.0
    left_tokens = _tokens(left_normalized)
    right_tokens = _tokens(right_normalized)
    overlap = len(left_tokens & right_tokens) / max(
        1, max(len(left_tokens), len(right_tokens))
    )
    sequence = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    if left_tokens < right_tokens or right_tokens < left_tokens:
        # Character similarity must not hide a material expansion or truncation
        # when every token on the shorter side happens to match.
        return overlap * sequence
    return max(overlap, sequence)


def _is_date_like_number(text: str, match: re.Match[str]) -> bool:
    """Return whether a bare four-digit number appears in date context."""
    prefix = text[max(0, match.start() - 24) : match.start()].casefold()
    suffix = text[match.end() : min(len(text), match.end() + 16)].casefold()
    month = (
        r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
        r"dec(?:ember)?)"
    )
    return bool(
        re.search(rf"\b{month}\s*$", prefix)
        or (
            re.search(
                r"\b(?:in|since|during|from|until|through|between)\s*$", prefix
            )
            and re.match(r"^\s*(?:$|[,.;:)])", suffix)
        )
        or re.search(r"\b\d{4}\s*[-–—/]\s*$", prefix)
        or re.match(r"^\s*[-–—/]\s*(?:\d{4}|present|current)\b", suffix)
    )


def _numeric_claims(text: str) -> Counter[str]:
    """Extract metric-like numeric claims (``%:40``, ``$:1200``, ``5``, ...)."""
    claims: Counter[str] = Counter()
    for match in _NUMBER_RE.finditer(text):
        raw_number = match.group("number").replace(",", "")
        unit = (match.group("unit") or "").casefold()
        prefix = text[max(0, match.start() - 16) : match.start()].casefold()
        if re.search(r"(?:python|node(?:\.js)?|java|version|v)\s*$", prefix):
            continue
        if not unit and not match.group("currency"):
            try:
                integer = int(raw_number)
            except ValueError:
                integer = 0
            if 1900 <= integer <= 2100 and _is_date_like_number(text, match):
                continue
        try:
            value = Decimal(raw_number)
        except InvalidOperation:
            continue
        scale = {
            "k": 1_000,
            "thousand": 1_000,
            "m": 1_000_000,
            "million": 1_000_000,
            "b": 1_000_000_000,
            "billion": 1_000_000_000,
        }.get(unit, 1)
        value *= scale
        normalized_value = format(value.normalize(), "f")
        kind = (
            match.group("currency")
            or ("%" if unit in {"%", "percent"} else "")
            or ("x" if unit in {"x", "times"} else "")
            or (unit if unit in {"ms", "gb", "mb", "tb"} else "")
        )
        claims[f"{kind}:{normalized_value}"] += 1
    return claims


def _novel_numbers(
    source: str,
    candidate: str,
    evidence_numbers: Counter[str] | None = None,
) -> bool:
    source_numbers = _numeric_claims(source)
    if evidence_numbers:
        source_numbers = source_numbers + evidence_numbers
    candidate_numbers = _numeric_claims(candidate)
    return any(
        count > source_numbers[value] for value, count in candidate_numbers.items()
    )


def _evidence_context(
    extra_evidence: str | None,
) -> tuple[set[str] | None, Counter[str] | None]:
    """Tokenize an extra grounding source (e.g. original upload markdown)."""
    if not extra_evidence or not extra_evidence.strip():
        return None, None
    return _tokens(extra_evidence), _numeric_claims(extra_evidence)


def _grounded_in_evidence(
    candidate_row: str,
    evidence_tokens: set[str] | None,
    evidence_numbers: Counter[str] | None,
) -> bool:
    """Whether a rewritten row is supported by the extra evidence text."""
    if evidence_tokens is None:
        return False
    if _novel_numbers("", candidate_row, evidence_numbers):
        return False
    row_tokens = _tokens(candidate_row)
    if not row_tokens:
        return True
    coverage = len(row_tokens & evidence_tokens) / len(row_tokens)
    return coverage >= _GROUNDING_REVIEW_THRESHOLD


def _normalized_candidate_rows(value: Any) -> list[str]:
    """Mirror ResumeData's newline and bullet cleanup before preservation."""
    if not isinstance(value, list):
        return []
    rows: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        for raw_line in re.split(r"\r?\n+", item):
            line = re.sub(r"^\s*(?:[-*•‣◦▪▫]+|\d+[.)])\s*", "", raw_line).strip()
            if line:
                rows.append(line)
    return rows


def _best_source_row(
    candidate: str,
    source_rows: list[str],
    available: set[int],
) -> tuple[int, float] | None:
    if not available:
        return None
    scored = [
        (_similarity(source_rows[index], candidate), index) for index in available
    ]
    score, index = max(scored, key=lambda item: (item[0], -item[1]))
    return index, score


def _row_relocated(source_row: str, relocated_texts: set[str]) -> bool:
    """Whether a dropped source row was moved (verbatim) into another section.

    Matched by token coverage against the union of relocated item texts, so a
    label prefix ("奖项:") or splitting one line into two items still counts.
    Rows that are only partially covered are kept (duplication beats loss).
    """
    if not relocated_texts:
        return False
    row_tokens = _tokens(source_row)
    if not row_tokens:
        return False
    covered = sum(
        1 for token in row_tokens if any(token in item for item in relocated_texts)
    )
    return covered / len(row_tokens) >= 0.7


def _candidate_style(
    candidate_entry: dict[str, Any],
    candidate_index: int,
) -> str | None:
    """Candidate style at a normalized-row index when metadata is trustworthy.

    Style edits are only honoured when the model kept every description row as
    a single aligned string with a one-to-one styles array; any split/filter/
    dropout means indices no longer line up and styles must be ignored.
    """
    raw_rows = candidate_entry.get("description")
    raw_styles = candidate_entry.get("descriptionStyles")
    if not isinstance(raw_rows, list) or not isinstance(raw_styles, list):
        return None
    if len(raw_styles) != len(raw_rows) or candidate_index >= len(raw_styles):
        return None
    if any(not isinstance(row, str) for row in raw_rows):
        return None
    # Every raw row must normalize to exactly one surviving string.
    normalized = _normalized_candidate_rows(raw_rows)
    if len(normalized) != len(raw_rows):
        return None
    style = raw_styles[candidate_index]
    return style if style in ("plain", "bullet") else None


def _approved_row_style(
    candidate_entry: dict[str, Any],
    candidate_index: int,
    row_norm: str,
) -> str:
    """Style for a pre-approved inserted row; labels only via canonical set."""
    if row_norm.rstrip("：:").strip() in _INJECTED_LABEL_NORMS:
        return "label"
    candidate_style = _candidate_style(candidate_entry, candidate_index)
    return candidate_style or "bullet"


def _merge_description_rows(
    source_entry: dict[str, Any],
    candidate_entry: dict[str, Any],
    *,
    allow_review_claims: bool,
    allow_appended_rows: bool,
    allow_style_edits: bool = False,
    evidence_tokens: set[str] | None = None,
    evidence_numbers: Counter[str] | None = None,
    relocated_rows: set[str] | None = None,
    approved_rows: frozenset[str] | None = None,
) -> tuple[list[str], list[str]]:
    source_rows = source_entry.get("description")
    candidate_rows = candidate_entry.get("description")
    if not isinstance(source_rows, list):
        return [], []
    source_text = " ".join(str(row) for row in source_rows)
    candidate_list = _normalized_candidate_rows(candidate_rows)
    source_styles = source_entry.get("descriptionStyles")
    styles = source_styles if isinstance(source_styles, list) else []
    available = set(range(len(source_rows)))
    merged_rows: list[str] = []
    merged_styles: list[str] = []
    # Row insertion is opt-in: when no approved set was supplied the walk below
    # is byte-identical to the previous prefix-pairing behavior.
    approval_active = approved_rows is not None
    approved = approved_rows or frozenset()

    paired = 0
    tail_candidates: list[str] = []
    for candidate_index, raw_candidate in enumerate(candidate_list):
        if not isinstance(raw_candidate, str):
            continue
        candidate_norm = _normalized(raw_candidate)
        # The deterministic insert_row gate forbids digits. A later LLM pass
        # (keyword injection) can rewrite an approved row; if it smuggles in a
        # number, that row loses its exemption and goes through ordinary gates.
        digit_free_approval = (
            candidate_norm in _INJECTED_LABEL_NORMS
            or not _ANY_DIGIT_RE.search(raw_candidate)
        )
        if (
            approval_active
            and digit_free_approval
            and _row_approval_matches(candidate_norm, approved)
        ):
            # Pre-verified inserted row (project 技术栈 / 项目亮点 content or an
            # injected canonical label): emitted at the model's position and
            # bypasses the grounding/novel-number gates it already passed
            # deterministically in apply_diffs.
            merged_rows.append(raw_candidate)
            merged_styles.append(
                _approved_row_style(candidate_entry, candidate_index, candidate_norm)
            )
            # Normally approved rows do not consume a source row. But if the
            # candidate happens to have REUSED an existing row verbatim (e.g.
            # an approved stack name matching a pre-existing source bullet),
            # mark that exact source row consumed so it is not force-restored.
            exact_source = next(
                (
                    idx
                    for idx in available
                    if _normalized(source_rows[idx]) == candidate_norm
                ),
                None,
            )
            if exact_source is not None:
                available.remove(exact_source)
            continue
        if paired < len(source_rows):
            match = _best_source_row(raw_candidate, source_rows, available)
            if match is None:
                break
            source_index, score = match
            candidate_row = raw_candidate
            source_row = str(source_rows[source_index])
            requires_restore = (
                not candidate_row.strip()
                or _novel_numbers(source_text, candidate_row, evidence_numbers)
                or _rank_mutated(source_row, candidate_row)
                or (
                    not allow_review_claims
                    and score < _GROUNDING_REVIEW_THRESHOLD
                    and not _grounded_in_evidence(
                        candidate_row, evidence_tokens, evidence_numbers
                    )
                )
            )
            if not candidate_row.strip() and candidate_index in available:
                source_index = candidate_index
                source_row = str(source_rows[source_index])
            available.remove(source_index)
            if requires_restore:
                candidate_row = source_row
            source_style = (
                styles[source_index]
                if source_index < len(styles)
                and styles[source_index] in _PRESERVED_DESCRIPTION_STYLES
                else "bullet"
            )
            bound_style = source_style
            # Explicit formatting requests ("turn the paragraphs under a nested
            # head into an ordered list") may switch a kept row between plain and
            # bullet. Label styles are never accepted from the candidate, and a
            # row whose text had to be restored also keeps its source style.
            if (
                allow_style_edits
                and not requires_restore
                and source_style in ("plain", "bullet")
            ):
                candidate_style = _candidate_style(candidate_entry, candidate_index)
                if candidate_style is not None:
                    bound_style = candidate_style
            merged_rows.append(candidate_row)
            merged_styles.append(bound_style)
            paired += 1
        else:
            tail_candidates.append(raw_candidate)

    for source_index in sorted(available):
        source_row = str(source_rows[source_index])
        if relocated_rows is not None and _row_relocated(source_row, relocated_rows):
            continue
        merged_rows.append(source_row)
        merged_styles.append(
            styles[source_index]
            if source_index < len(styles)
            and styles[source_index] in _PRESERVED_DESCRIPTION_STYLES
            else "bullet"
        )
    if allow_appended_rows:
        for candidate_row in tail_candidates:
            match = _best_source_row(
                candidate_row, source_rows, set(range(len(source_rows)))
            )
            grounded = match is not None and match[1] >= _GROUNDING_REVIEW_THRESHOLD
            evidence_grounded = _grounded_in_evidence(
                candidate_row, evidence_tokens, evidence_numbers
            )
            if _novel_numbers(source_text, candidate_row, evidence_numbers) or (
                not allow_review_claims and not grounded and not evidence_grounded
            ):
                continue
            merged_rows.append(candidate_row)
            merged_styles.append("bullet")
    return merged_rows, merged_styles


def merge_row_provenance(
    source_entry: dict[str, Any],
    finalized_entry: dict[str, Any],
) -> tuple[dict[int, int], list[int]]:
    """Map source description rows to their position in a finalized entry.

    Replays the matching used by :func:`_merge_description_rows` (a paired
    prefix in candidate order, unmatched source rows restored in index
    order, candidate-only rows appended last) and returns
    ``({source_index: finalized_index}, appended_finalized_indices)``. The
    map covers every source row because finalized output never drops one;
    the appended list holds finalized rows with no source counterpart. Used
    by fine-tune's label-region overlay to replace rows in place.
    """
    source_rows = source_entry.get("description")
    finalized_rows = finalized_entry.get("description")
    if not isinstance(source_rows, list) or not isinstance(finalized_rows, list):
        return {}, []
    candidate_list = _normalized_candidate_rows(finalized_rows)
    available = set(range(len(source_rows)))
    provenance: dict[int, int] = {}
    output_position = 0
    for candidate_index, raw_candidate in enumerate(
        candidate_list[: len(source_rows)]
    ):
        if not isinstance(raw_candidate, str):
            continue
        if not raw_candidate.strip() and candidate_index in available:
            source_index = candidate_index
        else:
            match = _best_source_row(raw_candidate, source_rows, available)
            if match is None:
                break
            source_index = match[0]
        available.remove(source_index)
        provenance[source_index] = output_position
        output_position += 1
    for source_index in sorted(available):
        provenance[source_index] = output_position
        output_position += 1
    assigned = set(provenance.values())
    appended = [
        index
        for index in range(len(finalized_rows))
        if index not in assigned
    ]
    return provenance, appended


def _description_contract_preserved(
    source_entry: dict[str, Any],
    candidate_entry: dict[str, Any],
    *,
    allow_appended_rows: bool = False,
    approved_rows: set[str] | None = None,
) -> bool:
    source_rows = source_entry.get("description")
    candidate_rows = candidate_entry.get("description")
    if not isinstance(source_rows, list):
        return True
    if not isinstance(candidate_rows, list) or len(candidate_rows) < len(source_rows):
        return False
    if not allow_appended_rows and len(candidate_rows) != len(source_rows):
        return False
    approval_active = approved_rows is not None
    approved = approved_rows or set()
    if "descriptionStyles" not in source_entry:
        # Without style metadata the structural contract is just "every source
        # row survives (possibly reordered), plus optional inserted rows".
        available = set(range(len(source_rows)))
        for candidate_row in candidate_rows:
            if not isinstance(candidate_row, str):
                return False
            candidate_norm = _normalized(candidate_row)
            if (
                approval_active
                and not _ANY_DIGIT_RE.search(candidate_row)
                and _row_approval_matches(candidate_norm, approved)
            ):
                # A label the pipeline auto-creates can coincide with a source
                # label; consume that exact source row so it isn't reported lost.
                exact = next(
                    (
                        idx
                        for idx in available
                        if _normalized(source_rows[idx]) == candidate_norm
                    ),
                    None,
                )
                if exact is not None:
                    available.remove(exact)
                continue
            match = _best_source_row(candidate_row, source_rows, available)
            if match is None:
                if not allow_appended_rows:
                    return False
                continue
            available.remove(match[0])
        return not available
    source_styles = source_entry.get("descriptionStyles")
    candidate_styles = candidate_entry.get("descriptionStyles")
    if not isinstance(source_styles, list) or not isinstance(candidate_styles, list):
        return False
    if len(candidate_styles) != len(candidate_rows):
        return False

    available = set(range(len(source_rows)))
    for candidate_index, candidate_row in enumerate(candidate_rows):
        if not isinstance(candidate_row, str):
            return False
        candidate_norm = _normalized(candidate_row)
        # An insert_row-created sub-module row has no source counterpart; it
        # still must carry a valid aligned style, which the length check covers.
        if (
            approval_active
            and not _ANY_DIGIT_RE.search(candidate_row)
            and _row_approval_matches(candidate_norm, approved)
        ):
            # An approved row equal to an available source row (typically a
            # pre-existing label) consumes it, style included, so the source
            # row is not reported as lost.
            exact_source = next(
                (
                    idx
                    for idx in available
                    if _normalized(source_rows[idx]) == candidate_norm
                    and (
                        source_styles[idx]
                        if idx < len(source_styles)
                        and source_styles[idx] in _PRESERVED_DESCRIPTION_STYLES
                        else "bullet"
                    )
                    == candidate_styles[candidate_index]
                ),
                None,
            )
            if exact_source is not None:
                available.remove(exact_source)
            continue
        match = _best_source_row(candidate_row, source_rows, available)
        if match is None:
            # Every source row must survive; only genuine tail appends (never
            # mid-list) were allowed by the legacy prefix contract.
            if not allow_appended_rows or available:
                return False
            continue
        source_index, _ = match
        available.remove(source_index)
        expected_style = (
            source_styles[source_index]
            if source_index < len(source_styles)
            and source_styles[source_index] in _PRESERVED_DESCRIPTION_STYLES
            else "bullet"
        )
        if candidate_styles[candidate_index] != expected_style:
            return False
    return not available


def _merge_entries(
    source_entries: Any,
    candidate_entries: Any,
    section: str,
    *,
    allow_review_claims: bool,
    allow_appended_rows: bool,
    allow_style_edits: bool = False,
    evidence_tokens: set[str] | None = None,
    evidence_numbers: Counter[str] | None = None,
    relocated_rows: set[str] | None = None,
    approved_rows: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(source_entries, list):
        return []
    source_dicts = [entry for entry in source_entries if isinstance(entry, dict)]
    if not source_dicts:
        return []
    result: list[dict[str, Any]] = []
    available = set(range(len(source_dicts)))
    candidates = candidate_entries if isinstance(candidate_entries, list) else []
    for candidate_entry in candidates:
        if not isinstance(candidate_entry, dict):
            continue
        source_index = _matching_source_index(
            candidate_entry,
            source_dicts,
            available,
            section,
        )
        if source_index is None:
            continue
        available.remove(source_index)
        source_entry = source_dicts[source_index]
        merged = copy.deepcopy(candidate_entry)
        for field in _PROTECTED_FIELDS[section]:
            # A presentation-only date rewrite ("2016 年 06 月" -> "2016.06")
            # carries the exact same date points, so it is safe to honour the
            # candidate; real date edits and precision loss stay reverted.
            if field == "years" and _is_format_only_date_change(
                source_entry.get("years"), merged.get("years")
            ):
                continue
            if field in source_entry:
                merged[field] = copy.deepcopy(source_entry[field])
            else:
                merged.pop(field, None)
        if section != "education":
            has_style_metadata = (
                "descriptionStyles" in source_entry or "descriptionStyles" in merged
            )
            rows, styles = _merge_description_rows(
                source_entry,
                merged,
                allow_review_claims=allow_review_claims,
                allow_appended_rows=allow_appended_rows,
                allow_style_edits=allow_style_edits,
                evidence_tokens=evidence_tokens,
                evidence_numbers=evidence_numbers,
                relocated_rows=relocated_rows,
                approved_rows=approved_rows,
            )
            merged["description"] = rows
            if has_style_metadata:
                merged["descriptionStyles"] = styles
            else:
                merged.pop("descriptionStyles", None)
        else:
            source_description = source_entry.get("description")
            candidate_description = merged.get("description")
            if (
                not isinstance(source_description, str)
                or not isinstance(candidate_description, str)
                or not candidate_description.strip()
            ):
                merged["description"] = copy.deepcopy(source_description)
            elif isinstance(source_description, str) and (
                _novel_numbers(
                    source_description,
                    candidate_description,
                    evidence_numbers,
                )
                or _rank_mutated(source_description, candidate_description)
            ):
                merged["description"] = source_description
            elif (
                isinstance(source_description, str)
                and not allow_review_claims
                and _similarity(source_description, candidate_description)
                < _GROUNDING_REVIEW_THRESHOLD
                and not _grounded_in_evidence(
                    candidate_description, evidence_tokens, evidence_numbers
                )
            ):
                merged["description"] = source_description
        result.append(merged)

    for source_index in sorted(available):
        result.append(copy.deepcopy(source_dicts[source_index]))
    return result


def _grounded_extra_items(
    source_items: list[str],
    candidate_items: list[str],
    evidence_tokens: set[str] | None,
    evidence_numbers: Counter[str] | None,
) -> list[str]:
    """Candidate list items absent from source but supported by evidence text.

    Used for cross-section relocation (an award line moved out of an education
    description is not an invented fact when the original text contains it).
    """
    if evidence_tokens is None:
        return []
    remaining = Counter(_normalized(item) for item in source_items)
    extras: list[str] = []
    for item in candidate_items:
        key = _normalized(item)
        if remaining[key] > 0:
            remaining[key] -= 1
            continue
        if _grounded_in_evidence(item, evidence_tokens, evidence_numbers):
            extras.append(item)
    return extras


def _merge_additional(
    source: Any,
    candidate: Any,
    *,
    allowed_extra: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    source_dict = source if isinstance(source, dict) else {}
    candidate_dict = candidate if isinstance(candidate, dict) else {}
    result: dict[str, list[str]] = {}
    for field in ("technicalSkills", "languages", "certificationsTraining", "awards"):
        source_items = [
            item for item in source_dict.get(field, []) if isinstance(item, str)
        ]
        candidate_items = [
            item for item in candidate_dict.get(field, []) if isinstance(item, str)
        ]
        if field != "technicalSkills":
            remaining_source_items = Counter(_normalized(item) for item in source_items)
            allowed_keys = {
                _normalized(item)
                for item in (allowed_extra or {}).get(field, [])
                if isinstance(item, str)
            }
            preserved_candidate_items: list[str] = []
            for item in candidate_items:
                key = _normalized(item)
                if remaining_source_items[key] > 0:
                    preserved_candidate_items.append(item)
                    remaining_source_items[key] -= 1
                elif key in allowed_keys:
                    preserved_candidate_items.append(item)
            candidate_items = preserved_candidate_items
        remaining_candidate_items = Counter(
            _normalized(item) for item in candidate_items
        )
        result[field] = list(candidate_items)
        for item in source_items:
            key = _normalized(item)
            if remaining_candidate_items[key] > 0:
                remaining_candidate_items[key] -= 1
            elif field == "technicalSkills" and any(
                _skill_entry_covers(item, candidate)
                for candidate in candidate_items
                if isinstance(candidate, str)
            ):
                # The bare skill line was expanded into a verified
                # "name: capability detail" entry — keep the elaboration,
                # do not re-append the bare name.
                continue
            else:
                result[field].append(item)
    return result


def _merge_custom_sections(
    source: Any,
    candidate: Any,
    *,
    allow_review_claims: bool,
    allow_appended_rows: bool,
    allow_style_edits: bool = False,
    evidence_tokens: set[str] | None = None,
    evidence_numbers: Counter[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    candidate_dict = candidate if isinstance(candidate, dict) else {}
    result: dict[str, Any] = {}
    for key, source_section in source.items():
        if not isinstance(source_section, dict):
            result[key] = copy.deepcopy(source_section)
            continue
        candidate_section = candidate_dict.get(key)
        if not isinstance(candidate_section, dict):
            result[key] = copy.deepcopy(source_section)
            continue
        if source_section.get("sectionType") != "itemList":
            result[key] = copy.deepcopy(source_section)
            continue
        merged_section = copy.deepcopy(candidate_section)
        merged_section["sectionType"] = source_section.get("sectionType")
        merged_section["items"] = _merge_entries(
            source_section.get("items"),
            candidate_section.get("items"),
            "customItems",
            allow_review_claims=allow_review_claims,
            allow_appended_rows=allow_appended_rows,
            allow_style_edits=allow_style_edits,
            evidence_tokens=evidence_tokens,
            evidence_numbers=evidence_numbers,
        )
        result[key] = merged_section
    return result


def finalize_ai_resume(
    source: dict[str, Any],
    candidate: dict[str, Any],
    *,
    allow_review_claims: bool = True,
    allow_appended_rows: bool = False,
    extra_evidence: str | None = None,
    allow_relocation: bool = False,
    allow_style_edits: bool = False,
    approved_appended_rows: set[str] | None = None,
) -> dict[str, Any]:
    """Return a non-mutating AI result that preserves the source contract.

    Weakly grounded rewrites remain when ``allow_review_claims`` is true so a
    preview can present them for explicit confirmation. Definite new metrics,
    extra rows, missing sections and identity drift are always repaired.

    ``extra_evidence`` supplies an additional grounding text (e.g. the
    resume's original upload markdown). Metrics and phrasings present in that
    text are treated as source evidence, so content the parser dropped can be
    restored. When omitted/empty the behavior is byte-identical to the
    structured-source-only policy.

    ``allow_style_edits`` (fine-tune only) lets a kept description row switch
    between "plain" and "bullet" to honour explicit formatting requests
    (paragraphs ↔ ordered list). Label styles are never taken from the
    candidate; defaults to false, leaving all other flows byte-identical.

    ``approved_appended_rows`` (tailor diff flow only) carries normalized text
    of rows the deterministic diff applier already verified (project 技术栈 /
    项目亮点 insertions, plus injected canonical labels). Such rows are kept at
    the model's position with their candidate style instead of passing the
    generic grounding gate. When ``None`` (every other flow) behavior is
    byte-identical to the prefix-pairing merge.
    """
    evidence_tokens, evidence_numbers = _evidence_context(extra_evidence)
    approved_rows = frozenset(approved_appended_rows or set())
    result = copy.deepcopy(candidate) if isinstance(candidate, dict) else {}
    result["personalInfo"] = copy.deepcopy(source.get("personalInfo", {}))
    source_summary = source.get("summary")
    candidate_summary = result.get("summary")
    if isinstance(source_summary, str):
        if not isinstance(candidate_summary, str) or not candidate_summary.strip():
            result["summary"] = source_summary
        elif _novel_numbers(
            source_summary, candidate_summary, evidence_numbers
        ) or _rank_mutated(source_summary, candidate_summary) or (
            not allow_review_claims
            and _similarity(source_summary, candidate_summary)
            < _GROUNDING_REVIEW_THRESHOLD
            and not _grounded_in_evidence(
                candidate_summary, evidence_tokens, evidence_numbers
            )
        ):
            result["summary"] = source_summary

    # Cross-section relocation (fine-tune only): candidate awards/certs/
    # languages that don't exist in source ARE kept when grounded in the
    # evidence text (original upload or the structured descriptions), and
    # their texts license dropping the matching source description rows.
    relocated_rows: set[str] = set()
    allowed_extra: dict[str, list[str]] | None = None
    if allow_relocation and evidence_tokens is not None:
        source_additional = source.get("additional")
        candidate_additional = result.get("additional")
        if isinstance(source_additional, dict) and isinstance(
            candidate_additional, dict
        ):
            allowed_extra = {}
            for field in ("languages", "certificationsTraining", "awards"):
                source_items = [
                    item
                    for item in source_additional.get(field, [])
                    if isinstance(item, str)
                ]
                candidate_items = [
                    item
                    for item in candidate_additional.get(field, [])
                    if isinstance(item, str)
                ]
                extras = _grounded_extra_items(
                    source_items,
                    candidate_items,
                    evidence_tokens,
                    evidence_numbers,
                )
                allowed_extra[field] = extras
                relocated_rows.update(_normalized(item) for item in extras)

    for section in ("workExperience", "education", "personalProjects"):
        result[section] = _merge_entries(
            source.get(section),
            result.get(section),
            section,
            allow_review_claims=allow_review_claims,
            allow_appended_rows=allow_appended_rows,
            allow_style_edits=allow_style_edits,
            evidence_tokens=evidence_tokens,
            evidence_numbers=evidence_numbers,
            relocated_rows=relocated_rows if allow_relocation else None,
            # insert_row targets project sub-modules only; keep the exemption
            # scoped so identical text in other sections keeps its source gates.
            approved_rows=(
                approved_rows
                if approved_appended_rows is not None and section == "personalProjects"
                else None
            ),
        )
    result["additional"] = _merge_additional(
        source.get("additional"),
        result.get("additional"),
        allowed_extra=allowed_extra,
    )
    result["customSections"] = _merge_custom_sections(
        source.get("customSections"),
        result.get("customSections"),
        allow_review_claims=allow_review_claims,
        allow_appended_rows=allow_appended_rows,
        allow_style_edits=allow_style_edits,
        evidence_tokens=evidence_tokens,
        evidence_numbers=evidence_numbers,
    )
    if "sectionMeta" in source:
        result["sectionMeta"] = copy.deepcopy(source["sectionMeta"])
    return result


def _entry_map(
    entries: Any, section: str
) -> dict[tuple[str, ...], list[dict[str, Any]]]:
    result: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                result[_identity(entry, section)].append(entry)
    return result


def _entry_bucket_violation(
    source_entries: list[dict[str, Any]],
    candidate_entries: list[dict[str, Any]],
    section: str,
    *,
    allow_appended_rows: bool,
    approved_rows: set[str] | None = None,
) -> str | None:
    """Validate one identity bucket using the finalizer's content matching."""
    available = set(range(len(source_entries)))
    for candidate_entry in candidate_entries:
        source_index = _matching_source_index(
            candidate_entry, source_entries, available, section
        )
        if source_index is None:
            return "identity"
        available.remove(source_index)
        source_entry = source_entries[source_index]
        if any(
            field in source_entry
            and source_entry.get(field) != candidate_entry.get(field)
            and not (
                field == "years"
                and _is_format_only_date_change(
                    source_entry.get(field), candidate_entry.get(field)
                )
            )
            for field in _PROTECTED_FIELDS[section]
        ):
            return "identity"
        if not _description_contract_preserved(
            source_entry,
            candidate_entry,
            allow_appended_rows=allow_appended_rows,
            approved_rows=approved_rows,
        ):
            return "descriptions"
    return None


def validate_confirmed_resume(
    source: dict[str, Any],
    candidate: dict[str, Any],
    *,
    allow_appended_rows: bool = False,
    approved_project_rows: set[str] | None = None,
) -> list[str]:
    """Return stable source-contract violation codes for a confirm payload.

    ``approved_project_rows`` holds normalized insert_row texts (plus any
    auto-created sub-module labels) bound to the server-registered preview;
    project description rows in that set need no source counterpart. It is
    ignored outside ``personalProjects``.
    """
    violations: list[str] = []
    if (
        isinstance(source.get("summary"), str)
        and source["summary"].strip()
        and not _normalized(candidate.get("summary"))
    ):
        violations.append("summary")

    for section in ("workExperience", "education", "personalProjects"):
        source_map = _entry_map(source.get(section), section)
        candidate_map = _entry_map(candidate.get(section), section)
        if Counter({key: len(value) for key, value in source_map.items()}) != Counter(
            {key: len(value) for key, value in candidate_map.items()}
        ):
            violations.append(f"{section}.entries")
            continue
        for key, source_entries in source_map.items():
            candidate_entries = candidate_map[key]
            violation = _entry_bucket_violation(
                source_entries,
                candidate_entries,
                section,
                allow_appended_rows=allow_appended_rows,
                approved_rows=(
                    approved_project_rows if section == "personalProjects" else None
                ),
            )
            if violation is not None:
                violations.append(f"{section}.{violation}")

    source_custom = source.get("customSections")
    candidate_custom = candidate.get("customSections")
    if isinstance(source_custom, dict):
        candidate_custom_dict = (
            candidate_custom if isinstance(candidate_custom, dict) else {}
        )
        if set(source_custom) - set(candidate_custom_dict):
            violations.append("customSections")
        for key, source_section in source_custom.items():
            candidate_section = candidate_custom_dict.get(key)
            if not isinstance(source_section, dict) or not isinstance(
                candidate_section, dict
            ):
                continue
            if source_section.get("sectionType") != candidate_section.get(
                "sectionType"
            ):
                violations.append(f"customSections.{key}.sectionType")
                continue
            if source_section.get("sectionType") != "itemList":
                source_value = source_section.get("strings", source_section.get("text"))
                candidate_value = candidate_section.get(
                    "strings", candidate_section.get("text")
                )
                if source_value != candidate_value:
                    violations.append(f"customSections.{key}.content")
                continue
            source_map = _entry_map(source_section.get("items"), "customItems")
            candidate_map = _entry_map(candidate_section.get("items"), "customItems")
            if Counter(
                {identity: len(entries) for identity, entries in source_map.items()}
            ) != Counter(
                {identity: len(entries) for identity, entries in candidate_map.items()}
            ):
                violations.append(f"customSections.{key}.entries")
                continue
            for identity, source_entries in source_map.items():
                violation = _entry_bucket_violation(
                    source_entries,
                    candidate_map[identity],
                    "customItems",
                    allow_appended_rows=allow_appended_rows,
                )
                if violation is not None:
                    violations.append(f"customSections.{key}.{violation}")

    source_additional = source.get("additional")
    candidate_additional = candidate.get("additional")
    if isinstance(source_additional, dict):
        candidate_dict = (
            candidate_additional if isinstance(candidate_additional, dict) else {}
        )
        for field in (
            "technicalSkills",
            "languages",
            "certificationsTraining",
            "awards",
        ):
            source_raw = [
                item
                for item in source_additional.get(field, [])
                if isinstance(item, str)
            ]
            candidate_raw = [
                item
                for item in candidate_dict.get(field, [])
                if isinstance(item, str)
            ]
            if field == "technicalSkills":
                # A bare source skill ("Redis") survives as an elaboration
                # ("Redis：高可用缓存……"), so coverage is prefix-plus-boundary
                # rather than exact equality. Extras stay allowed for skills.
                missing = Counter(
                    _normalized(item)
                    for item in source_raw
                    if not any(
                        _skill_entry_covers(item, candidate)
                        for candidate in candidate_raw
                    )
                )
                extras = Counter()
            else:
                source_items = Counter(_normalized(item) for item in source_raw)
                candidate_items = Counter(_normalized(item) for item in candidate_raw)
                missing = source_items - candidate_items
                extras = candidate_items - source_items
            if missing or extras:
                violations.append(f"additional.{field}")
    return list(dict.fromkeys(violations))


def approved_preview_project_rows(
    source: dict[str, Any], candidate: dict[str, Any]
) -> set[str]:
    """Collect insert_row-created project rows in a hash-bound preview payload.

    Confirm payloads are bound to a server-registered preview hash, so every
    extra project row was produced by this pipeline. Re-deriving the approval
    set structurally (rather than trusting client metadata) lets mid-list
    技术栈 / 项目亮点 rows survive finalize exactly as they did at preview:

    - a canonical sub-module label the pipeline auto-created, or
    - a digit-free extra row positioned inside a labeled tech-stack or
      highlight region in the candidate; stack rows additionally satisfy the
      same bare-name restrictions enforced by apply_diffs.

    Rows in duty/background regions and unlabeled rows are NOT approved here:
    ordinary append bullets keep going through the standard grounding gate.
    """
    approved: set[str] = set()
    source_entries_raw = source.get("personalProjects")
    candidate_entries_raw = candidate.get("personalProjects")
    if not isinstance(source_entries_raw, list) or not isinstance(
        candidate_entries_raw, list
    ):
        return approved
    source_entries = [entry for entry in source_entries_raw if isinstance(entry, dict)]
    available = set(range(len(source_entries)))
    for candidate_entry in candidate_entries_raw:
        if not isinstance(candidate_entry, dict):
            continue
        source_index = _matching_source_index(
            candidate_entry, source_entries, available, "personalProjects"
        )
        if source_index is None:
            continue
        available.remove(source_index)
        source_rows = _normalized_candidate_rows(
            source_entries[source_index].get("description")
        )
        source_row_norms = {_normalized(row) for row in source_rows}

        raw_rows = candidate_entry.get("description")
        if not isinstance(raw_rows, list):
            continue
        candidate_rows = _normalized_candidate_rows(raw_rows)
        styles = candidate_entry.get("descriptionStyles")
        styles = styles if isinstance(styles, list) else []
        active_region: str | None = None
        for index, row in enumerate(candidate_rows):
            if not isinstance(row, str):
                continue
            core = row.strip().rstrip("：:").strip().casefold()
            style = styles[index] if index < len(styles) else None
            is_label = style != "plain" and (
                core in _REGION_STACK_LABEL_NORMS
                or core in _REGION_HIGHLIGHT_LABEL_NORMS
                or core in _REGION_OTHER_LABEL_NORMS
            )
            if is_label:
                if core in _REGION_STACK_LABEL_NORMS:
                    active_region = "tech_stack"
                elif core in _REGION_HIGHLIGHT_LABEL_NORMS:
                    active_region = "highlight"
                else:
                    active_region = None
                if core in _INJECTED_LABEL_NORMS:
                    row_norm = _normalized(row)
                    if row_norm not in source_row_norms:
                        approved.add(row_norm)
                continue
            row_norm = _normalized(row)
            if row_norm in source_row_norms or _ANY_DIGIT_RE.search(row):
                continue
            if active_region == "tech_stack" and (
                len(row) <= 40 and not any(ch in row for ch in "：:、,，;；")
            ):
                approved.add(row_norm)
            elif active_region == "highlight":
                approved.add(row_norm)
    return approved


def _grounding_warning(path: str) -> str:
    return f"{GROUNDING_REVIEW_CODE}: Review {path} against the source resume."


def _entry_grounding_warnings(
    source_entries: Any,
    candidate_entries: Any,
    section: str,
    path_prefix: str,
    evidence_tokens: set[str] | None = None,
    evidence_numbers: Counter[str] | None = None,
) -> list[str]:
    warnings: list[str] = []
    if not isinstance(source_entries, list) or not isinstance(candidate_entries, list):
        return warnings
    source_dicts = [entry for entry in source_entries if isinstance(entry, dict)]
    available_entries = set(range(len(source_dicts)))
    for candidate_index, candidate_entry in enumerate(candidate_entries):
        if not isinstance(candidate_entry, dict):
            continue
        source_index = _matching_source_index(
            candidate_entry, source_dicts, available_entries, section
        )
        if source_index is None:
            continue
        available_entries.remove(source_index)
        source_entry = source_dicts[source_index]
        source_description = source_entry.get("description")
        candidate_description = candidate_entry.get("description")
        description_path = f"{path_prefix}[{candidate_index}].description"
        if isinstance(source_description, str) and isinstance(
            candidate_description, str
        ):
            if (
                _normalized(source_description) != _normalized(candidate_description)
                and _similarity(source_description, candidate_description)
                < _GROUNDING_REVIEW_THRESHOLD
                and not _grounded_in_evidence(
                    candidate_description, evidence_tokens, evidence_numbers
                )
            ):
                warnings.append(_grounding_warning(description_path))
            continue
        if not isinstance(source_description, list) or not isinstance(
            candidate_description, list
        ):
            continue
        available_rows = set(range(len(source_description)))
        row_assignments: dict[int, tuple[int, float]] = {}
        for row_index, row in enumerate(candidate_description):
            if not isinstance(row, str):
                continue
            exact = next(
                (
                    source_index
                    for source_index in sorted(available_rows)
                    if _normalized(source_description[source_index]) == _normalized(row)
                ),
                None,
            )
            if exact is not None:
                row_assignments[row_index] = (exact, 1.0)
                available_rows.remove(exact)
        for row_index, row in enumerate(candidate_description):
            if not isinstance(row, str) or row_index in row_assignments:
                continue
            match = _best_source_row(
                row,
                source_description,
                available_rows,
            )
            if match is None:
                continue
            source_index, score = match
            available_rows.remove(source_index)
            row_assignments[row_index] = (source_index, score)
        for row_index, row in enumerate(candidate_description):
            if not isinstance(row, str):
                continue
            assignment = row_assignments.get(row_index)
            if assignment is None:
                match = _best_source_row(
                    row, source_description, set(range(len(source_description)))
                )
                if _normalized(row) and (
                    match is None or match[1] < _GROUNDING_REVIEW_THRESHOLD
                ) and not _grounded_in_evidence(
                    row, evidence_tokens, evidence_numbers
                ):
                    warnings.append(
                        _grounding_warning(f"{description_path}[{row_index}]")
                    )
                continue
            source_index, score = assignment
            if (
                _normalized(row) != _normalized(source_description[source_index])
                and score < _GROUNDING_REVIEW_THRESHOLD
                and not _grounded_in_evidence(
                    row, evidence_tokens, evidence_numbers
                )
            ):
                warnings.append(_grounding_warning(f"{description_path}[{row_index}]"))
    return warnings


def grounding_review_warnings(
    source: dict[str, Any],
    candidate: dict[str, Any],
    extra_evidence: str | None = None,
) -> list[str]:
    """Return stable warnings for narrative rewrites with weak source overlap.

    Rows grounded in ``extra_evidence`` (original upload text) are not warned.
    """
    evidence_tokens, evidence_numbers = _evidence_context(extra_evidence)
    warnings: list[str] = []
    source_summary = source.get("summary")
    candidate_summary = candidate.get("summary")
    if (
        isinstance(source_summary, str)
        and isinstance(candidate_summary, str)
        and _normalized(source_summary) != _normalized(candidate_summary)
        and _similarity(source_summary, candidate_summary) < _GROUNDING_REVIEW_THRESHOLD
        and not _grounded_in_evidence(
            candidate_summary, evidence_tokens, evidence_numbers
        )
    ):
        warnings.append(_grounding_warning("summary"))

    for section in ("workExperience", "personalProjects", "education"):
        warnings.extend(
            _entry_grounding_warnings(
                source.get(section),
                candidate.get(section),
                section,
                section,
                evidence_tokens,
                evidence_numbers,
            )
        )

    source_custom = source.get("customSections")
    candidate_custom = candidate.get("customSections")
    if isinstance(source_custom, dict) and isinstance(candidate_custom, dict):
        for key, source_section in source_custom.items():
            candidate_section = candidate_custom.get(key)
            if (
                not isinstance(source_section, dict)
                or not isinstance(candidate_section, dict)
                or source_section.get("sectionType") != "itemList"
            ):
                continue
            warnings.extend(
                _entry_grounding_warnings(
                    source_section.get("items"),
                    candidate_section.get("items"),
                    "customItems",
                    f"customSections.{key}.items",
                    evidence_tokens,
                    evidence_numbers,
                )
            )
    return warnings
