"""Deterministic canonical casing for technical English terms.

Covers ``app.services.tech_terms`` (the table-backed regex pass) and its place
in the read-time self-heal chain ``normalize_resume_data``.
"""

import copy
from typing import Any

from app.schemas.models import normalize_resume_data
from app.services.tech_terms import canonicalize_tech_terms, canonicalize_terms_in_text


def test_lowercase_term_gets_canonical_casing() -> None:
    assert canonicalize_terms_in_text("熟悉 java 和 python") == "熟悉 Java 和 Python"


def test_all_caps_compound_gets_canonical_casing() -> None:
    assert canonicalize_terms_in_text("SPRING BOOT") == "Spring Boot"
    assert canonicalize_terms_in_text("Devops ci/cd") == "DevOps CI/CD"


def test_short_acronyms_uppercase() -> None:
    assert canonicalize_terms_in_text("svn, git, aws") == "SVN, Git, AWS"


def test_term_adjacent_to_cjk_matches() -> None:
    assert canonicalize_terms_in_text("mysql集群") == "MySQL集群"
    assert canonicalize_terms_in_text("使用redis缓存") == "使用Redis缓存"


def test_longest_term_wins_over_prefix() -> None:
    # "javascript" must become JavaScript, never "javaScript" (Java prefix).
    assert canonicalize_terms_in_text("javascript") == "JavaScript"
    assert canonicalize_terms_in_text("JAVASCRIPT and JAVA") == "JavaScript and Java"


def test_ascii_letter_adjacency_is_not_a_match() -> None:
    # Vue.js must not match inside Vue.jsx; Java must not match inside Javanese.
    assert canonicalize_terms_in_text("Vue.jsx") == "Vue.jsx"
    assert canonicalize_terms_in_text("Javanese tea") == "Javanese tea"


def test_non_strings_pass_through() -> None:
    assert canonicalize_terms_in_text(None) is None
    assert canonicalize_terms_in_text(123) == 123
    assert canonicalize_terms_in_text("") == ""


def test_dates_and_numbers_untouched() -> None:
    assert canonicalize_terms_in_text("2020.06~2023.09") == "2020.06~2023.09"


def _full_resume() -> dict[str, Any]:
    return {
        "personalInfo": {"name": "java 张三", "email": "java@example.com"},
        "summary": "五年 java 开发经验，熟悉 spring boot。",
        "workExperience": [
            {
                "id": 1,
                "title": "java 开发工程师",
                "department": "平台研发部",
                "company": "Acme java Corp",
                "years": "2020.06~2023.09",
                "description": ["主导 spring cloud 微服务改造", "使用 mysql 与 redis"],
                "descriptionStyles": ["bullet", "bullet"],
            }
        ],
        "personalProjects": [
            {
                "id": 1,
                "name": "vue.js 组件库",
                "role": "前端负责人",
                "description": ["基于 typescript 开发", "node.js 构建"],
            }
        ],
        "education": [
            {"id": 1, "institution": "Java University", "degree": "本科"}
        ],
        "additional": {
            "technicalSkills": ["java", "Spring Boot", "mysql集群"],
            "languages": ["英语 CET-6"],
            "certificationsTraining": ["aws 解决方案架构师"],
            "awards": ["校级 kafka 竞赛一等奖"],
        },
        "customSections": {
            "tech_stack": {
                "sectionType": "itemList",
                "items": [
                    {
                        "title": "docker 与 kubernetes",
                        "subtitle": "devops 方向",
                        "description": ["ci/cd 流水线"],
                    }
                ],
            },
            "hobbies": {"sectionType": "stringList", "strings": ["阅读 linux 内核源码"]},
            "self_evaluation": {
                "sectionType": "text",
                "text": "熟悉 nginx 与 tomcat",
            },
        },
    }


def test_full_resume_content_fields_are_canonicalized() -> None:
    result = canonicalize_tech_terms(_full_resume())

    assert result["summary"] == "五年 Java 开发经验，熟悉 Spring Boot。"
    work = result["workExperience"][0]
    assert work["title"] == "Java 开发工程师"
    assert work["description"] == ["主导 Spring Cloud 微服务改造", "使用 MySQL 与 Redis"]
    project = result["personalProjects"][0]
    assert project["name"] == "Vue.js 组件库"
    assert project["description"] == ["基于 TypeScript 开发", "Node.js 构建"]
    assert result["additional"]["technicalSkills"] == [
        "Java",
        "Spring Boot",
        "MySQL集群",
    ]
    assert result["additional"]["certificationsTraining"] == ["AWS 解决方案架构师"]
    assert result["additional"]["awards"] == ["校级 Kafka 竞赛一等奖"]
    item = result["customSections"]["tech_stack"]["items"][0]
    assert item["title"] == "Docker 与 Kubernetes"
    assert item["subtitle"] == "DevOps 方向"
    assert item["description"] == ["CI/CD 流水线"]
    assert result["customSections"]["hobbies"]["strings"] == ["阅读 Linux 内核源码"]
    assert result["customSections"]["self_evaluation"]["text"] == "熟悉 Nginx 与 Tomcat"


def test_skip_fields_are_untouched() -> None:
    source = _full_resume()
    result = canonicalize_tech_terms(source)

    # personalInfo (name, email), years, company/institution and sectionMeta are
    # deliberately outside the term table's reach.
    assert result["personalInfo"]["name"] == "java 张三"
    assert result["personalInfo"]["email"] == "java@example.com"
    assert result["workExperience"][0]["company"] == "Acme java Corp"
    assert result["workExperience"][0]["years"] == "2020.06~2023.09"
    assert result["education"][0]["institution"] == "Java University"


def test_input_dict_is_not_mutated() -> None:
    source = _full_resume()
    snapshot = copy.deepcopy(source)

    canonicalize_tech_terms(source)

    assert source == snapshot


def test_malformed_containers_pass_through() -> None:
    data: dict[str, Any] = {
        "summary": None,
        "workExperience": [None, "oops", {"title": "java"}],
        "personalProjects": None,
        "additional": {"technicalSkills": None},
        "customSections": {"broken": None},
    }

    result = canonicalize_tech_terms(data)

    assert result["workExperience"][2]["title"] == "Java"
    assert result["personalProjects"] is None
    assert result["additional"]["technicalSkills"] is None
    assert result["customSections"]["broken"] is None


def test_canonicalize_is_idempotent() -> None:
    once = canonicalize_tech_terms(_full_resume())
    twice = canonicalize_tech_terms(once)

    assert twice == once


def test_read_time_heal_chain_canonicalizes_terms() -> None:
    # Stored resumes predating the term table heal on read.
    data: dict[str, Any] = {
        "personalInfo": {"name": "张三"},
        "additional": {"technicalSkills": ["java", "Java", "spring boot"]},
    }

    normalized = normalize_resume_data(data)

    # Casing is unified and the later dedupe pass collapses casing duplicates.
    assert normalized["additional"]["technicalSkills"] == ["Java", "Spring Boot"]
