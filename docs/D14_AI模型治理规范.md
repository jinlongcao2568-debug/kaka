# D14 AI模型治理规范

- **文档名称**：D14 AI模型治理规范
- **文档 ID**：CE-D14-MODEL-GOVERNANCE-CN
- **状态**：DRAFT
- **基线层级**：L1 配套正式文档 / D14
- **定位**：冻结  在建设工程域正式链路下对 AI / 模型的使用边界、输入输出约束、人工复核要求、评测与发布条件、运行审计与禁用场景
- **上位依据**： 建设工程域全闭环权威总文档（L0）
- **目标读者**：产品、架构、研发、测试、规则、治理、法务、交付、SRE、AI / Codex 执行代理
- **机器承接**：`contracts/model/model_catalog.json`、`contracts/model/model_usage_policy.json`、`contracts/model/prompt_policy_catalog.json`、`contracts/model/model_release_gates.json`、`contracts/model/eval_suite_catalog.json`、`contracts/model/output_target_matrix.json`、`contracts/testing/model_golden_cases.json`、`control/model_registry.yaml`、`control/model_release_manifest.yaml`
- **生效说明**：本文只冻结 AI / 模型治理；不改写 L0 已冻结的正式对象、阶段顺序、结果语义、公开边界、字段策略、交付矩阵、触达合规与发布治理口径

---

## [D14-R-001] 0. 文档任务

本文档解决以下问题：

1.  在哪些场景下允许使用模型，哪些场景下只允许模型作为内部辅助；
2. 何时必须形成 `model_governance_record`，它至少要记录哪些治理字段；
3. 模型可以读取什么输入，不可以读取什么输入；
4. 模型输出可以进入哪些正式对象，不能进入哪些正式对象；
5. 何时必须人工复核、何时必须阻断、何时只允许降级为内部建议；
6. 模型上线前必须完成哪些评测、金标、门禁与审批；
7. 运行时如何监控模型漂移、提示词漂移、来源越界、结果越界、成本失控与审计缺失；
8. 发生模型事故、误放行、越界外发或高限制字段泄露时，如何冻结、回滚、隔离与追责。

本文档不是通用大模型教程，不展开模型训练算法原理、供应商采购谈判、GPU 运维细节或通用提示词技巧。

---

## [D14-R-002] 1. 模型治理总原则

### [D14-R-003] 1.1 单向承接原则

- 模型治理只允许承接 L0、D2、D3、D6、D7、D11、D12、D13 已冻结口径，不得反向改写正式对象、结果语义、字段策略、交付矩阵、公开边界或发布门禁。
- 任何模型输出若要进入正式链路，必须先满足上位对象、规则、字段、交付与测试约束；模型治理不是绕开上述约束的快捷通道。
- 模型相关例外只能降低、暂停、隔离或回退能力，不得把 D 层输入、未审计输出或未经审批的高限制信息提升为正式可见结果。

### [D14-R-004] 1.2 正式链路触发原则

- 仅当模型输出直接进入正式对象、正式报告、正式触达建议、正式外发材料或正式法律动作建议时，模型治理才被提升为主链强制项。
- 未进入上述正式链路的模型输出，只允许作为内部辅助、草稿、解释建议或检索增强结果使用，不得直接形成客户可见或正式裁决对象。
- 一旦模型输出进入正式链路，必须同步生成 `model_governance_record`；未形成治理记录的模型输出，一律不得进入正式对象或正式外发面。

### [D14-R-005] 1.3 保守优先原则

- 对模型边界不清、评测不足、输入来源不稳、输出目标不稳、人工复核规则未冻结的场景，一律降级为内部辅助。
- 对模型可能影响 `project_fact`、`legal_action_recommendation`、`saleable_opportunity`、`contact_target`、客户版报告、外发异议辅助包的场景，一律按更严格标准治理。
- 模型生成的摘要、解释、建议、归纳、排序理由，不得替代可回链原始证据、字段 lineage、双闸门、release gate 或审批链。

### [D14-R-006] 1.4 可审计优先原则

- 任一正式模型调用都必须可回答：谁调用、调用了哪个模型版本、输入边界是什么、读取了哪些对象、输出进入了哪个对象、是否经过人工复核、当时 release 状态是什么。
- 不能追溯到模型版本、提示词版本、输入快照、输出落点与审批记录的模型运行，一律视为违规正式运行。

---

## [D14-R-007] 2. 适用范围与非适用范围

### [D14-R-008] 2.1 适用范围

本文适用于以下模型使用场景：

1. 公开页面、公开附件、公开链说明、版本差异说明的辅助摘要；
2. 规则解释、证据说明、字段归一建议、冲突解释建议；
3. 人工复核草稿、报告草稿、外发辅助包草稿；
4. 真实竞争者识别的辅助排序理由、buyer fit 辅助标签、触达建议草稿；
5. 任何会把模型输出写回正式对象、正式报告、正式交付包、正式 API、正式触达对象的场景。

### [D14-R-009] 2.2 非适用范围

以下场景不属于本文允许的正式模型使用方式：

- 用模型替代项目归一、法定节点判断、正式双闸门裁决或正式 release gate；
- 用模型直接认定围标串标、当然废标、当然违法、当然中标无效；
- 用模型直接生成自然人高限制联系对象并默认放行；
- 用模型直接消费 D 层输入、灰色联系人来源、非公开社保或内部底稿并输出正式结论；
- 用模型绕开 D6 字段策略、D7 交付矩阵、D11 测试门槛或 D12 发布门禁。

---

## [D14-R-010] 3. 模型使用分层

### [D14-R-011] 3.1 使用层级

| 层级 | 正式含义 | 允许输出落点 | 最低治理要求 |
|---|---|---|---|
| `M0_INTERNAL_ASSIST` | 内部辅助层 | 内部草稿、解释建议、摘要候选 | 记录模型版本与调用日志即可；不得写入正式对象 |
| `M1_REVIEW_ASSIST` | 复核辅助层 | `review_request`、内部报告草稿、复核意见候选 | 必须保留人工复核；输出不得直达客户可见面 |
| `M2_STRUCTURED_ASSIST` | 结构化辅助层 | 结构化候选、摘要候选、标签候选 | 必须有字段级校验与人工确认；不得直接成为真相层主证 |
| `M3_FORMAL_CHAIN_CONSTRAINED` | 正式链路受限层 | 正式对象中的受限字段、正式报告中的受限摘要 | 必须形成 `model_governance_record`、评测通过、审批通过、人工复核规则冻结 |
| `M4_PROHIBITED` | 禁用层 | 无 | 一律禁止进入正式链路 |

### [D14-R-012] 3.2 默认分层规则

- 任何新模型能力默认从 `M0_INTERNAL_ASSIST` 起步，不得直接宣称为 `M3_FORMAL_CHAIN_CONSTRAINED`。
- 只有在目标对象、输入边界、输出边界、评测、人工复核、发布门禁全部冻结后，模型能力才允许升到 `M3_FORMAL_CHAIN_CONSTRAINED`。
- 以下场景默认至少为 `M3_FORMAL_CHAIN_CONSTRAINED`：
  - 输出进入 `project_fact`；
  - 输出进入 `legal_action_recommendation`；
  - 输出进入客户版报告正文；
  - 输出进入外发异议辅助包主说明；
  - 输出影响 `saleable_opportunity`、`contact_target` 的正式放行。
- 以下场景默认属于 `M4_PROHIBITED`：
  - 生成或改写 D 层证据结论；
  - 直接认定违法或终局结论；
  - 未经审批释放自然人高限制字段；
  - 读取或拼接非法、灰色、不可审计联系人来源。

---

## [D14-R-013] 4. model_governance_record 正式对象

### [D14-R-014] 4.1 正式存在性

`model_governance_record` 是  的跨阶段正式治理对象；只要模型输出进入正式链路，就必须同步形成该对象。

### [D14-R-015] 4.2 最小必有字段

`model_governance_record` 至少必须包含：

- `model_record_id`
- `model_usage_scope`
- `model_family`
- `model_provider`
- `model_version`
- `prompt_template_id`
- `prompt_template_version`
- `retrieval_policy_id_optional`
- `input_boundary_note`
- `input_object_refs`
- `input_data_classification`
- `output_target_object`
- `output_target_field_refs`
- `output_surface_family`
- `human_review_required`
- `human_review_role_chain`
- `public_boundary_tier`
- `release_level_required`
- `model_eval_suite_id`
- `eval_result_snapshot_ref`
- `release_status`
- `allowed_from`
- `allowed_until_optional`
- `rollback_target_version_optional`
- `audit_log_ref`

### [D14-R-016] 4.3 硬约束

- 未填写 `input_boundary_note`、`output_target_object`、`human_review_required` 或 `release_status` 的治理记录，不得进入正式链路。
- `output_target_object` 只能引用 D2 已冻结正式对象；不得写入页面临时状态、销售备注或未冻结对象。
- `public_boundary_tier` 必须能回指 D13 的能力层级；模型不得把 `C_PUBLIC_CONDITIONAL` 或 `D_NON_PUBLIC_OR_FORENSIC` 场景包装成 A 层正式能力。
- `release_status` 未达正式放行态的模型调用，只允许停留在内部辅助或复核辅助层。

---

## [D14-R-017] 5. 输入边界治理

### [D14-R-018] 5.1 允许输入

模型正式使用时，只允许读取以下输入：

- D2 已冻结的正式对象；
- D6 已允许的字段族；
- D7 已允许进入当前交付形态的对象 / 字段投影；
- 公开可回链原始载体、公开附件、公开链快照；
- 已登记且允许的内部治理元数据，如 gate 结果、release 状态、审批状态、coverage 状态；
- 经审批允许的私有补证元数据，但正文材料是否可读必须以 D6 / D7 更严格者为准。

### [D14-R-019] 5.2 禁止输入

模型一律不得直接读取或拼接以下输入进入正式链路：

- D13 D 层输入；
- 非公开社保、内部档案、客户底稿正文、灰色联系人列表；
- 未完成审批的 `private_supplement_record` 正文；
- 未通过字段治理的自然人高限制字段明文；
- 无法审计来源、无合法基础或无 release 状态的外部数据。

### [D14-R-020] 5.3 检索与上下文拼装规则

- 检索增强必须有正式 `retrieval_policy_id`，并声明允许检索的对象族、字段族、时间窗与角色范围。
- 提示词上下文中不得静默混入未放行字段或不可见对象。
- 多来源拼装时，必须保留来源列表与去重策略，避免把不同项目、不同版本、不同阶段对象拼成单一事实。

---

## [D14-R-021] 6. 输出边界治理

### [D14-R-022] 6.1 允许输出类型

模型允许产生以下类型的输出，但其正式可见级别各不相同：

- `summary_candidate`：摘要候选
- `explanation_candidate`：解释候选
- `review_note_candidate`：复核意见候选
- `label_candidate`：标签候选
- `draft_report_section`：报告段落草稿
- `draft_action_assist_section`：外发辅助段落草稿
- `ranking_reason_candidate`：排序理由候选
- `contact_message_candidate`：触达话术草稿

### [D14-R-023] 6.2 允许进入的正式对象

模型输出只允许在受控条件下进入以下正式对象：

- `report_record`
- `review_request`
- `legal_action_recommendation` 的理由摘要候选区
- `project_fact` 的解释型摘要字段
- `challenger_candidate_profile` 的辅助理由标签
- `buyer_fit` / `challenger_buyer_fit` 的原因标签
- `outreach_plan` 的草稿消息字段

### [D14-R-024] 6.3 禁止直接进入的正式对象或字段

模型输出不得直接成为以下对象或字段的唯一依据：

- `field_lineage_record`
- `rule_gate_decision`
- `evidence_gate_decision`
- `public_chain` 法定节点判断字段
- `notice_version_chain` 决胜版本裁决字段
- `contact_target` 的合法基础字段
- 任何自然人明文联系方式字段
- 任何“已违法”“当然废标”“自动外发可用”等终局表述字段

### [D14-R-025] 6.4 输出使用限制

- 模型摘要不得替代原始证据、原始页面、原始附件或固定包。
- 模型解释不得推翻 D3 的正式规则结果、gate 结果或优先序。
- 模型建议不得绕开 D7 release gate 直接进入客户版、外发包或对外 API。
- 模型生成话术不得绕开 D9 对渠道、合法基础、频控、quiet hours 与 opt-out 的正式约束。

---

## [D14-R-026] 7. 人工复核与人机分工

### [D14-R-027] 7.1 必须人工复核的场景

以下场景一律要求人工复核，不得自动放行：

1. 输出进入 `project_fact`；
2. 输出进入 `legal_action_recommendation`；
3. 输出进入客户版报告正文或外发异议辅助包；
4. 输出影响 `saleable_opportunity` 等级、`buyer_fit` 关键标签或 `contact_target` 放行；
5. 输出涉及自然人高限制字段；
6. 输出涉及 B/C 边界升级、D 层阻断、例外放行或补证释放。

### [D14-R-028] 7.2 人机职责分工

- 模型负责：草稿、摘要、解释候选、标签候选、排序理由候选、文本润色候选。
- 人工负责：事实确认、证据确认、gate 结论确认、release 放行、对外文本最终定稿、触达与外发审批。
- 任一场景中，如果人工只做“点确认”而没有实际复核能力，则不得视为满足人工复核要求。

### [D14-R-029] 7.3 人工复核留痕

每次正式人工复核至少记录：

- `reviewer_role`
- `reviewer_id`
- `review_at`
- `review_scope`
- `accepted_output_refs`
- `rejected_output_refs`
- `modification_summary`
- `reason_code`
- `audit_ref`

---

## [D14-R-030] 8. 提示词、模板与工具调用治理

### [D14-R-031] 8.1 正式提示词模板

- 所有正式链路模型调用必须引用正式 `prompt_template_id` 与 `prompt_template_version`。
- 提示词模板必须声明：适用范围、禁止事项、输入对象白名单、输出对象白名单、风险提示、人工复核要求。
- 不允许在正式运行时使用未登记的临时提示词、聊天历史自由拼接提示词或开发者本地口头模板。

### [D14-R-032] 8.2 工具调用治理

- 模型若调用检索、规则查询、对象查询、导出建议或触达建议工具，必须通过显式工具白名单。
- 模型不得自行发起未登记的外部联网、未登记数据源读取、未登记联系人抓取或未登记导出行为。
- 工具失败、来源缺失、对象冲突、边界冲突时，模型必须降级为“无法确定 / 需人工复核”，不得编造缺失事实。

### [D14-R-033] 8.3 上下文窗口与截断策略

- 必须声明最大上下文来源数、最大附件数、最大对象数、截断策略与优先保留顺序。
- 截断不得优先保留营销文本而丢弃法律动作、gate、版本冲突或公开链关键节点信息。

---

## [D14-R-034] 9. 评测、金标与发布条件

### [D14-R-035] 9.1 正式评测维度

每个进入正式链路的模型能力至少必须有以下评测维度：

1. **边界遵守率**：是否拒绝 D 层、灰色来源与越权输出；
2. **来源忠实度**：摘要、解释、草稿是否忠于输入来源；
3. **对象落点正确率**：输出是否写入正确对象与正确字段；
4. **降级正确率**：不确定时是否正确停留在 review / block；
5. **高限制信息保护率**：是否避免泄露自然人高限制字段；
6. **中文法务表达稳定性**：是否出现夸大、终局化、误导性表达；
7. **成本与时延稳定性**：正式链路中是否满足允许阈值；
8. **回归稳定性**：新模型版本与新提示词版本是否破坏既有 goldens。

### [D14-R-036] 9.2 金标样例类型

`contracts/testing/model_golden_cases.json` 至少包含：

- 正常摘要样例
- 冲突来源降级样例
- D 层输入阻断样例
- 高限制字段脱敏样例
- 规则解释不过度升级样例
- 客户版报告草稿保守措辞样例
- 触达话术不得越权样例
- 模型拒绝无合法基础联系人使用样例

### [D14-R-037] 9.3 发布前最低条件

模型能力进入 `M3_FORMAL_CHAIN_CONSTRAINED` 前，必须同时满足：

- `model_catalog` 已登记；
- `prompt_policy_catalog` 已登记；
- 评测集与金标通过；
- `output_target_matrix` 已声明允许落点；
- D11 已纳入回归；
- D12 发布门禁允许；
- 审批链完成；
- 回滚目标版本已登记。

---

## [D14-R-038] 10. 模型 release 状态与门禁

### [D14-R-039] 10.1 release 状态

| 状态 | 正式含义 | 允许动作 |
|---|---|---|
| `DRAFT` | 草稿中，未完成评测与审批 | 仅允许内部开发测试 |
| `VALIDATING` | 正在验证 | 允许灰度内部使用，不得正式外发 |
| `INTERNAL_ONLY` | 仅内部可用 | 可用于 M0/M1，不得进入客户可见面 |
| `FORMAL_CONSTRAINED` | 正式受限可用 | 可进入受控正式对象，但必须遵守人工复核与放行条件 |
| `SUSPENDED` | 暂停使用 | 禁止新调用进入正式链路 |
| `ROLLED_BACK` | 已回滚 | 旧版本仅保留审计意义，不得继续正式使用 |
| `REVOKED` | 已撤销 | 一律禁止调用 |

### [D14-R-040] 10.2 一票阻断条件

以下任一条件成立时，模型 release 必须阻断或冻结：

1. D 层输入被读入正式链路；
2. 模型输出被发现直接充当主证；
3. 高限制字段明文泄露；
4. 模型把 CLUE / review_request 写成终局结论；
5. 模型绕开人工复核直接进入客户版或外发包；
6. 模型调用不可追溯到版本、提示词、输入快照与输出落点；
7. 关键 goldens 失效；
8. 回滚路径不存在或已损坏。

---

## [D14-R-041] 11. 运行监控、事故与回滚

### [D14-R-042] 11.1 运行监控项

模型正式运行至少监控：

- 调用量
- 成功率 / 失败率
- 平均时延 / 峰值时延
- 单次成本 / 日成本
- D 层输入拦截次数
- 高限制字段拦截次数
- 自动降级次数
- 人工复核退回率
- 输出拒绝率
- golden 漂移告警
- 提示词版本漂移告警
- 模型版本未登记调用告警

### [D14-R-043] 11.2 事故分级

| 等级 | 场景 | 最低处理要求 |
|---|---|---|
| `SEV-1` | 高限制信息泄露、正式外发越界、终局结论误放行 | 立即冻结模型、阻断外发、启动事故审计与回滚 |
| `SEV-2` | 大面积摘要失真、正式对象落点错误、gate 越权升级 | 暂停正式链路、切回人工模式、修复后重放评测 |
| `SEV-3` | 局部成本失控、时延抖动、低风险措辞漂移 | 限流、降级、修模板、补评测 |
| `SEV-4` | 统计项异常、日志缺失、非关键告警 | 修监控、补审计、纳入周度治理 |

### [D14-R-044] 11.3 回滚原则

- 回滚优先于现场修辞性热修；
- 回滚必须回到已登记的上一正式版本；
- 回滚后必须重新验证 goldens、边界阻断、高限制字段保护与人工复核链；
- 不得在无审计的情况下临时更换模型供应商、替换提示词模板或关闭边界拦截器。

---

## [D14-R-045] 12. 角色与职责

| 角色 | 正式职责 | 不得做的事 |
|---|---|---|
| `product_admin` | 冻结模型使用范围、提示词目标、业务落点 | 不得单独放行高风险模型能力 |
| `model_governance_owner` | 维护模型目录、评测、release 状态、事故治理 | 不得改写对象或规则语义 |
| `verification_analyst` | 复核模型摘要、解释、草稿与排序理由 | 不得把模型草稿直接放行为正式结论 |
| `human_reviewer` | 执行正式人工复核、对外文本定稿 | 不得跳过审计与审批 |
| `delivery_governance_user` | 审批客户版、外发包、字段释放与 release gate | 不得把模型例外永久化 |
| `sre_ops_user` | 监控、冻结、回滚、事故处置 | 不得在运行层偷偷放宽模型边界 |

---

## [D14-R-046] 13. 与 D2 / D3 / D6 / D7 / D11 / D12 / D13 的单向衔接

### [D14-R-047] 13.1 与 D2 的衔接

- 模型输出落点只能引用 D2 已冻结正式对象与字段。
- 模型不得发明新对象、新状态、新字段来承接输出。

### [D14-R-048] 13.2 与 D3 的衔接

- 模型解释不得推翻 D3 的正式规则结果与双闸门。
- 模型最多生成“解释候选”，不得直接生成正式 gate 状态。

### [D14-R-049] 13.3 与 D6 的衔接

- 模型读取与输出字段必须受 D6 字段分类、脱敏与审批链约束。
- 高限制字段默认遮罩或阻断。

### [D14-R-050] 13.4 与 D7 的衔接

- 模型输出进入客户版、外发包或对外 API 前，必须满足 D7 的对象级交付矩阵与 release gate。

### [D14-R-051] 13.5 与 D11 的衔接

- 任何模型能力升级、提示词版本变更、供应商切换、输出落点扩展，必须触发 D11 回归。

### [D14-R-052] 13.6 与 D12 的衔接

- 模型 release 只能通过 D12 的正式发布与回滚流程进入运行态。

### [D14-R-053] 13.7 与 D13 的衔接

- 模型不得扩大 D13 的 A/B/C/D 能力边界。
- 对 B/C 层能力，模型只能在对应治理前提与公开颗粒度前提下工作；对 D 层能力，一律不得进入正式公开主链。

---

## [D14-R-054] 14. 机器承接与实现纪律

- `contracts/model/model_catalog.json` 是正式模型目录；每个正式模型能力都必须有唯一登记项。
- `contracts/model/model_usage_policy.json` 负责声明使用层级、输入边界、输出落点、人工复核要求。
- `contracts/model/prompt_policy_catalog.json` 负责登记提示词模板、版本、禁止事项与上下文策略。
- `contracts/model/model_release_gates.json` 负责模型 release 状态、阻断条件、回滚规则。
- `contracts/model/eval_suite_catalog.json` 负责评测集、指标、阈值与 goldens 绑定关系。
- `contracts/model/output_target_matrix.json` 负责模型输出可进入的正式对象 / 字段白名单。
- `contracts/testing/model_golden_cases.json` 负责模型金标与越界阻断样例。
- `control/model_registry.yaml` 与 `control/model_release_manifest.yaml` 负责运行态清单与当前放行版本。

任何模型相关实现若无法同时映射到上述机器资产与本文正式条目，不得进入正式链路。

### [D14-R-054A] 14.1 资产角色与当前限制

- 模型目录与 release gate 只冻结“使用边界与治理门禁”，不冻结具体供应商；
- `model_usage_policy` 与 `output_target_matrix` 必须明确“允许用途 / 禁止用途 / review required / 外部阻断”；
- 当前模型调用仅允许 internal assist / review assist，不得直接进入正式外发、正式触达或正式交付对象。

---

## [D14-R-055] 15. 完成定义（Definition of Done）

D14 相关能力只有同时满足以下条件，才算正式完成：

1. 模型使用范围、输入边界、输出落点已冻结；
2. `model_governance_record` 已纳入 D2 正式对象体系；
3. 提示词模板、评测集、输出白名单与 release gate 已机器化；
4. 人工复核、审批链、字段治理、交付矩阵与运行回滚链已打通；
5. D11 已纳入模型 goldens、边界样本与阻断样本；
6. D12 已纳入模型发布、冻结、回滚与事故治理；
7. 没有使用 D 层输入或高限制字段越界放行；
8. 不存在未登记模型版本、未登记提示词版本或不可追溯正式调用；
9. 对外表述未把模型能力包装成终局裁决；
10. 变更记录、审批记录与审计链完整可追。

少任一项，只能视为内部试运行或部分完成，不得宣称模型治理已封板。

---

## [D14-R-056] 16. 禁止事项总表

AI / 模型治理一律不得：

- 替代正式项目归一、正式双闸门或正式 release gate；
- 把模型摘要当主证；
- 把模型解释当正式规则结论；
- 把 CLUE、OBSERVATION、review_request 写成终局裁决；
- 直接生成或放行自然人高限制联系对象；
- 读取 D 层、灰色、不可审计或未审批输入；
- 使用未登记模型、未登记提示词、未登记评测集进入正式链路；
- 绕开人工复核直接进入客户版、外发包或正式触达；
- 在运行层偷偷放宽模型边界；
- 以“模型效果更好”为由突破 L0、D13、D6、D7、D11、D12 已冻结红线。


## 枚举冻结补表补充稿（C组）

| enum_name | doc_home | owning_objects | proposed_values | source_refs | confidence | requires_manual_confirmation | semantic_notes |
|---|---|---|---|---|---|---|---|
| `model_usage_scope` | D14 | `model_governance_record` | `INTERNAL_ASSIST / REVIEW_ASSIST / CLIENT_DELIVERY_ASSIST / EXTERNAL_ACTION_ASSIST` | `D14-R-015` | HIGH | NO | `C组冻结确认；声明模型允许使用范围` |

### [D14-R-055-A] C 组治理枚举补强补表（本轮）

#### D14-C1 `model_usage_scope` 允许/禁止动作与外发建议

| scope | 允许动作 | 禁止动作 | 外发建议 | 关联 release_status | 关联 usable_scope |
|---|---|---|---|---|---|
| `INTERNAL_ASSIST` | 辅助抽取/归因/排序 | 任何交付或外发 | 不允许 | `INTERNAL_ONLY / REVIEW_ONLY` | 不提升可用范围 |
| `REVIEW_ASSIST` | 复核辅助、生成 review_request | 直接进入线索包 | 不允许 | `REVIEW_ONLY` | `REVIEW_ONLY / GOVERNANCE_ONLY` |
| `CLIENT_DELIVERY_ASSIST` | 交付摘要/参考文本 | 直接决定交付 | 仅参考 | `RELEASED` | `DELIVERY_REFERENCE` |
| `EXTERNAL_ACTION_ASSIST` | 内部动作建议 | 自动触达/外部执行 | 仅在审批后作为建议 | `RELEASED` | 不得放宽 |

#### D14-C2 典型业务案例

- `MODEL-SCOPE-01`：内部运营看板使用 `INTERNAL_ASSIST` 生成线索归因提示，仅内部可见。
- `MODEL-SCOPE-02`：合规复核使用 `REVIEW_ASSIST` 生成 review_request，未审批不得进入交付。
- `MODEL-SCOPE-03`：线索包摘要使用 `CLIENT_DELIVERY_ASSIST`，仅摘要引用且需脱敏与审计。

---

## 附录：内部运营模型治理补表（新增）

本补表用于将模型治理口径对齐内部线索运营平台，不改写正文既有裁决。

### D14-A 模型作用边界

- 模型不得直接决定外发线索包是否可交付；
- 模型仅允许：辅助抽取、辅助归因、辅助排序、辅助建议。

### D14-B 线索包进入条件

- 进入线索包必须具备 `evidence`、`review`、`gate`，必要时需审批；
- 模型输出只能作为辅助信息，不得替代正式证据链与审计链。

---

## 附录：外部系统与模型接入边界冻结补表（新增）

本补表用于冻结外部系统接入与大模型辅助接入的阶段边界，不改写正文既有模型治理裁决。

### [D14-R-056-B] 阶段 1-9 模型辅助签字矩阵

| 阶段 | 模型辅助 | 工具辅助 | 允许用途 | 必须人工签字 | 禁止作为最终判断 |
|---|---|---|---|---|---|
| Stage 1 | 可选预留，非硬依赖 | 默认关闭 | 路由说明草稿、补充查询建议 | 仅当输出进入正式 review 记录时 | 不得用于主采集判断、主来源裁决 |
| Stage 2 | 可选预留，非硬依赖 | 默认关闭 | 采集异常说明草稿、补抓建议 | 仅当输出进入正式 review 记录时 | 不得用于主采集判断、主链覆盖结论 |
| Stage 3 | 允许 | 允许 | 抽取候选、字段归一建议、冲突解释、结构化候选补全建议 | 必须 | 不得做最终归一裁决、最终冲突消解裁决 |
| Stage 4 | 允许 | 允许 | 核验解释、补证建议、review assist | 必须 | 不得做 `verification_state` 最终裁决、最终核验证据通过/不通过裁决 |
| Stage 5 | 允许 | 允许 | 证据摘要、规则命中解释、review assist、证据链说明草稿 | 必须 | 不得做 `rule_gate_decision`、`evidence_gate_decision`、正式 gate 放行结论 |
| Stage 6 | 允许 | 允许 | 报告草稿、复核草稿、风险摘要、解释型摘要、review queue 辅助说明 | 必须 | 不得做正式报告通过裁决、正式 `project_fact` 入链裁决 |
| Stage 7 | 允许 | 允许 | `buyer_fit` 标签建议、排序理由、机会说明、推荐理由草稿、商业摘要 | 必须 | 不得单独决定 `saleable_opportunity` 成立与否，不得单独决定最终推荐 |
| Stage 8 | 允许 | 允许 | 触达文案草稿、跟进建议、next-step 建议、触达策略说明、review assist | 必须 | 不得做 `contact_target` 放行裁决，不得做 legal basis/channel/frequency/quiet hours/opt-out 最终判定 |
| Stage 9 | 允许 | 允许 | 结果摘要、异常说明、治理反馈摘要、交付说明草稿 | 必须 | 不得做 `order/payment/delivery` 正式状态裁决，不得做 outcome/governance feedback 最终写回裁决 |

补充说明：

- Stage 1-2 的模型辅助只允许作为预留能力，不得成为正式主链硬依赖。
- Stage 3-9 的模型输出一律只能作为 `assist / draft / review assist`，不得替代人工签字、正式 gate、审批链或审计链。
- “必须人工签字”在当前阶段至少意味着：输出进入正式对象前必须保留人工复核与审计留痕。

### [D14-R-056-C] `MODEL_PROVIDER` / `TOOL_PROVIDER` 角色冻结

| 角色 | 正式含义 | 当前冻结口径 | 当前禁止事项 |
|---|---|---|---|
| `MODEL_PROVIDER` | 提供通用大模型推理能力的供应方 | 当前只冻结 provider 角色、适用范围、评测门禁与审计要求；不绑定具体厂商 | 不得被写成正式最终判断者，不得被写成当前强依赖基础设施 |
| `TOOL_PROVIDER` | 被模型借助的外部工具或查询 provider | 当前只冻结 tool/provider 角色、允许阶段、trace 要求与 review 边界；不绑定具体厂商 | 不得绕过 D13 / D9 / D7 / D11 直接写入正式主结论，不得发起未登记联网与未登记联系人抓取 |

补充说明：

- `MODEL_PROVIDER` 与 `TOOL_PROVIDER` 是 provider 分层，不得与 `PUBLIC_OFFICIAL_SOURCE`、`THIRD_PARTY_SUPPORT_SOURCE`、`CONTACT_ENRICHMENT_SOURCE`、`EXECUTION_VENDOR` 混用。
- 任何 provider 变更、fallback 切换或 tool 路由扩展，都必须先过 D14 / D11 / D12 约束，不得在实现层静默替换。

### [D14-R-056-D] 统一 provider / adapter / trace 语义预留

| 语义项 | 当前正式要求 | 说明 |
|---|---|---|
| `model_provider_adapter` | 必须预留 | 统一承接模型供应方接入，不代表当前已接真实 provider |
| `tool_provider_adapter` | 必须预留 | 统一承接模型借助工具的 provider 路由 |
| `provider_id` / `provider_type` / `provider_role` | 必须预留 | 统一标识模型或工具 provider 身份 |
| `provider_trace_id` | 必须预留 | 统一承接 provider 级调用追溯 |
| `query_trace_id` | 必须预留 | 模型借助检索/查询工具时必须留痕 |
| `source_audit_ref` | 必须预留 | 工具读取外部来源时必须能回指审计来源 |
| `fallback_provider_id` | 必须预留 | 当前只允许预留 fallback 语义，不代表当前启用自动切换 |
| `requires_manual_review` | 必须预留 | provider/tool 输出只要影响正式链路，必须可标记人工复核 |

### [D14-R-056-E] 当前不绑定具体模型供应商口径

- 当前签死的是：阶段边界、允许用途、禁止用途、adapter 语义、trace / audit 语义、review / signoff 责任。
- 当前不签死的是：具体模型供应商、具体模型型号、具体工具供应商、具体联网检索供应商、是否上线即强依赖模型。
- 后续若进入模型/vendor 预对齐，只允许在不改写本补表边界的前提下补 registry / eval / release gate，不得反向放宽最终判断禁令。

### 统一 capability_mode 与 model/tool/provider 收口补表（本轮）

本补表用于把 model provider、tool provider、model release 与 Stage 8/9 运行执行统一到 `capability_mode` 语义；不改写既有 `M0~M4`、`release_state` 或 `release_layer`。

当前 capability_mode 统一词表为：
`PERMANENTLY_BLOCKED / BUILDABLE_BUT_OFF_BY_DEFAULT / INTERNAL_ONLY / INTERNAL_GOVERNED / APPROVAL_REQUIRED / SHADOW_MODE / DRY_RUN / REAL_RUN_READY / EMERGENCY_OFF`

| 对象/能力族 | 当前 capability_mode | 允许 capability_mode | 与 release_state / release_layer 的关系 |
|---|---|---|---|
| `MODEL_PROVIDER` | `BUILDABLE_BUT_OFF_BY_DEFAULT` | `BUILDABLE_BUT_OFF_BY_DEFAULT / INTERNAL_ONLY / SHADOW_MODE / INTERNAL_GOVERNED / EMERGENCY_OFF` | 只表示 provider 运行态，不替代 `INTERNAL_ONLY / FORMAL_CONSTRAINED` 等 release_state |
| fallback `MODEL_PROVIDER` | `BUILDABLE_BUT_OFF_BY_DEFAULT` | `BUILDABLE_BUT_OFF_BY_DEFAULT / SHADOW_MODE / EMERGENCY_OFF` | fallback 仍不得静默接管正式链路 |
| `TOOL_PROVIDER` | `SHADOW_MODE` | `BUILDABLE_BUT_OFF_BY_DEFAULT / SHADOW_MODE / INTERNAL_GOVERNED / EMERGENCY_OFF` | 默认只允许旁路辅助、比对与查询支持 |
| model-assisted Stage 8 execution | `APPROVAL_REQUIRED` | `SHADOW_MODE / DRY_RUN / APPROVAL_REQUIRED / EMERGENCY_OFF` | 不得把 capability_mode 当成 legal basis / channel / quiet hours 的最终裁决 |
| model-assisted Stage 9 execution | `SHADOW_MODE` | `BUILDABLE_BUT_OFF_BY_DEFAULT / SHADOW_MODE / DRY_RUN / APPROVAL_REQUIRED / EMERGENCY_OFF` | 不得把 capability_mode 当成 payment / delivery 最终裁决 |

补充说明：

- `M0~M4` 继续回答“模型治理层级”，`capability_mode` 只回答“当前运行态开关”；
- `REAL_RUN_READY` 对 model/tool provider 默认不直接赋值；只有未来绑定真实 provider 且通过 release gate 后才允许出现；
- `EMERGENCY_OFF` 一旦生效，优先于普通 provider / tool provider capability_mode。

### provider / tool capability resolver 补表（本轮）

- model/tool/provider 的 `capability_mode` 不得只停留在 registry 或 release manifest；任何进入正式链路的 provider/tool 路由前，必须先经统一 resolver 判定。
- resolver 对 provider/tool 至少必须输出：`capability_mode / decision / review_required / blocked_reason / provider trace metadata`。
- `MODEL_PROVIDER` / `TOOL_PROVIDER` 即使未来进入 `REAL_RUN_READY`，也不得覆盖 `EXTERNAL_BLOCKED` 或人工复核红线。
- `EMERGENCY_OFF / PERMANENTLY_BLOCKED` 一旦命中 model/tool/provider family，必须短路，不得继续进入下游 assist / query / writeback path。

## [D14-R-056-F] 附：model/tool capability canonical source 补表（本轮新增）

本补表用于明确 model/tool/provider 的 capability 词表与 family current mode 来源；不改写既有 `M0~M4` 或 provider externalization 红线。

| 语义项 | 当前唯一正式来源 | projection-only 面 |
|---|---|---|
| model/tool `capability_mode` 词表 | `contracts/release/runtime_policy_catalog.json#capability_mode_vocabulary` | `control/model_release_manifest.yaml` |
| `MODEL_PROVIDER` / `TOOL_PROVIDER` family current mode | `contracts/release/runtime_policy_catalog.json#capability_families` | `control/model_release_manifest.yaml` 只允许 projected state |
| capability priority order / protected short-circuit / `EXTERNAL_BLOCKED` redline relation | `contracts/release/runtime_policy_catalog.json#capability_mode_priority_order`、`contracts/release/runtime_policy_catalog.json#runtime_resolver_precedence` | `control/model_release_manifest.yaml`、`control/release_manifest.yaml` 只允许 projected refs/status |
| provider externalization prerequisite / decision | `contracts/release/external_unlock_prerequisite_matrix.json`、`contracts/release/future_unlock_decision_matrix.json` | `control/model_release_manifest.yaml`、`control/future_unlock_decision_state.yaml` |

补充约束：
- `control/model_release_manifest.yaml` 只能投影 provider/runtime current state、repo readiness 与 signoff 状态，不得再成为 provider capability mode 的判定义源；
- model/tool/provider runtime resolver precedence 一律以 `contracts/release/runtime_policy_catalog.json#runtime_resolver_precedence` 为准：`runtime_override -> target_policy_current_capability_mode -> target_registry_current_capability_mode -> family_current_capability_mode`。
- `EMERGENCY_OFF`、`PERMANENTLY_BLOCKED` 的 protected short-circuit 与 `REAL_RUN_READY` 不得覆盖 `EXTERNAL_BLOCKED` redline，均以 `runtime_policy_catalog.json` 为准。

### [D14-R-044-A] future externalization prerequisite 补表（本轮新增）

| 能力域 | 当前默认口径 | R6 decision | prerequisite baseline | post-R6 推荐下一阶段 |
|---|---|---|---|---|
| `model_provider_externalized_usage` | buildable but off by default | `DENY_BY_DEFAULT_CONTINUE` | external shadow / boundary / canary eval、owner signoff、output target matrix、rollback/emergency off | `shadow/canary design only` |
| `tool_provider_externalized_usage` | shadow only | `LONG_TERM_BLOCKED_OR_NEVER_DEFAULT_OPEN` | boundary eval、audit trace、owner signoff；仍不得 default-open | `no unlock path recommended` |

补充说明：
- 本补表只定义 future externalization prerequisite，不代表 provider 已 externalized；
- model/tool provider externalization 仍不得替代 `EXTERNAL_BLOCKED`、human review 或 output target matrix；
- `DENY_BY_DEFAULT_CONTINUE` 表示可保留 prerequisite 与 eval 体系，但当前不进入 implementation 候选；
- `LONG_TERM_BLOCKED_OR_NEVER_DEFAULT_OPEN` 表示即使保留 shadow 能力，也不建议进入近期 unlock 序列；
- 缺 eval suite、缺 signoff、缺 rollback/emergency-off 任一项时，future externalization discussion 必须失败。

## 附：B9 model/tool provider registry and usage policy 补表（本轮新增）

本补表用于冻结 B9-S1 model/tool provider registry 与 usage policy 的 adapter-ready 边界；不改写既有 `M0~M4`、人工复核、release gate 或 externalization 红线。

| 资产 | 当前冻结内容 | 当前允许 | 当前禁止 |
|---|---|---|---|
| `contracts/model/model_usage_policy.json` | stage boundary、allowed/blocked action intents、final decision prohibited、assist/shadow 用法 | `PREVIEW_ONLY`、`INTERNAL_SOURCE_READ`、internal assist、review assist、structured assist、shadow evaluation | `APPROVAL_EXECUTION`、`INTERNAL_WRITEBACK`、`LIVE_EXECUTION`、模型最终裁决 |
| `contracts/model/tool_provider_registry_catalog.json` | registered-not-bound tool provider 角色、current capability mode、trace 与 no-live 默认值 | support tool registry、internal governed query、shadow support | direct mutation、external action、live execution、default-open |
| `contracts/model/tool_usage_policy_catalog.json` | tool provider 使用策略与 canonical capability mode ref | support-only / review-only / traceable lookup | formal gate decision、formal contact release decision、channel policy override |
| `control/model_release_manifest.yaml` | provider/runtime 状态投影 | status mirror、trace inventory、future prerequisite refs | capability mode 判定义源、provider externalization approval、live provider binding |

补充说明：

- B9-S1 不绑定具体模型供应商、工具供应商或联网检索供应商；
- model/tool provider 当前只允许 internal assist / review assist / structured assist / shadow，不得替代人工签字、正式 gate、审批链或审计链；
- tool provider externalized usage 继续保持 `LONG_TERM_BLOCKED_OR_NEVER_DEFAULT_OPEN`，不得因 registry 存在而进入 default-open 路径。

## 附：PTL-I100-OPEN-CAPABILITY-BASELINE 能力开放基线补表

本补表只同步 AI/模型治理开放口径，不新增模型供应商、模型 gate 或模型 release。

| 项 | D14 承接口径 |
|---|---|
| policy ref | `control/product_task_library.yaml#open_capability_policy` / `PTL-I100-OPEN-CAPABILITY-BASELINE` |
| AI 作用边界 | AI 只能辅助解析、摘要、分类、draft、review assist 和运营提示；不得把模型判断直接变成客户结论、事实结论、触达结论或支付/交付结论。 |
| `blocked-by-default` | 模型/工具能力 blocked-by-default 只表示 provider config、sandbox、approval、audit、operator action、field allowlist/masking、dedicated current_task、模型评测和验收未满足前不能 live，不表示永久不做。 |
| 人工复核 | 涉及客户可见结论、外发、触达、支付、交付、高限制字段或法律动作建议时，模型输出必须经人工复核与审计链。 |
| 自动退款边界 | 自动退款执行 excluded；模型不得触发退款，只能辅助 `manual exception` / 人工异常记录、manual approval/audit 和 governed review。 |
