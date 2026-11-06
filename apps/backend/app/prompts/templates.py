"""LLM prompt templates for resume processing."""

# Language code to full name mapping
LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "zh": "Chinese (Simplified)",
    "ja": "Japanese",
    "pt": "Brazilian Portuguese",
    "fr": "French",
    "ko": "Korean",
}


def get_language_name(code: str) -> str:
    """Get full language name from code."""
    return LANGUAGE_NAMES.get(code, "English")


# Schema with example values - used for prompts to show LLM expected format
RESUME_SCHEMA_EXAMPLE = """{
  "personalInfo": {
    "name": "John Doe",
    "title": "Software Engineer",
    "email": "john@example.com",
    "phone": "+1-555-0100",
    "location": "San Francisco, CA",
    "gender": "",
    "age": "",
    "workYears": "",
    "educationLevel": "",
    "website": "https://johndoe.dev",
    "linkedin": "linkedin.com/in/johndoe",
    "github": "github.com/johndoe"
  },
  "summary": "Experienced software engineer with 5+ years...",
  "workExperience": [
    {
      "id": 1,
      "title": "Senior Software Engineer",
      "company": "Tech Corp",
      "department": "Platform Engineering",
      "location": "San Francisco, CA",
      "years": "2020.01~至今",
      "description": [
        "Led development of microservices architecture",
        "Improved system performance by 40%"
      ],
      "descriptionStyles": ["bullet", "bullet"]
    }
  ],
  "education": [
    {
      "id": 1,
      "institution": "University of California",
      "degree": "B.S. Computer Science",
      "years": "2014~2018",
      "description": "Graduated with honors"
    }
  ],
  "personalProjects": [
    {
      "id": 1,
      "name": "Open Source Tool",
      "role": "Creator & Maintainer",
      "years": "2021.03~至今",
      "scale": "",
      "description": [
        "Built CLI tool with 1000+ GitHub stars",
        "Used by 50+ companies worldwide"
      ],
      "descriptionStyles": ["bullet", "bullet"]
    }
  ],
  "additional": {
    "technicalSkills": ["Python", "JavaScript", "AWS", "Docker"],
    "languages": ["English (Native)", "Spanish (Conversational)"],
    "certificationsTraining": ["AWS Solutions Architect Associate (2023)"],
    "awards": ["Employee of the Year 2022"]
  },
  "customSections": {
    "self_evaluation": {
      "sectionType": "text",
      "text": "Careful engineer who values code quality and teamwork.\\nComfortable leading incident response under production pressure."
    },
    "publications": {
      "sectionType": "itemList",
      "items": [
        {
          "id": 1,
          "title": "Paper Title",
          "subtitle": "Journal Name",
          "years": "2023.06",
          "description": ["Brief description of the publication"],
          "descriptionStyles": ["bullet"]
        }
      ]
    },
    "volunteer_work": {
      "sectionType": "text",
      "text": "Description of volunteer activities..."
    }
  },
  "sectionMeta": [
    {"id": "personalInfo", "key": "personalInfo", "displayName": "Personal Info", "sectionType": "personalInfo", "isDefault": true, "isVisible": true, "order": 0},
    {"id": "education", "key": "education", "displayName": "Education", "sectionType": "itemList", "isDefault": true, "isVisible": true, "order": 1},
    {"id": "summary", "key": "summary", "displayName": "Summary", "sectionType": "text", "isDefault": true, "isVisible": true, "order": 2},
    {"id": "additional", "key": "additional", "displayName": "Skills", "sectionType": "stringList", "isDefault": true, "isVisible": true, "order": 3},
    {"id": "workExperience", "key": "workExperience", "displayName": "Experience", "sectionType": "itemList", "isDefault": true, "isVisible": true, "order": 4},
    {"id": "personalProjects", "key": "personalProjects", "displayName": "Projects", "sectionType": "itemList", "isDefault": true, "isVisible": true, "order": 5},
    {"id": "self_evaluation", "key": "self_evaluation", "displayName": "Self Evaluation", "sectionType": "text", "isDefault": false, "isVisible": true, "order": 6}
  ]
}"""

# Schema for improve prompts - excludes personalInfo (preserved from original)
IMPROVE_SCHEMA_EXAMPLE = """{
  "summary": "Experienced software engineer with 5+ years...",
  "workExperience": [
    {
      "id": 1,
      "title": "Senior Software Engineer",
      "company": "Tech Corp",
      "department": "Platform Engineering",
      "location": "San Francisco, CA",
      "years": "2020.01~至今",
      "description": [
        "Led development of microservices architecture",
        "Improved system performance by 40%"
      ],
      "descriptionStyles": ["bullet", "bullet"]
    }
  ],
  "education": [
    {
      "id": 1,
      "institution": "University of California",
      "degree": "B.S. Computer Science",
      "years": "2014~2018",
      "description": "Graduated with honors"
    }
  ],
  "personalProjects": [
    {
      "id": 1,
      "name": "Open Source Tool",
      "role": "Creator & Maintainer",
      "years": "2021.03~至今",
      "scale": "",
      "description": [
        "Built CLI tool with 1000+ GitHub stars",
        "Used by 50+ companies worldwide"
      ],
      "descriptionStyles": ["bullet", "bullet"]
    }
  ],
  "additional": {
    "technicalSkills": ["Python", "JavaScript", "AWS", "Docker"],
    "languages": ["English (Native)", "Spanish (Conversational)"],
    "certificationsTraining": ["AWS Solutions Architect"],
    "awards": ["Employee of the Year 2022"]
  },
  "customSections": {
    "publications": {
      "sectionType": "itemList",
      "items": [
        {
          "id": 1,
          "title": "Paper Title",
          "subtitle": "Journal Name",
          "years": "2023.06",
          "description": ["Brief description of the publication"],
          "descriptionStyles": ["bullet"]
        }
      ]
    },
    "volunteer_work": {
      "sectionType": "text",
      "text": "Description of volunteer activities..."
    }
  }
}"""

PARSE_RESUME_PROMPT = """Parse this resume into JSON. Output ONLY the JSON object, no other text.

Example output format (note the sectionMeta array — it is REQUIRED, see rule 1):
{schema}

Custom section types:
- "text": Single text block (e.g., objective, statement, self evaluation)
- "itemList": List of items with title, subtitle, years, description (e.g., publications, research)
- "stringList": Simple list of strings (e.g., hobbies, interests)

Rules:

1. SECTION METADATA (REQUIRED). Emit one sectionMeta row for EVERY section that
has content, including every customSections entry.
   - Six built-in sections use fixed ids/keys: personalInfo, education, summary,
     additional, workExperience, personalProjects; isDefault=true.
   - Every other section is custom: id and key both equal the same snake_case
     customSections key (e.g. "self_evaluation", "publications"); isDefault=false.
   - "displayName" is the section heading copied VERBATIM from the source resume
     in its original language (e.g. "兴趣爱好", "自我评价", "个人优势",
     "Publications"). Never translate, rename, or invent a heading.
   - sectionType is "personalInfo", "text", "itemList", or "stringList".
   - order follows the source document's section order, starting from 0;
     isVisible=true for every row you emit.
   - The key in sectionMeta MUST exactly match the customSections object key.

2. SECTION IDENTITY — never merge distinct sections. Chinese resumes commonly
use these headings; map them exactly as specified:
   - 个人优势 / 核心优势 / 竞争优势 / 综合优势 / 个人亮点 (and
     Summary/Profile/Objective): put the text in top-level "summary". It is one
     section; do not duplicate it into customSections.
   - 自我介绍 / 个人介绍 / 个人简介 / 个人简述 / 个人评价 / 自我评价 / 自我评定 /
     个人总结 (Self Introduction / Personal Summary): a SEPARATE customSections
     text block, key "self_evaluation", displayName copied verbatim from the
     source (a source heading "个人总结" stays displayName "个人总结"; a heading
     "个人评价" is the self-introduction block and renders as 自我介绍). Never
     put these into "summary", and never merge this block with 个人优势.
   - 工作经历 / 工作经验 / 实习经历 / 从业经历 / 职业履历 / 任职经历 / 工作履历 /
     职场经历 (Experience): workExperience.
   - 项目经验 / 项目经历 / 项目履历 / 重点项目 (Projects): personalProjects.
   - 教育背景 / 教育经历 / 学历信息 / 求学履历 (Education): education.
   - 专业技能 / 职业技能 / 核心技能 / 专业能力 / 技术能力 / 技术技能 / 技能 /
     技能清单 (Skills): skills
     go to additional.technicalSkills, one entry per source line or listed skill.
     When the source groups skills under category prefixes (e.g.
     "后端：Java、Spring Boot、MySQL" / "Frontend: React, TypeScript"), keep
     each category line as ONE entry with its category prefix and inline name
     list intact; never invent categories the source does not have, and keep
     bare (unprefixed) skill names as one entry per line.
   - 荣誉证书 / 荣誉/证书 / 荣誉 / 证书 / 获奖情况 / 资质荣誉 / 资格证书 / 奖项 /
     资质认证, whether presented as a DEDICATED section or found inside a
     combined skills block, go into additional, NEVER into customSections:
       * items that are certificates/qualifications/credentials (证书/资格/认证/
         资质) go to additional.certificationsTraining;
       * items that are awards/prizes/honors (获奖/奖项/荣誉) go to
         additional.awards.
     A mixed heading such as 荣誉证书 / 荣誉/证书 splits its entries between the
     two arrays by what each entry actually is. One entry per source line; keep
     any date or issuer text inline in the entry (e.g. "AWS Solutions Architect
     Associate (2023)"); do not build an itemList or any custom section for
     them.
   - 语言能力 / 外语水平 (Languages): additional.languages ONLY (e.g. 英语 CET-6,
     日语 N1, 雅思 7.0). Language proficiency and language certificates must
     NEVER appear in additional.technicalSkills, even when the source lists
     them inside a combined skills block.
   - 求职意向 / 期望职位 / 目标岗位 goes to personalInfo.title; 期望城市 / 意向城市 /
     工作地点 goes to personalInfo.location. Do not create custom sections for
     these.
   - Header demographics also belong in personalInfo, copied VERBATIM from the
     source header and never inferred from the name, dates, or education:
     gender (性别, e.g. "男"/"女"), age (年龄, keep the source wording such as
     "28岁"), workYears (工作年限/工作经验, e.g. "5年"/"5-10年"/"3年以上"),
     educationLevel (最高学历/学历). educationLevel MUST keep every qualifier and
     parenthetical tag from the source — 统招/全日制/非全日制/自考 and tags such
     as (211)/(985)/双一流/省重点 — e.g. "统招本科(211)", never just "本科".
     Use "" for any of the four when the source header does not state it; do
     not move these facts into custom sections.

3. FORMAT FIDELITY — preserve the source structure; never collapse content into
one big paragraph.
   - Each source bullet/line becomes its OWN array element in description /
     technicalSkills / strings. Never join several source lines into one long
     string using commas, semicolons, or connecting words, and never split one
     source line across invented bullets.
   - NEVER copy the source's own numbering/bullet markers into element text:
     no "1、"/"1."/"1)"/"(1)"/"①"/"一、"/"•"/"- " prefixes. The renderer
     numbers every list itself; an element starts directly with its content.
     This applies to description rows, technicalSkills, stringList entries and
     every other array element.
   - In "text" blocks (summary, self_evaluation, custom text), keep one point
     per line joined by "\\n", in source order. When the source self-evaluation
     is one paragraph whose clauses are separated by "；" or "。" (e.g.
     "做事认真；学习能力强。有团队精神。"), SPLIT it into one point per clause,
     each on its own "\\n" line, dropping the boundary punctuation; never leave
     such a paragraph as a single line.
   - customSections content must reproduce the source formatting exactly:
     "text" blocks are one string with "\\n" between source lines (never a
     space- or comma-joined single line, never an array); "stringList" keeps
     one entry per source line; itemList keeps one description element per
     source line. Keep the original sub-labels, punctuation, and line breaks;
     do not reflow, rewrap, renumber, or restructure the section.
   - Copy wording faithfully; do not rewrite, summarize, polish, reorder, or add
     connectors. Do not invent content absent from the source.
   - Keep category/group labels when the source groups skills
     (e.g. one entry "后端框架：Spring Boot、Spring Cloud"), but each source line
     is still a separate entry.

4. WORK EXPERIENCE. Each company/role is one workExperience entry: years,
company, title (岗位), department, location when given, and one description
element per source bullet. The department field holds the org unit the source
shows on its own line under the company (Chinese: 全球资金部 / 研发部 /
云计算集成部 / 保险事业群 / 平台研发中心; English: "Platform Engineering
Department" / "Payments Team") — copy it into department verbatim and NEVER
leave it in description; use "" when the source gives no department. Keep
internship titles verbatim (e.g. title containing 实习) in their own entry;
do not merge companies or roles and do not merge bullets. Sub-labels inside an
entry follow the same label-row rules as projects (rule 5).

5. PROJECTS — extract each source project as its OWN personalProjects entry (do
not merge projects). For every entry capture what the source provides:
   - name (项目名称), role (担任角色, e.g. 负责人/核心开发/参与者; a source
     line "项目角色：…" / "担任角色：…" fills role, never stays in the
     description), scale (项目规模: team size/budget/user volume, a source
     line "项目规模：…" / "团队规模：…" fills scale, copied verbatim; use ""
     when absent — NEVER invent one),
   - years copied exactly when a project period is stated; use "" when the
     source gives no period — NEVER invent one,
   - one description element per source line, preserving: project
     background/business scenario (背景/场景), the technologies used (each named
     technology stays explicit, e.g. Spring Cloud、Redis、Kafka — at least two
     distinct technologies when the source lists them), action verbs describing
     duties, and quantified results copied VERBATIM (numbers, percentages,
     performance figures must not be dropped, rounded, or made up),
   - IN-ITEM SUB-MODULES stay in place as their OWN description element with
     descriptionStyles "label": keep each label on its own row, NEVER merge it
     with the following line and never drop it. When the source organizes a
     project into these sub-modules, EVERY source line is placed under its
     matching sub-label in source order — nothing is dropped, merged, or moved
     between modules, and the source line structure (one element per source
     line) is preserved exactly. PROJECT sub-labels are renamed
     to one of four canonical names (keep every OTHER label verbatim —
     项目描述 / 系统架构 / AND ANY OTHER label, including unlisted ones):
       * duty-like labels 工作职责 / 主要职责 / 负责内容 / 核心工作 / 工作内容 /
         个人职责 / 项目责任 / 个人职责与成果 / 核心职责与成果
         → output as 项目职责 (项目职责 itself stays),
       * highlight/result/difficulty labels 项目成果 / 个人成果 / 技术亮点 /
         技术难点 / 难点与解决 / 技术难点及亮点 → output as 项目亮点
         (项目亮点 itself stays),
       * intro/background labels 项目概述 / 业务背景 / 项目简介 / 需求背景 /
         项目概况 / 项目介绍 → output as 项目背景 (项目背景 itself stays),
       * technology labels 技术选型 / 技术架构 / 所用技术 / 技术清单 /
         技术列表 → output as 技术栈 (技术栈 itself stays);
     this rename applies to personalProjects ONLY — workExperience labels
     such as 工作职责 stay verbatim,
   - project intro/background/technology rows — 项目背景 / 项目概述 / 业务背景 /
     项目简介 / 需求背景 / 项目概况 / 项目介绍 / 项目描述 / 技术栈 / 技术选型 /
     技术架构 / 所用技术 / 技术清单 / 技术列表 / 系统架构 / 架构说明 — whether
     the label is glued to the text on one row or sits on its own row above the
     content, are NOT duty points: the label is one "label" row and ALL of its
     content row(s) are "plain" rows that render below the bold label, aligned
     to the label text, and must never be numbered; each technology listed
     under 技术栈 is its own "plain" row (e.g. "Java", "Spring Boot"), never a
     "label"; when the source structures the stack by category ("后端：Java、Spring Boot", "数据库：MySQL、Redis", "前端：Vue.js"), keep EACH category line verbatim as ONE "plain" row with its "类别：" prefix and its names inline — one category per source line, never inventing categories, never splitting a category's names into multiple rows, never joining two categories; only 项目职责/项目亮点 duty and achievement points are "bullet",
   - a "label" row is ONLY a short standalone heading ending with "："
     ("项目职责："), or a bare sub-module name alone on its own row with no
     trailing colon ("项目职责") — both are "label" rows; NEVER mark a content
     paragraph as "label" — a row that starts with a bold-looking prefix but
     carries a full sentence
     ("负责整体架构：基于……，避免配置漂移。") is a content row, not a label,
   - NESTED GROUP HEADINGS: when 项目职责/项目亮点 content is itself grouped
     under bold sub-headings that carry no colon and no number
     (e.g. "架构演进与技术债务治理", "主导促销中心组件设计", each followed by
     its own points), emit each sub-heading as its OWN short "label" row with
     no trailing colon, and every point under it as a separate "bullet" row;
     never merge a sub-heading into its first bullet, never skip a sub-heading,
     and never number either the headings or the points yourself — the
     renderer numbers them hierarchically (1. heading, 1.1/1.2 points,
     2. heading, 2.1/2.2 points),
   - numbered/bulleted points under a sub-label are normal "bullet" rows (one
     per source point); each sub-label's bullets restart numbering at 1 at
     render time, so do NOT number them yourself; when the source 项目职责 is
     one long paragraph with clauses separated by "；" or "。", emit one
     "bullet" row per clause (drop the boundary punctuation), never a single
     blob row; unplanned structures that
     have no schema field — tables such as 难点/方案/效果 grids, key/value
     blocks, free-form paragraphs — are reproduced as "plain" rows with one
     row per source line or table cell, in source order, text copied verbatim;
     NEVER join cells or lines with " - " or punctuation, and never renumber,
     rewrite, or restructure them,
   - include github/website links only when present in the source.

6. EDUCATION. One entry per degree: years, institution, degree (学历/学位, copy
qualifiers such as 统招/全日制/非全日制/自考 and parenthetical tags such as
(211)/(985)/双一流 verbatim — never strip them, e.g. "统招本科(211)"),
description holds ONLY the major/specialization (专业， without the "专业："
prefix) and genuinely academic text. Award, honor, certificate, qualification
or license lines printed inside the education block ("奖项：…", "获奖情况：…",
"荣誉：…", "证书：…", "资格证书：…", "认证：…") go ONLY into
additional.awards / additional.certificationsTraining — one string per item,
even when the source has no independent awards/certificates heading. NEVER
copy such lines into education.description and never leave a 奖项/证书/荣誉
label glued to the major text.

7. General field rules:
- Use "" for missing text fields, [] for missing arrays, null for optional fields
- Number IDs starting from 1
- For workExperience, personalProjects, and custom itemList items, include descriptionStyles with one value for each description row. Use "bullet" for normal bullet rows, "label" for bold sub-module headings (项目职责/负责内容/技术栈/难点与解决/… that own the following bullets), and "plain" for unnumbered body text (standalone paragraphs, free-form table content) that renders without a marker and without bold.
- Format EVERY date period as numeric "yyyy.MM" with a tilde connector and no spaces: a closed range is "2020.06~2023.09"; an ongoing position is "2024.03~至今" (use Chinese 至今 in every resume, including English ones). Convert English month names ("Jan 2020 - Dec 2023") to numeric form ("2020.01~2023.12"), and every open-ended marker (Present/Current/Now/Ongoing/现在/目前) to 至今.
- Preserve original precision: zero-pad months when the source has months ("2017.9" → "2017.09"); use bare years ("2018~2021") ONLY when the source has no months — never invent a month. Never put colloquial date prose ("三年经验", "至今在职") into a years field; if the source gives no parseable date, leave the field "".
- Write technical English terms with their standard canonical casing and keep it consistent across the whole resume, e.g. Java, JavaScript, TypeScript, Python, Spring Boot, Spring Cloud, MyBatis-Plus, MySQL, PostgreSQL, Elasticsearch, Kubernetes, Docker, DevOps, CI/CD, Vue.js, Node.js, React, Redis, Kafka. Do not output "java", "JAVA", "spring boot", "JAVASCRIPT".
- Fix obvious extraction/OCR damage while copying faithfully: garbled remnant characters, clear Chinese/English typos, and obvious English spelling errors may be corrected to the intended word. Do NOT rewrite wording, polish style, change technical facts, alter numbers/metrics, or "correct" words whose intended form is uncertain — when in doubt, copy the source.
- Use snake_case for custom section keys
- Preserve overlapping dates (concurrent roles) as separate entries; don't merge
- Do NOT output any section (default or custom) that has no content in the source

Resume to parse:
{resume_text}"""

EXTRACT_KEYWORDS_PROMPT = """Extract job requirements as JSON. Output ONLY the JSON object, no other text.

Example format:
{{
  "company": "Acme Corp",
  "role": "Senior Backend Engineer",
  "required_skills": ["Python", "AWS"],
  "preferred_skills": ["Kubernetes"],
  "experience_requirements": ["5+ years"],
  "education_requirements": ["Bachelor's in CS"],
  "key_responsibilities": ["Lead team"],
  "keywords": ["microservices", "agile"],
  "experience_years": 5,
  "seniority_level": "senior"
}}

Extract numeric years (e.g., "5+ years" → 5) and infer seniority level.
Set "company" to the hiring company name and "role" to the job title exactly as
written in the posting; use an empty string for either if it is not stated.

Job description:
{job_description}"""

CRITICAL_TRUTHFULNESS_RULES_TEMPLATE = """CRITICAL TRUTHFULNESS RULES - NEVER VIOLATE:
1. DO NOT add any skill, tool, technology, or certification that is not explicitly mentioned in the original resume
2. DO NOT invent numeric achievements (e.g., "increased by 30%") unless they exist in original
3. DO NOT add company names, product names, or technical terms not in the original
4. DO NOT upgrade experience level (e.g., "Junior" -> "Senior")
5. DO NOT add languages, frameworks, or platforms the candidate hasn't used
6. DO NOT extend employment dates or change timelines. Copy date ranges exactly as they appear, including months.
7. {rule_7}
8. Preserve factual accuracy - only use information provided by the candidate
9. NEVER remove existing skills, certifications, languages, or awards. You may reorder by relevance, but every original item must remain.

Violation of these rules could cause serious problems for the candidate in job interviews.
"""


def _build_truthfulness_rules(rule_7: str) -> str:
    return CRITICAL_TRUTHFULNESS_RULES_TEMPLATE.format(rule_7=rule_7)


CRITICAL_TRUTHFULNESS_RULES = {
    "nudge": _build_truthfulness_rules(
        "DO NOT add new bullet points or content - only rephrase existing content"
    ),
    "keywords": _build_truthfulness_rules(
        "You may rephrase existing bullet points to include keywords, but do NOT add new bullet points"
    ),
    "full": _build_truthfulness_rules(
        "You may expand existing bullet points or add new ones that elaborate on existing work, but DO NOT invent entirely new responsibilities"
    ),
}

IMPROVE_RESUME_PROMPT_NUDGE = """Lightly nudge this resume toward the job description. Output ONLY the JSON object, no other text.

{critical_truthfulness_rules}

IMPORTANT: Generate ALL text content (summary, descriptions, skills) in {output_language}.
Do NOT include personalInfo in your output - it will be preserved from the original resume.

Rules:
- Make minimal, conservative edits only where there is a clear existing match
- Do NOT change the candidate's role, industry, or seniority level
- Do NOT introduce new tools, technologies, or certifications not already present
- Do NOT add new bullet points or sections
- Preserve original bullet count and ordering within each section
- Preserve descriptionStyles arrays and keep them aligned one-to-one with description arrays
- Keep proper nouns (names, company names, locations) unchanged
- For customSections: preserve exact structure, item count, titles, subtitles, and years. If an item's description is an empty array [] in the original, keep it empty []. Do NOT generate descriptions for items that had none.
- Copy every date POINT exactly as it appears: same years, same months, same open-ended status; never shorten or drop months. Presentation (numeric "yyyy.MM", tilde connector, 至今 for open-ended ranges) is normalized server-side, so copy the values faithfully rather than restyling them.
- If the resume is non-technical, do NOT add technical jargon
- Do NOT use em dash ("—") anywhere in the writing/output, even if it exists, remove it

Job Description:
{job_description}

Keywords to emphasize (only if already supported by resume content):
{job_keywords}

Original Resume:
{original_resume}

Output in this JSON format:
{schema}"""

IMPROVE_RESUME_PROMPT_KEYWORDS = """Enhance this resume with relevant keywords from the job description. Output ONLY the JSON object, no other text.

{critical_truthfulness_rules}

IMPORTANT: Generate ALL text content (summary, descriptions, skills) in {output_language}.
Do NOT include personalInfo in your output - it will be preserved from the original resume.

Rules:
- Strengthen alignment by weaving in relevant keywords where evidence already exists
- You may rephrase bullet points to include keyword phrasing
- Do NOT introduce new skills, tools, or certifications not in the resume
- Do NOT change role, industry, or seniority level
- Preserve descriptionStyles arrays and keep them aligned one-to-one with description arrays
- For customSections: preserve exact structure, item count, titles, subtitles, and years. If an item's description is an empty array [] in the original, keep it empty []. Do NOT generate descriptions for items that had none.
- Copy every date POINT exactly as it appears: same years, same months, same open-ended status; never shorten or drop months. Presentation (numeric "yyyy.MM", tilde connector, 至今 for open-ended ranges) is normalized server-side, so copy the values faithfully rather than restyling them.
- If resume is non-technical, keep language non-technical while still aligning keywords
- Do NOT use em dash ("—") anywhere in the writing/output, even if it exists, remove it

Job Description:
{job_description}

Keywords to emphasize:
{job_keywords}

Original Resume:
{original_resume}

Output in this JSON format:
{schema}"""

IMPROVE_RESUME_PROMPT_FULL = """Tailor this resume for the job. Output ONLY the JSON object, no other text.

{critical_truthfulness_rules}

IMPORTANT: Generate ALL text content (summary, descriptions, skills) in {output_language}.
Do NOT include personalInfo in your output - it will be preserved from the original resume.

Rules:
- Make targeted adjustments to bullet points to align with job description phrasing. Preserve the candidate's original details and voice - adjust wording, do not rewrite entirely.
- DO NOT invent new information
- Preserve existing action verbs. Do not invent quantifiable achievements not in the original.
- Keep proper nouns (names, company names, locations) unchanged
- Translate job titles, descriptions, and skills to {output_language}
- Preserve descriptionStyles arrays and keep them aligned one-to-one with description arrays
- For customSections: preserve exact structure, item count, titles, subtitles, and years. If an item's description is an empty array [] in the original, keep it empty []. Do NOT generate descriptions for items that had none.
- Improve custom section content the same way as standard sections
- Copy every date POINT exactly as it appears: same years, same months, same open-ended status; never shorten or drop months. Presentation (numeric "yyyy.MM", tilde connector, 至今 for open-ended ranges) is normalized server-side, so copy the values faithfully rather than restyling them.
- Calculate and emphasize total relevant experience duration when it matches requirements
- Do NOT use em dash ("—") anywhere in the writing/output, even if it exists, remove it

Job Description:
{job_description}

Keywords to emphasize:
{job_keywords}

Original Resume:
{original_resume}

Output in this JSON format:
{schema}"""

IMPROVE_PROMPT_OPTIONS = [
    {
        "id": "nudge",
        "label": "Light nudge",
        "description": "Minimal edits to better align existing experience.",
    },
    {
        "id": "keywords",
        "label": "Keyword enhance",
        "description": "Blend in relevant keywords without changing role or scope.",
    },
    {
        "id": "full",
        "label": "Full tailor",
        "description": "Comprehensive tailoring using the job description.",
    },
]

IMPROVE_RESUME_PROMPTS = {
    "nudge": IMPROVE_RESUME_PROMPT_NUDGE,
    "keywords": IMPROVE_RESUME_PROMPT_KEYWORDS,
    "full": IMPROVE_RESUME_PROMPT_FULL,
}

DEFAULT_IMPROVE_PROMPT_ID = "keywords"

# Backward-compatible alias
IMPROVE_RESUME_PROMPT = IMPROVE_RESUME_PROMPT_FULL

COVER_LETTER_PROMPT = """Write a brief cover letter for this job application.

IMPORTANT: Write in {output_language}.

Job Description:
{job_description}

Candidate Resume (JSON):
{resume_data}

Requirements:
- 100-150 words maximum
- 3-4 short paragraphs
- Opening: Reference ONE specific thing from the job description (product, tech stack, or problem they're solving) - not generic excitement about "the role"
- Middle: Pick 1-2 qualifications from resume that DIRECTLY match stated requirements, and reframe them in the job's language/terminology where the candidate's proven experience supports it (e.g., if the resume shows "built automated data pipelines" and the job says "ETL," describe that real work as ETL) - prioritize relevance over impressiveness
- Closing: Simple availability to discuss, no desperate enthusiasm
- If resume shows career transition, frame the pivot as intentional and relevant
- Extract company name from job description - do not use placeholders
- Do NOT invent information not in the resume
- Tone: Confident peer, not eager applicant
- Do NOT use em dash ("—") anywhere in the writing/output, even if it exists, remove it

Output plain text only. No JSON, no markdown formatting."""

OUTREACH_MESSAGE_PROMPT = """Generate a cold outreach message for LinkedIn or email about this job opportunity.

IMPORTANT: Write in {output_language}.

Job Description:
{job_description}

Candidate Resume (JSON):
{resume_data}

Guidelines:
- 70-100 words maximum (shorter than a cover letter)
- First sentence: Reference specific detail from job description (team, product, technical challenge) - never open with "I'm reaching out" or "I saw your posting"
- One sentence on strongest matching qualification with a concrete metric if available
- End with low-friction ask: "Worth a quick chat?" not "I'd love the opportunity to discuss"
- Tone: How you'd message a former colleague, not a stranger
- Do NOT include placeholder brackets
- Do NOT use phrases like "excited about" or "passionate about"
- Do NOT use em dash ("—") anywhere in the writing/output, even if it exists, remove it

Output plain text only. No JSON, no markdown formatting."""

INTERVIEW_PREP_PROMPT = """Generate structured interview preparation for this tailored resume and job.

IMPORTANT: Write in {output_language}.
Do NOT translate JSON property names. Keep every JSON key exactly as shown in the schema; translate only string values.

Job Description:
{job_description}

Candidate Resume (JSON):
{resume_data}

Truthfulness guardrails:
- Use only evidence from the resume JSON and job description.
- Do NOT invent experience, tools, employers, metrics, certifications, skills, responsibilities, education, projects, or claims beyond the provided evidence.
- Do NOT imply the candidate has a skill or background unless it is present in the resume.
- Skill gaps are preparation targets only. They are not claimed candidate skills.
- If a job requirement is not evidenced by the resume, present it as something to prepare for or explain honestly.

Return ONLY a valid JSON object with exactly these top-level keys:
{{
  "role_fit_analysis": ["Short evidence-based role-fit observation"],
  "resume_questions": [
    {{
      "question": "Interview question grounded in the resume and job",
      "focus_area": "Resume evidence or job requirement being tested",
      "suggested_answer_points": ["Truthful point based on resume evidence"]
    }}
  ],
  "project_follow_ups": [
    {{
      "question": "Follow-up question about a real resume project or experience",
      "focus_area": "Project, impact, tradeoff, or implementation detail",
      "suggested_answer_points": ["Truthful point based on resume evidence"]
    }}
  ],
  "skill_gaps": [
    {{
      "skill": "Job-relevant skill or topic to prepare",
      "why_it_matters": "Why this topic may come up for this role",
      "preparation_suggestion": "How to prepare without claiming unsupported experience"
    }}
  ],
  "talking_points": ["Concise role-specific talking point grounded in the resume"]
}}

Content requirements:
- role_fit_analysis: 3-5 bullets.
- resume_questions: 5-8 questions.
- project_follow_ups: 3-6 questions.
- skill_gaps: 3-5 preparation targets.
- talking_points: 5-8 concise points.
- Keep all suggested answer points factual and resume-grounded.
- Do NOT use markdown fences or commentary outside the JSON."""

GENERATE_TITLE_PROMPT = """Extract the job title and company name from this job description.

IMPORTANT: Write in {output_language}.

Job Description:
{job_description}

Rules:
- Format: "Role @ Company" (e.g., "Senior Frontend Engineer @ Stripe")
- If the company name is not found, return just the role (e.g., "Senior Frontend Engineer")
- Maximum 60 characters
- Use the most specific role title mentioned
- Do not add any other text, quotes, or formatting

Output the title only, nothing else."""

# Alias for backward compatibility
RESUME_SCHEMA = RESUME_SCHEMA_EXAMPLE

# Diff-based improvement: outputs targeted changes instead of full resume

DIFF_STRATEGY_INSTRUCTIONS = {
    "nudge": "Make minimal edits. Only rephrase where there is a clear match. Do not add skills, skill elaborations, project rows, or bullet points.",
    "keywords": (
        "Be assertive about the technologies the job emphasizes. For EVERY core "
        "JD technology the candidate can substantiate, close the three-place "
        "loop: (1) a detailed entry in professional skills (add_skill or "
        "elaborate_skill), (2) a bare tech-name row in each relevant project's "
        "tech-stack region, and (3) a project-highlight bullet showing its "
        "concrete business-scenario application (both via insert_row). Do not "
        "append ordinary new bullet points; rephrase existing bullets freely."
    ),
    "full": (
        "Make targeted adjustments, and be assertive about the technologies the "
        "job emphasizes. For EVERY core JD technology the candidate can "
        "substantiate, close the three-place loop: (1) a detailed entry in "
        "professional skills (add_skill or elaborate_skill), (2) a bare "
        "tech-name row in each relevant project's tech-stack region, and (3) a "
        "project-highlight bullet showing its concrete business-scenario "
        "application (both via insert_row). You may also append bullets that "
        "elaborate on existing work, but never invent new responsibilities."
    ),
}

# NOTE: keep this prompt short and imperative. Even with response_format
# json_object, DeepSeek-style models answer a verbose multi-paragraph brief
# with chain-of-thought prose (no JSON) instead of the plan; the router then
# catches the parse failure and continues with ZERO verified targets, which
# silently neutralizes the whole assertive tailoring pass. Short command-style
# rules ("List every ...", "Return ONLY a raw JSON object") reliably produce
# JSON. Add requirements as terse numbered rules, not prose paragraphs.
SKILL_TARGET_PLAN_PROMPT = """Build a concise skill target plan for tailoring this resume to the job.

Return ONLY a raw JSON object. No prose, no reasoning, no markdown. Do not rewrite the resume.

Rules:
1. List every technology, framework, platform, and technical capability the JD states as required or preferred, including ones missing from the resume skills list; a downstream verifier decides which are supportable. Put the most heavily emphasized ("must-have", repeated, core) skills first.
2. Also include existing resume skills that are highly relevant to the JD, even when the JD does not name them explicitly.
3. Keep each reason to ONE short phrase in this format: "core requirement/preferred/supporting; demonstrated in <project/entry>" or "core requirement/preferred/supporting; not demonstrated".
4. When a technology already appears in the resume skills list in ANY form (a bare entry, a long "Name: detail" sentence, or a name embedded in a category/group row such as "后端：Java、Kafka"), mark it as demonstrated and quote that entry in the reason; never call it missing.
5. Do not include skills unrelated to the JD.
6. Do not include certifications.
7. Generate reasons in {output_language}.

Existing resume skills:
{existing_skills}

JD keywords and skills:
{job_keywords}

Job Description:
{job_description}

Resume JSON:
{original_resume}

Output this exact JSON format:
{{
  "target_skills": [
    {{
      "skill": "skill name",
      "reason": "core requirement/preferred/supporting; demonstrated in <project/entry> or not demonstrated"
    }}
  ],
  "strategy_notes": "name the JD's core technologies and the resume projects that demonstrate them"
}}"""

DIFF_IMPROVE_PROMPT = """Given this resume and job description, output a JSON object with targeted changes that better align the resume with the job.

The tailoring must be assertive about the technologies the job emphasizes: each CORE technology of the job description that the candidate can substantiate must visibly appear in BOTH places - (a) professional skills as its own DETAILED entry (never a bare stack dump), and (b) project experience, both as a tech-stack row and inside a project-highlight bullet that shows its concrete business-scenario application. This is a closed loop across three places; see the THREE-PLACE SKILL LOOP below.

RULES:
1. Only modify content; never change names, companies, dates, institutions, or degrees
2. Do not invent metrics or achievements not supported by the original resume text; this includes scale figures, versions, years of experience, and rankings. Skill details and inserted project rows MUST NOT contain any digits unless the source text already contains them - describe capability qualitatively instead
3. Do not add new work entries, education entries, or project entries
4. {strategy_instruction}
5. Each replace change MUST include the original text copied exactly so it can be verified; use null for "original" on reorder/add_skill/elaborate_skill/insert_row actions
6. For each change, explain WHY it helps match the job description
7. Generate all new text in {output_language}
8. Do not use em dash characters
9. Do not rewrite content that already aligns well
10. Only add or elaborate skills, and only insert project rows, for technologies listed in "Verified skill targets" below. Targets tagged (jd_added) are not evidenced in the resume: they may be added to the skills list for reviewer approval, but MUST NOT be claimed inside any project's tech stack or highlights unless that project's existing text already demonstrates the technology
11. By DEFAULT, scan the summary and every work, project, and education description for content that already demonstrates a job-description keyword or skill, and reframe that text using the job description's terminology where it is not already phrased that way (per rule 9, leave content that already aligns well), while preserving the candidate's actual accomplishment. Do NOT add new work, metrics, or responsibilities; only restate existing content in the JD's language, and verify every reframe stays factually accurate
12. Preserve original capitalization, especially for proper nouns, technical terms (e.g., REST, API, AWS), and acronyms. Do not change the casing of words that were capitalized in the original

THREE-PLACE SKILL LOOP (apply to every core JD technology the candidate substantiates):
A. Professional skills - the technology must appear as its OWN detailed sentence:
   - Style: every NEW or expanded entry MUST open with a proficiency-positioning word chosen to match the job description's emphasis on that technology. Chinese: "精通" (a core/expert-level JD requirement), "深入理解" (deep principles), "熟练掌握" / "熟练使用" / "熟练运用" (skilled daily use), "熟悉" (familiar), "了解" / "具备" (awareness). English: "Expert in", "Deep understanding of", "Proficient in", "Experienced in", "Familiar with", "Working knowledge of". Continue directly into WHAT the technology is used FOR (e.g., "熟练掌握 Redis 核心数据结构与缓存、分布式锁等典型用法").
   - NEVER write a "Name: detail" label prefix for add_skill (forbidden forms: "Kafka：……", "Kafka: ……"). Position the technology name naturally inside the sentence, like the resume's existing detailed entries.
   - If it is missing entirely: action "add_skill" on path "additional.technicalSkills"; value is one proficiency-first sentence, naming at most two verified technologies.
   - If it exists as a BARE single-technology entry: action "elaborate_skill" on path "additional.technicalSkills[i]" (i = its index). The value may be EITHER a proficiency-first sentence containing the exact bare name, OR the legacy form starting with the exact existing name followed by a separator ("：" for Chinese, ":" or " - " otherwise) and the capability detail.
   - If an entry is ALREADY a detailed proficiency sentence (it already opens with 精通/熟练/熟悉/了解/Proficient/Familiar etc.), skip A for that technology entirely: do NOT re-polish, shorten, or reword it, and NEVER use action "replace" on additional.technicalSkills entries.
   - The sentence is a SINGLE line of at most two visual lines (about 90 Chinese characters or 160 Latin characters). It must say WHAT the technology is used FOR (e.g., distributed caching, stream processing, declarative API development), not list more technology names. Never elaborate a category/group row that already contains "、", ":", or "："; never add new digits, versions, or year counts.
   - DEDUPLICATION: never add a technology the skills list ALREADY contains in any form - a bare entry, an elaborated "Name: detail" entry, a proficiency sentence naming it, or a name embedded in a category/group row such as "后端：Java、Kafka". In those cases use elaborate_skill (bare entries only) or skip A; do not create a second entry for the same technology.
B. Tech stack - in a project whose existing narrative text ALREADY names the technology (its responsibilities or highlights describe real use in THAT project), its BARE name must appear as one row in the project's 技术栈 / Tech Stack sub-module: action "insert_row", path "personalProjects[i].description", "anchor": "tech_stack". The value is the bare technology name ONLY (exact verified spelling, at most 40 characters, no separator punctuation, no digits, one technology per row). EVIDENCE: the technology must already be named somewhere in THAT project's own rows; a mention in another project, or only in the global skills list, is not evidence - never plant a stack row into a project that does not demonstrate the technology. DEDUPLICATION: list each technology at most once per project - do not insert it when the stack region already lists the name on its own row, inside a combined row ("Kafka、RocketMQ"), or with a qualifier ("Kafka（消息队列）").
C. Highlight - in that same project, one row in the 项目亮点 / Project Highlights sub-module: action "insert_row", same path, "anchor": "highlight". The value is one single line (at most two visual lines, no digits or quantified claims) stating a CONCRETE business-scenario application of the technology in THIS project (what problem it solved or what part of the system it powered), and it MUST contain the technology's name verbatim. GROUND IT IN THIS PROJECT: reuse the project's own vocabulary - name the actual modules, mechanisms, or problems already written in that project's rows (read those rows carefully and echo their nouns). Generic capability filler that any Kafka project could use ("通过Kafka实现高效异步通信，提升系统性能与稳定性") is forbidden and rejected. When an existing bullet already makes the point, do NOT insert a near-duplicate - use action "replace" to reframe that bullet with the technology's name and JD terminology instead. A second insert for the same technology is allowed ONLY for a genuinely different scenario already visible in the project's text.

insert_row mechanics:
- Path is always "personalProjects[i].description" with "anchor" set to "tech_stack" or "highlight".
- The server inserts the row at the end of the correct sub-module region and aligns descriptionStyles automatically; if the project has no such region, the server creates it with a canonical bold label ("技术栈：" / "项目亮点：" or "Tech Stack:" / "Project Highlights:"). Therefore NEVER put a label, list numbering, or a bullet marker inside "value", and do NOT output descriptionStyles edits.
- Never insert into a project whose existing text does not support the technology's actual use; fabricating usage is forbidden. A tech-stack row is accepted only when THAT project's own narrative rows already name the technology.
- A highlight is accepted only when it names a verified technology that the project demonstrates AND reuses that project's own scenario vocabulary (its real modules, mechanisms, problems); generic market-standard filler and restatements of existing bullets are rejected deterministically - use "replace" to reframe an existing bullet instead.
- Duplicate rows are rejected deterministically by the server: a technology already present in the stack region, and a highlight that repeats the same technology in the same scenario, must not be emitted.

PATHS you can target:
- "summary" - the resume summary text
- "workExperience[i].description[j]" - a specific bullet (i = entry index, j = bullet index)
- "workExperience[i].description" - append a new bullet (action: "append")
- "personalProjects[i].description[j]" - a specific project bullet (replace)
- "personalProjects[i].description" - append a normal bullet (action: "append") or insert a tech-stack/highlight row (action: "insert_row" with "anchor")
- "education[i].description" - the education entry's description text (replace only; it is a single string, not a list)
- "additional.technicalSkills" - reorder the skills list (action: "reorder") or add one verified skill (action: "add_skill")
- "additional.technicalSkills[i]" - turn a BARE skill entry into a detailed one (action: "elaborate_skill"); action "replace" is never valid on skills, and already-detailed proficiency sentences must be left untouched
- "additional.languages" - reorder the languages list (action: "reorder")
- "additional.certificationsTraining" - reorder the certifications list (action: "reorder")
- "additional.awards" - reorder the awards list (action: "reorder")

Do NOT target: personalInfo, dates/years, company names, education degree/institution/years, customSections, descriptionStyles.

Keywords to emphasize (only if already supported by resume content):
{job_keywords}

Verified skill targets:
{skill_targets}

Job Description:
{job_description}

Original Resume:
{original_resume}

Output this exact JSON format, nothing else:
{{
  "changes": [
    {{
      "path": "workExperience[0].description[1]",
      "action": "replace",
      "original": "the exact original text at this path",
      "value": "the improved text",
      "reason": "why this change helps"
    }},
    {{
      "path": "additional.technicalSkills",
      "action": "reorder",
      "original": null,
      "value": ["most relevant skill first", "then next", "..."],
      "reason": "reordered to prioritize JD core technologies"
    }},
    {{
      "path": "additional.technicalSkills",
      "action": "add_skill",
      "original": null,
      "value": "熟悉 Kafka 高吞吐分布式事件流，用于服务异步解耦与高峰流量削峰",
      "reason": "core JD technology missing from the skills list, added as a proficiency-positioned capability sentence"
    }},
    {{
      "path": "additional.technicalSkills[3]",
      "action": "elaborate_skill",
      "original": null,
      "value": "Redis：分布式缓存与会话存储，负责热点数据读写、过期策略与高可用方案设计",
      "reason": "core JD technology was a bare stack entry; expanded to its core capability, within two lines"
    }},
    {{
      "path": "personalProjects[0].description",
      "action": "insert_row",
      "anchor": "tech_stack",
      "original": null,
      "value": "Kafka",
      "reason": "the JD core technology must appear in the project tech-stack sub-module"
    }},
    {{
      "path": "personalProjects[0].description",
      "action": "insert_row",
      "anchor": "highlight",
      "original": null,
      "value": "基于 Kafka 构建订单事件异步流水线，解耦下单与下游履约环节，并在促销高峰承担流量削峰",
      "reason": "shows the technology's concrete business-scenario application inside this project"
    }}
  ],
  "strategy_notes": "brief summary of the tailoring approach and the JD core technologies covered"
}}"""
