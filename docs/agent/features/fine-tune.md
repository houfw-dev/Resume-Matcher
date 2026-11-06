# 简历智能微调（Fine-Tune）

结合**上传原文 `original_markdown`** 与**解析后的结构化数据 `processed_data`**，对简历做无 JD 的自我润色：让内容更有逻辑、更有重点。用户选择范围（整体 / 模块 / 模块内条目）→ 生成预览 → 在「当前模板真实渲染」与「改动对照」两个视图间核对 → 选择**覆盖原简历**或**另存副本**落库。

与既有 AI 能力的边界：

| 能力 | 是否绑定 JD | 产物 | 事实依据 |
| --- | --- | --- | --- |
| Tailor（/improve） | 必须 | 总是另存新简历 + Improvement | 结构化数据 |
| Enrichment regenerate | 否 | 逐条改写 work/project/skills 描述行 | 结构化数据 |
| **Fine-Tune** | **否** | 用户选择覆盖或副本，**不产生 Improvement、不进 tracker** | **结构化数据 + 原文双证据源** |

---

## 1. 范围语法（前后端共享语义）

scope 为 `{kind: "all" | "modules", targets: string[]}`：

- `all`：整体微调；`targets` 必须为空。
- `modules`：1–30 个去重 target，正则白名单
  `^(summary|education|additional|customSections|workExperience|personalProjects|work_\d+|project_\d+|(work|project)_\d+:(techStack|background|duties|highlights|achievements|role)|custom_[\w.-]+)$`。
- 模块 token：`summary` / `education` / `additional`（技能、语言、证书、奖项整体）/ `workExperience` / `personalProjects`。
- 自定义块 token：
  - `custom_<key>`：**单个自定义版块**，`<key>` 为 `customSections` 字典键（解析器产 snake_case slug；builder 自建键本身是 `custom_N`，故 token 带双前缀 `custom_custom_1`；正则用 Unicode `\w`，容许不合规解析器产出的 CJK 键）。
  - `customSections`：全部自定义块整体的**遗留整包 token**，后端全链路保留（旧预览 TTL 内 replay 不坏），但弹窗 UI 不再产生它。
  - **per-key overlay 语义**：结果始于 source 深拷贝，仅把选中 key 替换为候选对应 key；key 必须在 source 与 candidate **两侧都存在**，否则该 token 进 ignored 警告；candidate-only 新 key 在 per-key 范围绝不并入（整段 `customSections` 是唯一并入新键的途径）；整段 token 在场时压制全部 `custom_*`（不进 ignored，同 workExperience/work_N）。
  - 语法合法但简历中无此键（如 `custom_ghost`）是**运行时 ignored 警告，不是 422**（与 `work_9` 同哲学）。
- 条目 token：`work_N` / `project_N`，**N 从 0 起，取存储（canonical 预览）序列索引**，与 enrichment 的 `exp_N` / `proj_N` 同索引约定（不是同一套 ID，但同一份 canonical 序列派生，前端从 `normalizeResumeForRender` 后的保存数据生成）。
- **子模块（label 分区）token**：`work_N:<region>` / `project_N:<region>`，第三级粒度——只改某一条目内某个标签分区下的行。六个 region id：

  | id | 项目条目 | 工作条目 |
  | --- | --- | --- |
  | `techStack` | ✅（技术栈；别名 技术选型/技术架构/所用技术/技术清单/技术列表） | ✅（同一组别名） |
  | `background` | ✅（项目背景；别名 项目概述/简介/概况/介绍/业务背景/需求背景） | — |
  | `duties` | ✅（项目职责；别名 工作职责/主要职责/负责内容/核心工作/工作内容，及组合标题 项目职责与成果/和成果/及成果、工作职责与成果/和成果/及成果、职责与成果/和成果/及成果——职责+成果合并标题归入职责区） | ✅（curated：工作职责/工作内容/主要职责/核心职责/责任描述/负责内容/核心工作，及同一组职责+成果组合标题；工作条目标签逐字保留不改名） |
  | `highlights` | ✅（项目亮点；别名 项目成果/技术亮点/技术难点/难点与解决/技术难点及亮点） | — |
  | `achievements` | — | ✅（curated：工作业绩/项目业绩/主要成果/核心成果/工作成果） |
  | `role` | — | ✅（curated：项目角色/担任角色） |

  - **分区区间** = 标签行之后、下一个 heading 形行（`style ∈ {label, plain}` 且呈独立短标题形）之前的内容行；**标签行本身永不改写**。第一个标签之前的松散行不属于任何分区；无法归类的独立标题（如 `解决方案：`）**关闭当前分区**，其行不可选、分区微调中冻结；`项目描述：`/`系统架构：`/`架构说明：` 是仅描述性分隔标签，不产生分区。项目职责/亮点区内出现的未知加粗冒号头视为**嵌套编号头**，留在当前分区内。同一 id 出现多次（两个职责块）→ 一个 token，区间取并集。
  - 项目标签经解析器 `PROJECT_SUB_LABEL_CANONICAL` 归一识别（显示仍用存储原文，如 `技术选型：`）；**工作标签只识别上表 curated core，绝不归一化、不改名**（parser 行为零改动，旧测试继续锁定）。
  - 形状合法但该条目无此分区（如项目条目上的 `project_0:achievements`、条目中不存在的 region）或条目越界（`project_9:highlights`）→ **运行时 ignored 警告，不是 422**（与 `work_9` 同哲学）。
  - **压制层级**：整段 token 在 → 该段全部 item/region token 被压制；同条目 item token 在 → 其 region token 被压制（整条优先，均不进 ignored）。前端勾选整条时清扫该条目的 region token。
  - **行数不变 + 原位替换**：分区 overlay 在 source 深拷贝上按行号一对一替换区间内容行，**样式默认取源行不动**（plain 仍 plain、bullet 仍 bullet），标签行与区间外行逐字节冻结；模型多产出/合并/拆分出的行一律丢弃。任一分区存在被丢弃的追加行 → 警告 `REGION_APPEND_DROPPED`（前端按前缀本地化）。
  - **显式排版请求例外（plain ↔ bullet）**：当用户指令明确要求把分区内段落改成有序列表（或反向改回段落）时，区间内对齐保留行的 `plain`/`bullet` 样式随候选翻转（见 §3 样式编辑策略）；`label` 样式永不参与翻转。
- **`personalInfo` 与 `sectionMeta` 没有 token，任何范围下都冻结**（对齐 apply_diffs 的 `_BLOCKED_PATH_PREFIXES`）。

前端纯函数在 `apps/frontend/lib/utils/fine-tune-scope.ts`（构建/校验/去重/30 上限、整体选区与条目选区互斥、`customSections` 与 `custom_<key>` 互斥、token → 渲染标题组映射、自定义块键↔token 往返、蓝框标题解析、标题归一化匹配、region token 的 `regionToken`/`parseRegionToken`/`toggleRegionToken`）；分区提取（description + styles → 标签区间）两侧镜像实现：后端 `app/services/description_regions.py`（`entry_label_regions` / `merged_entry_regions`，复用 parser 常量），前端 `lib/utils/description-regions.ts`（`extractEntryRegions` / `mergedEntryRegions`，复用 `list-format.ts` 的标签判定），两侧以同一份夹具矩阵对拍测试锁定一致；后端 schema 镜像校验在 `app/schemas/fine_tune.py`，范围裁剪在 `app/services/fine_tune.py::restrict_to_scope`（自定义块 per-key overlay + region overlay），行回溯用 `resume_preservation.merge_row_provenance`（`{source_index: finalized_index}` + 追加行下标），scope 描述（prompt 内）经 `_custom_display_name` 从 `sectionMeta` 解析真实版块名、经 region 区间给出标签原文与行数。

## 2. 后端流水线（`app/services/fine_tune.py::run_fine_tune`）

1. 取 `processed_data`（无结构化数据 → 400）与 `original_markdown`（可能为空）。规范源 `_canonical_source` 对深拷贝运行 `normalize_resume_data`（读时治理链：部首归一化、项目样式修复、教育/工作/项目错放凭证确定性归位、去重），再经 ResumeData 往返——AI 看到的输入与用户在查看页所见一致，且不 mutate 库中原始数据。指纹仍只哈希数据库原始三列，归一化不落库、不参与 `source_hash`；preview 注册与 confirm replay 两侧对同一行计算同一纯函数，逐字节一致，400/409 契约不变。
   - **语义变化（模块级范围）**：标签形态的错放凭证（`奖项：…/证书：…/语言：…`）由规则在 AI 之前确定性归位，**无视勾选范围**，冻结中的 `additional` 也会被治愈（与 GET 内存自愈、PATCH 落库自愈同一治理哲学）；规则不敢动的**无标签散文**（如「持有 PMP 证书的轮岗」）仍保持原位，模块级微调照常回传 `SCOPE_RELOCATION_HINT` 引导用户改做整体微调——LLM 归位长尾兜底不变。
2. 原文截断到 20,000 字符（复用 `interview_prep._truncate_text_for_prompt`，带截断告示）；结构化 JSON 序列化上限 30,000；指令经 improver 的 `_sanitize_user_input` 清洗，schema 层 strip + 限 2000 字符。
3. `complete_json(prompt, schema_type="fine_tune", max_tokens=8192, response_validator=ResumeData 往返)`。prompt 见 `app/prompts/fine_tune.py`：只允许改动范围内模块、允许把**原文中存在但结构化漏掉**的事实补回、禁止引入两个来源都没有的事实/数字/公司/时间、保持输出语言、输出完整 ResumeData JSON。scope 描述含 `sub-module`（region token）时，EDITING PRINCIPLES 常驻规则要求：只改写该标签自己拥有的行、**输出行数与区间行数完全一致**、原位一对一替换、不得合并/拆分/跨行或跨条目迁移、标签行（文本与 style）与其余所有行逐字节复制。另含 **PRESENTATION REQUESTS** 常驻规则：用户明确要求有序列表/编号列表/分级列表或改回普通段落时，仅可把受影响行在 `"bullet"`（编号点）与 `"plain"`（无编号段落）间翻转、文本与行数不变；`"label"` 样式永远不得指派或撤销，无显式排版要求时任何样式都不得改动。注意渲染规则：职责/亮点区内加粗冒号嵌套头下的**所有明细行一律渲染为 1.1/1.2 二级子点**（不区分 plain/bullet），plain↔bullet 翻转只在松散列表等其余位置控制编号有无。
4. **接地**：`finalize_ai_resume(source, candidate, allow_review_claims=True, allow_appended_rows=True, allow_style_edits=True, extra_evidence=original_markdown or None)`（`allow_style_edits` 仅微调路径开启，见下节；见 §3）。
5. **范围裁剪**：`restrict_to_scope` 深拷贝 source，按范围把接地后的数据放回；work/project 条目用 `resume_preservation._identity(entry, section)` 做身份匹配（抵御模型重排），只替换命中的索引槽，越界/未匹配 target 进 `ignored_targets` 并以 `Ignored out-of-range target: x` 警告回传；自定义块 per-key overlay 仅替换两侧都存在的 `custom_<key>` 键（整段 `customSections` 压制细粒度 token；见 §1）；**region overlay** 把同条目 region token 分组，整段/整条 token 在场则跳过，区间由 **source 条目**经 `merged_entry_regions` 计算（多 token 取并集），候选行经 `merge_row_provenance(source, candidate)` 回溯到源行号后原位替换 `description[i]`；样式默认原样保留，**唯一例外**是终审已按排版请求放行的 plain↔bullet 翻转（区间内、源/候选两侧均为 plain/bullet 且不同 → 跟随候选；label 行不动），未命中的源行留源行、追加行一律不进分区（任一分区丢过追加行 → 返回 dropped 标志，`run_fine_tune` 追加 `REGION_APPEND_DROPPED` 警告）；overlay 是确定性纯函数，preview 注册与 confirm replay 走同一函数保证逐字节对称；最后 ResumeData round-trip。
6. `grounding_review_warnings(...)` + `calculate_resume_diff(...)`（diff 失败只加 `DIFF_UNAVAILABLE_WARNING`，不阻断）。
7. **不调用** `sort_timeline_sections_newest_first`：LLM 的逻辑重排原样保留。

> **改动对照的判定语义**（`improver.calculate_resume_diff`，fine-tune 与 improve 共用）：工作经历与**项目经历**的描述行都逐行配对比较（`workExperience[i].description` / `personalProjects[i].description`，计入 chips「修改 N 条描述」）；条目的「修改」卡只在**可见标量字段**（title/company/name/role/years/location 等）实际变化时产生——纯 `description` 文本、`descriptionStyles`、`id` 差异不产生条目卡（描述变化走逐行卡；样式/id 对用户不可见），头部未变而次要标量变化时以 `key: value` 多行附加到 Before/After。技能/证书/语言/奖项按 casefold 集合比较，顺序不敏感。

## 3. 双证据源接地（`resume_preservation.finalize_ai_resume`）

`finalize_ai_resume` / `validate_confirmed_resume` / `grounding_review_warnings` 向后兼容地新增 `extra_evidence: str | None = None`：

- `None`（improve/enrichment 等既有调用方）→ 算法与逐字节行为完全不变，既有测试零改动。
- fine-tune 传入原文后：候选描述行中的**数字**若出现在证据文本中，不计为「虚构新数字」；定性行的相似度闸门在 `source_tokens ∪ evidence_tokens` 上计算。证据中仍无据的数字照剥；无法证实的定性表述以 `GROUNDING_REVIEW …: detail` 警告保留（预览路径允许 review claims，由用户人工核对）。

即：**原文能补回，两个来源都没有的事实禁止出现**。

> **标签样式保真修复**：终审器 `_merge_description_rows` 的样式白名单原为 `{"bullet","plain"}`，源行的 `"label"` 样式一律被降为 `"bullet"`——标签降级后前端无法分区渲染，整条描述落入一个连续 `<ol>`（微调后技术栈/背景/职责/亮点变成 1.–N. 连续编号的根因）。白名单（两处取样式点 + `_description_contract_preserved` 契约校验）扩大为 `{"bullet","plain","label"}`，**全部微调路径受益**。merged 样式仍只取自源行，候选无法注入样式；追加行固定 `"bullet"`（模型不得凭空制造标签），无注入面。

> **日期仅格式改写放行（`years` 保护例外）**：条目标题字段（id/institution/company/title/years 等，`_PROTECTED_FIELDS`）终审一律从源恢复，模型改不了真实日期；但用户通过微调要求**只改呈现格式**（如「受教育的时间改成 yyyy.MM - yyyy.MM」，源为 `2016 年 06 月 - 2020 年 09 月`）曾被这层保护静默还原，表现为「明明要求了却改不了」。现 `_date_points` 把两侧 years 解析为有序 `(年, 月)` 点序列 + 至今标记（支持中文年月日、`YYYY.MM`、`YYYY/MM`、`YYYY-MM`、英文月份、纯年份，与 parser 的日期识别镜像）：**点数相同、年/月逐点一致、至今标记一致 → 判定仅格式差异，保留候选写法**（`_merge_entries` 与 `_entry_bucket_violation` 契约对称放行，preview→confirm 重放逐字节一致）。月份精度丢失（`2016.06 - 2020.09` → `2016 - 2020`）、凭空补月份（`2016 - 2020` → `2016.06 - 2020.09`）、日期本身变化（`2016` → `2017`）、至今↔具体日期不一致仍判定为真实修改，继续从源还原并计 `identity` 契约违规；improve/tailor 路径同源受益，且不与 `restore_dates_from_markdown` / `_restore_original_dates` 冲突（月份未丢失，两道安全网不动）。

> **显式排版请求放行（`allow_style_edits`，仅微调开启）**：merged 描述样式默认逐行绑定源行，候选无法注入样式；但用户明确要求「把某分区下的内容用有序列表重新格式化」（plain 段落 ↔ bullet 编号点）时，这层冻结会让排版指令静默失效（截图报告：项目亮点下「重大生产环境问题解决：」「性能调优：」的段落改不了编号）。现终审新增 opt-in `allow_style_edits`（**仅** `run_fine_tune` 与 fine-tune confirm 重放传 True；improve/parse/refine 默认 False，行为逐字节不变）。放行条件全部满足才采纳候选样式：① 候选 description/descriptionStyles 都是等长 list 且逐行一一对应（任何行内含换行被规范化成多行、数组缺式/错位 → 整体忽略候选样式）；② 该行文本被原样保留（发生数字虚构/奖项级别篡改/接地失败等 restore 时，样式随源文本一起还原）；③ 源样式与候选样式都属于 `plain`/`bullet`——**`label` 永远不来自候选**（候选不能把内容行提升成标签，也不能把标签降级）。item/section/all 范围下翻转随整条候选进入结果；region overlay 只在目标区间的源行槽内搬运翻转，区间外样式冻结。preview 与 confirm 重放走同一终审参数 + 同一 overlay 纯函数，逐字节对称（缺任一侧开关 → 重放 400「no longer satisfies preservation rules」，由集成测试锁定）。
>
> **渲染端配套（嵌套冒号头分级有序列表）**：项目亮点/职责区内的未知加粗冒号头（如「重大生产环境问题解决：」「性能调优：」）始终是模块列表的**一级加粗编号点**（1. 2. 3. 连续编号）；其下**每一条明细行（不区分 plain/bullet 样式）都成为二级子列表**（用户规则：下级模块下内容仍分层时用有序列表）——多缩进一个编号槽，编号为复合标记 `1.1、1.2 … / 2.1、2.2 …`，每个一级头下重新计数（前端 `list-format.ts` 嵌套头打开期间无条件打行 `level: 2`，`description-list.tsx` 两级计数器；Word 导出 `resume_docx.py` 元组第 4 元素 `level` + 0.6/1.2 cm 两级缩进逐行镜像）。另：独立短标题正则三处镜像（`parser._STANDALONE_SUB_LABEL_RE`、`resume_docx._STANDALONE_LABEL_RE`、前端 `STANDALONE_LABEL_RE`）放宽为允许标题内部出现空格/连字符，使模型改写的 `CPU 飙升问题：`（拉丁前缀 + 空格）仍被识别为嵌套头而不是被降级成无编号正文。解析器读时自愈已允许 plain↔bullet 编辑穿越 GET/PATCH，无需改解析器。

> **Overlay 后的样式保持终审（`_validate_scoped_result`）**：范围裁剪/overlay 之后不重放完整 `normalize_resume_data`（完整链含区域样式状态机，会撤销用户显式要求的 plain↔bullet 排版翻转），只跑两个**样式保持**工序：`canonicalize_tech_terms`（技术术语规范大小写，如 `java→Java`）+ `normalize_text_hygiene`（trim、空白折叠、空行与样式等长双删、列表点尾标点统一），再做 `ResumeData` round-trip。这两个工序不触碰 `descriptionStyles`，故 AI 输出与导入解析一样满足日期/术语/标点/空白的全篇格式一致规则，同时排版翻转结果得以保留。

## 4. 预览记录表与租约（`fine_tune_previews`）

独立新表（不复用 `tailoring_previews`——后者与 `improvements.job_id` 均 NOT NULL，register/claim 内含 Job 断言）。无 ORM 外键；启动时 `Base.metadata.create_all` 自动建表。字段：`preview_id` PK、`source_id`（索引）、`scope_kind`/`scope_targets`(JSON)、`instruction`、`payload_hash`、`source_hash`、`prompt_id`（`fine_tune_v1`）、`claim_token`、`lease_expires_at`、`response_data`(JSON)、`result_resume_id`、`status`、`created_at`、`expires_at`。

协议（`app/database.py`，镜像 tailoring 的 register/claim/complete/release）：

- **register**：先 GC 过期行；`payload_hash` 经 ResumeData 往返后 sha256（共享 helper `app/preview.py::hash_resume_data`），`source_hash` 为 `resume_fingerprint(content, processed_data, original_markdown)`；同 source + 同 payload 的未过期行**幂等复用同一 preview_id**。
- **claim**（confirm 时）：`source_hash` 变更（预览后编辑过简历）→ 409 `PreviewConflictError`；活跃租约 → 409 `PreviewBusyError` + `Retry-After: 1`。
- **complete**：写入 `result_resume_id`、`mode`、`title`；对同一 completed 行的重复 confirm **幂等重放**同一 `resume_id`，不再建第二份副本。
- 客户端回显的 `improved_data` hash 与注册不符，或重放接地 + 范围裁剪后不再等于注册数据（"Registered preview no longer satisfies preservation rules"）→ 400 `PreviewValidationError`。
- TTL 取 `settings.preview_ttl_seconds`；租约时长 `request_timeout_seconds + 15`。
- 清理：`delete_resume` 删除源简历时连带删除其预览行、删除结果副本时把行标记为 `response_data=None`；`reset_database` 清表。

## 5. 落库语义（`POST …/fine-tune/confirm`）

- **overwrite**：`update_resume` 四键——`content`（JSON 文本）、`content_type: "json"`、`processed_data`、`processing_status: "ready"`。**不写 `original_markdown`**（原文保留），`is_master` 等列不变。
- **copy**：`create_resume(is_master=False, parent_id=source_id, filename=f"finetuned_{原文件名}", original_markdown=继承, title=请求 title 或 f"{source title} (fine-tuned)")`。不产生 Improvement、不触发 tracker。

## 6. HTTP 契约

路由挂在 enrichment 之后、applications 之前；`AIOperationRoute`（仅包 POST），240s 操作预算。

### `POST /api/v1/resumes/{resume_id}/fine-tune/preview`

请求：`{scope: {kind, targets[]}, instruction?: string (≤2000), output_language?: string (≤16)}`。
响应：`{preview_id, expires_at, scope（回显）, improved_data: ResumeData, diff_summary | null, detailed_changes[], warnings[]}`。

| 状态 | 条件 |
| --- | --- |
| 200 | 成功；同 source+payload 重发返回同一 `preview_id` |
| 400 | 简历无结构化数据 |
| 404 | 简历不存在 |
| 409 | register 冲突 |
| 422 | target 非法 / kind 与 targets 组合非法 / 指令超长（`PromptSizeError` 同样映射 422） |
| 500 | 生成失败（通用文案，详情服务端日志） |
| 504 | 操作预算超时 |

### `POST /api/v1/resumes/{resume_id}/fine-tune/confirm`

请求：`{preview_id, improved_data: ResumeData（回显）, mode: "overwrite"|"copy", title?: string | null (≤200)}`。
响应：`{resume_id, mode, title}`。

| 状态 | 条件 |
| --- | --- |
| 200 | 落库成功；completed 预览重放返回同一 `resume_id` |
| 400 | 未知/过期 preview_id、回显 payload hash 不符、重放接地后不再满足保存规则 |
| 404 | 简历不存在 |
| 409 | 预览后简历被改过（`source_hash` 变更，需重新预览）；另一确认进行中（`Retry-After: 1`） |
| 422 | 请求体/schema 非法 |
| 500 | 落库失败（通用文案） |

## 7. 前端

- `lib/api/fine-tune.ts`：两个调用，经 `apiPost`（240s 默认超时），错误取 `data.detail`。
- `lib/utils/fine-tune-scope.ts`：范围 token 纯函数（单测覆盖）。
- `hooks/use-fine-tune-wizard.ts`：`idle → selecting → generating → previewing` 状态机，`useOperationOwner` 防过期响应，confirm 防重入。
- `components/builder/fine-tune/`：范围+指令弹窗（整体/模块两张 radio 卡；**三级勾选**：模块行 chevron → 条目行，条目可再 chevron 展开勾选真实存在的 label 分区；零选择禁用生成；指令可选、2000 字、Enter stopPropagation；生成中弹窗不可关闭）、预览弹窗（`RetroTabs` 两 tab）、容器组件。
  - **三级作用域选择**：条目的可勾分区由 `resume-builder.tsx` 对 canonical 数据调 `mergedEntryRegions` 派生（只列出条目里真实存在的 region id，无标签条目不显示分区 chevron）；只勾分区时条目行显示部分选中态（蓝色小方块），勾选整条则清扫分区 token 并隐藏分区面板，整段选中时条目 chevron 禁用——与整段→条目同一范式。
  - **分区蓝框**：scope 仅含 region token 的模块不再整体框选；扫描 effect 在匹配 section 内按 `[class*='resume-items'] > [class*='resume-item']` 定位第 N 个条目（六套模板共享的 class 命名，无需改模板），在其中按 `extractEntryRegions(improved_data)` 的标签 core 找 `[data-sub-label]`，给标签行及其后直到下一个 `[data-sub-label]` 的兄弟节点打 `data-fine-tune-highlight="region"`，CSS 为左侧 3px 蓝色硬边条（区别于整段 2px outline）。
  - **模块行内容驱动**（`resume-builder.tsx` 经 `hasSectionContent(meta, canonicalData)` 派生门控）：个人总结为空、无工作/项目条目、无教育/技能内容的行**不显示**；每个非空自定义版块**各占一行**，标签取 `sectionMeta.displayName` 真实版块名（默认版块标题锁定不可改名，沿用 i18n 文案），勾选产生 `custom_<key>` token；聚合的「自定义区块」整行不再出现（遗留整包 token 仅后端兼容）。自定义行为普通 CheckRow、无条目展开 chevron。
  - **渲染 tab** 直接复用 `PaginatedPreview`（improved_data + 当前 templateSettings）。模块/条目级范围的受影响模块通过 DOM 属性 `[data-fine-tune-highlight]` + 蓝框 outline 高亮（`globals.css` 一条规则；`MutationObserver` + 短定时重扫适配异步分页/镜像节点），**不穿透修改模板组件**；**region 级范围不框整段**，改为分区蓝条（见上）。精确差异看对照 tab。蓝框标签集由 `customHeadingLabels(targets, blocks)` 计算——自定义块从 `preview.improved_data` 的 `sectionMeta`/`customSections` 推导，故 `custom_<key>` 只框选对应块（整段 `customSections` 才框全部；重名显示标题的固有限制由 builder 的 `validateSectionName` 防重名兜底）。
  - **改动 tab**：diff chips（总数/描述/技能增减）+ 逐字段卡片（added/removed/modified 三色、field_path、Before/After）。
  - warnings：橙色 Alert；`GROUNDING_REVIEW` / out-of-range / diff 不可用 / **`REGION_APPEND_DROPPED`**（子模块微调保持原行数，模型多产出/合并的行未采纳）在前端按前缀本地化，其余原样展示。
  - 底部：取消 / 覆盖原简历（红色 outline + ConfirmDialog 二次确认）/ 另存副本（展开标题输入，默认后缀 ` (fine-tuned)`）。
- 入口：builder 工具栏「AI 智能微调」按钮（默认整体）+ 每个可微调模块 `SectionHeader` 上的 Wand2 按钮（预选该模块；自定义版块预选其 `custom_<key>` token，如 `custom_publications` / 双前缀 `custom_custom_1`；personalInfo 无按钮）。发起前 `flushResumeChanges(true)` 保证 `source_hash` 对应已保存数据。
- 成功后：overwrite → 重新 `fetchResume` 并同步 builder 全部版本状态 + 成功 toast；copy → `router.push('/resumes/{newId}')`。
- i18n：`fineTune.*` 键树，**7 个语种**（en/es/zh/ja/pt-BR/fr/ko）结构一致，locale-parity 测试与 build 守门；三级选择新增 `fineTune.dialog.selectRegions`、`fineTune.dialog.regions.{techStack,background,duties,highlights,achievements,role}`、`fineTune.preview.regionAppendDropped`。
- 不新增 npm 依赖。

## 8. 测试锁

- 后端 `tests/unit/test_resume_preservation.py`（`extra_evidence` 新例：证据中数字保留、None 时旧行为逐字节不变、无据数字仍剥、无关证据不放宽）、`tests/unit/test_ai_preservation.py`（71 例；**label 保真 3 例**：配对行改写后四个标签样式存活、被候选丢弃的源标签行连同 label 样式补回、追加行固定 bullet 不继承 label；**日期仅格式放行 7 例**：中文年月日→`YYYY.MM` 教育/工作/项目（含至今↔Present）、英文月份→数字保留、真实日期/月份精度丢失/凭空补月份/至今标记不一致均还原并计 identity 违规；**样式编辑 6 例**：plain→bullet/bullet→plain 仅在 `allow_style_edits=True` 时采纳且默认路径逐字节不变、候选 `label` 永不注入、行内换行拆行/样式数组错位时整体忽略候选样式、文本被还原的行样式随源还原、自定义版块 item 同样线程化）、`tests/unit/test_description_regions.py`（11 例：区间行号精确断言、别名归一、未知 standalone 标签关区、嵌套编号头留区、描述性分隔标签无 id、首标签前松散行排除、bullet 形标签不算 heading、work curated 标签识别且不改名、同 id 并集取首标签文本、空/无标签边界）、`tests/unit/test_fine_tune_service.py`（52 例：范围裁剪/身份匹配/越界/round-trip/scope 描述；端到端日期仅格式改写（中文年月日→`YYYY.MM`）落地、伪装成格式统一的真实日期改动仍还原；`_canonical_source` 归一化不 mutate 入参、工作错放凭证在模块级范围确定性归位、无标签散文仍出 `SCOPE_RELOCATION_HINT`、治愈源与模型输出不产生重复条目；**`custom_<key>` 9 例**：语法放行含 CJK/双前缀、畸形 422、per-key overlay 只替换目标键、source/candidate 单侧缺键 ignored、整段 `customSections` 压制细粒度 token、candidate-only 新键不并入、scope 描述解析真实版块名；**region 一组**：token 语法接受/畸形参数化（`work_0:bogus`/`project_x:x` 等）、overlay 只换目标分区且标签行与其余分区逐字节相等（含样式）、双 region 并集、item/section token 压制、无此分区/越界 ignored、追加行丢弃 + dropped 标志、scope 描述含 `sub-module "项目亮点："` 与行数/缺失措辞、work achievements overlay、`run_fine_tune` 出 `REGION_APPEND_DROPPED` 警告；**排版翻转 3 例**：region overlay 只在区间内搬运 plain→bullet（文本逐字节不变、区间外样式冻结）、label 样式双向注入（头提 bullet / 明细降 label）均被冻结、端到端模拟「项目亮点下两个嵌套冒号头明细改有序列表」（包块项目夹具，四行 plain→bullet 落地且无 dropped 警告））、`tests/integration/test_fine_tune_api.py`（28 例：接地 e2e、幂等、409 两语义、400/422/404、overwrite/copy 持久化、工作错放凭证 preview 归位并穿越 overwrite 重放、delete/reset 清理；**custom per-block 4 例**：选中块改变而其他 itemList 自定义块被 scope 冻结（区分于 finalizer 冻结）、unknown key ignored 警告且结果 == canonical source、畸形 token 422 且不调 LLM、overlay 穿越 preview→copy replay 逐字节对称；**region 5 例**：只改亮点行且样式相等/区间外文本不动、preview→copy replay、多回行触发 `REGION_APPEND_DROPPED` 且长度不变/追加串不落库、畸形 token 422 且不触库、纯样式排版翻转（plain↔bullet、文本逐字节不变）穿越 preview→copy replay 落库且区间外样式不被翻转）、`tests/unit/test_resume_docx.py`（嵌套冒号头分级编号：混合夹具下头为加粗一级点 1./2./3. 连续编号，**全部明细（含 plain）**为二级复合编号且左缩进 1.2cm，全 bullet 夹具给出 1./1.1/1.2/2./2.1/2.2）、`tests/unit/test_parser.py`（+1：`CPU 飙升问题：` 这类拉丁前缀带空格的独立短标题仍被强制为 label）。全部确定性，LLM 经 `complete_json` mock，无真实网络。
- 前端 `tests/description-regions.test.ts`（11 例：与后端 `test_description_regions.py` 同一份夹具矩阵对拍——区间、别名、关区、嵌套头、分隔标签、bullet 形标签、work curated/技术别名、并集、空值边界）、`tests/fine-tune-scope.test.ts`（31 例：token 语法/互斥/标题映射 + `custom_<key>` 语法/双前缀往返/与整段 token 互斥/键提取/蓝框标签解析 + **region 一组**：语法接受/拒绝表、`regionToken`/`parseRegionToken` 往返、toggle 在整条/整段选中时 no-op、选整条清扫分区 token、section 前缀清扫覆盖 region）、`tests/fine-tune-wizard.test.tsx`（17 例：选择→零选禁用→条目 token→生成→两 tab/warnings→覆盖/副本 confirm→409 回退；**内容驱动 5 例**：极简简历无任何模块行且禁用生成、hasSummary 门控、自定义块逐行真实标题且无 chevron、点击发 `custom_publications`/`custom_custom_1`（含点击顺序）、`custom_<key>` preset 预勾；**三级选择 3 例**：带分区项目展开后显示四个分区行且点击发 `project_0:highlights`、勾整条清扫分区 token 并隐藏面板/禁用 chevron、无标签条目不显示分区 chevron）、`tests/list-format.test.ts` + `tests/description-list.test.tsx`（嵌套冒号头分级有序列表：头始终是一级加粗编号点，**全部明细行（含 plain）**打 `level: 2` 并渲染复合标记；混合夹具一级 marker 序列 `1./2./3.` 连续（含子列表之后的头）、二级 `2.1/2.2` 每个头重置且二级行多一个 3ch 缩进占位 span，全 bullet 夹具 1./1.1/1.2/2./2.1/2.2；DOM 层锁定 marker 序列、`data-nested-head` 与占位 span 数量；另锁 `looksLikeSubLabel('CPU 飙升问题：')/('JVM 调优：')` 为真、超长带空格句为假）。
