"""Deterministic checks for the V4-optimized resume rubric (checklist edition).

Every checker here answers one rubric item from the structured ResumeData
alone — no LLM — so hard verdicts (basic info, work-experience three elements,
timeline consistency, tenure arithmetic, employment gaps, short stints) are
reproducible and unit-testable. The remaining items are judged by the LLM (see
``app/services/diagnosis.py``), which also receives the ``facts`` packet
computed here.

V4 id map covered here:

* 1 格式规范 — block order (degree-branched) + section title governance
  (duplicates / renamed defaults / titled-but-empty optional blocks) +
  oversized paragraphs (date-format and cross-record conflicts are
  adjudicated by item 13, which owns all timeline checks, not here)
* 2 版式与篇幅 — page-count estimate (watermark/alignment go to the LLM)
* 3 内容布局 — five required modules (unconditional in V4) + 个人优势 gating
* 4 基本信息 / 5 教育经历 / 6 个人优势 / 7 专业技能 / 8 工作经历 /
  9 项目经验 / 10 自我评价
* 11 培训与证书 / 12 荣誉奖项 — objectively na when the optional module
  renders no entries (empty list or the additional meta is hidden); when
  entries exist they go to the LLM for relevance / count / ordering judgment
  (additional.certificationsTraining / additional.awards)
* 13 时间线自洽 — date format, reversed/future dates, education-education and
  work-work overlaps (with the rubric's annotated exemptions), project dates
  contained in the owning work tenure, work-start vs highest-degree
  enrollment, and stated years vs computed tenure
* 14 任职连续性 — stability *risk markers* (never a veto in V4; item 16 is the
  only red line)
* 15 职业成长性 — na below 5 effective dev years; otherwise LLM-judged
* 16 风险与合规 — privacy scan (fraud/confidentiality go to the LLM)

A verdict is a ``(rating, evidence, suggestion)`` triple where rating is one
of the constants from ``diagnosis_rules``. Evidence is a short Chinese string
naming the concrete signal that drove the rating; suggestion is the concrete
fix for *that signal* and stays empty when the signal is conform/na. When
several signals merge into one item, only non-conforming signals contribute
text — a problem row never carries positive notes or advice about the
sub-checks that passed.
"""

import copy
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NamedTuple

from app.schemas.diagnosis import (
    LayoutLocatorIn,
    LayoutPointIn,
    RenderedLayoutIn,
    TemplateSettingsIn,
)
from app.schemas.models import DEFAULT_SECTION_META
from app.services.diagnosis_rules import (
    RATING_CONFORM,
    RATING_NA,
    RATING_NONCONFORM,
    RATING_PARTIAL,
)
from app.services.section_order import (
    CANONICAL_SEQUENCE_FORMAL,
    CANONICAL_SEQUENCE_OTHER,
    CUSTOM_CLUSTER_SYMBOL,
    DEFAULT_SECTION_KEYS,
    REQUIRED_KEYS,
    canonicalize_section_meta,
    classify_highest_degree,
    is_accepted_default_title,
    is_section_empty,
    section_symbol,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Text / date helpers
# ---------------------------------------------------------------------------

_CHARS_PER_LINE = 46  # CJK chars per rendered line at the resume content width
_CHARS_PER_PAGE = 950  # CJK chars per A4 page at swiss-single density (estimate)

_DATE_RE = re.compile(
    r"(\d{4})\s*(?:[.\-/年]\s*(\d{1,2})\s*月?)?"
)
_OPEN_ENDED_RE = re.compile(r"至今|现在|当前|目前|今|present|current|now|till|to date", re.IGNORECASE)
_STATED_YEARS_RE = re.compile(r"工作年限[：:\s]*(\d{1,2}(?:\.\d+)?)\s*年")
_ID_CARD_RE = re.compile(r"\d{17}[\dXx]|\b\d{15}\b")
_PRIVACY_LABEL_RE = re.compile(r"(身份证号?码?|家庭住址|银行卡号|家人信息)[:：]?\s*\S+")
_PHONE_RE = re.compile(r"1[3-9]\d{9}")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_ENUMERATION_RE = re.compile(
    r"(?:^|[\n；;])\s*(?:\d{1,2}[.、)]|（\d{1,2}）|\(\d{1,2}\)|[①-⑳]|[•·▪\-*])"
)

# Item 7: mainstream stack groups (Java backend, 2026 profile from spec).
#
# Fields per group:
#   key    — stable id used by the LLM semantic-review protocol;
#   name   — public evidence name (quoted in client evidence when HIT);
#   pattern— deterministic regex over the 专业技能 entries;
#   hint   — public suggestion example, used ONLY when the group stays missing;
#   equiv  — SERVER-SIDE equivalence guidance for the LLM semantic review
#            (what may legitimately rescue a regex miss). It is injected into
#            the judge prompt only and never leaves the server.
class _StackGroup(NamedTuple):
    key: str
    name: str
    pattern: re.Pattern[str]
    hint: str
    equiv: str


_MAINSTREAM_GROUPS: tuple[_StackGroup, ...] = (
    _StackGroup(
        "spring_boot",
        "Spring Boot",
        re.compile(r"spring\s*boot", re.IGNORECASE),
        "服务框架（Spring Boot）",
        "JVM 服务端框架即可：Spring Boot、Spring MVC、Spring Framework、"
        "Jakarta EE/Java EE、Quarkus、Micronaut、Dropwizard；仅写"
        "「框架」「微服务」这类泛称不算",
    ),
    _StackGroup(
        "spring_cloud",
        "Spring Cloud Alibaba",
        re.compile(r"spring\s*cloud", re.IGNORECASE),
        "微服务框架（Spring Cloud Alibaba）",
        "微服务治理框架或其具体组件：Spring Cloud Alibaba、Nacos、Sentinel、"
        "Seata、Dubbo、OpenFeign、Spring Cloud Gateway、Eureka、Hystrix；"
        "仅写「微服务架构」「分布式」概念词不算",
    ),
    _StackGroup(
        "rdbms",
        "MySQL",
        re.compile(r"mysql", re.IGNORECASE),
        "关系型数据库（MySQL）",
        "关系型数据库或直接操作它的持久层框架：PostgreSQL、Oracle、SQL Server、"
        "MariaDB、达梦、金仓、MyBatis/MyBatis-Plus、JPA、Hibernate；"
        "Redis/MongoDB 等非关系型存储不算",
    ),
    _StackGroup(
        "redis",
        "Redis",
        re.compile(r"redis", re.IGNORECASE),
        "缓存中间件（Redis）",
        "分布式缓存/键值中间件：Redis、Memcached、Tair、KeyDB；本地缓存"
        "（Caffeine、Guava Cache）与仅写「缓存优化」不算",
    ),
    _StackGroup(
        "mq",
        "消息队列 MQ",
        re.compile(r"rocketmq|rabbitmq|activemq|kafka|(?:消息队列)|\bmq\b", re.IGNORECASE),
        "消息队列中间件（RocketMQ、Kafka）",
        "消息中间件：RocketMQ、Kafka、RabbitMQ、ActiveMQ、Pulsar，或"
        "「消息队列/MQ/消息中间件」字样；Redis 发布订阅、Spring 事件总线不算",
    ),
    _StackGroup(
        "jvm",
        "JVM",
        re.compile(r"\bjvm\b", re.IGNORECASE),
        "JVM 原理与调优",
        "Java 虚拟机运行时主题：JVM、Java 虚拟机、GC/垃圾回收、类加载机制、"
        "JMM/Java 内存模型、JVM 调优；仅写「Java」或「性能调优」不算",
    ),
    _StackGroup(
        "concurrency",
        "并发编程",
        re.compile(r"并发|多线程|concurrent", re.IGNORECASE),
        "并发与多线程编程",
        "并发/多线程技术：线程池、锁机制、JUC/java.util.concurrent、"
        "CompletableFuture、NIO/Netty、AQS、CAS；仅写「异步」不算",
    ),
    _StackGroup(
        "ai_app",
        "AI 应用 (Spring AI / LangChain4j)",
        re.compile(r"spring\s*ai|langchain4j|langchain|大模型|llm|ai\s*应用", re.IGNORECASE),
        "AI 应用开发（Spring AI、LangChain4j）",
        "大模型应用开发技术：Spring AI、LangChain4j/LangChain、RAG、AI Agent/"
        "智能体、Function Calling、MCP、向量数据库应用、Embedding 应用；"
        "仅写「关注 AI」「使用 AI 工具」不算",
    ),
    _StackGroup(
        "ai_coding",
        "AI 编码工具 (Codex/Claude Code/Trae)",
        re.compile(r"\bcodex\b|claude\s*code|\btrae\b|vibe\s*coding", re.IGNORECASE),
        "AI 编码工具（Codex、Claude Code、Trae）",
        "具名的 AI 编码助手：Codex、Claude Code、Trae、GitHub Copilot、Cursor、"
        "Windsurf、通义灵码、CodeGeeX、Aider；仅写「AI 编程」泛称不算",
    ),
)

#: Item-7 coverage threshold: 7 of 9 groups conform; 5–6 partial; ≤4 fail.
_STACK_CONFORM_RATIO = 0.75

# Tech vocabulary used to spot a "tech stack" bullet inside project text.
_TECH_VOCAB_RE = re.compile(
    r"java|spring|mysql|redis|rocketmq|rabbitmq|kafka|\bmq\b|jvm|微服务|分布式|"
    r"docker|k8s|kubernetes|elasticsearch|nginx|linux|python|langchain",
    re.IGNORECASE,
)
_METRIC_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|‰|倍|万|亿|个|人|台|条|次|笔|ms|毫秒|秒|分钟|小时|天|"
    r"qps|tps|rt)|提升|提高|降低|减少|缩短|节省|增长|优化了?|下降|节约",
    re.IGNORECASE,
)
_DUTY_RE = re.compile(r"负责|主导|承担|开发|设计|实现|参与|搭建|重构|推动|对接")
_BACKGROUND_RE = re.compile(r"背景|为了解决|由于|业务场景|源于|痛点|旨在|为支撑")
_INTERNSHIP_RE = re.compile(r"实习")

# Item 13 annotated-overlap exemptions: the V4 rubric allows otherwise
# conflicting intervals only when the resume itself carries the note.
_WORK_OVERLAP_NOTE_RE = re.compile(r"兼职|外包")
_EDU_OVERLAP_NOTE_RE = re.compile(r"双学位|联合培养|在职|非全日制|兼职")
_IN_SERVICE_EDU_RE = re.compile(r"在职|非全日制|委培")
_AMATEUR_PROJECT_RE = re.compile(r"个人业余项目|业余项目|个人开源|业余开源|side\s*project", re.IGNORECASE)

# Highest-first: 博士 must be checked before 硕士 (博士研究生 contains 研究生).
_DEGREE_RANK_PATTERNS: tuple[tuple[int, re.Pattern[str]], ...] = (
    (5, re.compile(r"博士")),
    (4, re.compile(r"硕士|研究生")),
    (3, re.compile(r"本科")),
    (2, re.compile(r"大专|专科|高职")),
    (1, re.compile(r"中专|中职|技校|高中")),
)


def _now_point() -> tuple[int, int]:
    """Current (year, month)."""
    now = datetime.now()
    return now.year, now.month


@dataclass(frozen=True)
class Interval:
    """A parsed [start, end] month range; end is None when open-ended."""

    start: tuple[int, int]
    end: tuple[int, int] | None
    raw: str
    label: str

    @property
    def length_months(self) -> int:
        """Inclusive month count (open-ended intervals count up to today)."""
        ey, em = self.end or _now_point()
        sy, sm = self.start
        return max(1, (ey - sy) * 12 + (em - sm) + 1)


def _month_index(year: int, month: int) -> int:
    """Months since epoch (ordering/arithmetic only)."""
    return year * 12 + (month - 1)


def _today_index() -> int:
    return _month_index(*_now_point())


def parse_date_range(raw: str | None) -> Interval | None:
    """Parse strings like ``2019.09 - 2021.06`` / ``2024.03 至今``.

    Returns None when no year is present.
    """
    if not raw or not isinstance(raw, str):
        return None
    matches = list(_DATE_RE.finditer(raw))
    if not matches:
        return None

    def point(match: re.Match[str]) -> tuple[int, int]:
        year = int(match.group(1))
        month = int(match.group(2)) if match.group(2) else 7
        return year, month

    start = point(matches[0])
    tail = raw[matches[0].end() :]
    if len(matches) >= 2:
        end: tuple[int, int] | None = point(matches[1])
    elif _OPEN_ENDED_RE.search(tail):
        end = None  # Open-ended ("2024.03 至今")
    else:
        end = start  # Single point in time; counts as one month
    return Interval(start=start, end=end, raw=raw.strip(), label=raw.strip())


def count_points(text: str | None) -> int:
    """Estimate the number of enumerated points in a free-text block."""
    if not text or not text.strip():
        return 0
    markers = _ENUMERATION_RE.findall(text)
    if len(markers) >= 2:
        return len(markers)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 2:
        return len(lines)
    segments = [segment.strip() for segment in re.split(r"[；;]", text) if segment.strip()]
    return max(1, len(segments))


@dataclass(frozen=True)
class LocatedBlock:
    """One free-text block plus the locator parts of its owning record.

    Mirrors the frontend ``enumerateExpectedPoints`` traversal: summary;
    work/project ``description[]`` elements; custom-section text and custom
    item descriptions.
    """

    text: str
    kind: str  # summary | entry | custom_text | custom_item
    scope: str  # summary | workExperience | personalProjects | custom key
    section_title: str = ""
    entry_title: str = ""
    section: str | None = None  # entry sections only
    custom_key: str | None = None  # custom sections only
    entry_index: int = -1


def _section_title_map(resume: dict[str, Any]) -> dict[str, str]:
    titles: dict[str, str] = {}
    meta = resume.get("sectionMeta")
    if isinstance(meta, list):
        for row in meta:
            if isinstance(row, dict):
                key = row.get("key")
                name = row.get("displayName")
                if isinstance(key, str) and isinstance(name, str) and name.strip():
                    titles[key] = name.strip()
    return titles


def _work_entry_title(item: dict[str, Any]) -> str:
    parts = [
        str(item.get("company") or "").strip(),
        str(item.get("title") or "").strip(),
    ]
    return " / ".join(part for part in parts if part)


def _entry_point_lines(item: dict[str, Any]) -> list[str]:
    """All non-empty rendered point lines of one entry, bullets flattened.

    Mirrors the renderer and the frontend ``enumerateExpectedPoints``: each
    description element is split on newlines and point lines are indexed
    continuously across bullets (``description.flatMap(nonEmptyLines)``).
    """
    lines: list[str] = []
    for bullet in item.get("description") or []:
        if not isinstance(bullet, str):
            continue
        lines.extend(line.strip() for line in bullet.splitlines() if line.strip())
    return lines


def _iter_located_blocks(resume: dict[str, Any]) -> list[LocatedBlock]:
    """All free-text blocks that could be oversized paragraphs, with locators.

    Traversal and line indexing MUST stay identical to the frontend
    ``enumerateExpectedPoints`` (layout-snapshot.ts), otherwise locator-exact
    alignment of measured points drifts onto the text-search fallback.
    """
    blocks: list[LocatedBlock] = []
    titles = _section_title_map(resume)
    summary = resume.get("summary")
    if isinstance(summary, str) and summary.strip():
        blocks.append(
            LocatedBlock(
                text=summary,
                kind="summary",
                scope="summary",
                section_title=titles.get("summary", ""),
            )
        )
    for key in ("workExperience", "personalProjects"):
        for entry_index, item in enumerate(resume.get(key) or []):
            if not isinstance(item, dict):
                continue
            if key == "personalProjects":
                entry_title = str(item.get("name") or "").strip()
            else:
                entry_title = _work_entry_title(item)
            lines = _entry_point_lines(item)
            if lines:
                blocks.append(
                    LocatedBlock(
                        text="\n".join(lines),
                        kind="entry",
                        scope=key,
                        section_title=titles.get(key, ""),
                        entry_title=entry_title,
                        section=key,
                        entry_index=entry_index,
                    )
                )
    for custom_key, section in (resume.get("customSections") or {}).items():
        if not isinstance(section, dict) or not isinstance(custom_key, str):
            continue
        # Mirror the frontend enumerator: stringList sections render as plain
        # ordered strings and never participate in paragraph checks; sections
        # without a known type are skipped the same way.
        section_type = section.get("sectionType")
        if section_type not in ("text", "itemList"):
            continue
        section_title = titles.get(custom_key, "")
        if section_type == "text":
            text = section.get("text")
            if isinstance(text, str) and text.strip():
                blocks.append(
                    LocatedBlock(
                        text=text,
                        kind="custom_text",
                        scope=custom_key,
                        section_title=section_title,
                        custom_key=custom_key,
                    )
                )
            continue
        for entry_index, item in enumerate(section.get("items") or []):
            if not isinstance(item, dict):
                continue
            entry_title = str(item.get("title") or "").strip()
            lines = _entry_point_lines(item)
            if lines:
                blocks.append(
                    LocatedBlock(
                        text="\n".join(lines),
                        kind="custom_item",
                        scope=custom_key,
                        section_title=section_title,
                        entry_title=entry_title,
                        custom_key=custom_key,
                        entry_index=entry_index,
                    )
                )
    return blocks


def _iter_text_blocks(resume: dict[str, Any]) -> list[str]:
    """All free-text blocks that could be oversized paragraphs."""
    return [block.text for block in _iter_located_blocks(resume)]


# Mirrors the frontend POINT_MARKER_RE (components/resume/list-format.ts):
# leading numbering/bullet markers are display-only and never part of the text.
_POINT_MARKER_RE = re.compile(
    r"^\s*(?:\d{1,2}\s*[.、)）．:：]|[（(]\d{1,2}[)）]|[①②③④⑤⑥⑦⑧⑨⑩]|"
    r"[•·・●▪▸▹◆■\-—–]\s*|[一二三四五六七八九十]{1,3}\s*[、.．)）])\s*"
)


def _norm_point_text(text: str) -> str:
    """Whitespace/emphasis/marker-free comparison form (CJK keeps all chars)."""
    stripped = _POINT_MARKER_RE.sub("", text.strip()).replace("**", "")
    return re.sub(r"\s+", "", stripped)


def _block_point_lines(block: LocatedBlock) -> list[str]:
    """Non-empty lines of a block, split exactly like the renderer splits."""
    return [line.strip() for line in block.text.splitlines() if line.strip()]


def _line_locator(block: LocatedBlock, point_index: int) -> dict[str, Any]:
    if block.kind == "summary":
        return {"kind": "summary", "point_index": point_index}
    if block.kind == "entry":
        return {
            "kind": "entry",
            "section": block.section,
            "entry_index": block.entry_index,
            "point_index": point_index,
        }
    if block.kind == "custom_text":
        return {"kind": "custom_text", "key": block.custom_key, "point_index": point_index}
    return {
        "kind": "custom_item",
        "key": block.custom_key,
        "entry_index": block.entry_index,
        "point_index": point_index,
    }


@dataclass(frozen=True)
class LocatedLine:
    block: LocatedBlock
    point_index: int
    text: str
    norm: str

    @property
    def locator(self) -> dict[str, Any]:
        return _line_locator(self.block, self.point_index)

    @property
    def location(self) -> str:
        return " / ".join(
            part for part in (self.block.section_title, self.block.entry_title) if part
        )


def _located_line_table(resume: dict[str, Any]) -> list[LocatedLine]:
    """Every rendered text point with its locator, in display order."""
    table: list[LocatedLine] = []
    for block in _iter_located_blocks(resume):
        for point_index, line in enumerate(_block_point_lines(block)):
            table.append(
                LocatedLine(
                    block=block,
                    point_index=point_index,
                    text=line,
                    norm=_norm_point_text(line),
                )
            )
    return table


def _locator_matches(backend: dict[str, Any], client: LayoutLocatorIn) -> bool:
    """Compare a backend locator dict with the client's validated locator."""
    if backend.get("kind") != client.kind:
        return False
    if backend.get("point_index") != client.point_index:
        return False
    if client.kind == "entry":
        return (
            backend.get("section") == client.section
            and backend.get("entry_index") == client.entry_index
        )
    if client.kind in ("custom_text", "custom_item"):
        if backend.get("key") != client.key:
            return False
        if client.kind == "custom_item":
            return backend.get("entry_index") == client.entry_index
    return True


def _norm_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    # Substring fallback for punctuation/emphasis residue; short strings
    # match too easily, so require 4+ normalized chars like the frontend.
    return len(a) >= 4 and len(b) >= 4 and (a in b or b in a)


@dataclass(frozen=True)
class ResolvedPoint:
    """A measured point attributed back to its source line."""

    line: LocatedLine | None
    source_text: str
    location: str
    verified: bool


def _resolve_layout_point(
    resume: dict[str, Any], point: LayoutPointIn, table: list[LocatedLine]
) -> ResolvedPoint:
    """Attribute a client-measured point to its structured source line.

    Resolution order: locator-exact path, whole-resume normalized text search
    (tolerates reversed entry order / index drift), then an *unverified*
    fallback that still trusts the measured line count but flags evidence.
    """
    client_norm = _norm_point_text(point.text)

    # 1) Locator path.
    for candidate in table:
        if not _locator_matches(candidate.locator, point.locator):
            continue
        if _norm_match(candidate.norm, client_norm):
            return ResolvedPoint(candidate, candidate.text, candidate.location, True)
        # Locator matched but the text drifted; fall through to text search.
        break

    # 2) Full text search across every enumerated line.
    for candidate in table:
        if _norm_match(candidate.norm, client_norm):
            return ResolvedPoint(candidate, candidate.text, candidate.location, True)

    # 3) Unverified: the numeric measurement still came from rendering THIS
    # resume; use the client text/location and mark evidence accordingly.
    return ResolvedPoint(
        line=None,
        source_text=point.text,
        location=point.location,
        verified=False,
    )


def _all_text(resume: dict[str, Any]) -> str:
    parts: list[str] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, str):
            parts.append(obj)
        elif isinstance(obj, list):
            for element in obj:
                walk(element)
        elif isinstance(obj, dict):
            for value in obj.values():
                walk(value)

    walk(resume)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Section visibility / module helpers
# ---------------------------------------------------------------------------

_DEFAULT_VISIBLE_KEYS = (
    "personalInfo",
    "summary",
    "workExperience",
    "education",
    "personalProjects",
    "additional",
)

def _visible_meta(resume: dict[str, Any]) -> list[dict[str, Any]]:
    meta = resume.get("sectionMeta")
    if isinstance(meta, list) and meta:
        return [m for m in meta if isinstance(m, dict) and m.get("isVisible", True)]
    # Freshly parsed resumes store no sectionMeta (the default set is injected
    # on GET): synthesize the same canonical, degree-branch view the renderer
    # shows, so missing meta is never itself flagged as a violation.
    synthetic = dict(resume)
    synthetic["sectionMeta"] = copy.deepcopy(DEFAULT_SECTION_META)
    return [
        row
        for row in canonicalize_section_meta(synthetic)
        if row.get("isVisible", True)
    ]


def _meta_order(meta: dict[str, Any]) -> int:
    order = meta.get("order", 0)
    if isinstance(order, bool):
        return 0
    return order if isinstance(order, int) else 0


def _is_visible(resume: dict[str, Any], key: str) -> bool:
    return any(m.get("key") == key for m in _visible_meta(resume))


def _required_section_empty(resume: dict[str, Any], key: str) -> bool:
    """A present-but-whitespace-only entry (e.g. education=[{}]) is empty."""
    return is_section_empty({"key": key}, resume)


# Title tokens and parser-generated data keys for the two named optional
# modules. Key fallbacks cover resumes parsed before sectionMeta was emitted,
# where 个人优势/自我评价 existed only as customSections keyed by snake_case
# ids with no displayName row.
_ADVANTAGE_TITLE_TOKENS: tuple[str, ...] = ("个人优势", "核心优势", "个人亮点")
_ADVANTAGE_KEY_TOKENS: tuple[str, ...] = (
    "personal_advantage",
    "advantage",
    "strength",
    "highlight",
    "competency",
)
_SELFEVAL_TITLE_TOKENS: tuple[str, ...] = ("自我评价", "个人总结", "个人评价")
_SELFEVAL_KEY_TOKENS: tuple[str, ...] = (
    "self_evaluation",
    "self_eval",
    "self_appraisal",
    "selfassessment",
)


def _custom_section_text(section: Any) -> str:
    """All point-bearing text of a custom section, across container types.

    Handles ``text`` blocks, ``stringList.strings`` and ``itemList.items``
    (title/subtitle/description); older parses misfiled text points as
    itemList titles.
    """
    if not isinstance(section, dict):
        return ""
    parts: list[str] = []
    text = section.get("text")
    if isinstance(text, str) and text.strip():
        parts.append(text)
    strings = section.get("strings")
    if isinstance(strings, list):
        parts.extend(s for s in strings if isinstance(s, str) and s.strip())
    items = section.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            for field in ("title", "subtitle"):
                value = item.get(field)
                if isinstance(value, str) and value.strip():
                    parts.append(value)
            description = item.get("description")
            if isinstance(description, list):
                parts.extend(
                    point
                    for point in description
                    if isinstance(point, str) and point.strip()
                )
    return "\n".join(parts)


def _find_named_custom_section(
    resume: dict[str, Any],
    title_tokens: tuple[str, ...],
    key_tokens: tuple[str, ...] = (),
) -> str:
    """Return the text of a custom section identified by title or data key.

    Primary path: a visible sectionMeta row whose displayName contains a title
    token. Fallback for meta-less parsed resumes: a customSections key whose
    folded snake_case name contains one of ``key_tokens``.
    """
    custom = resume.get("customSections")
    if not isinstance(custom, dict):
        return ""
    matched_keys: set[str] = set()
    for meta in _visible_meta(resume):
        key = meta.get("key")
        if not key or not isinstance(key, str) or key in _DEFAULT_VISIBLE_KEYS:
            continue
        name = str(meta.get("displayName") or "")
        if any(token in name for token in title_tokens):
            matched_keys.add(key)
    if not matched_keys:
        for key in custom:
            folded = key.casefold().replace("-", "_")
            if any(token in folded for token in key_tokens):
                matched_keys.add(key)
    parts = [
        text
        for key in matched_keys
        if (text := _custom_section_text(custom.get(key)))
    ]
    return "\n".join(parts)


def _advantage_text(resume: dict[str, Any]) -> str:
    """个人优势 content: the summary slot wins, else a custom 个人优势 block."""
    if _is_visible(resume, "summary"):
        text = str(resume.get("summary") or "")
        if text.strip():
            return text
    return _find_named_custom_section(
        resume, _ADVANTAGE_TITLE_TOKENS, _ADVANTAGE_KEY_TOKENS
    )


# ---------------------------------------------------------------------------
# Timeline facts
# ---------------------------------------------------------------------------


def _work_intervals(resume: dict[str, Any]) -> list[tuple[str, Interval]]:
    intervals: list[tuple[str, Interval]] = []
    for entry in resume.get("workExperience") or []:
        if not isinstance(entry, dict):
            continue
        interval = parse_date_range(entry.get("years"))
        company = str(entry.get("company") or "").strip() or "（未命名公司）"
        if interval is not None:
            intervals.append((company, interval))
    intervals.sort(key=lambda pair: _month_index(*pair[1].start))
    return intervals


def _union_tenure_months(intervals: list[Interval]) -> int:
    """Union length in months (overlapping periods counted once)."""
    ranges = sorted(
        (_month_index(*iv.start), _month_index(*(iv.end or _now_point())))
        for iv in intervals
    )
    if not ranges:
        return 0
    total = 0
    cur_start, cur_end = ranges[0]
    for start, end in ranges[1:]:
        if start <= cur_end + 1:
            cur_end = max(cur_end, end)
        else:
            total += cur_end - cur_start + 1
            cur_start, cur_end = start, end
    total += cur_end - cur_start + 1
    return total


def _timeline_facts(intervals: list[tuple[str, Interval]]) -> dict[str, Any]:
    parsed = [iv for _, iv in intervals]
    today = _today_index()
    open_ended = any(iv.end is None for iv in parsed)
    ends = [_month_index(*iv.end) for iv in parsed if iv.end is not None]
    current_gap = 0
    if not open_ended and ends:
        current_gap = max(0, today - max(ends) - 1)

    historical_gap = 0
    overlaps: list[dict[str, str]] = []
    sorted_iv = sorted(parsed, key=lambda iv: _month_index(*iv.start))
    for previous, current in zip(sorted_iv, sorted_iv[1:]):
        prev_end = _month_index(*(previous.end or _now_point()))
        cur_start = _month_index(*current.start)
        gap = cur_start - prev_end - 1
        if gap >= 0:
            historical_gap += gap
        elif gap < -1:
            overlaps.append({"from": previous.raw, "to": current.raw, "months": str(-gap)})

    # Item 14 only counts ENDED full-time jobs; the current open-ended job is
    # excluded from short-stint statistics.
    short_stints = [
        {"company": company, "months": iv.length_months, "raw": iv.raw}
        for company, iv in intervals
        if iv.end is not None and iv.length_months < 12
    ]
    recent_companies: set[str] = set()
    for company, iv in intervals:
        start_idx = _month_index(*iv.start)
        end_idx = _month_index(*(iv.end or _now_point()))
        if end_idx >= today - 60 and start_idx <= today:
            recent_companies.add(company)

    return {
        "stints": [
            {"company": company, "raw": iv.raw, "length_months": iv.length_months,
             "open_ended": iv.end is None}
            for company, iv in intervals
        ],
        "current_gap_months": current_gap,
        "historical_gap_months": historical_gap,
        "open_ended": open_ended,
        "overlaps": overlaps,
        "short_stints": short_stints,
        "companies_last_5_years": sorted(recent_companies),
        "tenure_months": _union_tenure_months(parsed),
    }


# ---------------------------------------------------------------------------
# Individual checkers. Each returns (rating, evidence, suggestion).
# ---------------------------------------------------------------------------

# A finding names one signal: its rating, a resume-grounded problem
# description (empty on conform), and the single matching fix (empty on
# conform/na).
Finding = tuple[str, str, str]


def _finding(rating: str, evidence: str, suggestion: str = "") -> Finding:
    """Build one checker result; conform/na rows carry no suggestion."""
    return rating, evidence, suggestion


# Punctuation sitting directly before a join separator ("…标题。；将该长段…").
_JOIN_SEAM_RE = re.compile(r"[。.！？!?…]*(；|;)+")


def _join_text(parts: list[str], separator: str = "；") -> str:
    """Join fragment texts without doubled punctuation at the seams.

    Each part keeps its own terminal punctuation when it is the last one;
    punctuation immediately before a separator is removed so the result never
    reads "恢复…标题。；将该长段拆分…".
    """
    joined = separator.join(part for part in parts if part)
    return _JOIN_SEAM_RE.sub(separator, joined)


def _join_findings(findings: list[Finding]) -> Finding:
    """Combine one checker's internal signals: worst rating, problems only."""
    problems = [f for f in findings if f[0] in (RATING_NONCONFORM, RATING_PARTIAL)]
    if problems:
        rating = min(problems, key=lambda f: _VERDICT_RANK[f[0]])[0]
        evidence = _join_text([f[1] for f in problems])
        suggestions: list[str] = []
        for f in problems:
            if f[2] and f[2] not in suggestions:
                suggestions.append(f[2])
        return rating, evidence, _join_text(suggestions)
    conforming = [f for f in findings if f[0] == RATING_CONFORM]
    if conforming:
        return RATING_CONFORM, "", ""
    na_texts: list[str] = []
    for f in findings:
        if f[0] == RATING_NA and f[1] and f[1] not in na_texts:
            na_texts.append(f[1])
    return RATING_NA, "；".join(na_texts), ""


def _check_order(resume: dict[str, Any]) -> Finding:
    """Item 1a: visible blocks follow one of the two legal sequences.

    The sequence is chosen by the highest degree (formal education-second vs
    the default branch); unrecognised custom blocks occupy one cluster slot.
    Exact slot match is required — legacy scrambled meta is the backstop this
    check exists to flag.
    """
    visible = sorted(_visible_meta(resume), key=_meta_order)
    degree_class = classify_highest_degree(resume.get("education"))
    sequence = (
        CANONICAL_SEQUENCE_FORMAL if degree_class == "formal" else CANONICAL_SEQUENCE_OTHER
    )

    raw_slots = [
        section_symbol(meta) or CUSTOM_CLUSTER_SYMBOL
        for meta in visible
    ]
    # Several contiguous custom rows share the single cluster slot; custom
    # rows split around a fixed slot leave two cluster runs, which mismatches.
    actual: list[str] = []
    for slot in raw_slots:
        if slot == CUSTOM_CLUSTER_SYMBOL and actual and actual[-1] == CUSTOM_CLUSTER_SYMBOL:
            continue
        actual.append(slot)
    expected = [slot for slot in sequence if slot in set(raw_slots)]

    names = [str(m.get("displayName") or m.get("key") or "") for m in visible]
    rendered = " → ".join(names)
    if actual == expected:
        return _finding(RATING_CONFORM, "")
    return _finding(
        RATING_NONCONFORM,
        f"区块排列与固定顺序不一致，实际顺序：{rendered}",
        "按固定顺序重新排列各区块。",
    )


def _fold_title(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()


def _check_section_governance(resume: dict[str, Any]) -> Finding:
    """Item 1b: title governance — duplicates, renamed defaults, empty blocks.

    Optional blocks (个人优势 + custom) with a title but no content are a
    partial match; empty *required* blocks belong to item 3.
    """
    visible = _visible_meta(resume)
    findings: list[Finding] = []

    seen_titles: dict[str, str] = {}
    reported_dupes: set[str] = set()
    for meta in visible:
        name = str(meta.get("displayName") or meta.get("key") or "").strip()
        if not name:
            continue
        folded = _fold_title(name)
        if folded in seen_titles and folded not in reported_dupes:
            reported_dupes.add(folded)
            findings.append(
                _finding(
                    RATING_NONCONFORM,
                    f"「{seen_titles[folded]}」区块标题重复出现",
                    f"重命名或删除重复的「{seen_titles[folded]}」区块。",
                )
            )
        else:
            seen_titles.setdefault(folded, name)

    for meta in visible:
        key = meta.get("key")
        if not isinstance(key, str) or key not in DEFAULT_SECTION_KEYS:
            continue
        # The personal-info header never renders a section title (name plus
        # the fact grid only), so its stored displayName cannot be "renamed"
        # from the reader's point of view — every template ignores it.
        if key == "personalInfo":
            continue
        name = str(meta.get("displayName") or "").strip()
        if name and not is_accepted_default_title(key, name):
            findings.append(
                _finding(
                    RATING_NONCONFORM,
                    f"默认区块标题被改为「{name}」",
                    "恢复被改区块的默认标题。",
                )
            )

    for meta in visible:
        key = meta.get("key")
        if isinstance(key, str) and key in REQUIRED_KEYS:
            continue
        if is_section_empty(meta, resume):
            name = str(meta.get("displayName") or meta.get("key") or "").strip() or "未命名区块"
            findings.append(
                _finding(
                    RATING_PARTIAL,
                    f"「{name}」区块有标题无内容",
                    f"为「{name}」补充内容，或删除该空区块。",
                )
            )

    return _join_findings(findings) if findings else _finding(RATING_CONFORM, "")


def _point_rendered_lines(point: str) -> int:
    """Rendered line count of one newline-split point (min 1 for text)."""
    stripped = point.strip()
    if not stripped:
        return 0
    return math.ceil(len(stripped) / _CHARS_PER_LINE)


_MAX_POINT_LINES = 6


def _paragraph_evidence(
    resolved: ResolvedPoint, visual_lines: int
) -> Finding:
    preview = re.sub(r"\s+", "", resolved.source_text)[:40] or "该要点"
    place = resolved.location or "简历正文"
    tag = "" if resolved.verified else "（内容位置待核）"
    return _finding(
        RATING_NONCONFORM,
        f"「{preview}…」在所选模板下实际渲染约 {visual_lines} 行（{place}）{tag}，"
        "文字密度过高",
        "将该长句拆分为多条短句要点，每条单独成行。",
    )


def _check_paragraph_length(
    resume: dict[str, Any], layout: RenderedLayoutIn | None = None
) -> Finding:
    blocks = _iter_text_blocks(resume)
    if not blocks:
        return _finding(RATING_NA, "没有可检查的文本段落")

    if layout is not None and layout.points:
        # Measured path: resolve EVERY observed point first. Aligned source
        # lines are "covered" by real measurements — even a 300-char line that
        # the chosen (e.g. two-column-wide) template wraps within 6 visual
        # lines must NOT be re-flagged by the coarse char estimate. Only
        # source lines the snapshot could not align fall back to estimation so
        # an unmeasured long line can never slip through silently.
        findings: list[Finding] = []
        table = _located_line_table(resume)
        covered: set[int] = set()
        long_findings: list[tuple[int, Finding]] = []
        for point in layout.points:
            resolved = _resolve_layout_point(resume, point, table)
            if resolved.line is not None:
                covered.add(id(resolved.line))
            if point.visual_lines > _MAX_POINT_LINES:
                long_findings.append(
                    (point.visual_lines, _paragraph_evidence(resolved, point.visual_lines))
                )
        long_findings.sort(key=lambda item: item[0], reverse=True)
        findings.extend(finding for _, finding in long_findings[:2])

        worst_uncovered = ("", 0)
        for line in table:
            if id(line) in covered:
                continue
            line_count = _point_rendered_lines(line.text)
            if line_count > worst_uncovered[1]:
                worst_uncovered = (line.text, line_count)
        if worst_uncovered[1] > _MAX_POINT_LINES:
            findings.append(
                _finding(
                    RATING_NONCONFORM,
                    f"「{worst_uncovered[0][:40]}…」单段约 {worst_uncovered[1]} 行且无换行，"
                    "文字密度过高",
                    "将该长段拆分为多条短句要点，每条单独成行。",
                )
            )
        return _join_findings(findings) if findings else _finding(RATING_CONFORM, "")

    # Renderers split every block on "\n" into independent points, so density
    # is measured per point. Counting the joined block would flag an already
    # split 个人优势 (five short points with newlines) as one dense paragraph.
    worst_point = ""
    worst_lines = 0
    for block in blocks:
        points = [line.strip() for line in block.splitlines() if line.strip()]
        for point in points:
            line_count = _point_rendered_lines(point)
            if line_count > worst_lines:
                worst_lines = line_count
                worst_point = point
    if worst_lines > _MAX_POINT_LINES:
        preview = worst_point[:40]
        return _finding(
            RATING_NONCONFORM,
            f"「{preview}…」单段约 {worst_lines} 行且无换行，文字密度过高",
            "将该长段拆分为多条短句要点，每条单独成行。",
        )
    return _finding(RATING_CONFORM, "")


def _check_date_format(resume: dict[str, Any]) -> Finding:
    tokens: list[str] = []
    connectors: set[str] = set()
    precision: set[str] = set()
    for entry in (resume.get("workExperience") or []) + (resume.get("education") or []) \
            + (resume.get("personalProjects") or []):
        if not isinstance(entry, dict) or not isinstance(entry.get("years"), str):
            continue
        raw = entry["years"]
        for match in _DATE_RE.finditer(raw):
            tokens.append(match.group(0).strip())
            precision.add("month" if match.group(2) else "year")
        between = re.search(
            r"\d{4}(?:[.\-/年]\d{1,2})?\s*([\-–—~～至]+)\s*(?:\d{4}|至今|现在)",
            raw,
        )
        if between:
            connectors.add(between.group(1))
    if not tokens:
        return _finding(RATING_NA, "简历中没有可解析的日期")
    families: set[str] = set()
    for token in tokens:
        if re.fullmatch(r"\d{4}", token):
            families.add("yyyy")
        elif "." in token:
            families.add("yyyy.MM")
        elif "-" in token:
            families.add("yyyy-MM")
        elif "/" in token:
            families.add("yyyy/MM")
        elif "年" in token:
            families.add("yyyy年MM月")
        else:
            families.add(token)
    issues: list[Finding] = []
    if len(families) > 1:
        issues.append(
            _finding(
                RATING_NONCONFORM,
                f"日期格式不统一：{'、'.join(sorted(families))}",
                "全篇日期统一为同一种书写格式（如 2024.03）。",
            )
        )
    if len(precision) > 1:
        issues.append(
            _finding(
                RATING_PARTIAL,
                "时间精度不统一（部分只到年、部分到月）",
                "日期统一写到月份，补齐只写到年份的条目。",
            )
        )
    if len(connectors) > 1:
        issues.append(
            _finding(
                RATING_NONCONFORM,
                f"连接符混用：{'、'.join(sorted(connectors))}",
                "日期之间的连接符统一为同一种写法。",
            )
        )
    if not issues:
        return _finding(RATING_CONFORM, "")
    return _join_findings(issues)


_TEMPLATE_LABELS: dict[str, str] = {
    "swiss-single": "经典单栏",
    "swiss-two-column": "经典双栏",
    "modern": "现代单栏",
    "modern-two-column": "现代双栏",
    "latex": "LaTeX 风格",
    "clean": "简洁风格",
    "vivid": "活力双栏",
}


def _check_page_length(
    resume: dict[str, Any], layout: RenderedLayoutIn | None = None
) -> Finding:
    if layout is not None:
        pages = layout.page_count
        if pages > 3:
            label = _TEMPLATE_LABELS.get(layout.template, layout.template)
            return _finding(
                RATING_NONCONFORM,
                f"按所选模板（{label}，{layout.page_size}）实际渲染为 {pages} 页，篇幅偏长",
                "精简篇幅，优先保留与目标岗位最相关的经历，删减次要细节。",
            )
        return _finding(RATING_CONFORM, "")

    total = len(re.sub(r"\s", "", _all_text(resume)))
    pages = max(1, math.ceil(total / _CHARS_PER_PAGE))
    note = f"正文约 {total} 字，估算 {pages} 页（以导出 PDF 实际页数为准）"
    if pages > 3:
        return _finding(
            RATING_NONCONFORM,
            f"{note}，篇幅偏长",
            "精简篇幅，优先保留与目标岗位最相关的经历，删减次要细节。",
        )
    return _finding(RATING_CONFORM, "")


def _check_modules(resume: dict[str, Any], tenure_years: float | None) -> Finding:
    """Item 3: the five required modules from the V4-optimized rubric.

    必填模块 = 基础信息（含内置求职意向子项）、教育经历、专业技能、工作
    经历、项目经验，全部无条件必填——V4 删除了应届生以项目替代工作经历的
    豁免。个人优势仅对 8 年以上有效开发年限必填；培训与证书、荣誉奖项与
    自我评价为选填。
    """
    missing: list[str] = []
    info = resume.get("personalInfo")
    if (
        not _is_visible(resume, "personalInfo")
        or not isinstance(info, dict)
        or not str(info.get("name") or "").strip()
    ):
        missing.append("基础信息")
    if not _is_visible(resume, "education") or _required_section_empty(resume, "education"):
        missing.append("教育经历")
    has_work = _is_visible(resume, "workExperience") and not _required_section_empty(
        resume, "workExperience"
    )
    has_projects = _is_visible(
        resume, "personalProjects"
    ) and not _required_section_empty(resume, "personalProjects")
    if not has_work:
        missing.append("工作经历")
    if not has_projects:
        missing.append("项目经验")
    skills = (resume.get("additional") or {}).get("technicalSkills") or []
    if not _is_visible(resume, "additional") or not skills:
        missing.append("专业技能")
    if not _advantage_text(resume) and tenure_years is not None and tenure_years >= 8:
        missing.append("个人优势")
    if not missing:
        return _finding(RATING_CONFORM, "")
    rendered = "、".join(f"「{name}」" for name in missing)
    if len(missing) == 1:
        rating = RATING_PARTIAL
        evidence = f"缺少模块：{rendered}"
    else:
        rating = RATING_NONCONFORM
        evidence = f"缺少 {len(missing)} 个模块：{rendered}"
    suggestion = f"补齐缺失的模块：{rendered}。"
    if "个人优势" in missing:
        suggestion += "个人优势可概括最核心的履历亮点。"
    return _finding(rating, evidence, suggestion)


def _check_basic_info(resume: dict[str, Any]) -> Finding:
    """Item 4: required basic/contact fields resolvable from structured data.

    V4 必填项 = 姓名、性别、手机号、邮箱、求职意向；性别自
    personalInfo.gender 成为一等字段后纳入核验（解析时从原文表头逐字复制，
    缺失即判不符合）。期望城市（personalInfo.location）为选填项，缺失不扣分；
    年龄/有效IT开发年限/学历在评分表中仅为推荐项，缺失不扣分，故不在此检查；
    期望薪资等数据模型未承载的字段不核验。
    """
    info = resume.get("personalInfo") or {}
    phone = re.sub(r"[\s\-()（）]", "", str(info.get("phone") or ""))
    missing: list[str] = []
    if not str(info.get("name") or "").strip():
        missing.append("姓名")
    if not str(info.get("gender") or "").strip():
        missing.append("性别")
    if not _PHONE_RE.search(phone):
        missing.append("手机号")
    if not _EMAIL_RE.search(str(info.get("email") or "")):
        missing.append("邮箱")
    if not str(info.get("title") or "").strip():
        missing.append("求职意向")
    if missing:
        rendered = "、".join(f"「{name}」" for name in missing)
        suggestion = f"补全基本信息中的{rendered}。"
        if "手机号" in missing or "邮箱" in missing:
            suggestion += "手机号填写 11 位数字，邮箱需包含 @ 与域名。"
        return _finding(RATING_NONCONFORM, f"缺少必填基本信息：{rendered}", suggestion)
    return _finding(RATING_CONFORM, "")


def _check_education_elements(resume: dict[str, Any]) -> Finding:
    education = [e for e in (resume.get("education") or []) if isinstance(e, dict)]
    if not education:
        return _finding(RATING_NA, "教育经历模块缺失，不适用")
    missing_total = 0
    unannotated = 0
    for edu in education:
        missing = [
            label
            for value, label in (
                (edu.get("years"), "就读时间"),
                (edu.get("institution"), "就读大学"),
                (edu.get("description"), "所学专业"),
                (edu.get("degree"), "学历/学位"),
            )
            if not (isinstance(value, str) and value.strip())
        ]
        missing_total += len(missing)
        degree_text = str(edu.get("degree") or "")
        if degree_text and not re.search(r"统招|全日制|自考|成教|专升本", degree_text):
            unannotated += 1
    if missing_total == 0 and unannotated == 0:
        return _finding(RATING_CONFORM, "")
    findings: list[Finding] = []
    if missing_total:
        rating = RATING_PARTIAL if missing_total == 1 else RATING_NONCONFORM
        findings.append(
            _finding(
                rating,
                (
                    f"教育经历必填要素缺 1 项（共 {len(education)} 段）"
                    if missing_total == 1
                    else f"教育经历必填要素缺 {missing_total} 项"
                ),
                "补全各段教育经历的就读时间、院校、专业与学历/学位。",
            )
        )
    if unannotated:
        findings.append(
            _finding(
                RATING_PARTIAL,
                "教育经历未注明是否统招/全日制",
                "在学历条目中注明就读性质（统招、全日制、自考等）。",
            )
        )
    return _join_findings(findings)


def _check_summary_points(resume: dict[str, Any], tenure_years: float | None) -> Finding:
    """Item 6: content quality of 个人优势 (its absence is judged by item 3)."""
    text = _advantage_text(resume)
    points = count_points(text)
    if points == 0:
        # The missing-module case belongs to item 3; do not double count.
        return _finding(RATING_NA, "个人优势模块未设置，不适用")
    if 2 <= points <= 5:
        return _finding(RATING_CONFORM, "")
    if points < 2:
        return _finding(
            RATING_PARTIAL,
            f"个人优势 {points} 点，要点数量偏少",
            "用多条要点概括与目标岗位相关的核心优势，每条结合具体背景或能力。",
        )
    return _finding(
        RATING_PARTIAL,
        f"个人优势 {points} 点，要点数量偏多",
        "精简合并个人优势要点，保留最核心的几条，避免空泛表述。",
    )


def _check_skill_count(resume: dict[str, Any]) -> Finding:
    skills = [
        str(s).strip()
        for s in ((resume.get("additional") or {}).get("technicalSkills") or [])
        if isinstance(s, str) and s.strip()
    ]
    if not skills:
        return _finding(RATING_NA, "专业技能模块为空，不适用")
    count = len(skills)
    if count < 8:
        return _finding(
            RATING_NONCONFORM,
            f"专业技能仅 {count} 条，覆盖面不足",
            "补充与目标岗位相关的专业技能条目，避免只列少量关键词。",
        )
    if count > 15:
        return _finding(
            RATING_NONCONFORM,
            f"专业技能 {count} 条，条目过多、重点被稀释",
            "按与目标岗位的相关度取舍、分类排列技能条目，突出核心技能。",
        )
    return _finding(RATING_CONFORM, "")


def technical_skill_entries(resume: dict[str, Any]) -> list[str]:
    """Non-blank 专业技能 strings (the only text item 7 scans)."""
    raw = (resume.get("additional") or {}).get("technicalSkills") or []
    return [str(s).strip() for s in raw if isinstance(s, str) and s.strip()]


def mainstream_stack_coverage(
    skills: list[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split stack groups into (hit keys, miss keys) by deterministic regex.

    The miss tuple preserves the canonical group order; it feeds the LLM
    semantic review that may rescue synonym coverage (diagnosis.py).
    """
    haystack = "\n".join(skills)
    hit: list[str] = []
    miss: list[str] = []
    for group in _MAINSTREAM_GROUPS:
        (hit if group.pattern.search(haystack) else miss).append(group.key)
    return tuple(hit), tuple(miss)


def build_mainstream_stack_finding(hit_keys: tuple[str, ...]) -> Finding:
    """Build the item-7 stack finding from a set of covered group keys.

    Used both by the pure-regex checker and by diagnosis.py after the LLM
    semantic review rescues synonym-covered groups. Evidence names only what
    this resume actually contains (each quoted so a run of resume facts can't
    reproduce the rubric's canonical enumeration); the fix points only at
    directions THIS resume still lacks — capped at three examples so the
    client never receives the full canonical checklist, and categories
    already present are never suggested.
    """
    hit = [group.name for group in _MAINSTREAM_GROUPS if group.key in set(hit_keys)]
    missing_hints = [group.hint for group in _MAINSTREAM_GROUPS if group.key not in set(hit_keys)]
    ratio = len(hit) / len(_MAINSTREAM_GROUPS)
    if ratio >= _STACK_CONFORM_RATIO:
        return _finding(RATING_CONFORM, "")
    suggestion = (
        "在真实掌握的前提下，补齐简历尚缺的后端主流技术方向，"
        f"如{'、'.join(missing_hints[:3])}等。"
    )
    evidence = (
        f"简历中已见核心技术方向：{'、'.join(f'「{name}」' for name in hit)}；" if hit else ""
    )
    if ratio >= 0.5:
        return _finding(RATING_PARTIAL, evidence + "核心技术方向覆盖不足", suggestion)
    return _finding(RATING_NONCONFORM, evidence + "未见主流后端技术方向的关键词", suggestion)


def _check_mainstream_stack(resume: dict[str, Any]) -> Finding:
    skills = technical_skill_entries(resume)
    if not skills:
        return _finding(RATING_NA, "专业技能模块为空，不适用")
    hit_keys, _miss_keys = mainstream_stack_coverage(skills)
    return build_mainstream_stack_finding(hit_keys)


def _check_work_elements(
    resume: dict[str, Any], tenure_years: float | None
) -> Finding:
    """Item 8: 时间 / 公司 / 岗位 three elements + internship-entry rules."""
    work = [e for e in (resume.get("workExperience") or []) if isinstance(e, dict)]
    if not work:
        return _finding(RATING_NA, "工作经历模块缺失，不适用")
    findings: list[Finding] = []
    for entry in work:
        missing = [
            label
            for value, label in (
                (entry.get("years"), "时间"),
                (entry.get("company"), "公司"),
                (entry.get("title"), "岗位"),
            )
            if not (isinstance(value, str) and value.strip())
        ]
        if missing:
            company = str(entry.get("company") or "（未命名）")
            rendered = "/".join(missing)
            findings.append(
                _finding(
                    RATING_PARTIAL,
                    f"{company} 缺{rendered}",
                    f"补全{company}工作经历的{rendered}信息。",
                )
            )

    internships = [
        str(entry.get("company") or "（未命名）")
        for entry in work
        if _INTERNSHIP_RE.search(str(entry.get("title") or ""))
    ]
    experienced = tenure_years is not None and tenure_years >= 1
    if internships and experienced:
        findings.append(
            _finding(
                RATING_NONCONFORM,
                f"正式工作经历中混入实习条目：{'、'.join(internships)}",
                "将实习条目从正式工作经历中移出，单独列示或并入项目/实习经历。",
            )
        )

    if not findings:
        return _finding(RATING_CONFORM, "")
    return _join_findings(findings)


def _check_projects(resume: dict[str, Any]) -> Finding:
    """Item 9: six required fields per project + project count (2–4).

    项目时间在 V4 规范中为条件可选字段（周期＞半年才建议填写），因此不作
    为必填项核对；时间与任职区间的归属冲突由 item 13 校验。结构化数据无法
    直接区分「项目简介/职责/亮点」，这里用描述中的背景表述、技术词汇、
    职责动词与量化结果做代理识别。
    """
    projects = [p for p in (resume.get("personalProjects") or []) if isinstance(p, dict)]
    if not projects:
        return _finding(RATING_NA, "项目经验模块缺失，不适用")

    findings: list[Finding] = []
    if len(projects) > 4:
        findings.append(
            _finding(
                RATING_NONCONFORM,
                f"项目共 {len(projects)} 个，数量过多",
                "精简项目数量，优先保留与目标岗位最相关的项目。",
            )
        )
    elif len(projects) == 1:
        findings.append(
            _finding(
                RATING_NONCONFORM,
                "项目仅 1 个",
                "补充与目标岗位相关的项目经历。",
            )
        )

    field_failures = 0
    for project in projects:
        name = str(project.get("name") or "").strip()
        role = str(project.get("role") or "").strip()
        bullets = [b for b in (project.get("description") or []) if isinstance(b, str) and b.strip()]
        joined = "\n".join(bullets)
        has_duty = bool(_DUTY_RE.search(joined))
        has_metric = bool(_METRIC_RE.search(joined))
        tech_hits = len(set(m.group(0).lower() for m in _TECH_VOCAB_RE.finditer(joined)))
        has_stack = tech_hits >= 2
        has_background = bool(_BACKGROUND_RE.search(joined))
        missing: list[str] = []
        if not name:
            missing.append("项目名称")
        if not role:
            missing.append("项目角色")
        if not has_background:
            missing.append("项目简介")
        if not has_stack:
            missing.append("技术栈")
        if not has_duty:
            missing.append("项目职责")
        if not has_metric:
            missing.append("项目亮点（量化结果）")
        if missing:
            field_failures += 1
            rendered_missing = "、".join(f"「{label}」" for label in missing)
            project_label = name or "（未命名项目）"
            findings.append(
                _finding(
                    RATING_PARTIAL,
                    f"{project_label}：缺 {rendered_missing}",
                    f"为{project_label}补齐{rendered_missing}。",
                )
            )

    if not findings:
        return _finding(RATING_CONFORM, "")
    # Every project missing fields is a stronger signal than a single one.
    if not (len(projects) > 4 or len(projects) == 1) and field_failures == len(projects):
        for index, finding in enumerate(findings):
            if finding[0] == RATING_PARTIAL:
                findings[index] = _finding(RATING_NONCONFORM, finding[1], finding[2])
    return _join_findings(findings)


def _check_selfeval_points(resume: dict[str, Any]) -> Finding:
    text = _find_named_custom_section(
        resume, _SELFEVAL_TITLE_TOKENS, _SELFEVAL_KEY_TOKENS
    )
    points = count_points(text)
    if points == 0:
        return _finding(RATING_NA, "自我评价模块缺失，不适用（选填模块）")
    if 3 <= points <= 5:
        return _finding(RATING_CONFORM, "")
    if points < 3:
        return _finding(
            RATING_PARTIAL,
            f"自我评价 {points} 点，要点数量偏少",
            "用多条要点呈现与岗位相关的具体素养与事实，避免只写一句口号。",
        )
    return _finding(
        RATING_PARTIAL,
        f"自我评价 {points} 点，要点数量偏多",
        "精简合并自我评价要点，不重复技能与项目中已有的内容。",
    )


def _entry_free_text(entry: dict[str, Any]) -> str:
    """All human-readable text of one structured record (for note markers)."""
    parts: list[str] = []
    for value in entry.values():
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(v) for v in value if isinstance(v, str))
    return "\n".join(parts)


def _pairwise_overlaps(
    records: list[tuple[str, str, Interval, str]],
    *,
    note_pattern: re.Pattern[str],
    conflict_wording: str,
) -> list[str]:
    """Find unnoted overlaps between same-kind intervals.

    Each record is ``(label, raw, interval, free_text)``. Intervals sorted by
    start; an overlap needs more than a shared boundary month (gap < -1 months,
    matching ``_timeline_facts``). Records whose own text carries the rubric's
    exemption note (兼职/外包, 双学位/联合培养/在职…) are skipped.
    """
    parsed = sorted(records, key=lambda r: _month_index(*r[2].start))
    findings: list[str] = []
    for previous, current in zip(parsed, parsed[1:]):
        prev_label, prev_raw, prev_iv, prev_text = previous
        cur_label, cur_raw, cur_iv, cur_text = current
        prev_end = _month_index(*(prev_iv.end or _now_point()))
        gap = _month_index(*cur_iv.start) - prev_end - 1
        if gap >= -1:
            continue
        if note_pattern.search(prev_text) or note_pattern.search(cur_text):
            continue
        findings.append(
            f"{prev_label}（{prev_raw}）与 {cur_label}（{cur_raw}）"
            f"时间重叠 {-gap} 个月（{conflict_wording}）"
        )
    return findings


def _check_work_overlap(resume: dict[str, Any]) -> Finding:
    """Item 13: no unnoted overlap between formal full-time jobs."""
    records: list[tuple[str, str, Interval, str]] = []
    for entry in resume.get("workExperience") or []:
        if not isinstance(entry, dict):
            continue
        interval = parse_date_range(entry.get("years"))
        if interval is None:
            continue
        label = str(entry.get("company") or "").strip() or "（未命名公司）"
        records.append((label, interval.raw, interval, _entry_free_text(entry)))
    if len(records) < 2:
        return _finding(RATING_NA, "可核对的工作时间段不足两段")
    findings = _pairwise_overlaps(
        records, note_pattern=_WORK_OVERLAP_NOTE_RE, conflict_wording="未见兼职/外包备注"
    )
    if findings:
        return _finding(
            RATING_NONCONFORM,
            "；".join(findings),
            "核对相互重叠的工作时间段；若确属兼职或外包情形，在简历中补充备注。",
        )
    return _finding(RATING_CONFORM, "")


def _check_education_overlap(resume: dict[str, Any]) -> Finding:
    """Item 13: no unnoted overlap between formal education records."""
    records: list[tuple[str, str, Interval, str]] = []
    for entry in resume.get("education") or []:
        if not isinstance(entry, dict):
            continue
        interval = parse_date_range(entry.get("years"))
        if interval is None:
            continue
        label = str(entry.get("institution") or "").strip() or "（未命名院校）"
        records.append((label, interval.raw, interval, _entry_free_text(entry)))
    if len(records) < 2:
        return _finding(RATING_NA, "可核对的教育时间段不足两段")
    findings = _pairwise_overlaps(
        records,
        note_pattern=_EDU_OVERLAP_NOTE_RE,
        conflict_wording="未见双学位/联合培养/在职就读备注",
    )
    if findings:
        return _finding(
            RATING_NONCONFORM,
            "；".join(findings),
            "核对相互重叠的就读时间段；若属双学位、联合培养或在职就读，在简历中补充备注。",
        )
    return _finding(RATING_CONFORM, "")


def _check_project_timeline(resume: dict[str, Any]) -> Finding:
    """Item 13: project dates stay inside a work tenure (or marked amateur)."""
    work_spans = [
        (
            _month_index(*iv.start),
            _month_index(*(iv.end or _now_point())),
        )
        for _, iv in _work_intervals(resume)
    ]
    if not work_spans:
        return _finding(RATING_NA, "没有可核对的工作任职区间")
    findings: list[str] = []
    dated = 0
    for project in resume.get("personalProjects") or []:
        if not isinstance(project, dict):
            continue
        interval = parse_date_range(project.get("years"))
        if interval is None:
            continue
        dated += 1
        name = str(project.get("name") or "").strip() or "（未命名项目）"
        if _AMATEUR_PROJECT_RE.search(_entry_free_text(project)):
            continue
        start_idx = _month_index(*interval.start)
        end_idx = _month_index(*(interval.end or _now_point()))
        contained = any(ws <= start_idx and end_idx <= we for ws, we in work_spans)
        if not contained:
            findings.append(
                f"{name}（{interval.raw}）时间未落在任何一段工作任职区间内，"
                "也未标注个人业余项目"
            )
    if dated == 0:
        return _finding(RATING_NA, "项目均未填写可核对的时间")
    if findings:
        return _finding(
            RATING_NONCONFORM,
            "；".join(findings),
            "核对项目时间与工作任职区间；若为业余时间完成的项目，明确标注个人业余项目。",
        )
    return _finding(RATING_CONFORM, "")


def _degree_rank(entry: dict[str, Any]) -> int:
    """Highest degree level mentioned in one education record (0 = unknown)."""
    text = str(entry.get("degree") or "")
    for rank, pattern in _DEGREE_RANK_PATTERNS:
        if pattern.search(text):
            return rank
    return 0


def _check_work_education_order(resume: dict[str, Any]) -> Finding:
    """Item 13 🟡: first full-time job must not predate highest-degree enrolment."""
    education = [e for e in (resume.get("education") or []) if isinstance(e, dict)]
    ranked = [(entry, _degree_rank(entry), parse_date_range(entry.get("years"))) for entry in education]
    ranked = [(e, rank, iv) for e, rank, iv in ranked if rank > 0 and iv is not None]
    if not ranked:
        return _finding(RATING_NA, "缺少可判定最高学历的就读时间")
    highest_entry, _, highest_iv = max(ranked, key=lambda r: (r[1], _month_index(*r[2].start)))
    if _IN_SERVICE_EDU_RE.search(_entry_free_text(highest_entry)):
        return _finding(RATING_CONFORM, "")

    work_starts: list[tuple[int, str]] = []
    for entry in resume.get("workExperience") or []:
        if not isinstance(entry, dict):
            continue
        if _INTERNSHIP_RE.search(str(entry.get("title") or "")):
            continue  # Internships while studying are expected, not full-time jobs.
        interval = parse_date_range(entry.get("years"))
        if interval is None:
            continue
        work_starts.append((_month_index(*interval.start), interval.raw))
    if not work_starts:
        return _finding(RATING_NA, "缺少可核对的正式工作起始时间")

    earliest_start, earliest_raw = min(work_starts, key=lambda pair: pair[0])
    school = str(highest_entry.get("institution") or "").strip() or "最高学历"
    lead = _month_index(*highest_iv.start) - earliest_start
    # Year-only dates normalize to July; a ≤6-month lead is within rounding noise.
    if lead > 6:
        return _finding(
            RATING_PARTIAL,
            f"最早正式工作经历（{earliest_raw}）早于{school}（{highest_iv.raw}）"
            "的入学时间，简历未见在职学历备注",
            "核对最早正式工作时间与最高学历入学时间；若为在职就读，在简历中补充备注。",
        )
    return _finding(RATING_CONFORM, "")


def _check_date_validity(resume: dict[str, Any]) -> Finding:
    """Reversed ranges (start later than end) and end dates in the future."""
    today = _today_index()
    problems: list[str] = []
    for key in ("workExperience", "education", "personalProjects"):
        for entry in resume.get(key) or []:
            if not isinstance(entry, dict):
                continue
            interval = parse_date_range(entry.get("years"))
            if interval is None:
                continue
            label = str(
                entry.get("company") or entry.get("institution") or entry.get("name") or "条目"
            )
            if interval.end is not None:
                if _month_index(*interval.start) > _month_index(*interval.end):
                    problems.append(f"{label}（{interval.raw}）起始时间晚于结束时间")
                elif _month_index(*interval.end) > today:
                    problems.append(f"{label}（{interval.raw}）结束时间晚于当前时间")
    if not problems:
        return _finding(RATING_CONFORM, "")
    return _finding(
        RATING_NONCONFORM,
        "；".join(problems),
        "按实际起止时间更正倒置或晚于当前时间的日期。",
    )


def _check_stated_years(resume: dict[str, Any], tenure_months: int) -> Finding:
    match = _STATED_YEARS_RE.search(_all_text(resume))
    if not match:
        return _finding(RATING_NA, "简历中未找到自述工作年限，无法核对")
    stated = float(match.group(1))
    actual = round(tenure_months / 12, 1)
    diff = round(stated - actual, 1)
    if abs(diff) > 0.5:
        if diff > 0:
            return _finding(
                RATING_NONCONFORM,
                f"自述工作年限 {stated:g} 年，但各段在职时间累计约 {actual:g} 年，两者对不上",
                "按各段工作的实际起止时间核对并更正自述工作年限。",
            )
        return _finding(
            RATING_PARTIAL,
            f"自述 {stated:g} 年，累计在职约 {actual:g} 年，自述年限偏少",
            "核对自述工作年限，补全漏写的工作时间段后保持两者一致。",
        )
    return _finding(RATING_CONFORM, "")


# Worst-rating-first order used when merging several signals into one item.
_VERDICT_RANK = {
    RATING_NONCONFORM: 0,
    RATING_PARTIAL: 1,
    RATING_CONFORM: 2,
    RATING_NA: 3,
}


def _check_gaps(facts: dict[str, Any]) -> Finding:
    current_gap = facts["current_gap_months"]
    historical_gap = facts["historical_gap_months"]
    worst = max(current_gap, historical_gap)
    detail = f"本次空窗 {current_gap} 个月，历史空窗累计 {historical_gap} 个月"
    if worst > 6:
        return _finding(
            RATING_NONCONFORM,
            detail + "，存在较长空窗，简历中未见安排说明",
            "在简历中说明空窗期安排（如业务调整、项目到期、学习或家庭安排）。",
        )
    if worst >= 3:
        return _finding(
            RATING_PARTIAL,
            detail + "，存在空窗且简历未见说明",
            "在简历中补充空窗期的客观安排说明。",
        )
    return _finding(RATING_CONFORM, "")


def _check_job_hops(facts: dict[str, Any]) -> Finding:
    """Item 14 signal: ≥4 companies in the last 5 years (🟡 risk marker)."""
    companies = facts["companies_last_5_years"]
    if not facts["stints"]:
        return _finding(RATING_NA, "没有可解析的工作时间段，不适用")
    rendered = "、".join(companies) or "无"
    if len(companies) >= 4:
        return _finding(
            RATING_PARTIAL,
            f"近年经历 {len(companies)} 家公司：{rendered}，变动较频繁",
            "可在简历中简要说明历次变动的客观原因，突出每段经历的成长与稳定性。",
        )
    return _finding(RATING_CONFORM, "")


def _check_short_stints(facts: dict[str, Any]) -> Finding:
    short = facts["short_stints"]
    if not facts["stints"]:
        return _finding(RATING_NA, "没有可解析的工作时间段，不适用")
    if not short:
        return _finding(RATING_CONFORM, "")
    strong = [s for s in short if s["months"] <= 6]
    rendered = "；".join(f"{s['company']} {s['raw']}（{s['months']} 个月）" for s in short)
    # Risk marker, not a veto: item 14 is never a red line in V4.
    rating = RATING_NONCONFORM if strong else RATING_PARTIAL
    return _finding(
        rating,
        f"存在短周期已结束任职：{rendered}，简历未见客观原因备注",
        "为短周期任职补充客观原因说明（如项目到期、业务调整、公司裁员等）。",
    )


def _check_privacy(resume: dict[str, Any], supplementary_text: str | None = None) -> Finding:
    # Scan both the structured data and the user's original resume verbatim:
    # sensitive tokens the LLM extraction dropped must not escape the red line.
    text = _all_text(resume)
    if supplementary_text and supplementary_text.strip():
        text = f"{text}\n{supplementary_text}" if text else supplementary_text
    hits: list[str] = []
    seen: set[str] = set()
    for match in _ID_CARD_RE.finditer(text):
        token = match.group(0)
        label = f"疑似身份证号 {token[:6]}…{token[-2:]}"
        if label not in seen:
            seen.add(label)
            hits.append(label)
    for match in _PRIVACY_LABEL_RE.finditer(text):
        label = match.group(0)[:20]
        if label not in seen:
            seen.add(label)
            hits.append(label)
    if hits:
        return _finding(
            RATING_NONCONFORM,
            "；".join(hits),
            "删除证据中点名的敏感信息；涉密内容使用模糊代称描述，不出现可识别信息。",
        )
    return _finding(RATING_CONFORM, "")


def _usable_layout(
    rendered_layout: RenderedLayoutIn | None,
    template_settings: TemplateSettingsIn | None,
) -> RenderedLayoutIn | None:
    """Return the snapshot only when it is safe to trust its measurements.

    The snapshot is client-reported, so require: settings present, template
    and page size agreeing with the settings the client rendered, and a sane
    page count (Pydantic already bounds it to 1-12). Anything else logs and
    degrades to the text-estimate path rather than misjudging on bad data.
    """
    if rendered_layout is None or template_settings is None:
        return None
    if rendered_layout.template != template_settings.template:
        logger.info(
            "Rendered layout rejected: template mismatch (%s vs settings %s)",
            rendered_layout.template,
            template_settings.template,
        )
        return None
    if rendered_layout.page_size != template_settings.pageSize:
        logger.info(
            "Rendered layout rejected: page size mismatch (%s vs settings %s)",
            rendered_layout.page_size,
            template_settings.pageSize,
        )
        return None
    return rendered_layout


def _layout_facts(layout: RenderedLayoutIn) -> dict[str, Any]:
    long_points = sorted(
        (point for point in layout.points if point.visual_lines > _MAX_POINT_LINES),
        key=lambda point: point.visual_lines,
        reverse=True,
    )[:5]
    return {
        "template": layout.template,
        "page_size": layout.page_size,
        "two_column": layout.two_column,
        "page_count": layout.page_count,
        "points_measured": len(layout.points),
        "header": {
            "cell_count": layout.header.cell_count,
            "rows": len(layout.header.rows),
            "height_px": layout.header.height_px,
        },
        "sections": [
            {"title": section.title, "pages": list(section.pages)}
            for section in layout.sections
        ],
        "long_points": [
            {
                "location": point.location,
                "visual_lines": point.visual_lines,
                "page": point.page,
            }
            for point in long_points
        ],
    }


def _additional_strings(resume: dict[str, Any], field: str) -> list[str]:
    """Return cleaned ``additional.<field>`` string entries in stored order."""
    additional = resume.get("additional")
    if not isinstance(additional, dict):
        return []
    raw = additional.get(field)
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if isinstance(item, str) and item.strip()]


def run_objective_checks(
    resume: dict[str, Any],
    supplementary_text: str | None = None,
    rendered_layout: RenderedLayoutIn | None = None,
    template_settings: TemplateSettingsIn | None = None,
) -> tuple[dict[int, Finding], dict[str, Any]]:
    """Run every deterministic checker.

    ``supplementary_text`` is the user's original resume transcription (when
    available); only the #16 privacy scan reads it, so sensitive content the
    structured extraction dropped is still caught by the red line.

    Optional modules 11/12 resolve to an objective na verdict when they
    render no entries; with entries present they are left to the LLM, which
    receives the authoritative certification / award / language lists in the
    facts packet.

    ``rendered_layout``/``template_settings`` carry the client's offscreen
    measurement of the resume rendered with the builder's chosen template;
    when usable, items 1/2 judge real pagination instead of char estimates.

    Returns:
        (verdicts keyed by rubric item id, JSON-serializable facts packet).
    """
    layout = _usable_layout(rendered_layout, template_settings)
    intervals = _work_intervals(resume)
    timeline = _timeline_facts(intervals)
    tenure_months = int(timeline["tenure_months"])
    tenure_years: float | None = round(tenure_months / 12, 1) if tenure_months else None

    verdicts: dict[int, Finding] = {
        # Item 1: block order + title governance + paragraph length
        # (date issues belong to #13). Only failing signals contribute text.
        1: _join_findings(
            [
                _check_order(resume),
                _check_section_governance(resume),
                _check_paragraph_length(resume, layout),
            ]
        ),
        2: _check_page_length(resume, layout),
        3: _check_modules(resume, tenure_years),
        4: _check_basic_info(resume),
        5: _check_education_elements(resume),
        6: _check_summary_points(resume, tenure_years),
        7: _join_findings([_check_skill_count(resume), _check_mainstream_stack(resume)]),
        8: _check_work_elements(resume, tenure_years),
        9: _check_projects(resume),
        10: _check_selfeval_points(resume),
        13: _join_findings(
            [
                _check_date_format(resume),
                _check_date_validity(resume),
                _check_work_overlap(resume),
                _check_education_overlap(resume),
                _check_project_timeline(resume),
                _check_work_education_order(resume),
                _check_stated_years(resume, tenure_months),
            ]
        ),
        14: _join_findings(
            [
                _check_gaps(timeline),
                _check_job_hops(timeline),
                _check_short_stints(timeline),
            ]
        ),
        16: _check_privacy(resume, supplementary_text=supplementary_text),
    }
    # Item 15 (growth) is reference-only below 5 effective dev years:
    # objectively na; from 5 years on it goes to the LLM with the facts packet.
    if tenure_years is not None and tenure_years < 5:
        verdicts[15] = (
            RATING_NA,
            f"有效开发年限约 {tenure_years:g} 年，职业成长性暂不评估，仅作参考",
            "",
        )

    # Optional modules 11 (培训与证书) / 12 (荣誉奖项): they render solely
    # from additional.certificationsTraining / additional.awards, gated on the
    # additional meta being visible. No rendered entries → the module is
    # absent, which is objectively na (the LLM must not guess emptiness from
    # the raw upload's catch-all headings such as 「其他」); non-empty lists
    # go to the LLM for relevance / count / format / ordering judgment.
    additional_visible = _is_visible(resume, "additional")
    certifications = _additional_strings(resume, "certificationsTraining")
    awards = _additional_strings(resume, "awards")
    languages = _additional_strings(resume, "languages")
    if not additional_visible or not certifications:
        verdicts[11] = (RATING_NA, "未包含培训与证书内容，选填模块不参与评估", "")
    if not additional_visible or not awards:
        verdicts[12] = (RATING_NA, "未包含荣誉奖项内容，选填模块不参与评估", "")

    skills = [
        s
        for s in ((resume.get("additional") or {}).get("technicalSkills") or [])
        if isinstance(s, str) and s.strip()
    ]
    facts = {
        "timeline": timeline,
        "tenure_years": tenure_years,
        "skill_count": len(skills),
        # Authoritative module contents for the LLM's 11/12 judgment; the raw
        # upload may group these under a 「其他」 heading, so it cannot be the
        # source of truth for module presence / duplication.
        "certifications_training": certifications if additional_visible else [],
        "awards": awards if additional_visible else [],
        "languages": languages,
        "work_experience_count": len(resume.get("workExperience") or []),
        "project_count": len(resume.get("personalProjects") or []),
        "education_count": len(resume.get("education") or []),
        "summary_points": count_points(_advantage_text(resume)),
        "selfeval_points": count_points(
            _find_named_custom_section(
                resume, _SELFEVAL_TITLE_TOKENS, _SELFEVAL_KEY_TOKENS
            )
        ),
    }
    if layout is not None:
        facts["layout"] = _layout_facts(layout)
    return verdicts, facts
