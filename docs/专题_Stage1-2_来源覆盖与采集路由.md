# 专题_Stage1-2_来源覆盖与采集路由

## 1. 文档目的
本专题用于冻结 AX9S 阶段 1-6 的来源覆盖、采集路由与来源状态机口径，供开发、规则、测试与治理统一消费。

- 不是基础设施手册
- 不是抓取代码说明
- 不是全国站点全量目录
- 是来源覆盖与真相形成的专题规范

---

## 2. 与现有文档的关系
- L0：总纲与阶段主链不被本专题改写。
- D2：后续由 D2 承接对象字段与正式对象关系。
- D3：后续由 D3 承接来源/采集相关规则与降级/阻断。
- D11：后续由 D11 承接来源覆盖与状态机测试。
- D13：能力边界与放行不由本专题取代。
- D12：运行治理与发布治理不由本专题取代。
- `任务契约_Stage1-6文件分析闭环与经验库能力落地.md`：本专题只承接其中的来源覆盖、采集路由、状态机、早期线索和字段血缘输入，不承接完整能力矩阵和 Stage4-5 规则定义。

### 2.1 与 Stage1-6 任务契约的分工

本专题是来源和路由规范，不是风控规则目录。与 Stage1-6 任务契约的分工如下：

| 阶段 | 本专题负责 | 本专题不负责 |
|---|---|---|
| Stage1-2 | 来源家族、平台层级、载体类型、采集路由、采集状态、版本链、早期线索候选 | 项目是否值得投、是否疑似控标、是否废标 |
| Stage3 | 给解析和字段血缘提供 `source_family`、`platform_level`、`carrier_type`、`collection_state` 等输入 | 规则命中、风险结论、法律适用结论 |
| Stage4 | 给公开核验提供来源、附件、快照、hash、字段血缘和 readback 依赖 | 核验规则本身、项目经理/资质/信用风险判断 |
| Stage5 | 给规则门和证据门提供可审计来源链和 evidence gate 输入 | `rule_hit`、`rule_gate_decision`、`evidence_gate_decision` 的规则定义 |
| Stage6 | 给事实报告提供来源可回放基础 | 报告结论、商业钩子、复核队列策略 |

新增经验库能力在本专题中的处理边界：

- 两法体系分流：本专题只提供平台类型、来源家族、采购/招标线索和资金来源文本的采集入口。
- 公告前机会：本专题负责采购意向、招标计划、重大项目清单、审批/土地/新闻等来源候选和路由。
- 地区规则画像：本专题只登记地方公共资源平台规则、地方政策、历史样本来源，不给地区好投/难投结论。
- AI 采集与项目档案：本专题只保留字段模板、`source_url`、快照和字段血缘要求；AI 输出不能替代原始来源。
- 控标、废标、自评分、公平竞争、救济、结算：本专题只提供来源和证据输入，具体规则归 Stage4-5/Stage6 规则与报告链承接。

### 2.2 招投标双线业务路由

本专题的来源和采集路由必须服从双线业务方向契约：

- 人类可读方向源：`docs/业务方向_候选公示后证据包与投前预测双线契约.md`。
- 机器可读方向源：`contracts/evaluation/business_direction_strategy_contract.json`。

默认核心商业路线是 `POST_CANDIDATE_EVIDENCE_PACK`。当任务涉及候选公示、候选人核查、真实竞争者、控标/围标/串标/陪标证据包或销售承接时，采集应先从近期 `07 中标候选人公示` 入池，再回溯同一项目全流程材料。评标结果、开标记录、中标结果、合同和异常材料是回溯或支撑阶段，不再作为默认商业入口：

`07 中标候选人公示 -> 03 招标公告/关联公告 -> 招标文件附件 -> 04 答疑澄清/补遗 -> 05 开标信息 -> 06 资审结果 -> 08 投标文件公开 -> 09/10 中标结果/中标信息 -> 11/12 后期核验材料`

`PRE_BID_PREDICTION` 只用于近期 `02 招标文件公示`、`03 招标公告/关联公告`、`04 澄清答疑`。该线可以做是否值得投、控标/定制标预测、废标风险、澄清/质疑建议，但不得输出候选人核查、真实竞争者结论或陪标组合结论。若只有 `02/03` 且尚无 `04`，必须标记 `PREDICTION_BEFORE_CLARIFICATION`；后续出现澄清、答疑、补遗或补充招标文件时，必须标记 `PREDICTION_RECALC_REQUIRED` 并重新预测。

投前预测还有硬时钟门槛：若同项目已经出现 `05 开标信息`，或者投标截止日期/开标日期已经过去，采集路由不得继续把该项目送入投前预测，只能转入开标后核验、候选后跟踪或证据包路线。若已经出现 `07 中标候选人公示`，直接进入 `POST_CANDIDATE_EVIDENCE_PACK`。标准投前预测销售窗口为截止/开标前 168 小时以上；72-168 小时只能进入限时快筛；少于 72 小时不作为正常投前预测销售。

两条业务入口默认只抓工作日 72 小时内的近期公告，不再把 30 天作为默认生产入口窗口；30 天或更长窗口只用于广州 `01-12` 流程接口覆盖、历史适配验证或人类明确指定的回溯/历史场景。后续仍可增加最近 1/3/7/15/30 天或自定义时间段的显式筛选。近期 `07` 项目通常不会有 `11 合同信息公开` 和 `12 项目异常`，缺 11/12 不能算当前销售窗口失败；如 11/12 已存在，应按历史/后期核验或复盘场景另判。

公开页面或附件人工可见但系统无法抓取/下载时，必须进入修复队列；失败原因必须区分 `code_or_adapter_bug`、`detail_transport_blocked`、`attachment_challenge_required`、`tls_or_waf_or_proxy_issue`、`login_or_ca_required`、`platform_sync_delay_or_no_public_endpoint`，不得泛化为单一失败。

在 `AttachmentList` 之后、真实下载或解析之前，必须生成 `AnalysisStrategyPlan v1` 口径的分析计划，明确每个流程和文件是否下载、是否解析、解析深度、规则核验和大模型触发条件。候选后证据包主线需要全面识别控标、围标、串标、陪标和真实买家线索，但仍必须按证据价值分层解析，不允许发现文件就全部深解析。

广东来源固定口径：

- 广东主动采集和校准主源使用广州交易集团相关 source profile。
- 广东工程建设现行来源只保留广州交易集团/广州公共资源交易中心。
- `tender_file` smoke 只证明招标文件下载、snapshot、MarkItDown/解析和项目审计链路，不代表候选公示后证据包主线完成。
- 广州 `01-12` 流程接口覆盖是适配器验证，不是生产爬取目标清单；人类提供的流程样例 URL 只能用于验证流程码、页面结构、附件入口和挑战状态，不能作为默认采集入口或样本数量统计。

---

## 3. 地区覆盖范围模型
本专题冻结以下覆盖范围表达模型：

- `NATIONAL`：全国级覆盖
- `PROVINCE`：省级覆盖
- `CITY`：市级覆盖
- `COUNTY`：区县级覆盖

规则：
- coverage 是能力放行与数据可靠度的重要输入。
- coverage 不等于对外承诺。
- coverage 不足可触发 `downgrade / review / block`。

---

## 4. 来源家族与平台类型模型
采用三维分类：来源家族 + 平台层级 + 载体类型。

### 4.1 来源家族（source_family）
- 招标/采购公告类
- 中标/成交公示类
- 住建/四库/监管公示类
- 企业信息/工商/资质类
- 法院/处罚/信用/风险类
- 附件/补遗/答疑类
- 其他公开链补充来源

说明：重大项目清单、审批/用地/规划、土地招拍挂、地方新闻、设计/咨询中标、行业官网、上下游反推、圈子信息等，先作为项目生命周期早期线索来源候选登记；未完成来源评估、回链固定和证据分级前，不新增正式 `source_family` 枚举，也不自动进入 authoritative source baseline。

### 4.2 平台层级（platform_level）
- 国家级
- 省级
- 市级
- 区县级
- 行业/专题平台
- 企业自有公开页

### 4.3 载体类型（carrier_type）
- `HTML_PAGE`：HTML 页面
- `PDF_ATTACHMENT`：PDF 附件
- `DOC_ATTACHMENT`：DOC/DOCX 附件
- `IMAGE_ATTACHMENT`：图片扫描件
- `TABLE_SEGMENT`：表格型页面
- `TEXT_SEGMENT`：纯文本片段

### 4.4 实施层字段承接模型（阶段 1-2）
本专题冻结以下字段作为阶段 1-2 的正式实施层字段表达：

- `source_family`
- `platform_level`
- `region_scope`
- `coverage_tier`
- `carrier_type`
- `default_route`
- `collection_state`
- `requires_manual_review`

字段承接对象（最小落点）：

- `execution_context`：`region_scope`、`source_family`、`platform_level`、`coverage_tier`、`default_route`、`requires_manual_review`
- `public_chain`：`source_family`、`platform_level`、`region_scope`、`coverage_tier`、`carrier_type`、`default_route`、`collection_state`、`requires_manual_review`
- `clock_chain_profile`：`collection_state`、`requires_manual_review`
- `notice_version_chain`：`source_family`、`platform_level`、`region_scope`、`carrier_type`、`default_route`、`collection_state`
- `field_lineage_record`：`source_family`、`platform_level`、`carrier_type`、`coverage_tier`、`collection_state`

---

## 5. 代表性来源目录模型
本章冻结“目录条目表达方式”，不做全国全量列举。

### 5.1 目录字段模型
每个目录条目必须包含：
- `source_family`
- `platform_level`
- `region_scope`
- `carrier_type`
- `coverage_tier`
- `maturity_level`
- `requires_manual_review`
- `default_route`
- `collection_state`
- `source_examples`

### 5.2 代表性来源示例（非全量）
| source_family | platform_level | region_scope | carrier_type | coverage_tier | maturity_level | requires_manual_review | default_route | collection_state | source_examples |
|---|---|---|---|---|---|---|---|---|---|
| PROCUREMENT_NOTICE | PROVINCE | PROVINCE | HTML_PAGE | T1_REGIONAL | MEDIUM | true | VERSION_CHAIN | ELIGIBLE | 省级公共资源交易公告平台（示例） |
| AWARD_ANNOUNCEMENT | CITY | CITY | HTML_PAGE | T2_LOCAL | MEDIUM | true | LIST_TO_DETAIL | ELIGIBLE | 市级中标公示平台（示例） |
| REGULATORY_PUBLICATION | NATIONAL | NATIONAL | HTML_PAGE | T0_CORE | HIGH | false | DETAIL_DIRECT | ELIGIBLE | 全国建筑市场监管公共服务平台（四库） |
| ENTERPRISE_REGISTRY | INDUSTRY_PLATFORM | NATIONAL | TABLE_SEGMENT | T1_REGIONAL | MEDIUM | true | METADATA_ONLY | ELIGIBLE | 企业资质公示平台（示例） |
| ANNEX_QA_SUPPLEMENT | PROVINCE | PROVINCE | PDF_ATTACHMENT | T1_REGIONAL | LOW | true | ATTACHMENT_FIRST | ELIGIBLE | 招标答疑附件库（示例） |
| JUDICIAL_CREDIT_RISK | NATIONAL | NATIONAL | PDF_ATTACHMENT | T1_REGIONAL | MEDIUM | true | ATTACHMENT_FIRST | ELIGIBLE | 信用与处罚公开库（示例） |

说明：
- `coverage_tier` 仅表达覆盖层级与稳定性，不等于对外承诺。
- `maturity_level` 用于评估采集稳定性与可用性（HIGH / MEDIUM / LOW）。
- `default_route` 采用 `route_type` 正式枚举值。

### 5.3 项目生命周期早期线索来源候选（非 authoritative baseline）
本节只记录“项目还没正式公告前，可能出现机会线索的来源类型”。这些来源候选用于扩展情报发现和人工跟进，不代表已进入 authoritative source baseline，不代表自动采集能力已经成熟，也不代表可以直接进入正式证据链。

| 候选来源 | 常见可见阶段 | 可用信息 | 默认处理 | 边界 |
|---|---|---|---|---|
| 专业招标网站 | 公告、补遗、中标、聚合转载 | 多平台公告聚合、时效差异、附件入口 | 多平台对比、去重、回链到原始平台 | 聚合页本身通常不作为最终权威来源 |
| 政府采购网、公共资源交易平台 | 采购意向、需求意见征集、正式公告、补遗、结果 | 采购方式、预算、采购人、代理、时间链 | 优先进入公开链候选，按版本链和附件链固定 | 仍需区分政府采购、依法必招和平台采购口径 |
| 重大项目清单 | 年度重点项目、新建、续建、前期项目 | 项目名称、建设性质、投资规模、建设周期、主管口径 | 建立早期 watchlist，按生命周期阶段跟进 | 只能提示机会方向，不能替代采购公告 |
| 发改、住建、自然资源等审批平台 | 立项、备案、可研、用地、规划、施工许可 | 建设单位、建设内容、审批节点、用地/规划状态 | 作为公告前 3-6 个月机会线索，保留官方页面或快照 | 字段可能不等同于最终采购范围 |
| 土地招拍挂 | 工业、商业、住宅等用地成交 | 地块位置、竞得人、用途、成交时间、建设强度 | 从土地成交反推后续建设、设备、服务采购机会 | 反推结果只作内部线索，必须标注推断链 |
| 地方新闻 | 签约、开工、奠基、封顶、竣工、投产 | 项目进度、投资主体、地方重点推进事项 | 补充时间线和背景，交叉核验公开平台信息 | 新闻稿不单独支撑正式采购结论 |
| 设计院、咨询公司中标信息 | 可研、设计、施工图、咨询服务中标 | 前期服务承接方、项目阶段、后续采购方向 | 作为施工、设备、家具、系统采购的前置信号 | 只能说明阶段推进，不证明后续招标必然发生 |
| 细分行业官网 | 教育、医疗、金融、国企、上市公司采购平台 | 行业采购意向、供应商征集、企业自采公告 | 登记行业来源，按平台规则评估采集可行性 | 企业自有公开页要单独判断权威性和完整性 |
| 上下游反推 | 土建、装修、家具、设备、系统集成等上下游链条 | 相邻环节进度、潜在采购窗口 | 形成内部跟进线索和行业分类标签 | 不得把商业推断写成事实结论 |
| 圈子信息、社群信息 | 协会、商会、校友会、供应商群等非公开或半公开消息 | 早期消息、联系人提示、关键词线索 | 只能 `REGISTER_ONLY` 或人工弱线索登记 | 必须有公开来源回链、可固定载体和证据分级后，才能进入正式证据链 |

执行边界：
- 以上来源先进入候选登记和来源评估；是否进入 `source_registry`、`source_family_registry` 或正式采集计划，需要另行通过成熟度、合法性、回链和人工复核判断。
- 圈子信息、社群信息、非正式经验材料和评论区只能作为弱线索或关键词来源，不得单独形成正式结论，不得直接生成外发证据。
- AI 输出的项目表、分类表或网页预览只是收集、清洗、分类、整理结果；每条记录必须保留 `source_url`、快照或字段血缘，不能用模型生成内容替代原始来源。

### 5.4 AI 采集输出候选（非自动采集成熟度承诺）
AI 可用于把多渠道线索整理为统一字段，减少人工重复整理，但不替代项目判断、证据核验和商业决策。本节不新增正式 schema，只给后续采集和项目档案设计预留候选字段。

候选字段：
- `project_name`
- `region`
- `construction_nature`
- `owner_or_project_entity`
- `construction_content`
- `investment_amount`
- `construction_period`
- `industry_category`
- `source_channel_type`
- `project_lifecycle_stage`
- `source_url`
- `captured_at`
- `field_lineage`
- `review_required`

候选输出：
- 表格版：用于筛选、排序、导入内部项目池。
- 网页版：用于人工查看、共享和复核，不作为证据链原件。
- 复盘记录：沉淀高质量平台、有效关键词、分类规则和失败原因。

---

## 6. 采集路由模型
本章冻结“采集路由类型”，不写技术脚本实现。

| 路由类型（route_type） | 适用来源家族 | 适用载体类型 | 默认产出 | 常见失败点 | 自动进入下一步 | 是否必须人工复核 |
|---|---|---|---|---|---|---|
| `LIST_TO_DETAIL` 列表页发现 → 详情页拉取 | 招标/采购公告类、中标/成交公示类 | `HTML_PAGE` | 详情页正文 + 元数据 | 列表分页缺失、详情链接漂移 | 是 | 视稳定性 |
| `DETAIL_DIRECT` 详情页直取 | 住建/四库/监管公示类 | `HTML_PAGE` | 结构化元数据 | 字段变更、site challenge 限制 | 是 | 否 |
| `ATTACHMENT_FIRST` 附件优先 | 附件/补遗/答疑类、法院/处罚类 | `PDF_ATTACHMENT` / `DOC_ATTACHMENT` | 附件正文 + 元数据 | 附件缺失、格式异常 | 受控 | 是 |
| `VERSION_CHAIN` 版本链追踪 | 多版本公告链 | `HTML_PAGE` / `TEXT_SEGMENT` | 版本关系链 + 最新版本 | 版本号缺失、链断裂 | 否 | 是 |
| `METADATA_ONLY` 仅元数据采集 | 企业信息/资质类 | `TABLE_SEGMENT` | 目录元数据 | 元数据不全、字段冲突 | 是 | 视稳定性 |
| `SEMI_MANUAL` 半人工补采 | 任意低成熟来源 | 任意 | 人工补证 + 结构化要点 | 人工负载 | 否 | 是 |
| `REGISTER_ONLY` 不可自动采集，仅登记来源 | 受限来源 | 任意 | 来源登记记录 | 法律/robots限制 | 否 | 是 |

---

## 7. 采集生命周期状态机
本状态机用于阶段 1-6 的采集与真相形成子流程，不替代 1-9 主链。

### 7.1 状态定义（最小集合）
- `DISCOVERED`：来源已发现但未评估
- `ELIGIBLE`：来源满足基础采集条件
- `SCHEDULED`：已进入采集计划
- `FETCHED`：已完成采集
- `PARSED`：已解析
- `NORMALIZED`：已归一化
- `VERIFIED`：已核验
- `EVIDENCED`：已形成可审计证据链
- `FACT_READY`：可进入事实层
- `REVIEW_REQUIRED`：需人工复核
- `BLOCKED`：阻断不可进入主链

### 7.2 允许迁移关系
- `DISCOVERED → ELIGIBLE → SCHEDULED → FETCHED → PARSED → NORMALIZED → VERIFIED → EVIDENCED → FACT_READY`
- 任一状态可转入 `REVIEW_REQUIRED`
- 任一状态可转入 `BLOCKED`

### 7.3 触发 review 的条件（示例）
- 来源成熟度为 LOW
- 版本链不完整
- 载体为图片扫描件或 OCR 退化
- 元数据不足或字段冲突

### 7.4 触发 downgrade 的条件（示例）
- 覆盖层级不足（coverage_tier 下降）
- 来源稳定性下降
- 时钟冲突未解

### 7.5 触发 block 的条件（示例）
- 站点不可访问且无替代来源
- 法律/robots 禁止采集
- 证据链不可审计或不可回链

---

## 8. 异常、降级与人工介入规则
| 异常类型 | 处理结果 | 是否允许人工补证 | 补证后是否允许恢复 |
|---|---|---|---|
| 站点不可访问 | review 或 block | 是 | 视替代来源与审计情况 |
| robots / 法律限制 | block | 否 | 否 |
| 附件缺失 | review | 是 | 是 |
| OCR/截图退化 | downgrade + review | 是 | 是 |
| 版本冲突 | review | 是 | 是 |
| 时钟冲突 | review | 是 | 是 |
| 载体不完整 | review | 是 | 是 |
| 元数据不足 | downgrade | 是 | 是 |
| 颗粒度不足 | downgrade | 是 | 是 |
| 来源可信度不足 | review / block | 是 | 视审计结果 |

---

## 9. 与正式对象的预留映射说明
后续将由以下对象消费本专题口径（本轮不改 D2）：
- `public_chain`
- `clock_chain_profile`
- `notice_version_chain`
- `field_lineage_record`
- `execution_context`
- 阶段 5/6 的规则与事实对象

---

## 10. 后续同步计划
后续同步顺序固定为：
1. 先同步 `D2`
2. 再同步 `D3`
3. 再同步 `D11`
4. 再同步机器资产
5. 最后考虑 API / 页面 / 运行层承接

---

## 11. 本专题实施层承接清单

本专题必须被以下正式承接面消费：

- D2：阶段 1-2 对象字段落点与最小必需字段
- D3：阶段 1-2 规则码、降级/阻断与路由失败处理
- D11：阶段 1-2 采集覆盖与状态机测试入口
- contracts：
  - `contracts/schemas/schema_catalog.json`
  - `contracts/enums/enum_catalog.json`
  - `contracts/rules/rule_catalog.json`

---

## 12. M2 Stage1-2 extractor contract 补表（本轮新增）

本补表用于把 Stage 1-2 的 source/route/time-range/clock/version 解析责任收口到 extractor 层；不改写既有正式对象、既有 handoff contract 或 Stage 3+ 业务语义。

### 12.1 extractor 接口分层

当前最小 extractor 接口固定为三层：

1. `stage1_source_route_extractor`
2. `stage1_time_window_extractor`
3. `stage2_collection_clock_version_extractor`

### 12.2 producer ownership

| extractor | canonical producer | owned fields | consumer |
|---|---|---|---|
| `stage1_source_route_extractor` | Stage 1 | `source_registry_id`、`route_policy_id`、`default_route`、`fallback_route` | Stage 2 |
| `stage1_time_window_extractor` | Stage 1 | `time_range_from`、`time_range_until`、`window_priority_policy`、`clock_resolution_rule_id` | Stage 2 |
| `stage2_collection_clock_version_extractor` | Stage 2 | `collection_state`、`clock_conflict_state`、`window_clock_state`、`winning_version_resolution_rule_id`、`fixation_bundle_id`、`origin_carrier_type`、`first_seen_at`、`last_retrieved_at` | Stage 3 |

规则：
- Stage 2 不得再从 raw payload 重算 `default_route`、`source_registry_id`、`route_policy_id`。
- Stage 3 不得再在无 `fixation_bundle`、无 `clock_conflict_state` 语义下继续解析。

### 12.3 fallback taxonomy

本轮 extractor 只允许使用以下 fallback reason：

- `fallback_route_from_registry_or_policy`
- `fallback_route_fell_back_to_default_route`
- `time_range_from_from_now_year`
- `time_range_until_from_now_year`
- `default_route_source=h01_authority`
- `winning_version_resolution_rule_id_source=fallback_default`

说明：
- 这些 fallback 只表达“保守默认如何得出”，不等于放行。
- 若 fallback 与现有 block/review 条件冲突，仍以 block/review 优先。

### 12.4 mismatch / review taxonomy

本轮 extractor 只收口以下 mismatch/review reason：

- `default_route_mismatch_requires_review`
- `collection_state_requires_review`
- `clock_conflict_requires_review`
- `rollout_scope_requires_review`
- `version_precedence_requires_review`

说明：
- 本轮不新增正式枚举，也不新增新的 exception 流程。
- mismatch/review reason 仅作为 extractor trace，不提升为新的 release gate 或 formal exception。

### 12.5 当前明确不做

- 不新增正式对象
- 不新增正式枚举集合
- 不改 Stage 3+ 逻辑
- 不改 transport/bootstrap
- 不放开任何 external/live 执行能力

---

## 13. Stage1-2 authoritative baseline 补表（本轮新增）

本补表只冻结“路线图可诚实引用”的最小 authoritative baseline，不代表全国全量来源目录，不代表真实采集器已接通。

### 13.1 authoritative source baseline

| source_registry_id | source_family | platform_level | region_scope | carrier_type | coverage_tier | default_route | route_policy_id | 当前口径 |
|---|---|---|---|---|---|---|---|---|
| `SRC-REG-PROC-NATIONAL-HTML` | `PROCUREMENT_NOTICE` | `NATIONAL` | `NATIONAL` | `HTML_PAGE` | `T0_CORE` | `LIST_TO_DETAIL` | `ROUTE-PROC-NOTICE-001` | 国家级招采公告主 baseline |
| `SRC-REG-PROC-CITY-PDF` | `PROCUREMENT_NOTICE` | `CITY` | `CITY` | `PDF_ATTACHMENT` | `T2_LOCAL` | `ATTACHMENT_FIRST` | `ROUTE-PROC-ATTACHMENT-001` | 地方 PDF 公告附件 baseline |
| `SRC-REG-AWARD-CITY-HTML` | `AWARD_ANNOUNCEMENT` | `CITY` | `CITY` | `HTML_PAGE` | `T2_LOCAL` | `LIST_TO_DETAIL` | `ROUTE-AWARD-ANNOUNCEMENT-001` | 市级中标/成交公示 baseline |
| `SRC-REG-REG-NATIONAL-HTML` | `REGULATORY_PUBLICATION` | `NATIONAL` | `NATIONAL` | `HTML_PAGE` | `T0_CORE` | `DETAIL_DIRECT` | `ROUTE-REG-PUBLICATION-001` | 国家级监管公示 baseline |
| `SRC-REG-ENTERPRISE-INDUSTRY-TABLE` | `ENTERPRISE_REGISTRY` | `INDUSTRY_PLATFORM` | `NATIONAL` | `TABLE_SEGMENT` | `T1_REGIONAL` | `METADATA_ONLY` | `ROUTE-ENTERPRISE-REGISTRY-001` | 企业/资质目录元数据 baseline |
| `SRC-REG-JUDICIAL-NATIONAL-PDF` | `JUDICIAL_CREDIT_RISK` | `NATIONAL` | `NATIONAL` | `PDF_ATTACHMENT` | `T1_REGIONAL` | `ATTACHMENT_FIRST` | `ROUTE-JUDICIAL-ATTACHMENT-001` | 法院/处罚/信用 PDF baseline |
| `SRC-REG-JUDICIAL-COUNTY-IMAGE` | `JUDICIAL_CREDIT_RISK` | `COUNTY` | `COUNTY` | `IMAGE_ATTACHMENT` | `T2_LOCAL` | `SEMI_MANUAL` | `ROUTE-JUDICIAL-SEMI-MANUAL-001` | OCR/截图退化 baseline |
| `SRC-REG-ANNEX-PROVINCE-DOC` | `ANNEX_QA_SUPPLEMENT` | `PROVINCE` | `PROVINCE` | `DOC_ATTACHMENT` | `T1_REGIONAL` | `VERSION_CHAIN` | `ROUTE-ANNEX-VERSION-001` | 补遗/答疑 DOC baseline |
| `SRC-REG-ANNEX-PROVINCE-TEXT` | `ANNEX_QA_SUPPLEMENT` | `PROVINCE` | `PROVINCE` | `TEXT_SEGMENT` | `T1_REGIONAL` | `VERSION_CHAIN` | `ROUTE-ANNEX-VERSION-001` | 补遗/答疑文本版本链 baseline |
| `SRC-REG-OTHER-ENTERPRISE-TEXT` | `OTHER_PUBLIC_SOURCE` | `ENTERPRISE_SITE` | `CITY` | `TEXT_SEGMENT` | `T2_LOCAL` | `REGISTER_ONLY` | `ROUTE-OTHER-REGISTER-001` | 其他公开补充来源 baseline |

说明：
- 上表是 route map 可引用的最小 baseline，不代表同 family/platform 的全量来源都已建档。
- `source_family_registry.json` 与 `platform_level_registry.json` 负责把 family / platform baseline 再抽一层 machine-readable 说明；`source_registry.json` 负责代表性 entry。

### 13.2 authoritative route baseline

| route_policy_id | route_type | baseline source family / carrier | fallback_route | default_decision | version / clock / deadline 关系 |
|---|---|---|---|---|---|
| `ROUTE-PROC-NOTICE-001` | `LIST_TO_DETAIL` | `PROCUREMENT_NOTICE` + `HTML_PAGE` | `DETAIL_DIRECT` | `ALLOW` | `NOTICE_REPLACEMENT_CHAIN` + `CLOCK-DEFAULT` + deadline 缺失走 review |
| `ROUTE-PROC-ATTACHMENT-001` | `ATTACHMENT_FIRST` | `PROCUREMENT_NOTICE` + `PDF_ATTACHMENT` | `DETAIL_DIRECT` | `REVIEW` | 附件优先，时钟冲突/附件缺失进入 review |
| `ROUTE-AWARD-ANNOUNCEMENT-001` | `LIST_TO_DETAIL` | `AWARD_ANNOUNCEMENT` + `HTML_PAGE` | `DETAIL_DIRECT` | `ALLOW` | award 详情页与版本链基线 |
| `ROUTE-REG-PUBLICATION-001` | `DETAIL_DIRECT` | `REGULATORY_PUBLICATION` + `HTML_PAGE` | `METADATA_ONLY` | `ALLOW` | 监管详情直取，缺明细降级 metadata |
| `ROUTE-ENTERPRISE-REGISTRY-001` | `METADATA_ONLY` | `ENTERPRISE_REGISTRY` + `TABLE_SEGMENT` | `SEMI_MANUAL` | `REVIEW` | 企业目录只承诺 metadata baseline |
| `ROUTE-JUDICIAL-ATTACHMENT-001` | `ATTACHMENT_FIRST` | `JUDICIAL_CREDIT_RISK` + `PDF_ATTACHMENT` | `SEMI_MANUAL` | `REVIEW` | PDF 附件 + OCR/审计 review baseline |
| `ROUTE-JUDICIAL-SEMI-MANUAL-001` | `SEMI_MANUAL` | `JUDICIAL_CREDIT_RISK` + `IMAGE_ATTACHMENT` | `REGISTER_ONLY` | `REVIEW` | 图片/OCR 退化直接半人工 |
| `ROUTE-ANNEX-VERSION-001` | `VERSION_CHAIN` | `ANNEX_QA_SUPPLEMENT` + `DOC_ATTACHMENT/TEXT_SEGMENT` | `ATTACHMENT_FIRST` | `REVIEW` | version chain 是 annex baseline，不得高估自动成熟度 |
| `ROUTE-OTHER-REGISTER-001` | `REGISTER_ONLY` | `OTHER_PUBLIC_SOURCE` + `TEXT_SEGMENT` | `SEMI_MANUAL` | `REVIEW` | 只登记来源，不宣称自动采集成熟 |

说明：
- `route_policy_catalog.json` 必须承接 `platform_level_refs / carrier_type_refs / default_decision / downgrade_signals / review_conditions / blocked_signals / version_chain_relation / clock_chain_relation / action_deadline_relation`。
- `public_chain` 必须 machine-readably 承接 `source_registry_id / route_policy_id / fallback_route / route_decision_state / route_review_reasons / route_downgrade_signals / route_block_signals`。
- `notice_version_chain` 必须 machine-readably 承接 `source_registry_id / route_policy_id / fallback_route / version_chain_strategy`。
- `clock_chain_profile` 必须 machine-readably 承接 `clock_resolution_rule_id / current_action_start_at_optional / current_action_deadline_at_optional`。

### 13.3 family / platform baseline registry

| registry | 当前职责 |
|---|---|
| `contracts/governance/source_family_registry.json` | 机器可读声明 family 级 baseline：代表 entry、支持平台/载体、默认 route |
| `contracts/governance/platform_level_registry.json` | 机器可读声明 platform level 级 baseline：默认 `region_scope / coverage_tier`、支持 family、默认 route，并冻结 platform-level canonical authority |

补充说明：
- 这两份 registry 只声明 authoritative baseline，不替代 `source_registry.json` 的代表 entry；
- `source_family_registry.json` 与 `platform_level_registry.json` 都必须声明 `baseline_scope`；其中 platform registry 还必须声明 `canonical_authority`，把 `platform_level -> region_scope / coverage_tier / default_route` 的 producer authority 固定在 machine-readable 层；
- 若路线图引用 family/platform baseline，必须以这两份 registry + `source_registry.json` 共同判断，不得把代表 entry 误写成全国全量覆盖。

### 13.4 rollout / backlog scope（本轮补齐）

本轮把 Stage1-2 的 representative baseline 从 “minimum authoritative baseline only” 提升为“representative rollout + backlog with precedence”：

| scope | machine-readable 落点 | 当前含义 | 当前边界 |
|---|---|---|---|
| `rollout` | `source_registry.rollout_scope.rollout_registry_refs` + `source_family_registry.entries[*].rollout_registry_refs` + `source_registry.entries[*].rollout_enabled=true` | 当前 internal implementation scope 内要求 extractor runtime 真消费、tests 真覆盖的 representative source baseline | 不代表全国全量来源已建档，不代表真实外部 source 已接入 |
| `backlog` | `source_registry.rollout_scope.backlog_registry_refs` + `source_family_registry.entries[*].backlog_registry_refs` + `source_registry.entries[*].backlog_reason_optional` | 已进入 authoritative baseline，但当前只允许留在 guarded / review-first / backlog 路径，不得误写成默认成熟能力 | 允许进入代表性基线与 regression，不代表当前 rollout 实施面 |

规则：
- rollout/backlog 只表达当前 Stage1-2 representative implementation scope，不改写 D13 能力边界；
- backlog entry 仍可保留在 representative baseline 中，但 extractor runtime 必须把它们导向 `REVIEW_REQUIRED` 或等价 guarded path；
- 不得把 family 级 representative rollout/backlog 写成全国全量覆盖承诺。

### 13.5 collection_state runtime mapping 与 version / clock precedence（本轮补齐）

本轮固定两类 machine-readable 规则：

1. `collection_state` lifecycle 与 runtime projection 分离：
   - `source_registry.entries[*].collection_state` 表示 representative baseline 起点；
   - `route_policy_catalog.policies[*].collection_state_runtime_map` 表示 Stage 2 extractor 把 baseline 状态投影为 runtime `collection_state` 的规则；
   - 当前固定最小投影：`DISCOVERED -> REVIEW_REQUIRED`、`ELIGIBLE -> PARSED`、`REVIEW_REQUIRED -> REVIEW_REQUIRED`、`BLOCKED -> BLOCKED`。
2. version / clock precedence 必须 machine-readable：
   - version precedence：`payload.winning_version_resolution_rule_id -> source_registry.winning_version_resolution_rule_id -> route_policy.version_chain_relation.winning_version_resolution_rule_id`
   - clock precedence：`clock_strategy_profile.clock_resolution_rule_id -> source_registry.clock_precedence_rule_id -> route_policy.clock_chain_relation.clock_precedence_rule_id`

补充说明：
- `clock_resolution_rule_id` 当前仍保留 compatibility sink 角色，但 precedence 本身不得再只靠 `CLOCK-DEFAULT` 隐式代表；
- `winning_version_resolution_rule_id` 当前必须优先消费 formal precedence source，不得再停留在 `VERSION-DEFAULT` 占位；
- 若 precedence source 缺失，只允许进入 `REVIEW_REQUIRED` / `UNRESOLVED` guarded path，不得伪造成熟度。

### 13.6 canonical authority / adapter-ready producer authority（B1-S1 补齐）

本轮进一步把 Stage1-2 authoritative baseline 的 canonical source 写入 machine-readable contract，不新增真实采集器、不开放外部来源 live 接入。

| authority 面 | machine-readable 落点 | producer / consumer | 当前边界 |
|---|---|---|---|
| source entry authority | `source_registry.canonical_authority` | Stage 1 producer；Stage 2 consumer | Stage 1 产出 `source_registry_id / route_policy_id / default_route / fallback_route / rollout_enabled / precedence`，Stage 2 不得回退 raw input 重算 |
| source family authority | `source_family_registry.canonical_authority` | governance contract producer；Stage 1-2 runtime consumer | family 只做 representative rollout/backlog projection，不代表全国全量覆盖 |
| platform level authority | `platform_level_registry.canonical_authority` | governance contract producer；Stage 1-2 runtime consumer | platform level 只做 `region_scope / coverage_tier / default_route` authoritative projection，不代表全国全量覆盖 |
| route authority | `route_policy_catalog.canonical_authority` | Stage 1 producer；Stage 2 consumer | route fallback / review / block / version / clock / deadline relation 以 route policy 为 canonical source |
| adapter reservation | `*.canonical_authority.adapter_contract_state=RESERVED_NOT_LIVE` | 后续 adapter 预留 | adapter-ready 只表示 contract 可被 adapter 消费，不表示外部 source/live execution 已启用 |

### 13.7 deadline provenance requirement（B1-S1 补齐）

`current_action_deadline_at_optional` 仍落在 `clock_chain_profile`，但 deadline 是否可信必须能回指 route/source authority。

| 项 | machine-readable 落点 | 当前要求 |
|---|---|---|
| deadline provenance requirement | `route_policy_catalog.policies[*].action_deadline_relation.deadline_provenance_requirement` | 必须声明 `required=true`、`source_object=clock_chain_profile`、deadline fields 与 anchor fields |
| deadline fields | `current_action_start_at_optional`、`current_action_deadline_at_optional` | 缺失时进入 review/fallback，不得伪造成熟窗口 |
| provenance anchor fields | `source_registry_id`、`route_policy_id`、`clock_precedence_rule_id`、`clock_resolution_rule_id` | Stage 2 后续投影必须能说明 deadline 来源关联到哪一路 source/route/clock authority |

补充说明：
- 本补充不新增 `clock_chain_profile` schema 字段；它先把 provenance requirement 固定在 route policy relation 层；
- 后续如需把 deadline provenance materialize 为运行时对象字段，可作为后续 direct-dev 或受控批次推进；只有跨阶段机器契约、schema/migration 或 live/source-policy 语义变更时才需要 scoped subpacket，不能在 B1-S1 中顺手进入 Stage3+。
