"""Resume improvement service using LLM."""

import copy
import functools
import json
import logging
import re
from difflib import SequenceMatcher
from dataclasses import dataclass
from typing import Any, Callable

from app.llm import complete_json
from app.prompts import (
    CRITICAL_TRUTHFULNESS_RULES,
    DEFAULT_IMPROVE_PROMPT_ID,
    DIFF_IMPROVE_PROMPT,
    DIFF_STRATEGY_INSTRUCTIONS,
    EXTRACT_KEYWORDS_PROMPT,
    IMPROVE_RESUME_PROMPTS,
    SKILL_TARGET_PLAN_PROMPT,
    get_language_name,
)
from app.prompts.templates import IMPROVE_SCHEMA_EXAMPLE
from app.schemas import ResumeData, ResumeFieldDiff, ResumeDiffSummary
from app.schemas.models import ImproveDiffResult, ResumeChange
from app.services.parser import has_meaningful_resume_content

logger = logging.getLogger(__name__)

# LLM-011: Prompt injection patterns to sanitize
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"disregard\s+(all\s+)?above",
    r"forget\s+(everything|all)",
    r"new\s+instructions?:",
    r"system\s*:",
    r"<\s*/?\s*system\s*>",
    r"\[\s*INST\s*\]",
    r"\[\s*/\s*INST\s*\]",
]


def _validate_string_list_field(
    result: dict[str, Any],
    field: str,
) -> list[str]:
    """Return a normalized required list of non-empty strings."""
    value = result.get(field)
    if not isinstance(value, list):
        raise ValueError(f"LLM response requires a '{field}' list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"LLM response field '{field}' must contain text")
    return [item.strip() for item in value]


def _validate_keyword_result(result: dict[str, Any]) -> dict[str, Any]:
    """Validate keyword fields consumed by tailoring while allowing sparse output."""
    validated = dict(result)
    for field in ("required_skills", "preferred_skills", "keywords"):
        validated[field] = _validate_string_list_field(result, field)
    for field in (
        "experience_requirements",
        "education_requirements",
        "key_responsibilities",
    ):
        if field in result:
            validated[field] = _validate_string_list_field(result, field)
    return validated


def _validate_diff_result(result: dict[str, Any]) -> dict[str, Any]:
    """Validate an explicit diff result, including a legitimate empty list."""
    if "changes" not in result:
        raise ValueError("LLM diff response is missing 'changes'")
    return ImproveDiffResult.model_validate(result).model_dump()


def _validate_skill_plan_result(result: dict[str, Any]) -> dict[str, Any]:
    """Validate an explicit skill-target plan without coercing invalid leaves."""
    raw_targets = result.get("target_skills")
    if not isinstance(raw_targets, list):
        raise ValueError("LLM skill plan requires a 'target_skills' list")

    normalized: list[dict[str, str]] = []
    for target in raw_targets:
        if isinstance(target, str):
            skill = target.strip()
            reason = ""
        elif isinstance(target, dict):
            raw_skill = target.get("skill")
            raw_reason = target.get("reason", "")
            if not isinstance(raw_skill, str) or not isinstance(raw_reason, str):
                raise ValueError("Skill targets require text skill and reason fields")
            skill = raw_skill.strip()
            reason = raw_reason.strip()
        else:
            raise ValueError("Skill targets must be strings or objects")
        if not skill:
            raise ValueError("Skill targets cannot be blank")
        normalized.append({"skill": skill, "reason": reason})

    raw_notes = result.get("strategy_notes", "")
    if not isinstance(raw_notes, str):
        raise ValueError("Skill plan strategy_notes must be text")

    return {
        **result,
        "target_skills": normalized,
        "strategy_notes": raw_notes.strip(),
    }


def _validate_resume_result(result: dict[str, Any]) -> dict[str, Any]:
    """Validate schema and reject a structurally valid but empty resume."""
    validated = ResumeData.model_validate(result).model_dump()
    if not has_meaningful_resume_content(validated):
        raise ValueError("LLM returned an empty structured resume")
    return validated


@dataclass(frozen=True)
class DiffConfidence:
    added: str
    removed: str
    modified: str


def _sanitize_user_input(text: str) -> str:
    """LLM-011: Sanitize user input to prevent prompt injection.

    Removes or redacts common injection patterns that could manipulate LLM behavior.
    """
    sanitized = text
    for pattern in _INJECTION_PATTERNS:
        sanitized = re.sub(pattern, "[REDACTED]", sanitized, flags=re.IGNORECASE)
    return sanitized


# ---------------------------------------------------------------------------
# Diff-based improvement: path resolution, applier, verifier, LLM generator
# ---------------------------------------------------------------------------

_PATH_SEGMENT_RE = re.compile(r"([a-zA-Z_]+)(?:\[(\d+)\])?")

# Allowed path patterns — only these can be modified by diffs
_ALLOWED_PATH_PATTERNS = [
    re.compile(r"^summary$"),
    re.compile(r"^workExperience\[\d+\]\.description(\[\d+\])?$"),
    re.compile(r"^personalProjects\[\d+\]\.description(\[\d+\])?$"),
    # Indexed skill entries are the target of the elaborate_skill action
    # (bare stack name -> "name: capability detail", at most two lines).
    re.compile(r"^additional\.technicalSkills(\[\d+\])?$"),
    # Education description is a single string (Education.description: str | None),
    # so only the scalar path is allowed — not a [j]-indexed bullet form.
    re.compile(r"^education\[\d+\]\.description$"),
    re.compile(r"^additional\.languages$"),
    re.compile(r"^additional\.certificationsTraining$"),
    re.compile(r"^additional\.awards$"),
]

# Blocked path prefixes — always rejected
_BLOCKED_PATH_PREFIXES = frozenset({
    "personalInfo",
    "customSections",
    "sectionMeta",
})

# Blocked field names — rejected when they appear as the leaf of a path
_BLOCKED_FIELD_NAMES = frozenset({
    "years",
    "company",
    "institution",
    "title",
    "degree",
    "name",
    "role",
    "github",
    "website",
    "location",
    "id",
})

_METRIC_RE = re.compile(r"\d+%|\d+x|\$\d+")

# Any digit in newly authored skill/highlight text is treated as a fabricated
# metric/date claim; only digits already present in the source entry survive.
_ANY_DIGIT_RE = re.compile(r"\d")
_CJK_CHAR_RE = re.compile(r"[㐀-䶿一-鿿]")

# "Skill name: capability detail" entries. Two lines on an A4 resume hold
# roughly 90 CJK chars / 160 Latin chars at the body font size; the LLM prompt
# states the same "at most two lines" rule and these caps deterministically
# reject runaway entries.
_SKILL_DETAIL_CJK_LIMIT = 90
_SKILL_DETAIL_LATIN_LIMIT = 160
_HIGHLIGHT_CJK_LIMIT = 90
_HIGHLIGHT_LATIN_LIMIT = 160

# What may directly follow a bare skill name when it was expanded into a
# "name: detail" entry (whitespace, CJK adjacency, or a separator). Used to
# tell an elaboration of "Redis" apart from an unrelated skill "RedisExporter".
_SKILL_DETAIL_SEPARATORS = "：:·|（(［[\\-—、,，/；;"

# Proficiency-positioning words. Newly ADDED skill entries must open with one
# of these (chosen by how strongly the JD demands the skill) so they read like
# the resume's existing sentences ("熟练掌握 Redis 核心数据结构……") instead of
# a "Redis：……" prefixed stack label.
_PROFICIENCY_MARKERS_ZH = (
    "深入理解",
    "熟练掌握",
    "熟练使用",
    "熟练运用",
    "精通",
    "熟悉",
    "了解",
    "具备",
)
_PROFICIENCY_MARKERS_EN = (
    "expert in",
    "expertise in",
    "deep understanding of",
    "proficient in",
    "proficiency in",
    "experienced in",
    "hands-on experience",
    "strong knowledge of",
    "skilled in",
    "familiar with",
    "working knowledge of",
    "knowledge of",
    "aware of",
)

# A new entry may center on at most this many verified technologies; naming
# more is the category-row stack dump the format forbids.
_MAX_VERIFIED_TECHS_PER_SKILL = 2

# Minimum text similarity (difflib ratio) for pairing a removed bare skill with
# an added proficiency-first sentence that names it mid-line. The bounded term
# match carries the real evidence (gates forbid adding a second entry for an
# already-listed technology); this floor only prunes pathological length gaps.
_SKILL_REWRITE_MIN_RATIO = 0.15


def _text_too_long(text: str, cjk_limit: int, latin_limit: int) -> bool:
    """Whether an authored entry exceeds the two-line render budget."""
    return len(text) > (cjk_limit if _CJK_CHAR_RE.search(text) else latin_limit)


def _skill_detail_boundary(tail: str) -> bool:
    """Whether text immediately after a skill name is an elaboration boundary."""
    if not tail:
        return False
    if tail[0].isspace():
        return True
    return tail[0] in _SKILL_DETAIL_SEPARATORS or bool(_CJK_CHAR_RE.match(tail[0]))


def _match_verified_skill(
    entry: str,
    allowed_skill_keys: set[str],
) -> str | None:
    """Return the verified skill key an entry is grounded by, if any.

    Matches both a bare name ("Kubernetes") and an elaborated entry
    ("Kubernetes：容器编排、Service/Ingress 流量治理……"), checking longest keys
    first so "Spring Boot" wins over "Spring".
    """
    normalized = _normalize_skill_key(entry)
    for key in sorted(allowed_skill_keys, key=len, reverse=True):
        if normalized == key:
            return key
        if normalized.startswith(key) and _skill_detail_boundary(
            normalized[len(key) :]
        ):
            return key
    return None


# Project sub-module label rows, normalized without trailing colon. Mirrors the
# parser's canonical label mapping (PARSE_RESUME_PROMPT rule 5); English forms
# cover the labels the diff flow itself may create when a region is missing.
_TECH_STACK_LABELS = frozenset(
    {
        "技术栈",
        "技术选型",
        "技术架构",
        "所用技术",
        "技术清单",
        "技术列表",
        "系统架构",
        "架构说明",
        "tech stack",
        "technology stack",
        "technologies",
    }
)
_HIGHLIGHT_LABELS = frozenset(
    {
        "项目亮点",
        "项目成果",
        "技术亮点",
        "技术难点",
        "难点与解决",
        "技术难点及亮点",
        "project highlights",
        "key highlights",
        "highlights",
    }
)
_DUTY_LABELS = frozenset(
    {
        "项目职责",
        "工作职责",
        "主要职责",
        "负责内容",
        "核心工作",
        "工作内容",
        "职责",
        "responsibilities",
        "duties",
    }
)
_ALL_KNOWN_PROJECT_LABELS = (
    _TECH_STACK_LABELS
    | _HIGHLIGHT_LABELS
    | _DUTY_LABELS
    | {
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
    }
)


def _label_core(row: Any) -> str | None:
    """Normalize a possible sub-module label row to its colon-stripped core."""
    if not isinstance(row, str):
        return None
    stripped = row.strip().rstrip("：:").strip()
    return stripped.casefold() or None


def _is_region_label(
    rows: list[Any], styles: list[Any], index: int, label_set: frozenset[str]
) -> bool:
    """Whether row ``index`` is a label heading in ``label_set``.

    Style metadata is authoritative when present; a known-label text fallback
    covers resumes whose descriptionStyles were backfilled to all "bullet".
    """
    core = _label_core(rows[index])
    if core is None or core not in label_set:
        return False
    if index < len(styles):
        return styles[index] != "plain"
    return True


def _find_project_region(
    rows: list[Any],
    styles: list[Any],
    label_set: frozenset[str],
) -> tuple[int, int] | None:
    """Return ``(label_index, end_index_exclusive)`` for a sub-module region."""
    for index in range(len(rows)):
        if not _is_region_label(rows, styles, index, label_set):
            continue
        end = index + 1
        while end < len(rows):
            if end < len(styles) and styles[end] == "label":
                break
            core = _label_core(rows[end])
            if core is not None and core in _ALL_KNOWN_PROJECT_LABELS:
                break
            end += 1
        return index, end
    return None


def _entry_uses_cjk(entry: dict[str, Any]) -> bool:
    """Whether a project entry is primarily CJK (for injected label language)."""
    blob = " ".join(
        [
            str(entry.get("name", "")),
            str(entry.get("role", "")),
            " ".join(str(r) for r in entry.get("description", [])),
        ]
    )
    return bool(_CJK_CHAR_RE.search(blob))


def _aligned_description_styles(
    entry: dict[str, Any], rows: list[Any]
) -> list[str]:
    """Return styles parallel to rows, backfilling bullets when metadata is off."""
    styles = entry.get("descriptionStyles")
    if isinstance(styles, list) and len(styles) == len(rows):
        return [s if s in ("label", "plain", "bullet") else "bullet" for s in styles]
    return ["bullet"] * len(rows)


def _row_already_present(rows: list[Any], text: str) -> bool:
    """Case-insensitive whole-phrase duplicate check against existing rows."""
    target = _normalize_skill_key(text)
    return any(
        isinstance(row, str) and _normalize_skill_key(row) == target for row in rows
    )


# Punctuation at which a technology name starts/ends inside a longer line
# (e.g. "Python、Kafka" or "Kafka（消息队列）"). "_" is deliberately excluded:
# it joins identifiers ("kafka_stream"), so it is not a name boundary.
_TERM_BOUNDARY_CHARS = frozenset(
    "：:·|（(［[\\-—、,，/；;）)】]。.！!？?\"'“”‘’<>《》「」 "
)

_CJK_RUN_RE = re.compile(r"[㐀-䶿一-鿿]+")
_SCENARIO_LATIN_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#./\-]*")


def _is_term_boundary(ch: str) -> bool:
    """Whether ``ch`` may bound a technology name inside a longer line.

    Unlike regex ``\\w`` lookarounds, adjacent CJK characters count as
    boundaries ("基于Kafka构建" names Kafka), matching resume phrasing.
    """
    if not ch or ch.isspace() or ch in _TERM_BOUNDARY_CHARS:
        return True
    return bool(_CJK_CHAR_RE.match(ch))


def _skill_appears_in_text(skill: str, text: str) -> bool:
    """Boundary-aware term presence (case-insensitive) inside ``text``."""
    needle = skill.strip().casefold()
    haystack = text.casefold()
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


def _skill_already_listed(skills: list[Any], base_key: str) -> bool:
    """Whether existing skills already cover ``base_key`` in any form.

    Covers bare names, elaborated "Name: detail" entries, and names embedded
    in category/group rows such as "后端：Java、Kafka、Redis".
    """
    for item in skills:
        if not isinstance(item, str):
            continue
        if _match_verified_skill(item, {base_key}) is not None:
            return True
        if _skill_appears_in_text(base_key, item):
            return True
    return False


def _starts_with_proficiency_marker(text: str) -> bool:
    """Whether a skill sentence opens with a JD-matched proficiency word.

    Mirrors the resume's existing phrasing ("熟练掌握 Redis……", "Familiar
    with Linux……") as opposed to a "Redis：……" name-label prefix.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if _CJK_CHAR_RE.search(stripped[:2]):
        return any(stripped.startswith(marker) for marker in _PROFICIENCY_MARKERS_ZH)
    head = stripped.casefold()[:48]
    return any(head.startswith(marker) for marker in _PROFICIENCY_MARKERS_EN)


def _skills_named_in_entry(entry: str, allowed_keys: set[str]) -> list[str]:
    """Verified technology keys named anywhere in a skill entry.

    Returns distinct mentions, longest first, dropping a shorter key that is
    itself part of a longer matched name ("spring" inside "spring boot").
    """
    matched = [
        key for key in allowed_keys if key and _skill_appears_in_text(key, entry)
    ]
    matched.sort(key=len, reverse=True)
    distinct: list[str] = []
    for key in matched:
        if any(
            key != longer and _skill_appears_in_text(key, longer)
            for longer in distinct
        ):
            continue
        distinct.append(key)
    return distinct


def _project_region_rows(
    project: dict[str, Any], label_set: frozenset[str]
) -> list[str]:
    """String rows inside a project's labeled sub-module region (label excluded)."""
    rows = project.get("description")
    if not isinstance(rows, list):
        return []
    styles = _aligned_description_styles(project, rows)
    region = _find_project_region(rows, styles, label_set)
    if region is None:
        return []
    label_index, end = region
    return [row for row in rows[label_index + 1 : end] if isinstance(row, str)]


def _stack_region_lists_tech(project: dict[str, Any], tech_key: str) -> bool:
    """Whether the project's tech-stack region already lists the technology.

    Catches bare rows, parenthetical variants ("Kafka（消息队列）"), and
    multi-technology rows ("Python、Kafka、Redis"), so the same stack item is
    never listed twice in the sub-module.
    """
    return any(
        _skill_appears_in_text(tech_key, row)
        for row in _project_region_rows(project, _TECH_STACK_LABELS)
    )


def _project_content_rows(
    project: dict[str, Any], *, include_stack: bool
) -> list[str]:
    """String content rows of a project, excluding sub-module label headings.

    ``include_stack`` controls whether rows inside the 技术栈 region count:
    tech-evidence checks scan everything, while scenario-grounding checks
    exclude bare stack names (a name in the stack is not evidence of HOW the
    technology was applied).
    """
    rows = project.get("description")
    if not isinstance(rows, list):
        return []
    styles = _aligned_description_styles(project, rows)
    stack_region = _find_project_region(rows, styles, _TECH_STACK_LABELS)
    label_indices = {
        index
        for index in range(len(rows))
        for label_set in (
            _TECH_STACK_LABELS,
            _HIGHLIGHT_LABELS,
            _DUTY_LABELS,
        )
        if _is_region_label(rows, styles, index, label_set)
    }
    content: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, str) or index in label_indices:
            continue
        if (
            not include_stack
            and stack_region is not None
            and stack_region[0] < index < stack_region[1]
        ):
            continue
        content.append(row)
    return content


def _project_mentions_tech(project: dict[str, Any], tech_key: str) -> bool:
    """Whether the project's existing text names the technology anywhere.

    A technology may be promoted into the stack/highlight sub-modules only
    when THIS project already demonstrates it; a name on a different project
    or in the global skills list is not evidence.
    """
    return any(
        _skill_appears_in_text(tech_key, row)
        for row in _project_content_rows(project, include_stack=True)
    )


def _scenario_tokens(text: str) -> set[str]:
    """Comparison tokens for highlight-scenario similarity.

    Latin/digit terms plus CJK character bigrams over each Han run (a lone
    Han character contributes a unigram).
    """
    lowered = text.casefold()
    tokens: set[str] = set()
    for match in _SCENARIO_LATIN_TOKEN_RE.findall(lowered):
        token = match.strip("+#.-/")
        if len(token) >= 2:
            tokens.add(token)
    for run in _CJK_RUN_RE.findall(lowered):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


# Function characters stripped from Han runs before bigramming (particles,
# conjunctions, aspect/suffix characters that never carry scenario meaning).
_SCENARIO_STOP_CHARS = frozenset(
    "的了在与和及或将把被使令其该各类种一二三个项次间内外上中前后时型式化性是有为不并也而"
    "等但对到从向由以则即且又很更最已能会可应要需之你我他并再便就都而若虽因所然"
)

# Resume boilerplate words; their bigrams carry no project-specific scenario
# ("提升性能", "保障稳定", "服务/业务/数据/系统" …). A grounded bullet must
# reuse THIS project's own vocabulary (modules, mechanisms, problems), so
# filtering these is what rejects generic market-standard filler.
_SCENARIO_STOP_WORDS_ZH = (
    "通过 使用 利用 基于 结合 实现 设计 开发 提升 保障 保证 支撑 解决 问题 能力 "
    "系统 性能 高效 稳定 可靠 一致 准确 吞吐 响应 速度 效率 维护 扩展 动态 服务 "
    "业务 场景 数据 核心 模块 架构 进行 以及 常见 常用 快速 特性 完整 整体 主要 "
    "负责 参与 协助 完成 支持 提供 接入 集成 调用 通信 交互 处理 流程 机制 优化 "
    "部署 监控 排查 线上 环境 容器 经验 具备 熟悉 熟练 精通 理解 掌握 了解 平台 "
    "项目 技术 持久 高可用 高并发 并发 存储 读写 访问 落地 方案 建设 构建 搭建 "
    "研发 编写 编码 增强 加强 深入 扎实 丰富 实际 实战 良好 优秀 团队 人员 用户 "
    "客户 产品 需求 分析 评审 文档 测试 验证 日常 及时 修复 根源 确保 满意 相关 "
    "工作 内容 情况 方面 方式 方法 特点 优势 质量"
).split()

_SCENARIO_STOP_WORDS_EN = frozenset(
    """
    used use using via based through for and the with of in on to a an by from as at
    is are it its this that ensure ensuring ensured improve improved improving
    improvement support supporting supported build built building builds develop
    developed developing development design designed designing implement
    implemented implementing implementation integrate integrated integrating
    integration provide provided providing achieve achieved efficient efficiently
    efficiency high higher performance stable stability reliable reliability
    scalable consistency consistent accurate accuracy throughput latency response
    speed fast quickly maintainability maintain service services system systems
    data business core module modules architecture scenario scenarios platform
    overall common commonly capability capabilities ability problem problems issue
    issues process processing mechanism mechanisms optimization optimize optimized
    deploy deployment monitor monitoring operations online environment environments
    container containerized layer cloud edge experience familiar proficient expert
    understanding knowledge deep strong related relevant etc also within between
    across during into per such can able well good great best full effective
    effectively robust flexible enable enabled ensuring
    """.split()
)


@functools.cache
def _scenario_stop_tokens() -> frozenset[str]:
    """All tokens (CJK bigrams/unigrams + Latin words) treated as filler."""
    stops: set[str] = set()
    for word in _SCENARIO_STOP_WORDS_ZH:
        chars = [ch for ch in word if ch not in _SCENARIO_STOP_CHARS]
        if len(chars) == 1:
            stops.add(chars[0])
        else:
            stops.update(
                "".join(chars[i : i + 2]) for i in range(len(chars) - 1)
            )
    stops.update(_SCENARIO_STOP_WORDS_EN)
    return frozenset(stops)


def _distinctive_scenario_tokens(
    text: str, tech_keys: set[str] | frozenset[str]
) -> set[str]:
    """Scenario-bearing tokens of a highlight, minus tech names and filler."""
    tech_tokens: set[str] = set()
    for key in tech_keys:
        tech_tokens.add(key)
        tech_tokens.update(_scenario_tokens(key))
    stops = _scenario_stop_tokens()
    distinctive: set[str] = set()
    for token in _scenario_tokens(text):
        if token in tech_tokens or token in stops:
            continue
        if _CJK_RUN_RE.fullmatch(token):
            if any(ch in _SCENARIO_STOP_CHARS for ch in token):
                continue
        elif len(token) < 3:
            continue
        distinctive.add(token)
    return distinctive


# A new highlight must reuse at least this many of the project's own
# scenario tokens (modules, mechanisms, problems from its real rows), and is
# rejected as a restatement when this fraction of its content already appears
# in an existing row of the same project.
_SCENARIO_GROUNDING_MIN_SHARED = 2
_SCENARIO_RESTATEMENT_RATIO = 0.5


def _highlight_rejection_reason(
    project: dict[str, Any],
    text: str,
    named_tech_keys: list[str],
    allowed_skill_keys: set[str],
) -> str | None:
    """Return why a proposed highlight may not be inserted, or None when valid.

    Three deterministic anti-fabrication conditions:
    1. At least one named technology is already demonstrated in THIS project's
       existing text (a global skills-list entry is not project evidence).
    2. The bullet reuses the project's own scenario vocabulary (modules,
       mechanisms, problems) - generic capability filler fails this.
    3. The bullet does not restate an existing row (an existing bullet should
       be reframed with "replace", not duplicated as a new highlight).
    """
    existing_rows = _project_content_rows(project, include_stack=True)
    if not any(
        _skill_appears_in_text(key, row)
        for key in named_tech_keys
        for row in existing_rows
    ):
        return "technology not demonstrated in this project"

    evidence_tokens: set[str] = set()
    for row in _project_content_rows(project, include_stack=False):
        evidence_tokens.update(
            _distinctive_scenario_tokens(row, allowed_skill_keys)
        )
    new_tokens = _distinctive_scenario_tokens(text, allowed_skill_keys)
    shared_with_project = new_tokens & evidence_tokens
    if len(shared_with_project) < _SCENARIO_GROUNDING_MIN_SHARED:
        return "generic scenario not grounded in this project's existing content"

    for row in existing_rows:
        row_tokens = _distinctive_scenario_tokens(row, allowed_skill_keys)
        shared = new_tokens & row_tokens
        if (
            len(shared) >= _SCENARIO_GROUNDING_MIN_SHARED
            and len(shared) / max(1, len(new_tokens))
            >= _SCENARIO_RESTATEMENT_RATIO
        ):
            return "restatement of an existing project row"
    return None


def _insert_project_row(
    entry: dict[str, Any],
    anchor: str,
    text: str,
) -> bool:
    """Insert one row into a project sub-module region, keeping styles aligned.

    ``tech_stack`` rows land at the end of the 技术栈 region as ``plain`` rows;
    ``highlight`` rows land at the end of the 项目亮点 region as ``bullet`` rows.
    A missing region is created with the canonical label (label row + style).
    """
    rows = entry.get("description")
    if not isinstance(rows, list):
        return False
    styles = _aligned_description_styles(entry, rows)
    cjk = _entry_uses_cjk(entry)
    stack_label = "技术栈：" if cjk else "Tech Stack:"
    highlight_label = "项目亮点：" if cjk else "Project Highlights:"

    if anchor == "tech_stack":
        region = _find_project_region(rows, styles, _TECH_STACK_LABELS)
        if region is not None:
            pos = region[1]
            rows.insert(pos, text)
            styles.insert(pos, "plain")
        else:
            # Prefer placement directly before 项目职责/项目亮点; else first label.
            duty = _find_project_region(rows, styles, _DUTY_LABELS)
            highlights = _find_project_region(rows, styles, _HIGHLIGHT_LABELS)
            candidates = [r[0] for r in (duty, highlights) if r is not None]
            pos = min(candidates) if candidates else 0
            rows[pos:pos] = [stack_label, text]
            styles[pos:pos] = ["label", "plain"]
    else:
        region = _find_project_region(rows, styles, _HIGHLIGHT_LABELS)
        if region is not None:
            pos = region[1]
            rows.insert(pos, text)
            styles.insert(pos, "bullet")
        else:
            pos = len(rows)
            rows[pos:pos] = [highlight_label, text]
            styles[pos:pos] = ["label", "bullet"]

    entry["description"] = rows
    entry["descriptionStyles"] = styles
    return True


def _is_path_allowed(path: str) -> bool:
    """Check if a path is in the allowed whitelist."""
    return any(p.match(path) for p in _ALLOWED_PATH_PATTERNS)


def _is_path_blocked(path: str) -> bool:
    """Check if a path matches any blocked pattern."""
    for prefix in _BLOCKED_PATH_PREFIXES:
        if path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "["):
            return True

    # Check if the leaf field is blocked
    segments = path.split(".")
    if segments:
        last_segment = segments[-1]
        field_name = re.sub(r"\[\d+\]$", "", last_segment)
        # "description" is the one allowed field that shares a name pattern
        if field_name in _BLOCKED_FIELD_NAMES and field_name != "description":
            return True

    if path.startswith("education"):
        # Education descriptions may be tailored; degree/institution/years stay
        # blocked (they are also caught by the blocked-leaf-name check above).
        if re.match(r"^education\[\d+\]\.description$", path):
            return False
        return True

    return False


def _resolve_path(data: dict[str, Any], path: str) -> tuple[Any, bool]:
    """Resolve a dot+bracket path to a value in the data dict.

    Returns:
        (value, success). On failure returns (None, False).
    """
    current: Any = data
    for segment_match in _PATH_SEGMENT_RE.finditer(path):
        key = segment_match.group(1)
        index_str = segment_match.group(2)

        if not isinstance(current, dict) or key not in current:
            return None, False
        current = current[key]

        if index_str is not None:
            index = int(index_str)
            if not isinstance(current, list) or index < 0 or index >= len(current):
                return None, False
            current = current[index]

    return current, True


def _set_at_path(data: dict[str, Any], path: str, value: Any) -> bool:
    """Set a value at the given path. Returns True on success."""
    segments = list(_PATH_SEGMENT_RE.finditer(path))
    if not segments:
        return False

    # Navigate to parent of the target
    current: Any = data
    for seg in segments[:-1]:
        key = seg.group(1)
        index_str = seg.group(2)

        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]

        if index_str is not None:
            index = int(index_str)
            if not isinstance(current, list) or index < 0 or index >= len(current):
                return False
            current = current[index]

    # Set on the final segment
    last = segments[-1]
    key = last.group(1)
    index_str = last.group(2)

    if index_str is not None:
        if not isinstance(current, dict) or key not in current:
            return False
        target = current[key]
        index = int(index_str)
        if not isinstance(target, list) or index < 0 or index >= len(target):
            return False
        target[index] = value
    else:
        if not isinstance(current, dict):
            return False
        current[key] = value

    return True


def _verify_original_matches(actual: Any, expected: str | list[str] | None) -> bool:
    """Verify that the original text from the diff matches the actual value."""
    if expected is None:
        return True  # no original provided (e.g. append) — nothing to verify
    if not isinstance(expected, str):
        return False  # a non-str original on a text action is malformed — reject
    if not isinstance(actual, str):
        return False
    return actual.strip().casefold() == expected.strip().casefold()


def apply_diffs(
    original: dict[str, Any],
    changes: list[ResumeChange],
    allowed_skill_targets: list[dict[str, Any] | str] | None = None,
) -> tuple[dict[str, Any], list[ResumeChange], list[ResumeChange]]:
    """Apply verified diffs to original resume.

    Each change goes through 4 gates:
    1. Path is in allowed whitelist
    2. Path is not in blocked list
    3. Path resolves to an actual value in the original
    4. Original text matches (for replace actions)

    For reorder: validates the new list contains exactly the same items.

    Args:
        original: The original resume data (ResumeData-compatible dict)
        changes: List of changes from the LLM
        allowed_skill_targets: Verified skill targets allowed for add_skill actions

    Returns:
        (result_dict, applied_changes, rejected_changes)
    """
    result = copy.deepcopy(original)
    applied: list[ResumeChange] = []
    rejected: list[ResumeChange] = []
    allowed_skill_keys = _build_allowed_skill_target_keys(allowed_skill_targets)

    for change in changes:
        path = change.path
        action = change.action

        # Gate 1: Path must be in allowed whitelist
        if not _is_path_allowed(path):
            logger.info("Diff rejected (not in allowed list): %s", path)
            rejected.append(change)
            continue

        # Gate 2: Path must not be blocked
        if _is_path_blocked(path):
            logger.info("Diff rejected (blocked path): %s", path)
            rejected.append(change)
            continue

        # Gate 3: Path must resolve to a real value
        actual_value, resolved = _resolve_path(result, path)
        if not resolved:
            logger.info("Diff rejected (path not found): %s", path)
            rejected.append(change)
            continue

        if action == "replace":
            # Gate 4: Original text must match what's actually there
            if not _verify_original_matches(actual_value, change.original):
                logger.info(
                    "Diff rejected (original mismatch): path=%s expected=%r actual=%r",
                    path,
                    change.original,
                    actual_value,
                )
                rejected.append(change)
                continue

            # Replace must use a string value (not list)
            if not isinstance(change.value, str):
                logger.info("Diff rejected (replace with non-string value): %s", path)
                rejected.append(change)
                continue

            if not _set_at_path(result, path, change.value):
                rejected.append(change)
                continue
            applied.append(change)

        elif action == "append":
            if not isinstance(actual_value, list):
                logger.info("Diff rejected (append to non-list): %s", path)
                rejected.append(change)
                continue
            # Append must use a non-empty string (not list, to avoid nested lists)
            if not isinstance(change.value, str) or not change.value.strip():
                logger.info("Diff rejected (append non-string or empty value): %s", path)
                rejected.append(change)
                continue
            actual_value.append(change.value)
            applied.append(change)

        elif action == "reorder":
            if not isinstance(actual_value, list) or not isinstance(change.value, list):
                rejected.append(change)
                continue
            orig_set = sorted(s.casefold() for s in actual_value if isinstance(s, str))
            new_set = sorted(s.casefold() for s in change.value if isinstance(s, str))
            reordered: list[str] = []
            if orig_set == new_set:
                # Pure permutation: map the new order back to original casing.
                casefold_to_originals: dict[str, list[str]] = {}
                for item in actual_value:
                    if isinstance(item, str):
                        casefold_to_originals.setdefault(item.casefold(), []).append(item)
                for item in change.value:
                    if isinstance(item, str):
                        originals = casefold_to_originals.get(item.casefold(), [])
                        reordered.append(originals.pop(0) if originals else item)
            else:
                # Salvage (issue #736): the LLM folded new/removed items into a
                # reorder. Rather than dropping the whole change, apply the SAFE
                # subset *in the requested order*: walk the proposed list, placing
                # each existing item where the model put it (so prioritized JD
                # skills stay near the top) and — for the skills list only —
                # inserting new items that pass the SAME verified gate as
                # add_skill. Originals the model omitted are appended at the end
                # so a real item is never silently lost. Other lists
                # (languages/certs/awards) have no verifier, so new items are
                # dropped to avoid fabrication.
                casefold_to_originals: dict[str, list[str]] = {}
                for item in actual_value:
                    if isinstance(item, str):
                        casefold_to_originals.setdefault(item.casefold(), []).append(item)
                original_cfs = set(casefold_to_originals)
                is_skills = path == "additional.technicalSkills"
                added_new: set[str] = set()
                for item in change.value:
                    if not isinstance(item, str):
                        continue
                    cf = item.casefold()
                    if cf in original_cfs:
                        bucket = casefold_to_originals[cf]
                        if bucket:  # place original in requested position (dupes preserved)
                            reordered.append(bucket.pop(0))
                        # else: a duplicate of an already-placed original — skip
                    elif is_skills and cf not in added_new:
                        skill = item.strip()
                        skill_key = (
                            _normalize_skill_key(skill) if skill else None
                        )
                        if skill_key is None or skill_key not in allowed_skill_keys:
                            logger.info("Reorder salvage dropped unverified skill: %s", skill)
                        elif _skill_already_listed(actual_value, skill_key):
                            # Already present as another entry or inside a
                            # category/group row — never duplicate it.
                            logger.info("Reorder salvage dropped duplicate skill: %s", skill)
                        else:
                            reordered.append(skill)  # verified new skill, requested position
                            added_new.add(cf)
                    # else: non-skills new item → dropped (no verifier to ground it)
                for item in actual_value:  # append any originals the model omitted
                    if isinstance(item, str):
                        bucket = casefold_to_originals[item.casefold()]
                        if bucket:
                            reordered.append(bucket.pop(0))
                logger.info("Diff reorder salvaged (item-set mismatch): %s", path)
            if not _set_at_path(result, path, reordered):
                rejected.append(change)
                continue
            applied.append(change)

        elif action == "add_skill":
            if path != "additional.technicalSkills":
                logger.info("Diff rejected (add_skill outside skills): %s", path)
                rejected.append(change)
                continue
            if not isinstance(actual_value, list):
                logger.info("Diff rejected (add_skill to non-list): %s", path)
                rejected.append(change)
                continue
            if not isinstance(change.value, str) or not change.value.strip():
                logger.info("Diff rejected (add_skill empty/non-string): %s", path)
                rejected.append(change)
                continue
            new_skill = change.value.strip()
            if "\n" in new_skill or _text_too_long(
                new_skill, _SKILL_DETAIL_CJK_LIMIT, _SKILL_DETAIL_LATIN_LIMIT
            ):
                logger.info("Diff rejected (add_skill not a <=2-line entry): %s", new_skill)
                rejected.append(change)
                continue
            # New entries are proficiency-positioned sentences in the resume's
            # own style ("熟练掌握 Redis……"), never a "Redis：……" name label.
            if not _starts_with_proficiency_marker(new_skill):
                logger.info(
                    "Diff rejected (add_skill missing proficiency positioning): %s",
                    new_skill,
                )
                rejected.append(change)
                continue
            named_keys = _skills_named_in_entry(new_skill, allowed_skill_keys)
            if not named_keys:
                logger.info("Diff rejected (skill not in verified targets): %s", new_skill)
                rejected.append(change)
                continue
            if len(named_keys) > _MAX_VERIFIED_TECHS_PER_SKILL:
                logger.info(
                    "Diff rejected (add_skill stacks multiple technologies): %s",
                    new_skill,
                )
                rejected.append(change)
                continue
            base_key = named_keys[0]
            # Skill entries may carry digits only when the bare name already does
            # (e.g. an existing "Python 3" entry); new claims stay unverifiable.
            if _ANY_DIGIT_RE.search(new_skill) and not any(
                isinstance(item, str) and _ANY_DIGIT_RE.search(item)
                for item in actual_value
            ):
                logger.info("Diff rejected (add_skill with invented numeric claim): %s", new_skill)
                rejected.append(change)
                continue
            # Reject duplicates in ANY form: bare name, an elaborated entry,
            # or a name buried inside a category/group row ("后端：Java、Kafka").
            if _skill_already_listed(actual_value, base_key):
                logger.info("Diff rejected (duplicate skill): %s", new_skill)
                rejected.append(change)
                continue
            actual_value.append(new_skill)
            applied.append(change)

        elif action == "elaborate_skill":
            indexed_skill = re.fullmatch(
                r"additional\.technicalSkills\[(\d+)\]", path
            )
            if indexed_skill is None:
                logger.info("Diff rejected (elaborate_skill path): %s", path)
                rejected.append(change)
                continue
            skill_index = int(indexed_skill.group(1))
            if not isinstance(actual_value, str):
                logger.info("Diff rejected (elaborate_skill on non-string): %s", path)
                rejected.append(change)
                continue
            current = actual_value.strip()
            elaborated = change.value.strip() if isinstance(change.value, str) else ""
            current_key = _normalize_skill_key(current)
            elaborated_key = _normalize_skill_key(elaborated)
            # The bare entry must name a verified technology; the elaboration
            # may keep the "Name: detail" prefix OR open with a proficiency
            # word ("熟练掌握 Redis 核心数据结构……") — in both forms the bare
            # name must appear as a whole term somewhere in the new sentence.
            current_is_verified = (
                current_key in allowed_skill_keys
                or _match_verified_skill(current, allowed_skill_keys) is not None
            )
            named_in_elaboration = _skills_named_in_entry(
                elaborated, {current_key} | allowed_skill_keys
            )
            valid = (
                elaborated
                and "\n" not in elaborated
                and not _text_too_long(
                    elaborated, _SKILL_DETAIL_CJK_LIMIT, _SKILL_DETAIL_LATIN_LIMIT
                )
                # Only expand a bare, single-tech line — never a category row
                # such as "后端：Java、Spring Boot".
                and "、" not in current
                and "：" not in current
                and ":" not in current
                and len(elaborated_key) > len(current_key) + 1
                and current_is_verified
                and current_key in named_in_elaboration
                # Same constraint as add_skill: one sentence elaborates at
                # most two verified technologies.
                and len(named_in_elaboration) <= _MAX_VERIFIED_TECHS_PER_SKILL
            )
            if not valid:
                logger.info(
                    "Diff rejected (invalid skill elaboration): %r -> %r",
                    current,
                    elaborated,
                )
                rejected.append(change)
                continue
            # No new numeric claims (years, versions, metrics) beyond the source.
            source_digits = set(_ANY_DIGIT_RE.findall(current))
            if set(_ANY_DIGIT_RE.findall(elaborated)) - source_digits:
                logger.info("Diff rejected (elaboration with new digits): %s", elaborated)
                rejected.append(change)
                continue
            skills_list, list_resolved = _resolve_path(result, "additional.technicalSkills")
            if not list_resolved or not isinstance(skills_list, list):
                rejected.append(change)
                continue
            if any(
                idx != skill_index
                and isinstance(item, str)
                and (
                    # Legacy "Name: detail" prefix form.
                    (
                        _normalize_skill_key(item).startswith(current_key)
                        and _skill_detail_boundary(
                            _normalize_skill_key(item)[len(current_key) :]
                        )
                    )
                    # Marker-first sentence form ("熟练掌握 Redis……") about
                    # the same bare technology. Category rows that merely list
                    # the name ("后端：Redis、Kafka") are not elaborations.
                    or (
                        _starts_with_proficiency_marker(item)
                        and _skill_appears_in_text(current_key, item)
                    )
                )
                for idx, item in enumerate(skills_list)
            ):
                logger.info("Diff rejected (duplicate elaboration): %s", current)
                rejected.append(change)
                continue
            skills_list[skill_index] = elaborated
            applied.append(change)

        elif action == "insert_row":
            project_match = re.fullmatch(
                r"personalProjects\[(\d+)\]\.description", path
            )
            anchor = change.anchor
            if project_match is None or anchor not in ("tech_stack", "highlight"):
                logger.info(
                    "Diff rejected (insert_row path/anchor): %s %s", path, anchor
                )
                rejected.append(change)
                continue
            project, project_resolved = _resolve_path(
                result, f"personalProjects[{project_match.group(1)}]"
            )
            if not project_resolved or not isinstance(project, dict):
                rejected.append(change)
                continue
            rows = project.get("description")
            if not isinstance(rows, list):
                logger.info("Diff rejected (insert_row on non-list project rows)")
                rejected.append(change)
                continue
            text = change.value.strip() if isinstance(change.value, str) else ""
            if (
                not text
                or "\n" in text
                or _text_too_long(
                    text, _HIGHLIGHT_CJK_LIMIT, _HIGHLIGHT_LATIN_LIMIT
                )
                or _row_already_present(rows, text)
            ):
                logger.info("Diff rejected (insert_row empty/long/duplicate): %s", text)
                rejected.append(change)
                continue
            if anchor == "tech_stack":
                # Stack rows are bare, verified tech names only — one technology,
                # no category prefixes, no invented numeric/version claims.
                tech_key = _normalize_skill_key(text)
                if (
                    tech_key not in allowed_skill_keys
                    or len(text) > 40
                    or any(ch in text for ch in "：:、,，;；")
                    or _ANY_DIGIT_RE.search(text)
                ):
                    logger.info("Diff rejected (tech stack row unverified): %s", text)
                    rejected.append(change)
                    continue
                # The stack sub-module lists each technology at most once,
                # including inside combined or parenthetical rows.
                if _stack_region_lists_tech(project, tech_key):
                    logger.info("Diff rejected (duplicate tech stack row): %s", text)
                    rejected.append(change)
                    continue
                # A tech is promoted into THIS project's stack only when the
                # project's own text already demonstrates it — never imported
                # from another project or the global skills list.
                if not _project_mentions_tech(project, tech_key):
                    logger.info(
                        "Diff rejected (tech not evidenced in this project): %s", text
                    )
                    rejected.append(change)
                    continue
            else:
                # A highlight must name a verified technology, must not invent
                # numbers (metrics/scale/years), must demonstrate the tech in
                # THIS project, and must reuse the project's own scenario
                # vocabulary rather than restate a row or paste generic filler.
                # CJK-adjacent mentions ("基于Kafka构建") count as mentions.
                named_tech_keys = _skills_named_in_entry(text, allowed_skill_keys)
                if not named_tech_keys or _ANY_DIGIT_RE.search(text):
                    logger.info(
                        "Diff rejected (highlight lacks verified tech or adds digits): %s",
                        text,
                    )
                    rejected.append(change)
                    continue
                reason = _highlight_rejection_reason(
                    project, text, named_tech_keys, allowed_skill_keys
                )
                if reason is not None:
                    logger.info(
                        "Diff rejected (highlight %s): %s", reason, text
                    )
                    rejected.append(change)
                    continue
            if not _insert_project_row(project, anchor, text):
                rejected.append(change)
                continue
            applied.append(change)

        else:
            logger.info("Diff rejected (unknown action): %s", action)
            rejected.append(change)

    return result, applied, rejected


def _count_description_words(data: dict[str, Any]) -> int:
    """Count total words in all description and summary fields."""
    total = 0
    for key in ("workExperience", "personalProjects"):
        for entry in data.get(key, []):
            if isinstance(entry, dict):
                desc = entry.get("description", [])
                if isinstance(desc, list):
                    total += sum(len(str(d).split()) for d in desc)
                elif isinstance(desc, str):
                    total += len(desc.split())
    summary = data.get("summary", "")
    if isinstance(summary, str):
        total += len(summary.split())
    return total


def verify_diff_result(
    original: dict[str, Any],
    result: dict[str, Any],
    applied_changes: list[ResumeChange],
    job_keywords: dict[str, Any],
) -> list[str]:
    """Local quality checks on the diff result. Returns list of warnings.

    All checks are local (zero LLM cost). Warnings are informational —
    they don't block the response.
    """
    warnings: list[str] = []

    # Check 1: No empty result
    if not applied_changes:
        warnings.append("No changes were applied — resume returned unchanged")
        return warnings

    # Check 2: Section counts preserved
    for key, label in [
        ("workExperience", "work experience"),
        ("education", "education"),
        ("personalProjects", "project"),
    ]:
        orig_count = len(original.get(key, []))
        result_count = len(result.get(key, []))
        if orig_count != result_count:
            warnings.append(
                f"Section count changed: {label} ({orig_count} → {result_count})"
            )

    # Check 3: Identity fields unchanged
    for key, id_fields in [
        ("workExperience", ["company", "title"]),
        ("education", ["institution", "degree"]),
    ]:
        orig_entries = original.get(key, [])
        result_entries = result.get(key, [])
        for i, (orig, res) in enumerate(zip(orig_entries, result_entries)):
            if not isinstance(orig, dict) or not isinstance(res, dict):
                continue
            for field in id_fields:
                o_val = str(orig.get(field, "")).strip()
                r_val = str(res.get(field, "")).strip()
                if o_val and o_val != r_val:
                    warnings.append(
                        f"Identity field changed: {key}[{i}].{field} "
                        f"('{o_val}' → '{r_val}')"
                    )

    # Check 4: Word count ratio
    orig_words = _count_description_words(original)
    result_words = _count_description_words(result)
    if orig_words > 0 and result_words > orig_words * 1.8:
        warnings.append(
            f"Word count increased significantly: "
            f"{orig_words} → {result_words} ({result_words / orig_words:.1f}x)"
        )

    # Check 5: Invented metrics (covers both replace and append)
    for change in applied_changes:
        if change.action in ("replace", "append") and isinstance(change.value, str):
            new_metrics = set(_METRIC_RE.findall(change.value))
            # For append, original is None — any metric is potentially invented
            original_text = change.original or ""
            old_metrics = set(_METRIC_RE.findall(original_text))
            invented = new_metrics - old_metrics
            if invented:
                warnings.append(
                    f"Possible invented metric in {change.path}: "
                    f"{', '.join(invented)} (not in original)"
                )

    return warnings


async def generate_resume_diffs(
    original_resume: str,
    job_description: str,
    job_keywords: dict[str, Any],
    language: str = "en",
    prompt_id: str | None = None,
    original_resume_data: dict[str, Any] | None = None,
    skill_targets: list[dict[str, Any]] | None = None,
) -> ImproveDiffResult:
    """Generate targeted resume diffs via LLM.

    Instead of asking the LLM for the full resume, asks for a list of
    targeted changes. Each change specifies a path, action, and new value.

    Args:
        original_resume: Resume content (markdown)
        job_description: Target job description
        job_keywords: Extracted job keywords
        language: Output language code (en, es, zh, ja)
        prompt_id: Strategy id (nudge/keywords/full)
        original_resume_data: Structured resume JSON
        skill_targets: Verified skill targets from the planning pass

    Returns:
        ImproveDiffResult with list of changes and strategy notes
    """
    keywords_str = _prepare_keywords_for_prompt(job_keywords)
    output_language = get_language_name(language)

    selected_id = prompt_id or DEFAULT_IMPROVE_PROMPT_ID
    if selected_id not in DIFF_STRATEGY_INSTRUCTIONS:
        logger.warning(
            "Unknown prompt_id '%s'; using default diff strategy.",
            selected_id,
        )
    strategy_instruction = DIFF_STRATEGY_INSTRUCTIONS.get(
        selected_id, DIFF_STRATEGY_INSTRUCTIONS[DEFAULT_IMPROVE_PROMPT_ID]
    )

    # LLM-011: Sanitize job description
    sanitized_jd = _sanitize_user_input(job_description)

    # Use structured JSON if available with month precision, else markdown
    if original_resume_data is not None:
        if _has_month_in_dates(original_resume_data):
            resume_input = json.dumps(original_resume_data)
        else:
            resume_input = original_resume
    else:
        resume_input = original_resume

    prompt = DIFF_IMPROVE_PROMPT.format(
        strategy_instruction=strategy_instruction,
        output_language=output_language,
        job_keywords=keywords_str,
        skill_targets=_prepare_skill_targets_for_prompt(skill_targets),
        job_description=sanitized_jd,
        original_resume=resume_input,
    )

    result = await complete_json(
        prompt=prompt,
        system_prompt="You are an expert resume editor. Output only valid JSON with targeted changes.",
        max_tokens=8192,
        schema_type="diff",
        response_validator=_validate_diff_result,
    )

    return ImproveDiffResult.model_validate(_validate_diff_result(result))


async def extract_job_keywords(job_description: str) -> dict[str, Any]:
    """Extract keywords and requirements from job description.

    Args:
        job_description: Raw job description text

    Returns:
        Structured keywords and requirements
    """
    # LLM-011: Sanitize job description before using in prompt
    sanitized_jd = _sanitize_user_input(job_description)
    prompt = EXTRACT_KEYWORDS_PROMPT.format(job_description=sanitized_jd)

    result = await complete_json(
        prompt=prompt,
        system_prompt="You are an expert job description analyzer.",
        schema_type="keywords",
        response_validator=_validate_keyword_result,
    )
    return _validate_keyword_result(result)


MONTH_PATTERN = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b",
    re.IGNORECASE,
)


def _has_month_in_dates(data: dict[str, Any]) -> bool:
    """Check whether any years field in the structured data includes a month."""
    for section_key in ("workExperience", "education", "personalProjects"):
        entries = data.get(section_key, [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                years = entry.get("years", "")
                if isinstance(years, str) and MONTH_PATTERN.search(years):
                    return True
    custom_sections = data.get("customSections", {})
    if isinstance(custom_sections, dict):
        for section in custom_sections.values():
            if isinstance(section, dict) and section.get("sectionType") == "itemList":
                items = section.get("items", [])
                if not isinstance(items, list):
                    continue
                for item in items:
                    if isinstance(item, dict):
                        years = item.get("years", "")
                        if isinstance(years, str) and MONTH_PATTERN.search(years):
                            return True
    return False


def _prepare_keywords_for_prompt(job_keywords: dict[str, Any]) -> str:
    """Format job keywords as a focused, readable list for the LLM prompt.

    Extracts only actionable fields (skills and keywords) and drops
    informational fields that add noise without helping the LLM tailor.
    """
    sections: list[str] = []

    required = job_keywords.get("required_skills", [])
    if required:
        sections.append("Required skills to emphasize:\n- " + "\n- ".join(str(s) for s in required))

    preferred = job_keywords.get("preferred_skills", [])
    if preferred:
        sections.append(
            "Preferred skills (include only if resume supports them):\n- "
            + "\n- ".join(str(s) for s in preferred)
        )

    keywords = job_keywords.get("keywords", [])
    if keywords:
        sections.append("Additional keywords to weave in naturally:\n- " + "\n- ".join(str(k) for k in keywords))

    return "\n\n".join(sections) if sections else "No specific keywords extracted."


def _normalize_skill_key(skill: str) -> str:
    """Normalize a skill for case-insensitive comparison."""
    return re.sub(r"\s+", " ", skill.strip()).casefold()


def _extract_skill_index(items: Any) -> dict[str, str]:
    """Build a normalized skill index from a string list."""
    if not isinstance(items, list):
        return {}
    index: dict[str, str] = {}
    for item in items:
        if not isinstance(item, str):
            continue
        skill = item.strip()
        if skill:
            index.setdefault(_normalize_skill_key(skill), skill)
    return index


def _skill_mentioned_in_text(skill: str, text: str) -> bool:
    """Return True when a skill phrase appears as a whole term in text."""
    escaped = re.escape(skill.strip().lower())
    if not escaped:
        return False
    return bool(re.search(rf"(?<!\w){escaped}(?!\w)", text.lower()))


def _build_allowed_skill_target_keys(
    allowed_skill_targets: list[dict[str, Any] | str] | None,
) -> set[str]:
    """Build normalized keys for skills approved by the planning verifier."""
    keys: set[str] = set()
    for target in allowed_skill_targets or []:
        if isinstance(target, str):
            skill = target
        elif isinstance(target, dict):
            skill = str(target.get("skill", ""))
        else:
            continue
        if skill.strip():
            keys.add(_normalize_skill_key(skill))
    return keys


def _extract_jd_skill_index(
    job_keywords: dict[str, Any],
    job_description: str | None = None,
) -> dict[str, str]:
    """Build a normalized index of explicit JD skills."""
    index: dict[str, str] = {}
    for field in ("required_skills", "preferred_skills"):
        values = job_keywords.get(field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, str):
                continue
            skill = value.strip()
            if skill and (
                job_description is None
                or _skill_mentioned_in_text(skill, job_description)
            ):
                index.setdefault(_normalize_skill_key(skill), skill)
    return index


def _skill_present_in_resume_text(skill: str, resume_data: dict[str, Any]) -> bool:
    """Return True when a skill phrase already appears in the resume text."""
    text = json.dumps(resume_data, ensure_ascii=False)
    return _skill_mentioned_in_text(skill, text)


def verify_skill_target_plan(
    raw_plan: dict[str, Any],
    original_resume_data: dict[str, Any],
    job_keywords: dict[str, Any],
    job_description: str | None = None,
) -> dict[str, list[dict[str, str]] | str]:
    """Filter and classify LLM-proposed skill targets before diff generation.

    Existing resume skills are accepted as low-risk targets. Required and
    preferred JD skills are accepted as explicit JD-added targets for user
    review. Other skills are accepted only when they already appear in the
    resume text.
    """
    original_skills = _extract_skill_index(
        original_resume_data.get("additional", {}).get("technicalSkills", [])
    )
    jd_skills = _extract_jd_skill_index(job_keywords, job_description)
    raw_targets = raw_plan.get("target_skills", [])
    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    seen: set[str] = set()

    if not isinstance(raw_targets, list):
        raw_targets = []

    for target in raw_targets:
        if isinstance(target, str):
            skill = target.strip()
            reason = ""
        elif isinstance(target, dict):
            skill = str(target.get("skill", "")).strip()
            reason = str(target.get("reason", "")).strip()
        else:
            continue

        skill_key = _normalize_skill_key(skill)
        if not skill or skill_key in seen:
            continue
        seen.add(skill_key)

        if skill_key in original_skills:
            accepted.append(
                {
                    "skill": original_skills[skill_key],
                    "source": "existing",
                    "reason": reason or "Already present in resume skills",
                }
            )
        elif skill_key in jd_skills:
            # JD-required/preferred skills are accepted as targets so the résumé
            # can be tailored to actually pass ATS/recruiter screening — adding
            # relevant JD skills is the product's purpose. (Truly unsupported
            # skills — neither in the JD nor the résumé — are still rejected
            # below.) The user reviews additions in the diff preview before save.
            accepted.append(
                {
                    "skill": jd_skills[skill_key],
                    "source": "jd_added",
                    "reason": reason or "Required or preferred by the job description",
                }
            )
        elif _skill_present_in_resume_text(skill, original_resume_data):
            accepted.append(
                {
                    "skill": skill,
                    "source": "supported_by_resume",
                    "reason": reason or "Appears in the existing resume content",
                }
            )
        else:
            rejected.append(
                {
                    "skill": skill,
                    "source": "unsupported",
                    "reason": reason or "Not found in resume or job keywords",
                }
            )

    return {
        "accepted": accepted,
        "rejected": rejected,
        "strategy_notes": str(raw_plan.get("strategy_notes", "")),
    }


async def generate_skill_target_plan(
    original_resume_data: dict[str, Any],
    job_description: str,
    job_keywords: dict[str, Any],
    language: str = "en",
) -> dict[str, Any]:
    """Ask the LLM for a compact skill target plan before editing diffs."""
    output_language = get_language_name(language)
    existing_skills = original_resume_data.get("additional", {}).get(
        "technicalSkills", []
    )
    sanitized_jd = _sanitize_user_input(job_description)
    prompt = SKILL_TARGET_PLAN_PROMPT.format(
        output_language=output_language,
        existing_skills=json.dumps(existing_skills, ensure_ascii=False),
        job_keywords=_prepare_keywords_for_prompt(job_keywords),
        job_description=sanitized_jd,
        original_resume=json.dumps(original_resume_data, ensure_ascii=False),
    )

    result = await complete_json(
        prompt=prompt,
        system_prompt=(
            "You are a resume skill planning agent. Output only valid JSON with "
            "target_skills and strategy_notes."
        ),
        max_tokens=2048,
        schema_type="diff",
        response_validator=_validate_skill_plan_result,
    )
    return _validate_skill_plan_result(result)


def _prepare_skill_targets_for_prompt(
    skill_targets: list[dict[str, Any]] | None,
) -> str:
    """Format verified skill targets for the diff prompt."""
    if not skill_targets:
        return "No verified skill targets."
    lines: list[str] = []
    for target in skill_targets:
        skill = str(target.get("skill", "")).strip()
        if not skill:
            continue
        source = str(target.get("source", "unknown")).strip() or "unknown"
        reason = str(target.get("reason", "")).strip()
        suffix = f": {reason}" if reason else ""
        lines.append(f"- {skill} ({source}){suffix}")
    return "\n".join(lines) if lines else "No verified skill targets."


async def improve_resume(
    original_resume: str,
    job_description: str,
    job_keywords: dict[str, Any],
    language: str = "en",
    prompt_id: str | None = None,
    original_resume_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Improve resume to better match job description.

    Args:
        original_resume: Original resume content (markdown)
        job_description: Target job description
        job_keywords: Extracted job keywords
        language: Output language code (en, es, zh, ja)
        prompt_id: Which tailor prompt to use
        original_resume_data: Structured resume JSON; used instead of
            markdown when available for higher-fidelity LLM input

    Returns:
        Improved resume data matching ResumeData schema

    LLM-006: Validates the structured result inside the content-retry budget.
    LLM-011: Sanitizes job description to prevent prompt injection.
    """
    keywords_str = _prepare_keywords_for_prompt(job_keywords)
    output_language = get_language_name(language)

    selected_prompt_id = prompt_id or DEFAULT_IMPROVE_PROMPT_ID
    prompt_template = IMPROVE_RESUME_PROMPTS.get(
        selected_prompt_id, IMPROVE_RESUME_PROMPTS[DEFAULT_IMPROVE_PROMPT_ID]
    )
    if selected_prompt_id not in CRITICAL_TRUTHFULNESS_RULES:
        logger.warning(
            "Missing truthfulness rules for prompt '%s'; using default rules.",
            selected_prompt_id,
        )
    truthfulness_rules = CRITICAL_TRUTHFULNESS_RULES.get(
        selected_prompt_id, CRITICAL_TRUTHFULNESS_RULES[DEFAULT_IMPROVE_PROMPT_ID]
    )

    # LLM-011: Sanitize job description to prevent prompt injection
    sanitized_jd = _sanitize_user_input(job_description)

    # Use structured JSON when available for higher-fidelity LLM input,
    # but fall back to raw markdown if the structured data has truncated
    # (year-only) dates — the markdown preserves months from the original PDF.
    if original_resume_data is not None:
        if _has_month_in_dates(original_resume_data):
            resume_input = json.dumps(original_resume_data)
        else:
            logger.info(
                "Structured resume data has year-only dates; using raw markdown "
                "to preserve month precision."
            )
            resume_input = original_resume
    else:
        resume_input = original_resume

    prompt = prompt_template.format(
        job_description=sanitized_jd,
        job_keywords=keywords_str,
        original_resume=resume_input,
        schema=IMPROVE_SCHEMA_EXAMPLE,
        output_language=output_language,
        critical_truthfulness_rules=truthfulness_rules,
    )

    result = await complete_json(
        prompt=prompt,
        system_prompt="You are an expert resume editor. Output only valid JSON.",
        max_tokens=8192,
        response_validator=_validate_resume_result,
    )
    return _validate_resume_result(result)


def _format_entry_label(parts: list[str], fallback: str) -> str:
    label = " | ".join([part for part in parts if part])
    return label if label else fallback


def _format_experience_entry(entry: dict[str, Any], index: int) -> str:
    return _format_entry_label(
        [
            entry.get("title", ""),
            entry.get("company", ""),
            entry.get("years", ""),
        ],
        f"Work experience #{index + 1}",
    )


def _format_education_entry(entry: dict[str, Any], index: int) -> str:
    return _format_entry_label(
        [
            entry.get("degree", ""),
            entry.get("institution", ""),
            entry.get("years", ""),
        ],
        f"Education #{index + 1}",
    )


def _format_project_entry(entry: dict[str, Any], index: int) -> str:
    return _format_entry_label(
        [
            entry.get("name", ""),
            entry.get("role", ""),
            entry.get("years", ""),
        ],
        f"Project #{index + 1}",
    )


def _normalize_entry(
    entry: dict[str, Any],
    ignore_keys: set[str] | None,
) -> dict[str, Any]:
    """Return an entry dict with ignored keys removed for diff comparisons.

    Ignored keys are excluded so entry-level change detection can skip fields
    that are diffed separately (e.g., description lists).
    """
    if ignore_keys is None:
        return entry
    return {key: value for key, value in entry.items() if key not in ignore_keys}


def _entry_scalar_changes(
    original_entry: dict[str, Any],
    improved_entry: dict[str, Any],
    ignore_keys: set[str],
) -> list[tuple[str, str, str]]:
    """Scalar field changes (whitespace-normalized), excluding complex fields.

    List/dict fields (descriptions, styles) are either diffed separately or
    intentionally ignored at entry level, so they never appear here.
    """
    scalar_changes: list[tuple[str, str, str]] = []
    keys = set(original_entry.keys()) | set(improved_entry.keys())
    for key in sorted(keys):
        if key in ignore_keys:
            continue
        old_raw = original_entry.get(key)
        new_raw = improved_entry.get(key)
        if isinstance(old_raw, (list, dict)) or isinstance(new_raw, (list, dict)):
            continue
        old_text = "" if old_raw is None else str(old_raw).strip()
        new_text = "" if new_raw is None else str(new_raw).strip()
        if old_text != new_text:
            scalar_changes.append((key, old_text, new_text))
    return scalar_changes


def _entry_diff_values(
    original_entry: dict[str, Any],
    improved_entry: dict[str, Any],
    formatter: Callable[[dict[str, Any], int], str],
    index: int,
    ignore_keys: set[str],
) -> tuple[str, str] | None:
    """Before/after text for a modified entry, or None when nothing visible moved.

    The formatted header (title | company | years, etc.) is the primary view.
    When the header is identical but secondary scalar fields changed (e.g.
    location), those "field: value" lines are appended so the two sides never
    render as a meaningless identical pair.
    """
    header_before = formatter(original_entry, index)
    header_after = formatter(improved_entry, index)
    header_changed = header_before.strip() != header_after.strip()
    scalar_changes = _entry_scalar_changes(original_entry, improved_entry, ignore_keys)
    if not scalar_changes and not header_changed:
        return None
    if header_changed or not scalar_changes:
        return header_before, header_after
    detail_before = "\n".join(
        f"{key}: {text}" for key, text, _ in scalar_changes if text
    )
    detail_after = "\n".join(
        f"{key}: {text}" for key, _old, text in scalar_changes if text
    )
    before = f"{header_before}\n{detail_before}" if detail_before else header_before
    after = f"{header_after}\n{detail_after}" if detail_after else header_after
    return before, after


def _append_entry_changes(
    changes: list[ResumeFieldDiff],
    field_key: str,
    field_type: str,
    original_items: list[dict[str, Any]],
    improved_items: list[dict[str, Any]],
    formatter: Callable[[dict[str, Any], int], str],
    ignore_keys: set[str] | None = None,
) -> None:
    min_len = min(len(original_items), len(improved_items))
    ignored = ignore_keys or set()

    for idx in range(min_len):
        original_entry = original_items[idx]
        improved_entry = improved_items[idx]
        if _normalize_entry(original_entry, ignore_keys) != _normalize_entry(
            improved_entry, ignore_keys
        ):
            diff_values = _entry_diff_values(
                original_entry, improved_entry, formatter, idx, ignored
            )
            if diff_values is None:
                # Only ignored/complex fields differ (e.g. description styles
                # realignment); their text changes are reported separately.
                continue
            changes.append(
                ResumeFieldDiff(
                    field_path=f"{field_key}[{idx}]",
                    field_type=field_type,
                    change_type="modified",
                    original_value=diff_values[0],
                    new_value=diff_values[1],
                    confidence="medium",
                )
            )

    for idx in range(min_len, len(improved_items)):
        changes.append(
            ResumeFieldDiff(
                field_path=f"{field_key}[{idx}]",
                field_type=field_type,
                change_type="added",
                new_value=formatter(improved_items[idx], idx),
                confidence="high",
            )
        )

    for idx in range(min_len, len(original_items)):
        changes.append(
            ResumeFieldDiff(
                field_path=f"{field_key}[{idx}]",
                field_type=field_type,
                change_type="removed",
                original_value=formatter(original_items[idx], idx),
                confidence="medium",
            )
        )


def _normalize_string_list(value: Any, field_name: str) -> list[str]:
    """Normalize string list values and log any non-string entries.

    Accepts lists of strings or objects containing name/label/value keys.
    """
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    invalid_count = 0
    for item in value:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                normalized.append(stripped)
            continue
        if isinstance(item, dict):
            candidate = item.get("name") or item.get("label") or item.get("value")
            if isinstance(candidate, str):
                stripped = candidate.strip()
                if stripped:
                    normalized.append(stripped)
                else:
                    invalid_count += 1
            else:
                invalid_count += 1
            continue
        if item is None:
            continue
        invalid_count += 1
    if invalid_count:
        logger.warning("Skipped non-string entries in %s: %d", field_name, invalid_count)
    return normalized


def _build_string_index(value: Any, field_name: str) -> dict[str, str]:
    """Build a case-insensitive index for string list comparisons."""
    items = _normalize_string_list(value, field_name)
    index: dict[str, str] = {}
    for item in items:
        key = item.casefold()
        if key not in index:
            index[key] = item
    return index


def _extract_description_list(entry: Any) -> list[str]:
    if not isinstance(entry, dict):
        return []
    return _normalize_string_list(entry.get("description", []), "workExperience.description")


def _append_list_changes(
    changes: list[ResumeFieldDiff],
    field_path: str,
    field_type: str,
    original_items: list[str],
    improved_items: list[str],
    confidences: DiffConfidence,
) -> None:
    matcher = SequenceMatcher(a=original_items, b=improved_items, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            for item in original_items[i1:i2]:
                changes.append(
                    ResumeFieldDiff(
                        field_path=field_path,
                        field_type=field_type,
                        change_type="removed",
                        original_value=item,
                        confidence=confidences.removed,
                    )
                )
        elif tag == "insert":
            for item in improved_items[j1:j2]:
                changes.append(
                    ResumeFieldDiff(
                        field_path=field_path,
                        field_type=field_type,
                        change_type="added",
                        new_value=item,
                        confidence=confidences.added,
                    )
                )
        elif tag == "replace":
            original_segment = original_items[i1:i2]
            improved_segment = improved_items[j1:j2]
            segment_len = max(len(original_segment), len(improved_segment))
            for offset in range(segment_len):
                original_value = (
                    original_segment[offset] if offset < len(original_segment) else None
                )
                new_value = (
                    improved_segment[offset] if offset < len(improved_segment) else None
                )
                if original_value is not None and new_value is not None:
                    changes.append(
                        ResumeFieldDiff(
                            field_path=field_path,
                            field_type=field_type,
                            change_type="modified",
                            original_value=original_value,
                            new_value=new_value,
                            confidence=confidences.modified,
                        )
                    )
                elif new_value is not None:
                    changes.append(
                        ResumeFieldDiff(
                            field_path=field_path,
                            field_type=field_type,
                            change_type="added",
                            new_value=new_value,
                            confidence=confidences.added,
                        )
                    )
                elif original_value is not None:
                    changes.append(
                        ResumeFieldDiff(
                            field_path=field_path,
                            field_type=field_type,
                            change_type="removed",
                            original_value=original_value,
                            confidence=confidences.removed,
                        )
                    )


def calculate_resume_diff(
    original: dict[str, Any],
    improved: dict[str, Any],
) -> tuple[ResumeDiffSummary, list[ResumeFieldDiff]]:
    """Compute the diff between original and improved resumes.

    Args:
        original: Original resume data dict
        improved: Improved resume data dict

    Returns:
        (diff summary, detailed change list)
    """
    changes: list[ResumeFieldDiff] = []

    # 1. Compare summary
    original_summary = (original.get("summary") or "").strip()
    improved_summary = (improved.get("summary") or "").strip()
    if original_summary != improved_summary:
        if original_summary and not improved_summary:
            change_type = "removed"
        elif improved_summary and not original_summary:
            change_type = "added"
        else:
            change_type = "modified"
        changes.append(
            ResumeFieldDiff(
                field_path="summary",
                field_type="summary",
                change_type=change_type,
                original_value=original_summary or None,
                new_value=improved_summary or None,
                confidence="medium",
            )
        )

    # 2. Compare skills (order changes are intentionally ignored)
    orig_skills = _build_string_index(
        original.get("additional", {}).get("technicalSkills", []),
        "additional.technicalSkills",
    )
    new_skills = _build_string_index(
        improved.get("additional", {}).get("technicalSkills", []),
        "additional.technicalSkills",
    )
    orig_skill_keys = set(orig_skills)
    new_skill_keys = set(new_skills)

    # An elaborated entry ("Redis" -> "Redis：高可用缓存设计与热点 key 治理")
    # is one modification, not a removal plus an addition. Pair on the bare
    # skill-name prefix (longest old name first so "Spring Boot" wins).
    added_keys = list(new_skill_keys - orig_skill_keys)
    removed_keys = list(orig_skill_keys - new_skill_keys)
    elaborated_pairs: list[tuple[str, str]] = []
    for added_key in added_keys:
        base = next(
            (
                old_key
                for old_key in sorted(removed_keys, key=len, reverse=True)
                if added_key.startswith(old_key)
                and _skill_detail_boundary(added_key[len(old_key) :])
            ),
            None,
        )
        if base is not None:
            elaborated_pairs.append((base, added_key))
    # Fallback for proficiency-first rewrites: "Redis" -> "熟练掌握 Redis 核心
    # 数据结构……" (the bare name sits mid-sentence, so prefix pairing misses).
    # Only bare single-technology entries are eligible; pair greedily on the
    # strongest bounded-name + text similarity, one-to-one.
    bare_removed = [
        key
        for key in removed_keys
        if len(key) >= 2
        and len(key) <= 24
        and not any(sep in key for sep in "、：:，,;；/")
    ]
    rewrite_candidates: list[tuple[float, str, str]] = []
    for added_key in added_keys:
        if added_key in {added for _, added in elaborated_pairs}:
            continue
        for old_key in bare_removed:
            if not _skill_appears_in_text(old_key, added_key):
                continue
            ratio = SequenceMatcher(None, old_key, added_key).ratio()
            if ratio >= _SKILL_REWRITE_MIN_RATIO:
                rewrite_candidates.append((ratio, old_key, added_key))
    for _, old_key, added_key in sorted(
        rewrite_candidates, key=lambda item: item[0], reverse=True
    ):
        if old_key in {base for base, _ in elaborated_pairs} or added_key in {
            added for _, added in elaborated_pairs
        }:
            continue
        elaborated_pairs.append((old_key, added_key))

    elaborated_bases = {base for base, _ in elaborated_pairs}
    elaborated_added = {added for _, added in elaborated_pairs}
    for base, added in elaborated_pairs:
        changes.append(
            ResumeFieldDiff(
                field_path="additional.technicalSkills",
                field_type="skill",
                change_type="modified",
                original_value=orig_skills[base],
                new_value=new_skills[added],
                confidence="high",
            )
        )

    for skill_key in added_keys:
        if skill_key in elaborated_added:
            continue
        changes.append(ResumeFieldDiff(
            field_path="additional.technicalSkills",
            field_type="skill",
            change_type="added",
            new_value=new_skills[skill_key],
            confidence="high"  # Newly added skills are high risk
        ))

    for skill_key in removed_keys:
        if skill_key in elaborated_bases:
            continue
        changes.append(ResumeFieldDiff(
            field_path="additional.technicalSkills",
            field_type="skill",
            change_type="removed",
            original_value=orig_skills[skill_key],
            confidence="medium"
        ))

    # 3. Compare work experience descriptions
    original_experiences = original.get("workExperience", [])
    improved_experiences = improved.get("workExperience", [])
    max_experience_len = max(len(original_experiences), len(improved_experiences))
    confidences = DiffConfidence(added="medium", removed="low", modified="medium")
    for idx in range(max_experience_len):
        original_entry = (
            original_experiences[idx] if idx < len(original_experiences) else None
        )
        improved_entry = (
            improved_experiences[idx] if idx < len(improved_experiences) else None
        )
        if not original_entry and not improved_entry:
            continue
        _append_list_changes(
            changes,
            field_path=f"workExperience[{idx}].description",
            field_type="description",
            original_items=_extract_description_list(original_entry),
            improved_items=_extract_description_list(improved_entry),
            confidences=confidences,
        )

    # 3b. Compare project descriptions (same list semantics as work experience)
    original_projects = original.get("personalProjects", [])
    improved_projects = improved.get("personalProjects", [])
    if not isinstance(original_projects, list):
        original_projects = []
    if not isinstance(improved_projects, list):
        improved_projects = []
    for idx in range(max(len(original_projects), len(improved_projects))):
        original_entry = (
            original_projects[idx] if idx < len(original_projects) else None
        )
        improved_entry = (
            improved_projects[idx] if idx < len(improved_projects) else None
        )
        if not original_entry and not improved_entry:
            continue
        _append_list_changes(
            changes,
            field_path=f"personalProjects[{idx}].description",
            field_type="description",
            original_items=_extract_description_list(original_entry),
            improved_items=_extract_description_list(improved_entry),
            confidences=confidences,
        )

    # 4. Compare certifications (order changes are intentionally ignored)
    orig_certs = _build_string_index(
        original.get("additional", {}).get("certificationsTraining", []),
        "additional.certificationsTraining",
    )
    new_certs = _build_string_index(
        improved.get("additional", {}).get("certificationsTraining", []),
        "additional.certificationsTraining",
    )
    orig_cert_keys = set(orig_certs)
    new_cert_keys = set(new_certs)
    for cert_key in new_cert_keys - orig_cert_keys:
        changes.append(ResumeFieldDiff(
            field_path="additional.certificationsTraining",
            field_type="certification",
            change_type="added",
            new_value=new_certs[cert_key],
            confidence="high"
        ))

    for cert_key in orig_cert_keys - new_cert_keys:
        changes.append(ResumeFieldDiff(
            field_path="additional.certificationsTraining",
            field_type="certification",
            change_type="removed",
            original_value=orig_certs[cert_key],
            confidence="medium"
        ))

    # 4b. Compare education descriptions (a single string per entry, not a list)
    original_education = original.get("education", [])
    improved_education = improved.get("education", [])
    for idx in range(max(len(original_education), len(improved_education))):
        orig_entry = original_education[idx] if idx < len(original_education) else None
        impr_entry = improved_education[idx] if idx < len(improved_education) else None
        orig_desc = (
            str(orig_entry.get("description") or "").strip()
            if isinstance(orig_entry, dict)
            else ""
        )
        impr_desc = (
            str(impr_entry.get("description") or "").strip()
            if isinstance(impr_entry, dict)
            else ""
        )
        if orig_desc == impr_desc:
            continue
        if orig_desc and not impr_desc:
            change_type = "removed"
        elif impr_desc and not orig_desc:
            change_type = "added"
        else:
            change_type = "modified"
        changes.append(ResumeFieldDiff(
            field_path=f"education[{idx}].description",
            field_type="education",
            change_type=change_type,
            original_value=orig_desc or None,
            new_value=impr_desc or None,
            confidence="medium",
        ))

    # 4c. Compare languages (order changes are intentionally ignored)
    orig_langs = _build_string_index(
        original.get("additional", {}).get("languages", []),
        "additional.languages",
    )
    new_langs = _build_string_index(
        improved.get("additional", {}).get("languages", []),
        "additional.languages",
    )
    for lang_key in set(new_langs) - set(orig_langs):
        changes.append(ResumeFieldDiff(
            field_path="additional.languages",
            field_type="language",
            change_type="added",
            new_value=new_langs[lang_key],
            confidence="high",
        ))
    for lang_key in set(orig_langs) - set(new_langs):
        changes.append(ResumeFieldDiff(
            field_path="additional.languages",
            field_type="language",
            change_type="removed",
            original_value=orig_langs[lang_key],
            confidence="medium",
        ))

    # 4d. Compare awards (order changes are intentionally ignored)
    orig_awards = _build_string_index(
        original.get("additional", {}).get("awards", []),
        "additional.awards",
    )
    new_awards = _build_string_index(
        improved.get("additional", {}).get("awards", []),
        "additional.awards",
    )
    for award_key in set(new_awards) - set(orig_awards):
        changes.append(ResumeFieldDiff(
            field_path="additional.awards",
            field_type="award",
            change_type="added",
            new_value=new_awards[award_key],
            confidence="high",
        ))
    for award_key in set(orig_awards) - set(new_awards):
        changes.append(ResumeFieldDiff(
            field_path="additional.awards",
            field_type="award",
            change_type="removed",
            original_value=orig_awards[award_key],
            confidence="medium",
        ))

    # 5. Compare added/removed/modified entries.
    # Descriptions are diffed separately (steps 3/3b/4b); description styles
    # are rendering metadata, not user-visible text; ids are model-assigned.
    # All three are ignored when detecting entry-level header changes.
    _append_entry_changes(
        changes,
        "workExperience",
        "experience",
        original.get("workExperience", []),
        improved.get("workExperience", []),
        _format_experience_entry,
        {"description", "descriptionStyles", "id"},
    )
    _append_entry_changes(
        changes,
        "education",
        "education",
        original.get("education", []),
        improved.get("education", []),
        _format_education_entry,
        {"description", "id"},  # description diffed separately in step 4b — no duplicate
    )
    _append_entry_changes(
        changes,
        "personalProjects",
        "project",
        original.get("personalProjects", []),
        improved.get("personalProjects", []),
        _format_project_entry,
        {"description", "descriptionStyles", "id"},  # descriptions diffed in step 3b
    )

    # 6. Build summary
    summary = ResumeDiffSummary(
        total_changes=len(changes),
        skills_added=len([c for c in changes if c.field_type == "skill" and c.change_type == "added"]),
        skills_removed=len([c for c in changes if c.field_type == "skill" and c.change_type == "removed"]),
        descriptions_modified=len(
            [
                c
                for c in changes
                if c.field_type == "description" and c.change_type == "modified"
            ]
        ),
        certifications_added=len([c for c in changes if c.field_type == "certification" and c.change_type == "added"]),
        high_risk_changes=len([c for c in changes if c.confidence == "high"])
    )

    return summary, changes


def generate_improvements(job_keywords: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate improvement suggestions based on job keywords.

    Args:
        job_keywords: Extracted job keywords

    Returns:
        List of improvement suggestions
    """
    improvements = []

    # Generate suggestions based on required skills
    required_skills = job_keywords.get("required_skills", [])
    for skill in required_skills[:3]:  # Top 3 required skills
        improvements.append(
            {
                "suggestion": f"Emphasized '{skill}' to match job requirements",
                "lineNumber": None,
            }
        )

    # Generate suggestions based on key responsibilities
    responsibilities = job_keywords.get("key_responsibilities", [])
    for resp in responsibilities[:2]:  # Top 2 responsibilities
        improvements.append(
            {
                "suggestion": f"Aligned experience with: {resp}",
                "lineNumber": None,
            }
        )

    # Default improvement if none generated
    if not improvements:
        improvements.append(
            {
                "suggestion": "Resume content optimized for better keyword alignment with job description",
                "lineNumber": None,
            }
        )

    return improvements
