# 简历诊断（V4 优化版清单式评分细则）

基于 `rules/简历诊断规范_V4_优化版.xlsx` 的 AI 辅助简历质量审计——工作表
`诊断规范V4`（页签名沿用原工作簿；细则为 22 项 / 7 维度，列为
序号/一级维度/二级维度/诊断前置条件/检查项·判定标准/质检违规等级建议）与工作表
`职级体系与能力模型对照表`（Java 职级矩阵）。本功能按
**7 个维度 / 连续 22 项 / 1 条红线**审计简历，产出
**只有清单——没有总分、没有等级档位、没有权重**。每个检查项给出四种结论之一：
`conform（符合） | partial（部分符合） | nonconform（不符合） | na（不适用）`。

| 维度（key） | 名称           |                         检查项 |
| ----------- | -------------- | -----------------------------: |
| appearance  | 简历外观       |                            1–2 |
| content     | 撰写规范       |                           3–13 |
| stability   | 工作稳定性     |     14（任职连续性，风险标记） |
| growth      | 职业成长性     |                             15 |
| compliance  | 风险与合规     |                             16 |
| fit         | 目标岗位匹配度 |             17（需 JD 才适用） |
| competence  | 专业能力       | 18–22（需意向/职级模型才适用） |

撰写规范维度内，#11「培训与证书」与 #12「荣誉奖项」是两条独立选填模块规则
（LLM 评判），#13「时间线自洽」为跨记录确定性检查。相对早期 V6 导入版的重要
变化：旧的「全局校验」维度取消，时间线自洽并入「撰写规范」；旧的「荣誉证书」
单条规则被 #11/#12 两条规则取代；`全局通用规则` 工作表（G1–G11）已从工作簿
删除，其指引折叠进各条判定标准单元格（制品仍保留 `global_rules: []` 以维持
结构稳定）；专业能力项 18–22 不再要求 JD，只要求有可解析到职级模型的明确目标
意向。

每项的**质检违规等级建议**（`qc` 列）把失败情形映射为
🔴 严重违规 / 🟡 一般违规 / 🟢 轻微违规 / 💡 提示。它是给 LLM 的内部评级参考
（🟡→`partial`、🔴→`nonconform`、🟢/💡→`conform`，静默映射），
**不是**面向客户端的字段。专业能力 5 个指针行**故意没有 QC 单元格**——
它们的标准来自职级矩阵。

红线**只有一条：#16** 风险与合规——它自己的 QC 标题即声明
一票否决（隐私泄露、造假、保密违规）。该项出现一个 `nonconform` 即判整份简历不
通过；`partial` 不否决。其他项上的普通 🔴 标记（包括第 14 项稳定性，其标题写作
🔴 严重违规（简历层面风险，缺少说明））属于严重发现但**绝不否决**——
红线识别用正则 `🔴[^\n]*一票否决` 匹配该项自身的 QC 标题，只可能命中 #16。

## 保密：判定标准永不离开服务器

被评判的标准——工作簿的检查项/判定标准文本（`criterion`）、质检违规等级建议
（`qc`）与职级行为标准——都属于内部评测材料：

- 规则 JSON 的每个条目只带一个简短的公开 **`topic`** 标签（即二级维度标签——
  问题*位置*，如 `格式规范`、`时间线自洽`、`任职连续性`、`风险与合规`）以及
  `dimension`/`sub_dimension`；完整的 `criterion` 与 `qc` 文本只渲染进 LLM
  评判提示词，绝不序列化给 API 客户端，也不进入 Word 导出。
- LLM 系统/用户提示词禁止引用、转述或翻译这些标准（不得出现阈值、页数、百分比、
  年份数量或"按规范要求"之类措辞）；`partial`/`nonconform` 行的 `evidence`
  必须点名模块/段落/条目并引用简历事实，`suggestion` 必须是针对**本份**简历该行
  问题的具体改动（不写泛泛评论，不写"继续保持"式建议）。**符合项按契约保持
  沉默**：`evidence` 与 `suggestion` 都是空字符串——不表扬、不复述优点、
  不输出 🟢/💡 提示行——服务端强制执行这一点（`_silence_conform_text`），
  即使模型或某个确定性检查器输出了正向评语也会被清空。`na` 行只带适用性说明
  （如缺少 JD）。18–22 项对能力模型标准另有保密条款：输出只能说明缺少什么证据、
  建议补充什么经历，绝不复述行为标准。
- 确定性检查器的证据**及其逐信号建议**都有审计
  （`test_objective_evidence_never_quotes_the_rubric`，在稀疏/脏乱/对抗性简历上
  运行）：只能描述简历事实——不得出现规则词汇
  （红线/检查项/规范/一票否决/质检违规），不得出现内部阈值或档位
  （点数区间、技能数区间、页数限制、五年观察窗口、`半年以内/7~12` 任职段标签、
  主流技术栈 `x/9` 占比）。当证据必须枚举植根于简历的标签时
  （缺失的模块/字段、命中的技术栈分组），每个标签单独加书名号引用（`「…」`），
  使一连串简历事实无法复刻细则的规范枚举。同一审计还断言：每个问题行都带非空且
  与其匹配的修复建议，每个符合行序列化时两个字段都为空。
- **发现项的有序列表契约。** 每个问题行的 `evidence` 与 `suggestion` 在所有端
  （网页报告、Word 导出）都渲染为**有序列表**，因此提示词只要求朴素的一行一点：
  点与点只用换行分隔，不带源文件的编号或项目符号
  （`1.`/`1、`/`①`/`-`），不加「问题：」/「建议：」前缀，不用分号把多条粘在
  一行。服务端用确定性手段强制该形态（`normalize_finding_points`，在报告组装时
  作用于检查项与红线）：剥掉每行标记，把粘在一行的点拆开
  （`a。2. b`、`1. a 2. b`、`①…②…`），而版本号与小数（`JDK 1.8`、
  `提升 2.5 倍`）保持完整、空行丢弃。可见编号由查看端负责——每个列表都从 1
  重新编号，因此编号永远不会重复。只有一个点时仍渲染为 `1.`；`na` 的适用性
  通知保持纯文本，不作为问题列表。

## 导出时处理的源工作簿怪癖

- **第 9 项的二级维度单元格被错标**为 `工作经历`（与第 8 项重复），但其判定标准
  正文是【项目经验】、行为也是项目类；导出器的 `SUBDIMENSION_FIXES` 将其改正为
  `项目经验`，保证每个公开 `topic` 唯一。
- 导出器**逐字**复制矩阵单元格（仅做空行归一化）；若某职级标准含有源文件笔误，
  原样发布——应在工作簿中修正，而不是在代码里打补丁。

## 架构：混合评判

高利害、可计算的判定由确定性 Python 产出，使结论在多次运行间不漂移；真正语义类
判断交给 LLM。

- **13 个固定项 id 有确定性执行器**
  （`app/services/diagnosis_checks.py`，`run_objective_checks()`）：
  `{1,2,3,4,5,6,7,8,9,10,13,14,16}`，外加三个条件性客观判定——**#15** 在有效
  开发年限不足 5 年时客观判 `na`；**#11/#12** 在选填模块无任何可见条目（证书/奖项
  列表为空，或 additional 版块被隐藏）时客观判 `na`，有条目时才交给 LLM 评判
  相关性/数量/格式/排序。**#7 是唯一带语义复核的客观项**：正则初筛默认成立，
  仅当未达符合线时搭 LLM 评判调用做同义词救回（详见下文 #7 条目），无救回则
  结论与纯正则逐字一致。重点检查：
  - **#1** 合并三个确定性信号（`_join_findings`——最差评级胜出，**只有失败的
    信号贡献文本**，证据与对应修复用 `；` 拼接，拼接处不产生 `。；` 双标点）：
    版块顺序、版块标题治理、超长段落。段落密度**按换行切分后的每个要点单独计行**
    （单要点超过 6 行才不符合）——已拆成多条要点的个人优势不会因总字数
    被误判为「单段无换行」。行数优先采用前端按所选模板离屏真实渲染、逐点测量的
    视觉行数（请求携带可用 `rendered_layout` 时，见下文
    “所选模板的实际渲染结果”）；无快照时回退 **46 字/行** 的文本估算。有可用
    快照且全部要点均 ≤6 行时直接判符合，不回退字数估算；快照中个别无法对齐的
    要点才走字数估算兜底。个人信息头部不渲染版块标题（只有姓名与事实网格），
    因此其 `displayName` 改名（如 LLM 写成「基本资料」）不参与标题治理判定。
    顺序与标题都通过的行只报告超长段落及其单条修复；
    通过的子检查不添加任何正向评语或建议。顺序有两条合法序列，由
    `classify_highest_degree` 选择——全日制统招学历把教育放第二位，其他所有
    情况把教育移到最后一个自我评价版块之前；无法识别的自定义版块形成保持相对顺序
    的簇，位于项目与荣誉（标题含 荣誉/证书/奖项）之间，自我评价（标题含
    自我评价）恒在末位。治理检查标记：重复的可见标题、标题既不是已发布的本地化
    标题/已接受别名也不是规范名的默认版块（见
    [custom-sections.md](custom-sections.md#fixed-section-order)）、以及无内容的
    可见*可选*版块（partial）。空的*必填*版块仍归 **#3** 管辖。刚解析完、没有
    `sectionMeta` 的简历按 GET 渲染器产出的同一套合成规范视图来评判，因此不会
    误报。日期格式与跨记录冲突属于 #13，不在这里。
  - **#2** 篇幅页数（超过 3 页不符合）：有可用渲染快照时以**实测页数**判定，
    证据为「按所选模板（模板中文名，纸张）实际渲染为 n 页，篇幅偏长」；无快照
    回退 **950 字/A4 页** 的文本估算（证据保留“估算”口径）。水印/对齐由 LLM
    评判，不是确定性的。
  - **#3** 五个必填模块（基础信息/教育/专业技能/工作/项目），V4 中无条件必填——
    旧的应届生替代规则（用项目代替正式工作）已从工作簿删除。存在但为空的版块
    （或只含空白条目的版块，如 `education: [{}]`）计为缺失；空必填版块绝不被 #1
    重复上报。求职意向被视为基础信息内置的必填子项（它锚定职级模型匹配）。
    个人优势仅在 8 年以上有效年限时必填（5–8 年建议有，5 年以下不鼓励）；它缺失
    会使 #6 判 `na`。
  - **#4** 必填基础信息：姓名 / 性别 / 手机号 / 邮箱 / 求职意向。**期望城市
    （`personalInfo.location`）为选填项**：留空不扣分、不进整改建议；填写后与
    目标岗位工作地不一致只在 **#17** 作异地求职提示。`gender` 是一等
    `personalInfo` 字段（由解析器从原文头部逐字复制），因此缺少
    性别现在与其他必填字段一样被标记。年龄 / 工作年限 / 学历按工作簿仅为建议项，
    绝不单独判失败；模型和原文都没有的字段（如 期望薪资）不评判。
  - **#5** 教育四要素（时间/大学/专业/学历学位）+ 统招/全日制标注。
  - **#6** 个人优势 2–5 点；模块为空 → `na`。**#7** 合并技能数量
    （8–15 个；过少、过多都不符合）与 9 个分组的主流技术栈覆盖，含两个 AI 分组
    （Spring AI/LangChain4j 与 Codex/Claude Code/Trae）；命中 ≥7 组判符合，
    5–6 组 partial，≤4 组不符合。**语义复核（防关键词漏判）**：正则初筛未命中、
    且当前未达符合线的分组，随当次诊断的 LLM 评判调用做一次附加复核——LLM 只能
    把技能条目中的**同义/等价技术**（如 MyBatis-Plus 之于关系库、Copilot 之于
    AI 编码工具）救回为命中，且必须逐字引用条目原文片段；服务端校验引用确为技能
    条目的子串（忽略大小写与空白差异），幻觉引用一律拒绝；只升级不降级，正则已
    命中的分组 LLM 无权改动。救回后重算评级；该行的 `judgment_method` 在发生救回
    时标 `subjective`，无救回/弱模型忽略附加任务时结论与纯正则完全一致。审查范围
    仅限 `additional.technicalSkills` 条目，不延伸到工作/项目描述；9 组的等价
    口径只进 LLM 提示词，不离开服务端。优化方案不是固定文案：只点名**本份简历
    实际缺失**的方向（按分组顺序最多 3 个示例），已具备的方向（如微服务、
    中间件、AI 编码工具）绝不出现在建议里，完整 9 组清单不离开服务端。
  - **#8** 工作三要素（时间/公司/岗位）+ 实习条目规则
    （有效年限 ≥1 年时，实习标题混在正式工作里判不符合）。
  - **#9** 项目检查：每个项目经内容代理的六字段
    （名称、角色、背景措辞、≥2 个技术词汇、职责动词、量化成果），数量 2–4
    （V4 中任何资历只有单个项目都不符合），且**项目时间有条件可选**（仅对超过
    六个月的项目要求填写）——日期包含关系由 #13 检查。
  - **#10** 自我评价 3–5 点（自定义 text 版块；可选 → `na`）。
  - **#11 培训与证书**是选填模块规则：模块存在性是**确定性的**——
    `run_objective_checks()` 读取 `additional.certificationsTraining` 的非空字符串
    条目（additional 版块可见为前提），无匹配证书/有效培训证明即客观判 `na`
    （规范同时要求此时直接删除区块、不留空标题；可见空选填版块由 #1 处理），
    LLM 不会被询问，也就不会把原始上传文件里「其他」之类兜底标题下的内容误报成
    「模块为空/放在其他模块」；有条目时交 LLM 评判相关性/数量/要素/格式/排序：
    仅接受与 Java 后端岗位强/弱相关的证书与技术培训结业证明（强相关参考：软考、
    云厂商技术认证、PMP 等工程类认证；驾驶证、心理咨询师证、教师资格证、会计证等
    完全无关证书判 🔴；虚构证书/培训证明判 🔴）；**应届生无强制要求，有工作年限后
    校园通识类证书（如四六级）不建议放入本模块**；有效条目 1–4 条（>4 为 🟡）；
    单条要素中**仅名称必填，颁发机构与获取时间均为选填，不做强制要求**——条目缺少
    颁发机构或获取时间不得判不符合/部分符合，也不得作为任何扣分或降档依据；仅当条目
    填写了获取时间时格式才必须为 `yyyy.MM`（已填但格式不符为 🟡，未填不违规）；
    强相关前置、弱相关后置，同相关性且可比较时间时按获取时间倒序
    （弱相关前置等排序混乱为 🟢），描述冗余过长为 🟢；英语四六级与表头外语水平
    重复填写、培训证明误放到【荣誉奖项】为 🟡。该约束同时写入 LLM 评审系统提示词
    （#9），避免模型把缺机构/缺时间的证书降档。
  - **#12 荣誉奖项**是与之平行的选填规则：`additional.awards` 无可见条目即客观
    判 `na`，有条目时交 LLM 评判——仅接受技术/项目/学业强弱势相关奖项（编程大赛、
    技术竞赛、项目评优、公司技术之星、科创奖项；完全无关奖项、虚构获奖判 🔴），
    应届生可写学校奖项、有工作年限后普通校园奖项不建议写；有效条目 1–4 条，要素中
    **仅奖项名称必填，颁发主体与获奖时间均为选填、不做强制要求**——条目缺少颁发
    主体或获奖时间不得判不符合/部分符合，也不得作为任何扣分或降档依据；仅当条目
    填写了获奖时间时格式才必须为 `yyyy.MM`（已填但格式不符为 🟡，未填不违规）；
    强相关前置、同相关性且可比较时间时按获奖时间倒序；证书/培训证明误放进本模块为
    🟡，排序混乱/空话冗长为 🟢。与 #11 相同，该约束同时写入 LLM 评审系统提示词
    （#9），避免模型把缺颁发主体/缺获奖时间的奖项降档。
  - 证书/奖项/外语的**实际条目**（已清洗、按存储顺序）随事实包注入提示词，作为
    模块归属与重复判定的唯一依据；数据字段是
    `additional.certificationsTraining` 与 `additional.awards`，渲染时投影为简历
    后部的独立模块（见 [custom-sections.md](custom-sections.md)）。
  - **#13 时间线自洽**是跨记录检查器（教育 + 工作 + 项目），合并七个信号
    （`_join_findings`，只含问题）：日期格式统一性；
    倒序/未来区间；未说明的**工作-工作重叠**（任一条目标注 兼职/外包 即豁免）；
    未说明的**教育-教育重叠**（双学位/联合培养/在职/非全日制 标注豁免）；
    **项目日期包含关系**（项目区间必须落在某段工作任期内，除非项目文本标注
    【个人业余项目】）；**首份全职工作 vs 最高学历入学**（工作早于入学超过 6
    个月为 🟡 partial；在职/非全日制学历豁免，跳过实习，6 个月容差吸收仅按年份
    归一化到 7 月的日期）；以及声称工作年限与并集工龄的算术校验，**±0.5 年**
    容差（虚报不符合，少报 partial）。
  - **#14** 不具否决力的稳定性*风险标记*：当前/历史空窗
    （>6 个月不符合，3–6 partial，边界严格），5 年内 ≥4 家公司为 **partial**
    （🟡 风险标记），短任期只统计**已结束**的工作（当前无固定结束日的工作排除；
    ≤6 个月不符合，7–12 partial）。证据只报事实（实际空窗与任期长度、公司名）
    ——五年窗口与 半年以内/7~12 档位标签绝不出现在客户端。建议只要求客观说明；
    不允许出现 淘汰/否决 措辞。
  - **#16** 隐私扫描（身份证号及带标签的敏感数据）；造假/保密情形交给 LLM。
    扫描同时覆盖结构化数据与逐字原始简历
    （`run_objective_checks(..., supplementary_text=original_markdown)`），因此
    LLM 解析器丢掉的敏感词仍会触发红线；两个来源的命中标签去重。
  - 每条确定性发现都是一个 `(rating, evidence, suggestion)` 三元组：建议就在
    检查器内与其信号相邻编写（不再有按 id 的建议映射表），且只修复该信号。合并
    多个信号的项（#1、#7、#13、#14）只拼接**失败信号**的文本，因此 partial 行
    绝不带针对已通过子检查的修复；全部符合的合并结果两个文本字段都序列化为空，
    全部 `na` 的合并结果拼接适用性说明。
  - 检查器还返回一个**事实包**（时间线区间、空窗、任期月数/年数、技能与要点计数、
    培训与证书/荣誉奖项/外语水平的实际条目）注入 LLM 提示词，使模型永不做日期
    算术，且模块归属/存在性/重复以事实包为准；`target_title` 由服务层添加，不在
    检查器内。
- **语义项**：一次结构化 JSON 的 LLM 调用
  （`complete_json(schema_type="diagnosis")`），覆盖确定性层未作答**且上下文支持**
  的所有项 id（无 JD 但意向匹配 P4 且证书/奖项模块有条目的运行会发送 #11/#12 加
  #18–22；空选填模块已客观判 `na`，不发送），带结构化
  `response_validator`（`_build_validator`，校验 id/评级/文本字段）。验证器故意
  对弱模型/本地模型宽容：数字字符串 id（`"20"` → 20）会被强转，超出范围的 id
  （客观项/门控项，本不该分配给模型）与评级非法或文本非字符串的条目被丢弃，
  重复 id 保留首个判定——只有零条可用记录的响应才被拒绝以消耗重试预算。如果模型
  每次都在数组中途停止（括号不平衡），`salvage_diagnosis_response`（经
  `complete_json` 的 `salvage_response` 钩子接入，仅最后一次尝试）会从残片中恢复
  每个完整的 `{...}` 条目对象。之后仍缺失的项默认为 `partial`、建议为空，并产出
  一条 `warnings`（"请人工复核"），因此部分畸形的模型响应永远不会变成 HTTP 500。
- **前置门控**（唯一来源：规则制品的 `prerequisite` 字段，
  `"" | "jd" | "intention"`）。V4 中两个门控相互独立：
  - 无 JD → **#17** 为 `na`（"未提供目标岗位 JD，岗位匹配度检查项不适用。"）。
    JD 文本裁剪并截断到 12,000 字符。
  - 无可解析意向/模型（求职意向为空、标题不匹配且未显式选择、或哨兵值
    `"none"`）→ **#18–22** 为 `na`
    （"未明确求职意向，或未匹配/选择对应职级的能力模型，专业能力项不适用。"）
    ——无论是否有 JD。
  - 因此**无 JD 但有意向匹配的诊断现在会评判 18–22**；反之，有 JD 但无意向时
    评判 #17，18–22 保持 `na`。
  - 有效开发年限不足 5 年时 **#15** 在检查器层客观判 `na`（仅供参考的规则）；
    ≥5 年时由 LLM 结合事实做晋升分析。

评判调用故意丢弃全局配置的 `reasoning_effort`（一次 `LLMConfig.model_copy`，
全局配置不动）：开启推理时，DeepSeek 等提供商会把整个输出预算花在隐藏思维链上、
返回空内容（`finish_reason="length"`，可见 token 为零）。显式细则不需要推理
轨迹。回归测试：`tests/service/test_diagnosis_service.py` 中的
`test_diagnosis_drops_global_reasoning_effort_for_judging`。

## 事实依据：原始简历管内容，结构化数据管模块组织

诊断及其建议必须植根于用户实际上传的简历，而不只是有损的 LLM 结构化
`processed_data` JSON（解析会丢弃、概括、偶尔错放内容）；但原始文件的**版块
分组**不是成品简历的模块结构，二者分层使用。

- 端点通过简历库辅助函数 `_get_original_markdown(resume)` 解析
  `original_markdown`：优先持久化的 `original_markdown` 列（上传时保存的
  解析器/OCR markdown），对 `content_type == "md"` 的老记录回退到 `content`。
  它被传入 `diagnose_resume(..., original_markdown=...)`。
- 评判提示词把它逐字注入为独立区块（`DIAGNOSIS_ORIGINAL_BLOCK`），放在结构化
  JSON **之前**；提示词规则 8 区分两层事实依据：
  - **模块组织层**（内容归属哪个模块、模块是否存在/为空、条目数量与排序、重复
    是否真实存在）一律以结构化数据 + 客观事实包为准。原始文件常把证书/奖项/外语
    堆在「其他」「补充信息」等兜底标题下，解析已按类型归入
    `additional.certificationsTraining` / `.awards` / `.languages`；模型不得据此
    声称「培训与证书模块为空」「证书放在其他模块」或「外语水平重复」（这是一次
    实际误报的修复：原始 markdown 的 `◆ 其他` 节同时列了证书和外语水平，成品
    简历中它们已分别投影到培训与证书模块和表头，无空模块也无重复）。
  - **内容细节层**（经历/证书/奖项真伪、原文措辞与具体数字）以原始转写为准，
    JSON 与原文冲突时取原文；证据引用取自原文或事实包条目；两者都没有的内容
    不得发明。JSON 区块是模块/字段定位视图。
- 文本以 20,000 字符为界（`_ORIGINAL_RESUME_CHAR_LIMIT`），用
  `_truncate_text_for_prompt` 截断并附加明确的截断提示，而不是悄悄切掉尾部；
  markdown 缺失或为纯空白时整个区块省略（如只有 JSON 的测试记录），评判回退到
  结构化视图。
- 确定性检查器仍跑在结构化数据上——只有 **#16** 额外扫描原始文本（见上）。
- **诊断对象是读时自愈后的副本，不是原始入库行**。GET 的 `normalize_resume_data`
  只作用于响应、不回写数据库，所以端点在深拷贝上先重放整条读时自愈链（含
  `reconcile_custom_section_shapes`：把声明为 `stringList` 却错装进 `items` 的
  自定义版块迁回 `strings`），再交给检查器，保证诊断口径与 UI/PDF/DOCX 的实际
  渲染一致；库里的 `processed_data` 不被修改。否则存量简历会按错装的原始行被
  判「版块有标题无内容」（真实案例：「其它」版块的 GitHub/博客链接不可见）。

## 所选模板的实际渲染结果（前端测量快照）

外观类判定（**#1** 段落密度、**#2** 篇幅）以用户在简历编辑器中选择的模板/排版
为准（`TemplateSettings`：7 套模板、A4/LETTER 纸张、四边页边距、字号/间距
等级、紧凑模式等，存浏览器 localStorage，单一全局份），做到
**屏幕预览 == PDF 导出 == 诊断口径**一致。

- **测量（浏览器侧，`lib/utils/measure-resume-layout.tsx`）**：发起诊断前用
  当前设置在隐藏容器中真实渲染与屏幕 `<Resume>` 同形的显示态数据（本地化版块、
  时间线倒序之后），等待字体与双 rAF 后得到：实测页数（复用分页纯函数
  `computePageBreaks`，与 live preview 同一模型）、逐要点视觉行数
  （Range `getClientRects` 按 top 聚类，真实折行，CJK/内联 HTML 均准确）、
  版块落页、头部事实网格、逐页文本镜像。简历非空而 `scrollHeight===0`
  （jsdom 式无布局环境）时自检抛 `LayoutMeasurementError`。枚举/对齐/镜像/
  钳制等纯计算在 `lib/utils/layout-snapshot.ts`：要点枚举逐字镜像后端
  `_iter_located_blocks`（summary 按换行拆；work/projects 的 `description`
  跨行扁平化、`point_index` 跨 bullet 连续；customSections 仅 `text`/`itemList`
  进 points，`stringList` 排除），观测行经归一化文本三级对齐（locator 精确 →
  双向 includes（≥4 字）→ 未对齐只影响证据措辞）。载荷硬上限 12 页/40 版块/
  300 要点、单要点 120 字、单页镜像 6000 字、JSON ≤48KB（`LAYOUT_LIMITS`，
  超限时保摘要截镜像并写 warnings）。
- **请求契约**：`template_settings` 与 `rendered_layout` 均为可选字段、
  **成对出现**（仅测量成功时下发；测量失败两者皆省略，后端回退估算）。后端
  可用性门禁 `_usable_layout()`：快照 `template` 与 `page_size` 必须与
  设置一致，否则整份快照视同不存在（`logger.info` 后按无快照处理）。Pydantic
  模型全部宽松校验 + `extra="ignore"`（`page_count` 1–12、sections ≤40、
  points ≤300、page_mirror ≤12×6000 字）；请求体 **>128KB 返回 413**
  （通用 detail，详情记日志；超长 JD 也走此门），字段越界返回 **422**。
- **确定性判定（`app/services/diagnosis_checks.py`）**：#1/#2 实测优先
  （见上两条）；`run_objective_checks()` 的 facts 在保留全部原有键的前提下新增
  紧凑 `layout` 摘要（模板/纸张/双栏/页数/已测要点数/头部网格/各版块落页/
  前 5 个超长点）。
- **LLM 区块（`DIAGNOSIS_RENDERED_BLOCK`）**：提示词在原始简历区块后插入
  “所选模板的实际渲染结果”——测量摘要 JSON + 逐页文本镜像，整块 ≤12,000
  字符，超限时保 facts 截镜像并附截断注记。三条硬口径：①#1/#2 已由规则引擎依
  实测判定，待评编号中不含 1、2，严禁在他项重复主张段落过长/页数/篇幅或给精简
  建议；②外观事实只能引用区块内容，**严禁按字数自行推算**或臆测镜像中不存在
  的问题；③文本事实仍以原始简历与结构化 JSON 为唯一依据。
- **失败语义**：测量失败绝不阻断诊断——前端 `console.warn` 后按无快照请求继续，
  报告区显示中性小字 `diagnosis.layoutSkipped`（页数与段落密度按文本估算），
  不是错误；loading 态新增 `diagnosis.measuringLayout` 两阶段文案。
- 快照是客户端自报数据，仅用于阈值判定与 LLM 上下文，**不入库、不回显
  warnings**；evidence 仍过 `normalize_finding_points`。查看页屏幕预览与 PDF
  下载跟随同一份设置、同一语言（uiLanguage）；DOCX 简历下载仍是单一规范版式，
  不受模板设置影响。

## 目标岗位名称

诊断是*针对一个岗位*进行的，在 `app/services/diagnosis.py`
（`_resolve_target_title`）中解析：

1. 请求显式字段 `target_title`（去首尾空白；空白 → null）。
2. 否则取简历的 `personalInfo.title`（求职意向）。
3. 两者都为空时不添加目标区块、不自动匹配模型；有 JD 时第 17 项仍评判、18–22
   返回 `na`；无 JD 时第 17 项也为 `na`。

解析出的名称通过 `report.target_title` 回显，并驱动能力模型自动匹配。前端
（`lib/utils/job-intentions.ts`，`splitJobIntentions`）把含多个意向的标题按
`/ ／ 、 , ， ; ； | ｜ +` 与换行切分、去空白、去重
（「和/与」故意**不**作为分隔符）。弹窗表现为：0 个意向 → 灰色提示，诊断仍可
运行；1 个 → 只读加粗目标行；≥2 个 → Swiss 单选卡片，默认第一个意向，选中的
名称作为 `targetTitle` 发送。

## 分岗能力模型（Java 职级矩阵）

`app/services/diagnosis_competency.py` 用岗位专属标准填充细则内置的专业能力项。
随包发布的目录是工作簿工作表 `职级体系与能力模型对照表` 的 **Java 工程职级
矩阵**：`Java` 族下六个模型 `java-p3` … `java-p8`，各含五个能力要素
（系统架构 / 业务架构 / 开发技能 / 应用技能 / 项目管理），其标准为该职级的行为
标准。这五个要素就是第七维度中正式基础细则的 **18–22 项**；模型只提供标准，
绝不新增清单行。

- 模型存于 `diagnosis_rules.json` 的 `competency_models`：
  `{key, name, family, level, title_patterns: string[], items:
[{item_id, sub_dimension, criterion}]}`，其中 `item_id` 为 18–22。
- `parse_competency_models` 把 `title_patterns` 编译为正则（作者自行加
  `(?i)` 等标志；匹配用 `re.search`）；畸形条目跳过，非法正则直接抛错。
- **标题自动匹配优先级**（`select_competency_model`，模型按 P3→P8 排序，首个
  命中为准）：P3 初级/助理/p3+java · P4 中级/p4+java **或** 整标题通用正则
  `(?i)^java\s*(?:开发)?工程师$` · P5 高级 · P6 资深 · P7 架构师 ·
  P8 技术专家。P4 通用模式故意做整标题锚定。示例：`Java 开发工程师` → P4，
  `高级Java开发工程师` → P5，`Java架构师` → P7，`Java/大数据/前端` 与
  `大数据开发工程师` → 不匹配。
- **解析**（`resolve_competency_model(models, title, explicit_key)`）：UI 的
  显式 key 永远优先；字面哨兵 `"none"`（`NO_COMPETENCY_MODEL_KEY`）完全退出
  标题匹配（否则标题自动命中时用户永远无法只跑基础细则）；空 key 回退到标题
  匹配；未知的真实 key 抛 `KeyError`，由路由映射为 **HTTP 400**（通用的"模型
  不可用"消息；详情记日志）。
- `expand_rules(base, model)` 深拷贝基础规则，并把 18–22 项的指针标准**原地**
  替换为模型标准（按 `item_id` 对应；未知/缺失 id 忽略，绝不追加）。清单因此
  始终保持 **22 项 / 7 维度**；专业能力维度（key `competence`，名称 专业能力）
  始终存在，无模型激活时直接渲染 `na` 行。缓存的基础规则永不被修改；（空的）
  全局规则列表与模型目录原样透传。
- **目录端点**：`GET /api/v1/diagnosis/competency-models?title=…` 返回
  `{models: [{key, name, family, level}], matched_key}`，使标题→职级正则留在
  服务端；省略 `title` 时 `matched_key: null`。

## 选择 / 确认 UX（需求：无明确意向或未匹配时可选择确认）

弹窗打开时拉取目录，所选目标名称变化时重新查询：

- 服务端返回匹配 → 预选该模型，并有一行 `modelMatchedHint` 点名它；用户可以改选
  其他职级，或显式选择"不使用能力模型"。
- 无标题或不匹配 → 预选显式 **none** 选项，`modelNoMatchHint` 请用户手动确认
  一个职级或不带模型运行。诊断不被阻塞——none 本身就是确认。
- 目录加载失败显示内联错误，但仍允许运行（请求省略 key → 后端标题自动匹配 /
  基础细则）。

## 清单汇总

`app/services/diagnosis_summary.py`（`summarize_verdicts`）只负责计数：

- 总体与各维度（全部七个维度，含专业能力）的
  `{conform, partial, nonconform, na, effective}` 计数；`na` 不计入
  `effective`（不变式：`effective + na === 22`）。
- `failed_redline_ids`：评级恰为 `nonconform` 的红线项（`partial` 不否决）；
  列表为空时 `redline_passed` 为真。缺失判定默认为 `na`，绝不默认为失败；
  未知评级字符串防御性计为 `nonconform`。

## 规则制品

`app/services/diagnosis_rules.json` 是随包发布的细则：
`{spec_version: "V4", title, dimensions, global_rules, competency_models,
items}`，每个 item 为 `{id, dimension, dimension_name, sub_dimension,
topic, prerequisite, criterion, qc, severity}`：

- `topic` 等于二级维度标签（含第 9 项的纠正），是客户端可见的唯一问题位置文本；
  `prerequisite` 为 `"" | "jd" | "intention"`；`criterion` 与 `qc` 仅服务端可见
  （专业能力指针行 `qc: ""`）；`severity` 为 `"redline" | "normal"`
  （V4 导入恰好产生一条红线 {16}）；`global_rules` 恒为 `[]`。
- 用 openpyxl 从 xlsx 生成（openpyxl **不是**运行时依赖——xlsx 是不可信数据，
  在仓库根目录用
  `uv run --with openpyxl python -I scripts/export_diagnosis_rules.py` 重新生成，
  然后 `git diff` 该 JSON；预期控制台输出：
  `wrote apps/backend/app/services/diagnosis_rules.json: 22 items, 7
dimensions, 1 redlines [16], 0 global rules, 6 competency models:
java-p3(5), …, java-p8(5)`）。导出器校验：序号连续、维度/prerequisite 已知、
  每项 criterion 非空、每个非专业能力项 QC 文本非空、公开 topic 唯一
  （第 9 项冲突被纠正而非容忍）、每个职级恰好五个标准，使工作簿漂移能响亮地失败。
  导出器仍保留旧工作簿的全局规则工作表解析器，但已非必需。
- 职级矩阵工作表（`职级体系与能力模型对照表`）导出到同一文件的
  `competency_models`。`diagnosis_rules.py` 加载制品（`lru_cache`）为
  `DiagnosisRules` 视图（含空的 `global_rules`）。

## 端点

- `GET /api/v1/diagnosis/competency-models?title=…` —— 目录 + 自动匹配（见上）；
  只读，不调用 LLM。
- `POST /api/v1/resumes/{resume_id}/diagnose` —— 请求体
  `{"job_description": string | null, "target_title": string | null,
"competency_model_key": string | null, "template_settings"?: TemplateSettingsIn,
"rendered_layout"?: RenderedLayoutIn}`（后两者可选、成对，仅前端测量成功时
  发送，见“所选模板的实际渲染结果”；老客户端与 `{}` 请求行为不变）。返回扁平
  `DiagnosisReport`
  （无 `data` 包装）：`counts`、分维度 `dimensions[].counts`、
  `redlines`（`{id, topic, passed, rating, evidence, suggestion}`——无
  criterion/qc）、`failed_redline_ids`、`redline_passed`、`items`
  （用 `topic` 代替 criterion；无 `qc`）、`target_title`、
  `competency_model`、`warnings`。简历未知返回 404，无 processed data 或模型
  key 非法返回 400，请求体超过 128KB（`Content-Length` 守卫）返回 **413**，
  快照字段越界返回 **422**（`extra` 字段一律忽略）。内容细节植根于简历存储的原始
  markdown（上传时的解析器/OCR 输出；老记录用 md `content`），逐字发送给 LLM；
  模块归属/存在性/重复以结构化数据与事实包为准——见上文
  “事实依据：原始简历管内容，结构化数据管模块组织”。输出语言跟随配置的内容语言；
  证据、建议与维度名称都以该语言生成。
- `POST /api/v1/resumes/{resume_id}/diagnose/document` —— Word 导出。

## Word 导出

文档端点把屏幕上已有的报告渲染成 `.docx`（客户端把 `DiagnosisReport`
回传——**不做第二次 LLM 调用**，因此响应在亚秒级）。渲染器：
`app/services/diagnosis_docx.py`，基于 python-docx（已随 markitdown 固定为
依赖）。中文排版用 `w:eastAsia` 字体绑定（黑体标题、宋体正文）；界面性文字按
`report.language` 中英双语。文档中所有计数都是动态的；副标题写作
依据《简历诊断规范 {spec_version}》（`N 维度 / M 检查项 / K 红线`，M 恒为
22）。

文档结构：

1. **总体结论** —— 计数行
   `适用 N 项 —— 符合 a、部分符合 b、不符合 c；不适用 d 项`，诊断目标名称，
   一行由报告 `competence` 维度计数驱动的
   `能力模型匹配：<模型名>：适用 N 项 —— 符合/部分符合/不符合；不适用 M 项`
   （英文界面：`Competency match (name): …`；无模型时省略），红线结论。
2. **未通过红线项** —— 未通过的红线（#16），含公开 `topic`、检查位置
   标签值（维度 / 二级维度）、问题描述（`evidence`）与优化方案
   （`suggestion`）；两个发现字段渲染为悬挂缩进的编号段落
   （`1.`、`2.`、…，一行一点，每个列表从 1 重新编号），检查位置保持行内；
   红线通过时整节省略（`1 条红线检查全部通过`）。
3. **维度统计** —— 6 列表格
   （`维度 / 适用 / 符合 / 部分符合 / 不符合 / 不适用`），报告中每个维度一行；
   所有项均 N/A 的维度显示适用 0。
4. **问题描述与优化方案** —— 每个 `partial`/`nonconform` 项，红线项优先并按
   维度分组；每条显示 `#id` + topic，随后是 检查位置（行内）/ 问题描述
   （植根简历）/ 优化方案（具体修复），两个发现字段为悬挂缩进编号段落，一行
   一点，每个列表从 1 重新编号。符合项在此排除。
5. **全部检查项一览** —— 附录表（`序号 / 维度 / 检查位置 / 评级`），按 id 顺序
   列出全部 22 项；检查位置列只放公开 topic 标签，绝不放判定标准或 QC 指引。

候选人姓名取自简历的 `processed_data.personalInfo.name`；下载文件名通过
RFC 5987 `filename*` 下发，格式为 `简历诊断报告-姓名-时间.docx`（本地时间
`YYYYMMDD-HHMM`，如 `简历诊断报告-王浩-20261030-2156.docx`；无姓名时用
`resume-<id8>` 占位，并提供 ASCII 回退名）；前端 Blob 保存由
`buildDiagnosisReportFilename` 用同样规则命名。错误在服务端记日志并返回通用 500。

## 前端

- 客户端：`lib/api/diagnosis.ts` ——
  `diagnoseResume(resumeId, { jobDescription?, targetTitle?,
competencyModelKey?, templateSettings?, renderedLayout? })`（240 秒超时；省略
  字段以 `null` POST；显式 `"none"` 哨兵逐字透传；后两个排版字段**只有同时
  存在**才下发）、`fetchCompetencyModels(title?)`（GET 目录）、
  `exportDiagnosisDocx`（快速，无 LLM）。`DiagnosisItem`/`RedLineStatus` 只暴露
  `topic`，不暴露 `criterion`/`qc`。
- UI 界面：
  - `components/diagnosis/diagnosis-modal.tsx`，从简历查看页
    （`app/(default)/resumes/[id]/page.tsx`，传入
    `intentionTitle={resumeData.personalInfo?.title}` 与显示态 `resumeData`；
    主简历与定制简历均可用）打开。表单显示目标名称选择器、能力模型单选字段集
    （目录驱动；预选匹配职级并提供显式 none 选项）与可选 JD 文本域（仅第
    17 项）。点击运行先进入 `measuring` 阶段按 builder 当前设置离屏测量
    （失败静默回退无快照诊断并显示 `layoutSkipped` 中性提示），再进入诊断
    阶段。
  - `components/diagnosis/diagnosis-workspace.tsx`，Dashboard 的「简历诊断」
    入口：上传 → 解析 → 测量（对与左侧分屏同形的
    `withLocalizedDefaultSections` 显示态数据；模板设置在工作区生命周期内快照
    一份）→ 自动诊断（无 JD 基础运行先解析标题的职级模型，因此意向匹配时
    18–22 都会被评判）、简历/报告分屏、JD 重诊（再次测量）、Word 导出。
  - `components/diagnosis/diagnosis-report-view.tsx` 是共享的纯维度驱动报告
    渲染器（`report.dimensions` + `item.dimension` 分组；无硬编码维度列表，
    因此 V4 的 7 维度布局无需组件改动）。
- 报告视图显示：等宽字体计数卡（无分数/档位/进度条）、目标/能力模型行、
  红线横幅（`#id topic`；只可能出现 #16）、分维度计数行、按维度分组的全部项
  （每项含 `#id` + topic 标题、二级维度 chip、评级徽章、evidence 与建议——
  各为有序列表（`FindingPoints`：后端给出的每行一个编号行，列表从 1 重新编号，
  剥掉残留源标记使编号永不重复；`na` 的适用性通知保持纯文本）、pip 条
  （`na` 时隐藏）与 全部/问题 过滤器。页脚"下载 Word 文档"按钮经
  `downloadBlobAsFile` 以带日期后缀的本地化文件名保存报告；失败显示可重试的
  内联错误。
- i18n：每个语种文件 `messages/` 下的 `diagnosis.*` 树
  （结构一致性由 `tests/i18n-locale-parity.test.ts` 与 pre-push 钩子强制）。
  `diagnosis.subtitle` 点名 V4 细则，`diagnosis.jdHint` 解释两个相互独立的
  门控（只有岗位匹配度需要 JD；五个能力项需要明确意向 + 匹配或手选的职级
  模型）。

## 测试

- 后端：`tests/unit/test_diagnosis_checks.py`（锁定每个确定性信号 → 评级，
  包括无条件必填模块 #3、技能 8–15 区间 #7、项目六字段代理与无条件 2–4 数量
  #9、带豁免标注的工作/教育重叠检测、带 个人业余项目 标记的项目任期包含关系、
  工作开始与学历顺序、±0.5 年声称年限 #13、不具否决力的 #14 语义——4 跳
  partial、只统计已结束任职、排除无固定结束日的工作、隐私 #16、执行器 id 集、
  只含问题的合并（#1 仅段落问题回归、符合行沉默、每个问题行带自己的信号专属
  修复、拼接处无 `。；` 双标点）、段落密度按换行后的单要点计行、个人信息头部
  改名不治理、#16 对逐字原文的补充扫描与跨来源命中去重，以及覆盖证据与建议中规则
  词汇和内部阈值的防泄漏断言），
  `tests/unit/test_diagnosis_summary.py`（计数/红线聚合），
  `tests/unit/test_diagnosis_competency.py`（随包 P3–P8 目录、标题自动匹配表、
  显式 key 优先、`"none"` 退出、KeyError、18–22 原地填充与全局规则透传且不修改
  缓存的基础规则），
  `tests/unit/test_diagnosis_docx.py`（合法 ZIP、topic/位置/问题/修复渲染、
  criterion/QC 防泄漏断言、动态计数表、能力匹配行、附录覆盖、V4 副标题、
  中/英界面文字、RFC 5987 头），
  `tests/unit/test_diagnosis_response.py`（验证器数字字符串 id 强转、越界/非法
  条目丢弃、去重、零可用条目拒绝；截断数组抢救，含 markdown 围栏与 JSON 字符串
  内的花括号），
  `tests/integration/test_llm_contract_reliability.py` 也锁定 `complete_json`
  抢救钩子（仅最后一次尝试、抢救内容仍须通过验证器、验证器拒绝时重新抛错），
  `tests/service/test_diagnosis_service.py`（LLM 打桩；始终 22/7、独立门控——
  无 JD 时第 17 项 na、意向可解析时无 JD 也评判 18–22、无模型才 na、有 JD 无
  标题时第 17 项评判而 18–22 为 na、Java 标题默认自动匹配 P4、显式 key 与
  none 处理、未知 KeyError、自定义模型原地填充、#15 不足 5 年 na、缺失项默认、
  验证器宽容（数字字符串 id、丢弃坏/越界条目、零可用条目拒绝）、丢弃
  reasoning-effort、LLM 与客观结论的符合行沉默、客观问题行带信号专属修复且不
  建议已通过的子检查、两层事实依据（逐字区块与规则 8 的内容/模块分层框架进入
  提示词、无存储 markdown 时省略区块、超长原文带明确提示截断、#16 红线扫描
  原文），
  以及覆盖 criterion/QC 文本、职级标准与全局规则材料缺席的"提示词 vs 报告"
  保密测试），
  `tests/integration/test_diagnosis_endpoint.py`（diagnose 200/400/404、两个
  独立门控含"有 JD 无标题"、目录 GET 列表/自动匹配、显式 key、none 退出、
  JSON 无 criterion/qc、评判植根于存储的原始 markdown），
  `tests/integration/test_diagnosis_document_endpoint.py`（HTTP 200 + 合法
  docx + 候选人姓名 + topic 附录；404），
  `tests/unit/test_diagnosis_layout_checks.py`（实测优先：4 页快照 → #2 判
  不符合且证据含“实际渲染”不含“估算”、2 页符合空证据、300 字估算必败但实测
  ≤6 行 → #1 符合、四类 locator 解析与全文搜索/未对齐兜底、stringList 不枚举、
  template/page_size 不匹配拒绝、facts.layout 形状、Pydantic 越界），
  `tests/service/test_diagnosis_rendered_layout.py`（渲染块/镜像/facts 进入
  提示词、待评编号不含 1/2、无快照无块、12KB 截断保 facts），
  `tests/integration/test_diagnosis_rendered_layout_endpoint.py`（带快照的
  200 客观判定、128KB → 413、page_count 越界 → 422、`{}` 仍 200）。
- 前端：`tests/diagnosis-modal.test.tsx`（0/1/多个意向的目标选择器、目录
  预选/手动确认/退出/加载失败、计数渲染、唯一 #16 红线的通过/失败横幅、
  topic 而非标准的渲染、过滤、错误重试、Word 下载成功/失败、离屏测量成功时
  成对透传两字段、测量中文案、测量失败仍诊断且无字段并显示 layoutSkipped、
  无 resumeData 不测量），
  `tests/diagnosis-api.test.ts`（POST 体含 `competency_model_key`、none
  哨兵、目录 GET URL/编码/错误映射、排版两字段成对透传/单边省略），
  `tests/layout-snapshot.test.ts`（要点枚举与后端遍历逐字一致、对齐三级路径、
  列/头部聚类、分页指派、双栏镜像顺序与截断、48KB 钳制），
  `tests/use-pagination-paginate.test.ts`（`computePageBreaks` 贪心分页纯
  函数：过半回退、硬切、多页单调推进），
  `tests/template-settings-storage.test.ts`（深合并/坏枚举/越界/坏 JSON/
  存储被阻不抛错），
  `tests/measure-resume-layout.test.tsx`（jsdom 零高度自检闸门、SSR 无
  DOM 抛 `LayoutMeasurementError`），
  `tests/resume-viewer-template-layout.test.tsx`（查看页 `<Resume>`/PDF
  下载/诊断弹窗跟随 localStorage 模板设置与 uiLanguage，缺省回退默认），
  `tests/job-intentions.test.ts`（切分/去重），以及 Dashboard 工作区套件
  （`tests/diagnosis-workspace.test.tsx` 及相关规格），覆盖
  上传→解析→测量→自动诊断（模型预先解析）、测量成功/失败两条路径、
  JD 重诊（再次测量）门控与 Word 导出。

没有任何测试发起真实 LLM 调用。
