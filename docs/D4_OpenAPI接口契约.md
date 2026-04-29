# D4 OpenAPI接口契约

- **文档名称**：D4 OpenAPI接口契约
- **文档 ID**：CE-D4-API-CN
- **状态**：DRAFT
- **基线层级**：L1 配套正式文档 / D4
- **定位**：冻结  正式接口目录、资源分组、请求与响应封套、角色权限、错误码、保留态接口、审批阻断与机器承接规则
- **适用范围**：中国公开证据边界下的建设工程域内部运营接口消费面（含线索包交付接口）
- **上位依据**：`L0.md`
- **配套依据**：`D2_正式对象契约与字段字典.md`、`D3_正式规则码总表与判定说明书.md`、`D13_公开可查边界能力清单.md`
- **机器承接**：`contracts/api/api_catalog.json`、`contracts/api/error_code_catalog.json`、`contracts/api/permission_matrix.json`
- **目标读者**：产品、架构、后端、前端、测试、人工复核、交付、治理、AI / Codex 执行代理
- **生效说明**：本文只展开正式接口消费面，不改写 L0 对九阶段主链、正式对象、统一事实中枢、公开边界、双闸门、字段治理、交付矩阵与对外交付受控开放边界的定义

---

## [D4-R-001] 0. 文档任务与裁决范围

本文档不是“接口草表”，也不是前后端联调时临时补出来的 URL 清单。
本文档的正式任务是：

1. 冻结  的正式接口目录与资源分组；
2. 冻结接口层的正式消费优先级，防止接口绕开 `project_fact`、`legal_action_recommendation` 与正式 gate 对象重算主结论；
3. 冻结请求封套、响应封套、分页、过滤、排序、错误码与阻断行为；
4. 冻结角色、权限、字段可见范围与高限制对象的接口暴露规则；
5. 冻结 D8 / D9 / D10 尚未正式放行前的保留态接口路径与阻断口径；
6. 冻结导出、审批、release gate、受控例外与治理类接口的正式入口；
7. 冻结机器承接要求，确保 `contracts/api/*` 与本文保持单一口径；
8. 冻结 D11 回归与接口验收要求，保证接口不是“写了路径就算生效”，而是可校验、可回归、可审计的正式消费面。

本文档必须回答以下问题：

- 哪些资源允许形成正式接口；
- 哪些对象只能作为内部解释层接口返回，不能成为外发线索包主判断；
- 哪些资源属于保留态路径，虽然可以冻结路径，但当前不得放行为正式执行面；
- 哪些错误必须阻断，哪些错误只允许进入复核或审批；
- 哪些角色可以看哪些对象、做哪些动作、导出哪些内容；
- 导出、审批、治理、例外与高限制对象如何在接口层被显式控制；
- 接口层如何与 D2、D3、D5、D6、D7、D11 一一承接。

本文档不直接展开以下内容：

- 页面布局、组件层级与按钮文案，由 D5 承接；
- 字段白名单、脱敏规则、审批链与线索包外发层级，由 D6 承接；
- 对象级交付矩阵与 release gate，由 D7 承接；
- 商业对象、触达对象、订单交付对象的最终放行规则，由 D8 / D9 / D10 承接；
- 测试、金标、发布前检查，由 D11 承接。

---

## [D4-R-002] 1. 生效规则与优先级

### [D4-R-003] 1.1 生效规则

- 本文是 L0 在“正式接口与消费面”维度的正式展开文档。
- 本文只允许细化 L0、D2、D3、D13 已冻结的对象、结果语义、边界与消费优先级，不允许新增会改变主路线、对象边界、公开边界或交付边界的新裁决。
- 本文与 L0 冲突时，以 L0 为准。
- 本文与 D2 冲突时，以 D2 的正式对象定义与字段命名为准。
- 本文与 D3 冲突时，以 D3 的结果语义、双闸门与优先序为准。
- 本文与 D6 / D7 冲突时，以更严格的字段治理与交付限制为准。
- 页面、后端、导出服务、脚本、联调 Mock、销售演示接口与临时调试端点，都不得反向定义正式接口口径。

### [D4-R-004] 1.2 接口优先级

| 优先级 | 文档或资产 | 裁决范围 |
|---|---|---|
| P1 | L0 权威总文档 | 主链、对象、统一事实中枢、公开边界、对外受控开放边界 |
| P2 | D2 / D3 / D13 | 正式对象、结果语义、双闸门、公开边界 |
| P3 | 本文 D4 | 接口目录、路径、方法、封套、权限、错误码、保留态接口 |
| P4 | D5 / D6 / D7 / D11 | 页面消费、字段策略、交付矩阵、测试验收 |
| P5 | `contracts/api/*` | OpenAPI 机器承接、权限矩阵、错误码目录 |
| P6 | 局部设计、联调说明、Postman、Mock Server | 不得突破上位口径 |

### [D4-R-005] 1.3 接口层不得改写的上位事项

接口层不得改写以下上位事项：

- `project_fact` 是唯一正式统一事实中枢；
- `legal_action_recommendation` 是正式动作建议对象；
- `rule_gate_decision` 与 `evidence_gate_decision` 缺一不可；
- `saleable_opportunity` 不得由单条规则、单页公告或销售备注直接生成；
- `contact_target` 只能来源于合规联系来源；
- D 层输入不得进入正式公开主模型；
- 字段级外发、脱敏与审批必须受 D6 / D7 限制，接口层不得擅自放宽。

---

## [D4-R-006] 2. 接口总原则

### [D4-R-007] 2.1 单向消费原则

 接口层必须遵守以下正式消费顺序：

`project_fact / legal_action_recommendation / report_record`
→ `rule_gate_decision / evidence_gate_decision / review_request`
→ `field_lineage_record / notice_version_chain / clock_chain_profile`
→ `project_base / public_chain / 核验画像对象`
→ `private_supplement_record / controlled_exception_record / 备注与说明对象`

因此：

- 一切顶层项目结论接口必须优先返回 `project_fact` 与 `legal_action_recommendation`，不得从 `rule_hit`、原始公告、字段 lineage 或 CRM 备注重算主判断；
- 中间解释对象可以作为 explainer surface 返回，但不得被包装成线索包顶层主结论；
- 导出、审批、交付与治理接口只能消费正式对象与正式 gate，不得直接消费临时结构；
- 外发线索包接口只能投影正式白名单对象与白名单字段，不得把内部解释对象原样透出。

### [D4-R-008] 2.2 资源对象化原则

- 正式接口必须以正式对象为中心进行资源分组；
- 接口路径应体现对象职责，而不是前端页面结构；
- 一个正式资源只允许有一套正式命名，不得同时存在多个同义路径；
- 顶层资源必须能映射到 D2 的正式对象；
- 任何无法回指正式对象的路径，都不得进入正式接口目录。

### [D4-R-009] 2.3 保留态原则

- D8 / D9 / D10 对应的商业对象、触达对象、订单交付对象接口，可以冻结路径，但必须显式标注为保留态；
- 保留态接口的存在只为冻结未来命名、资源边界与权限矩阵，不等于当前已允许上线；
- 保留态接口必须返回统一阻断错误码，不得假装成功或返回临时数据；
- 前端、脚本、演示版不得因为路径存在就将其当作已生效能力。

### [D4-R-010] 2.4 最小封套原则

所有正式接口都必须采用统一响应封套，禁止顶层随意扩字段。

正常响应最小结构：

```json
{
  "request_id": "req-20260412-001",
  "snapshot_at": "2026-04-12T10:00:00+08:00",
  "data": {}
}
```

可选扩展字段只允许出现在：

- `included`
- `warnings`
- `policy_tags`
- `paging`
- `meta`

错误响应最小结构：

```json
{
  "error_code": "GATE-409-DUAL_GATE_BLOCKED",
  "http_status": 409,
  "message": "Current request is blocked by gate policy.",
  "blocking_l0_ref_optional": "L0-R-005",
  "next_action_optional": "Route to review queue."
}
```

### [D4-R-011] 2.5 正式方法语义

| HTTP 方法 | 正式语义 | 使用边界 |
|---|---|---|
| `GET` | 查询、读取、列表、详情、状态 | 不得产生副作用 |
| `POST` | 创建任务、触发重建、申请导出、提交审批、生成记录 | 仅用于显式动作，不得伪装成查询 |
| `PATCH` | 对正式对象状态做受控更新 | 仅用于已声明可修改的字段 |
| `PUT` | 替换固定配置对象 | 仅用于治理配置类资源 |
| `DELETE` | 逻辑移除、撤销、作废 | 仅在 L0 / 下位文档允许时使用 |

接口层不得使用方法偷换语义。例如：

- 不得用 `GET` 触发重跑；
- 不得用 `POST` 查询列表；
- 不得用 `PATCH` 隐式放宽字段可见性；
- 不得用 `PUT` 批量重算主结论。

---

## [D4-R-012] 3. 接口分组与正式目录

### [D4-R-013] 3.1 接口分组总表

| 接口组 | 主资源 | 正式定位 | 当前状态 |
|---|---|---|---|
| 任务编排接口组 | `task_record`、`execution_context` | 阶段 1 入口与重建控制面 | development_open |
| 项目与统一事实接口组 | `project_base`、`project_fact`、`legal_action_recommendation` | 项目列表、项目详情、统一事实、动作建议 | internal_only |
| 公开链与追溯接口组 | `public_chain`、`clock_chain_profile`、`notice_version_chain`、`field_lineage_record` | 公开链核验、版本链、时钟链、字段追溯 | internal_only |
| 规则与证据接口组 | `rule_hit`、`evidence`、`rule_gate_decision`、`evidence_gate_decision`、`review_request` | 规则解释、证据与复核入口 | internal_only |
| 报告与复核接口组 | `report_record`、`review_queue_profile`、`private_supplement_record` | 报告、复核、补证、导出申请 | internal_only |
| 内部销售接口组 | `challenger_candidate_profile`、`legal_action_actor_profile`、`procurement_decision_actor_profile`、`saleable_opportunity` | 竞争驱动机会与 actor 资源 | external_delivery_blocked |
| 内部触达接口组 | `contact_target`、`outreach_plan`、`touch_record` | 合规触达准备与触达留痕 | external_delivery_blocked |
| 线索包交付与回写接口组 | `order_record`、`payment_record`、`delivery_record`、`opportunity_outcome_event` | 内部交付预览、支付草案、交付回写与结果写回 | external_delivery_blocked |
| 治理与例外接口组 | `coverage_registry`、`delivery_matrix`、`controlled_exception_record`、`governance_feedback_event` | coverage、release、例外、治理反馈 | internal_only |

### [D4-R-014] 3.2 最小正式接口目录

#### [D4-R-015] 3.2.1 任务编排接口组

| 方法 | 路径 | operationId | 说明 |
|---|---|---|---|
| `POST` | `/tasks` | `createTask` | 创建正式任务 |
| `GET` | `/tasks` | `listTasks` | 查看任务列表 |
| `GET` | `/tasks/{task_id}` | `getTask` | 查看任务详情 |
| `POST` | `/tasks/{task_id}/cancel` | `cancelTask` | 取消未完成任务 |
| `POST` | `/projects/{project_id}/rebuild` | `rebuildProjectFact` | 触发统一事实重建 |

#### [D4-R-016] 3.2.2 项目与统一事实接口组

| 方法 | 路径 | operationId | 说明 |
|---|---|---|---|
| `GET` | `/projects` | `listProjects` | 项目列表 |
| `GET` | `/projects/{project_id}` | `getProject` | 项目详情 |
| `GET` | `/projects/{project_id}/facts` | `getProjectFact` | 查询统一事实中枢 |
| `GET` | `/projects/{project_id}/legal-actions` | `getLegalActionRecommendation` | 查询正式动作建议 |
| `GET` | `/projects/{project_id}/summary` | `getProjectSummary` | 查询正式摘要投影 |

#### [D4-R-017] 3.2.3 公开链与追溯接口组

| 方法 | 路径 | operationId | 说明 |
|---|---|---|---|
| `GET` | `/projects/{project_id}/public-chain` | `getPublicChain` | 查询公开链 |
| `GET` | `/projects/{project_id}/clock-chain` | `getClockChainProfile` | 查询多时钟链 |
| `GET` | `/projects/{project_id}/version-chain` | `getNoticeVersionChain` | 查询多版本链 |
| `GET` | `/projects/{project_id}/field-lineage` | `listFieldLineage` | 查询字段级来源 |
| `GET` | `/projects/{project_id}/attack-surface` | `getPublicAttackSurface` | 查询公开攻击面 |

#### [D4-R-018] 3.2.4 规则与证据接口组

| 方法 | 路径 | operationId | 说明 |
|---|---|---|---|
| `GET` | `/projects/{project_id}/rule-hits` | `listRuleHits` | 查询规则命中 |
| `GET` | `/projects/{project_id}/evidence` | `listEvidence` | 查询证据集合 |
| `GET` | `/projects/{project_id}/rule-gates` | `getRuleGateDecision` | 查询规则闸门 |
| `GET` | `/projects/{project_id}/evidence-gates` | `getEvidenceGateDecision` | 查询证据闸门 |
| `GET` | `/projects/{project_id}/review-requests` | `listReviewRequests` | 查询复核请求 |

#### [D4-R-019] 3.2.5 报告与复核接口组

| 方法 | 路径 | operationId | 说明 |
|---|---|---|---|
| `GET` | `/projects/{project_id}/report-record` | `getReportRecord` | 查询报告记录 |
| `GET` | `/projects/{project_id}/review-queue` | `getReviewQueueProfile` | 查询复核队列 |
| `GET` | `/projects/{project_id}/private-supplements` | `listPrivateSupplementMetadata` | 只返回元数据，不返回正文 |
| `POST` | `/reports/{report_id}/export` | `requestReportExport` | 发起导出申请 |
| `POST` | `/reports/{report_id}/submit-review` | `submitReportForReview` | 提交复核 |

#### [D4-R-020] 3.2.6 内部销售接口组（外发阻断）

| 方法 | 路径 | operationId | 状态 | 说明 |
|---|---|---|---|---|
| `GET` | `/projects/{project_id}/challenger-candidates` | `listChallengerCandidates` | external_delivery_blocked | 冻结路径，不放行对外交付 |
| `GET` | `/projects/{project_id}/actors` | `listProjectActors` | external_delivery_blocked | 冻结法律行动主体与采购决策主体路径 |
| `GET` | `/saleable-opportunities` | `listSaleableOpportunities` | external_delivery_blocked | 冻结正式机会池路径 |
| `POST` | `/saleable-opportunities/{opportunity_id}/refresh` | `refreshSaleableOpportunity` | external_delivery_blocked | 冻结刷新动作 |

#### [D4-R-021] 3.2.7 内部触达接口组（外发阻断）

| 方法 | 路径 | operationId | 状态 | 说明 |
|---|---|---|---|---|
| `GET` | `/contact-targets` | `listContactTargets` | external_delivery_blocked | 冻结联系对象路径 |
| `POST` | `/contact-targets/compliance-check` | `checkContactCompliance` | external_delivery_blocked | 内部合规校验，直接返回 `semantic_envelope.surface_state` 与 canonical reason |
| `POST` | `/outreach-plans` | `createOutreachPlan` | external_delivery_blocked | 冻结触达方案路径 |
| `POST` | `/touch-records` | `createTouchRecord` | external_delivery_blocked | 冻结触达留痕路径 |

#### [D4-R-022] 3.2.8 线索包交付与回写接口组（外发阻断）

| 方法 | 路径 | operationId | 状态 | 说明 |
|---|---|---|---|---|
| `GET` | `/orders` | `listOrders` | external_delivery_blocked | internal preview / draft 仅返回状态摘要 |
| `POST` | `/orders` | `createOrder` | external_delivery_blocked | internal preview / draft；未通过审批链/审计返回 BLOCK/REVIEW_REQUIRED |
| `POST` | `/payments` | `createPaymentRecord` | external_delivery_blocked | internal preview / draft；支付凭证缺失需阻断 |
| `POST` | `/deliveries` | `createDeliveryRecord` | external_delivery_blocked | internal preview / draft；release gate 未通过返回 BLOCK |
| `GET` | `/projects/{project_id}/opportunity-outcomes` | `listOpportunityOutcomes` | external_delivery_blocked | 仅内部回写查询；外发阻断 |
| `POST` | `/opportunity-outcomes` | `createOpportunityOutcomeEvent` | external_delivery_blocked | 结果回写入口；internal only |

#### [D4-R-023] 3.2.9 治理与例外接口组

| 方法 | 路径 | operationId | 状态 | 说明 |
|---|---|---|---|---|
| `GET` | `/coverage-status` | `getCoverageStatus` | internal_only | 查询 coverage 状态 |
| `GET` | `/delivery-matrix` | `getDeliveryMatrix` | internal_only | 查询交付矩阵 |
| `GET` | `/projects/{project_id}/exceptions` | `listProjectExceptions` | internal_only | 查询受控例外元数据 |
| `POST` | `/exception-records` | `createExceptionRecord` | internal_only | 创建受控例外 |
| `GET` | `/governance-feedback-events` | `listGovernanceFeedbackEvents` | internal_only | 治理反馈列表（仅内部） |
| `POST` | `/governance-feedback-events` | `createGovernanceFeedbackEvent` | internal_only | 治理反馈写入（外发阻断） |

---

## [D4-R-024] 4. 资源语义与路径规则

### [D4-R-025] 4.1 路径命名规则

- 路径一律使用英文、复数资源名与 `kebab-case`；
- 路径层级必须体现资源从属关系，不得体现 UI 页签结构；
- 子资源路径只能建立在正式对象的依赖关系上；
- 同一正式资源不得存在两个同义路径；
- 保留态接口必须与未来正式资源同名，不得在放行后改路径。

### [D4-R-026] 4.2 顶层资源规则

顶层资源只允许包括：

- `tasks`
- `projects`
- `reports`
- `saleable-opportunities`
- `contact-targets`
- `orders`
- `payments`
- `deliveries`
- `coverage-status`
- `delivery-matrix`
- `exception-records`
- `governance-feedback-events`

任何新增顶层资源若会影响正式对象、正式 actor、正式机会、正式交付或正式外发，必须先补 D2 / D7 / D8 / D9 / D10 / D13，再补本目录。

### [D4-R-027] 4.3 查询参数规则

正式查询参数只允许用于以下用途：

- 分页：`page`、`page_size`；
- 排序：`sort_by`、`sort_order`；
- 状态过滤：`*_status`、`*_state`；
- 时间过滤：`*_from`、`*_until`；
- 搜索关键字：`q`；
- 受控 included：`include`。

不得通过查询参数临时扩展未冻结字段、未冻结对象或未冻结结果语义。

### [D4-R-028] 4.4 `include` 规则

- `include` 只能引用同一文档中已声明可嵌入的正式资源；
- `include` 不得绕开字段策略返回原本不应暴露的高限制对象；
- 对外线索包导出与外部交付接口，`include` 默认只允许解释层摘要，不允许返回内部 reasoning 对象全文；
- 对保留态接口，`include` 一律无效。

---

## [D4-R-029] 5. 响应封套、分页与版本规则

### [D4-R-030] 5.1 正常响应

#### [D4-R-031] 单对象响应

```json
{
  "request_id": "req-20260412-001",
  "snapshot_at": "2026-04-12T10:00:00+08:00",
  "data": {
    "project_id": "PRJ-001"
  }
}
```

#### [D4-R-032] 列表响应

```json
{
  "request_id": "req-20260412-010",
  "snapshot_at": "2026-04-12T10:10:00+08:00",
  "data": [
    {
      "project_id": "PRJ-001"
    }
  ],
  "paging": {
    "page": 1,
    "page_size": 20,
    "total": 135,
    "has_next": true
  }
}
```

### [D4-R-033] 5.2 `warnings` 规则

以下场景允许返回 `warnings`：

- 当前对象仅提供摘要投影；
- 低优先级解释对象被裁剪；
- 当前接口处于保留态或受限态；
- 因审批、交付矩阵或字段策略限制，部分字段未返回。

`warnings` 只允许解释裁剪与受限原因，不得承担正式主结论职责。

### [D4-R-034] 5.3 `policy_tags` 规则

当接口返回内容受到治理限制时，可以附带：

- `summary_only`
- `requires_review`
- `leadpack_deliverable`
- `internal_only`
- `release_blocked`
- `reserved_surface`

`policy_tags` 用于说明当前表面状态，不用于重定义结果语义。

### [D4-R-035] 5.4 版本规则

- 正式接口版本统一使用 `/v1` 主版本前缀；
- 破坏性变更必须升级主版本；
- 非破坏性新增必须先补 D4 与机器目录，再进入实现；
- 不允许在不升版本的情况下删除字段、改变字段语义或改变资源上游对象。

---

## [D4-R-036] 6. 角色与权限矩阵

### [D4-R-037] 6.1 正式角色

| 角色 ID | 正式角色 | 接口侧默认职责 |
|---|---|---|
| `product_admin` | 产品管理员 | 配置、重跑、目录查询、元数据查询、治理配置 |
| `verification_analyst` | 核查分析员 | 查看真相层、核验层、规则证据层与统一事实层内部对象 |
| `human_reviewer` | 人工复核员 | 消费复核队列、确认结果层影响、执行导出放行 |
| `sales_user` | 经营 / 销售用户 | 查看正式摘要、统一事实、受限商业对象 |
| `delivery_governance_user` | 交付 / 治理用户 | 审批导出、查看治理对象、处理例外与 release |
| `client_readonly` | 线索包只读接收方 | 仅查看授权范围内的正式摘要投影 |

### [D4-R-038] 6.2 角色暴露原则

- `verification_analyst` 与 `human_reviewer` 允许消费解释层对象，但不等于允许外发；
- `sales_user` 默认不得直接查看 `field_lineage_record`、`rule_gate_decision`、`evidence_gate_decision`、`review_queue_profile` 原文；
- `client_readonly` 只能消费经过 D6 / D7 放行的线索包摘要；
- `delivery_governance_user` 可以查看治理对象元数据，但高限制正文仍需专项审批；
- 任何角色都不得因为接口存在就默认可见 D 层输入。

### [D4-R-039] 6.3 高限制对象接口规则

以下对象属于高限制对象，必须按角色、审批链与 release gate 额外裁剪：

- `private_supplement_record`
- `controlled_exception_record`
- `legal_action_actor_profile`
- `procurement_decision_actor_profile`
- `contact_target`
- 任何自然人高限制字段

默认规则如下：

| 对象 | 默认对谁可见 | 返回强度 |
|---|---|---|
| `private_supplement_record` | `verification_analyst`、`human_reviewer`、`delivery_governance_user` | 默认只返元数据 |
| `controlled_exception_record` | `delivery_governance_user`、部分 `product_admin` | 默认只返元数据 |
| `legal_action_actor_profile` | `verification_analyst`、`sales_user`（摘要）、`delivery_governance_user` | 摘要化 |
| `procurement_decision_actor_profile` | `sales_user`（摘要）、`delivery_governance_user` | 摘要化 |
| `contact_target` | D9 生效前无人正式可见 | 阻断 |

---

## [D4-R-040] 7. 错误码与阻断策略

### [D4-R-041] 7.1 错误码分层

| 类别 | 典型错误码 | 正式含义 |
|---|---|---|
| 认证鉴权 | `AUTH-401-UNAUTHENTICATED`、`AUTH-403-FORBIDDEN_ROLE` | 未登录、角色不匹配或作用域不足 |
| 请求格式 | `REQ-400-BAD_REQUEST`、`REQ-422-UNFROZEN_FIELD` | 请求格式错误或引用未冻结字段 |
| 数据状态 | `DATA-404-PROJECT_NOT_FOUND`、`DATA-409-VERSION_CONFLICT` | 资源不存在，或版本 / 时钟 / 归一状态未解 |
| 规则与 gate | `GATE-409-DUAL_GATE_BLOCKED`、`GATE-409-REVIEW_REQUIRED` | 双闸门阻断或只能进入复核 |
| 字段治理 | `FIELD-403-REDACTED_FIELD`、`FIELD-409-POLICY_BLOCKED` | 字段未放行、脱敏或治理阻断 |
| release 与审批 | `EXPORT-409-NOT_RELEASEABLE`、`AUDIT-428-APPROVAL_REQUIRED` | 模板未放行、审批链未完成 |
| coverage 与治理 | `COVERAGE-409-NOT_SELLABLE`、`DELIVERY-409-RISK_BLOCKED` | coverage 不可售或交付风险阻断 |
| 保留态阻断 | `BATCH-423-CAPABILITY_NOT_EFFECTIVE`、`SURFACE-423-RESERVED_UNTIL_DX` | 对应能力尚未正式生效 |
| 合规触达 | `CONTACT-409-COMPLIANCE_BLOCKED` | 联系来源、频控、quiet hours 或审批不满足 |

### [D4-R-042] 7.2 正式阻断规则

以下场景必须返回阻断，而不是静默降级：

1. 请求试图消费未冻结字段或未冻结对象；
2. 请求路径对应保留态接口但被当作正式执行面调用；
3. 请求试图穿透 D 层输入形成正式主结论；
4. 导出、线索包外发或外部交付请求未满足审批链与 release gate；
5. 触达请求未满足 lawful basis、频控、quiet hours 或 contact policy；
6. 项目归一、版本链、时钟链或双闸门处于不可接受冲突状态。

### [D4-R-043] 7.3 复核型返回规则

以下场景允许返回 `REVIEW_REQUIRED` 而不是 `BLOCK`：

- 双闸门中至少一类为 `REVIEW`，但不是 `BLOCK`；
- 证据达到内部使用阈值但未达到线索包外发阈值；
- 当前对象可内部消费但不可线索包外发；
- 当前对象需要人工确认、治理审批或补证。

---

## [D4-R-044] 8. 各接口组正式约束

### [D4-R-045] 8.1 任务编排接口组

- 创建任务必须显式声明地区、时间范围、策略模板与复核车道；
- `POST /projects/{project_id}/rebuild` 只允许重建统一事实，不允许重写真相层事实；
- 任务接口不得直接形成业务结论；
- 重建动作必须产生审计事件。

### [D4-R-046] 8.2 项目与统一事实接口组

- `/projects/{project_id}/facts` 是一切顶层项目判断接口的主入口；
- `/projects/{project_id}/legal-actions` 只返回正式动作建议对象，不得返回接口层临时拼装文案；
- `/projects/{project_id}` 可返回项目基础信息与正式摘要，但不得替代 `/facts`；
- 任何项目列表接口如展示结论，必须来自 `project_fact` 摘要字段。

### [D4-R-047] 8.3 公开链与追溯接口组

- `field_lineage_record` 只允许作为解释层、追溯层或审计层接口；
- 线索包只读与销售默认不得消费原始 lineage；
- `public_chain`、`clock_chain_profile`、`notice_version_chain` 可进入内部工作台与摘要投影，但不得单独包装成线索包主结论；
- 攻击面对象只能作为事实解释与规则上游，不能替代 `project_fact`。

### [D4-R-048] 8.4 规则与证据接口组

- `rule_hit` 列表只表示规则层结果，不等于顶层主结论；
- `rule_gate_decision` 与 `evidence_gate_decision` 必须同时可读、同时可解释；
- `review_request` 是正式复核入口对象，接口不得把它写成“失败原因备注”；
- 证据接口不得在无原始载体时返回“外发可用”。

### [D4-R-049] 8.5 报告与复核接口组

- 报告接口必须消费 `report_record`，不得导出页面截图或内部 JSON 代替正式交付物；
- `private_supplement_record` 默认只返元数据；
- 任何导出申请必须明确模板、最低 release level 与审批链要求；
- 报告提交复核后，接口层不得绕过复核直接放行线索包外发导出。

### [D4-R-050] 8.6 商业对象接口组

- 在 D8 正式生效前，商业对象接口只能返回阻断，不得返回伪数据或演示数据冒充正式对象；
- 路径冻结后，不得在 D8 生效时重新改名；
- 一旦 D8 生效，`saleable_opportunity` 仍必须消费阶段 6 正式对象，而不是页面或销售层临时生成。

### [D4-R-051] 8.7 触达接口组

- 在 D9 正式生效前，所有触达接口默认阻断；
- 触达相关接口一旦放行，必须同时受 `contact_legal_basis`、`frequency_policy_state`、`opt_out_state`、`quiet_hours_policy_state` 约束；
- 触达接口不得返回未审批的自然人完整联系方式。

### [D4-R-052] 8.8 订单与交付接口组

- 在 D10 正式生效前，订单、支付、交付接口默认阻断；
- 一旦 D10 生效，订单与交付接口必须显式写入审计链与结果回写链；
- `delivery_record`、`opportunity_outcome_event` 只能由阶段 9 正式对象化形成，不得用 CRM 备注替代。

### [D4-R-053] 8.9 治理与例外接口组

- coverage、delivery matrix、release gate、受控例外都必须走正式治理接口，不得走隐藏端点；
- 治理接口的写操作必须留痕、审批与回归联动；
- 受控例外的创建、审批、释放不得落在同一角色链；
- 治理接口不得把例外机制变成常态放行通道。

---

## [D4-R-054] 9. 导出、审批与 release 接口

### [D4-R-055] 9.1 导出申请接口

`POST /reports/{report_id}/export` 的正式请求体至少必须包含：

```json
{
  "template_id": "leadpack_report",
  "requested_release_level": "CLIENT_VISIBLE"
}
```

接口必须同时校验：

- 模板是否存在且已冻结；
- 当前报告是否达到目标 `release_level`；
- 当前对象与字段是否在 D7 / D6 放行范围内；
- 当前审批链是否已完成；
- 当前证据等级是否满足场景要求。

### [D4-R-056] 9.2 审批型接口

审批型接口只允许用于：

- 导出申请；
- 高限制字段查看申请；
- 高限制联系对象释放申请；
- 受控例外申请；
- coverage / delivery matrix 治理变更申请。

审批型接口不得用于：

- 直接改写 `project_fact`；
- 直接把 `review_request` 改成 `AUTO_HIT`；
- 直接放行 D 层输入进入正式公开主链。

### [D4-R-057] 9.3 release gate 接口要求

release gate 的读写接口必须满足：

- 只能由治理角色消费；
- 所有变更必须进入回归检查；
- 返回体必须显示阻断原因、审批状态与影响范围；
- 变更成功不等于自动放行对应线索包外发版本，仍需对象级与字段级双重裁决。

---

## [D4-R-058] 10. 最小示例

### [D4-R-059] 10.1 创建任务

```json
POST /v1/tasks
{
  "region_code": "320500",
  "time_range_from": "2026-04-01",
  "time_range_until": "2026-04-12",
  "strategy_template_id": "public-core-standard",
  "review_lane": "STANDARD"
}
```

```json
{
  "request_id": "req-20260412-001",
  "snapshot_at": "2026-04-12T10:00:00+08:00",
  "data": {
    "task_id": "task-001",
    "task_state": "QUEUED",
    "accepted_review_lane": "STANDARD"
  }
}
```

### [D4-R-060] 10.2 查询统一事实

```json
GET /v1/projects/PRJ-001/facts
```

```json
{
  "request_id": "req-20260412-002",
  "snapshot_at": "2026-04-12T10:05:00+08:00",
  "data": {
    "project_id": "PRJ-001",
    "sale_gate_status": "REVIEW",
    "rule_gate_status": "PASS",
    "evidence_gate_status": "REVIEW",
    "coverage_sellable_state": "RESTRICTED",
    "delivery_risk_state": "REVIEW",
    "manual_override_status": "NONE"
  },
  "policy_tags": [
    "summary_only",
    "requires_review"
  ]
}
```

### [D4-R-061] 10.3 查询规则命中

```json
GET /v1/projects/PRJ-001/rule-hits
```

```json
{
  "request_id": "req-20260412-003",
  "snapshot_at": "2026-04-12T10:06:00+08:00",
  "data": [
    {
      "rule_code": "QUAL-001",
      "result_type": "CLUE",
      "boundary_note": "A_PUBLIC_CORE",
      "evidence_grade": "E3_CLIENT_VISIBLE"
    }
  ],
  "warnings": [
    "Rule hits are explainer surfaces and do not replace project_fact."
  ]
}
```

### [D4-R-062] 10.4 导出被阻断

```json
POST /v1/reports/RPT-001/export
{
  "template_id": "leadpack_report",
  "requested_release_level": "CLIENT_VISIBLE"
}
```

```json
{
  "error_code": "EXPORT-409-NOT_RELEASEABLE",
  "http_status": 409,
  "message": "Requested template is not releasable for the current report state.",
  "blocking_l0_ref_optional": "L0-R-008",
  "next_action_optional": "Route through reviewer or governance approval."
}
```

### [D4-R-063] 10.5 调用保留态接口

```json
GET /v1/contact-targets
```

```json
{
  "error_code": "SURFACE-423-RESERVED_UNTIL_D9",
  "http_status": 423,
  "message": "The current surface has been frozen for future use but is not yet effective.",
  "blocking_l0_ref_optional": "L0-R-009",
  "next_action_optional": "Wait until D9 becomes effective."
}
```

---

## [D4-R-064] 11. 机器承接与实现纪律

### [D4-R-065] 11.1 机器承接目录

- `contracts/api/api_catalog.json`：正式接口目录、路径、方法、operationId、资源状态、上游对象；
- `contracts/api/error_code_catalog.json`：错误码、HTTP 状态、错误语义、阻断级别、下一步动作；
- `contracts/api/permission_matrix.json`：角色、资源、动作、字段可见范围、审批前置条件。

### [D4-R-066] 11.2 强制承接规则

- 任一正式接口若未进入 `api_catalog.json`，不得进入正式实现；
- 任一错误码若未进入 `error_code_catalog.json`，不得在实现中直接发明；
- 任一资源暴露规则若未进入 `permission_matrix.json`，不得默认放行；
- 任一保留态接口若在目录中标为 `RESERVED_*`，实现层不得返回成功业务数据；
- 任一破坏性变更都必须同步更新 D4、机器资产与 D11 回归。

### [D4-R-067] 11.3 实现纪律

- 前端只能调用正式目录中已声明的 `operationId`；
- Mock、Postman、测试桩必须使用正式路径与正式封套，不得自造自由格式；
- 服务端不得把内部对象直接序列化给线索包外发接口；
- 接口层不得成为第二套主判断引擎；
- 保留态接口只能做冻结路径与返回阻断，不得承载演示态业务逻辑。

---

## [D4-R-068] 12. D11 测试与回归要求

接口层进入正式生效前，至少必须通过以下测试：

1. **目录一致性测试**：实现层路径与 `api_catalog.json` 一一对应；
2. **对象一致性测试**：返回体字段必须能回指 D2 正式对象与字段；
3. **结果一致性测试**：顶层主判断接口不得绕开 `project_fact`；
4. **gate 阻断测试**：双闸门 `REVIEW / BLOCK` 时接口返回符合 D3；
5. **字段治理测试**：高限制字段不得被未授权角色看到；
6. **保留态接口测试**：D8 / D9 / D10 未生效时接口统一阻断；
7. **导出审批测试**：导出申请未满足 release gate 时必须阻断；
8. **D 层渗透测试**：D 层输入不得通过接口成为正式公开主结论；
9. **错误码回归测试**：所有正式错误码都能映射到机器目录与阻断语义；
10. **版本兼容测试**：无破坏性变更混入未升版本发布。

---

## [D4-R-069] 13. 禁止事项总表

接口层一律不得：

- 从 `rule_hit`、原始公告、CRM 备注或前端状态重算项目主结论；
- 暴露未冻结字段、未冻结对象或未冻结枚举；
- 把 D 层输入包装成正式主结论、正式线索包主证或正式动作建议依据；
- 把 `private_supplement_record`、`controlled_exception_record` 正文默认透给普通角色；
- 因路径已存在就放行 D8 / D9 / D10 的正式执行面；
- 让导出接口绕过模板、审批链、字段策略与交付矩阵；
- 把高限制自然人信息直接返回给销售、外部接收方或未授权角色；
- 在未升版本的情况下做破坏性变更；
- 用联调临时端点、隐藏参数或自由 JSON 扩展第二套正式接口口径。

---

## [D4-R-070] 14. 开工基线与后续承接

### [D4-R-071] 14.1 首批必须先稳定的接口

首批必须优先稳定以下接口：

- `POST /v1/tasks`
- `GET /v1/projects`
- `GET /v1/projects/{project_id}`
- `GET /v1/projects/{project_id}/facts`
- `GET /v1/projects/{project_id}/legal-actions`
- `GET /v1/projects/{project_id}/public-chain`
- `GET /v1/projects/{project_id}/clock-chain`
- `GET /v1/projects/{project_id}/version-chain`
- `GET /v1/projects/{project_id}/rule-hits`
- `GET /v1/projects/{project_id}/evidence`
- `GET /v1/projects/{project_id}/rule-gates`
- `GET /v1/projects/{project_id}/evidence-gates`
- `GET /v1/projects/{project_id}/review-requests`
- `GET /v1/projects/{project_id}/report-record`
- `POST /v1/reports/{report_id}/export`

### [D4-R-072] 14.2 后续文档承接

- D5 继续展开这些接口被页面如何消费；
- D6 继续收紧这些接口能返回哪些字段；
- D7 继续裁决这些接口在不同交付形态下是否放行；
- D8 / D9 / D10 生效后，对外正式接口才可切换为正式生效态；阶段 7-8 仅允许 internal preview 接口承接；
- D11 负责把本目录中的路径、operationId、错误码与阻断逻辑全部纳入回归。

---

### [D4-R-073] 14.3 阶段 7-8 internal preview 接口补表（新增）

| 接口组 | 主要路径 | 内部定位 | preview / draft | 对外 |
|---|---|---|---|---|
| 商业封装接口 | `/saleable-opportunities` | internal only | preview / draft only | 否 |
| 触达编排接口 | `/contact-targets`、`/contact-targets/compliance-check`、`/outreach-plans`、`/touch-records` | internal only | preview / draft only | 否 |

说明：
- 上述接口仅用于内部工作台与审批链承接，不得作为对外触达或客户接口；
- 合规校验必须直接返回 `semantic_envelope.surface_state` 与 canonical reason，不得再造 `ALLOW_PREVIEW` 一类平行词表，也不得触发真实发送；
- 任何真实外发仍需 D7 / D9 / 审批链 / 审计链全部成立。

## 附录：内部经营主链接口承接补表（新增）

本补表用于把接口层承接为“内部经营主链接口”，不改写既有 OpenAPI 结构与路径。

| 接口组 | 经营主链承接 | 主要对象 | 内部定位 | LeadPack 导出关系 | 对外暴露 |
|---|---|---|---|---|---|
| 机会形成 / 商业封装接口 | 商业封装链 | `saleable_opportunity`、`offer_recommendation`、`buyer_fit` | 内部分析 / 内部销售作战 | 仅作为 LeadPack 导出输入 | 否 |
| 触达矩阵 / 触达执行接口 | 触达编排链 | `contact_target`、`outreach_plan`、`touch_record` | 内部销售作战 | 仅结果摘要可入包 | 否 |
| 交付 / 付款 / 回写接口 | 商务交付与反馈链 | `order_record`、`payment_record`、`delivery_record`、`opportunity_outcome_event`、`governance_feedback_event` | 内部交付与回写 | 仅结果与状态摘要可入包 | 否 |
| LeadPack 管理与导出接口 | 证据包与可售判断链 / 商业封装链 | `offer_recommendation`、`delivery_record` 等正式对象投影 | 内部交付与复核 | LeadPack 导出与审批入口 | 否 |

补充边界：
- 接口默认按内部运营面承接，不是客户开放 API。
- 仅正式对象可作为 LeadPack 导出输入，不得从低级线索反推主判断。

### [D4-R-073-A] 14.4 Stage 9 internal governed API 承接补表（本轮）

本补表用于明确 Stage 9 API 的 `draft / preview / writeback / internal only` 语义，不改写既有路径。

| 承接动作 | operationId / path | 当前正式语义 | internal only | 阻断条件 | 对外口径 |
|---|---|---|---|---|---|
| `order draft` | `createOrder` / `POST /orders` | 只创建/更新内部订单草案，不宣称商业闭环完成 | 是 | 审批链、审计链、sale gate 任一缺失即 `BLOCK/REVIEW_REQUIRED` | 非 external-ready 接口 |
| `payment draft` | `createPaymentRecord` / `POST /payments` | 只承接支付草案、异常、退款、金额不符状态 | 是 | 支付凭证缺失、付款方不匹配、审计缺失即阻断 | 非真实收款接口 |
| `delivery preview` | `createDeliveryRecord` / `POST /deliveries` | 只承接内部交付预览与 gate 校验 | 是 | release gate、审批链、审计链、字段策略任一不满足即阻断 | 非客户交付接口 |
| `outcome writeback` | `createOpportunityOutcomeEvent` / `POST /opportunity-outcomes` | 只承接结果写回草案/正式内部写回 | 是 | reason taxonomy 不合法、written_back_at 缺失、审计缺失即 review | 非客户结果回写接口 |
| `governance feedback writeback` | `createGovernanceFeedbackEvent` / `POST /governance-feedback-events` | 只承接内部治理反馈记录 | 是 | trigger/action/audit 缺失即 review/block | 非外部治理回执接口 |

补充说明：
- Stage 9 API 只形成 internal governed 最小闭环；
- direct object 不得通过这些接口直接进入 `LEADPACK_DELIVERABLE` 或 `EXTERNAL_PLATFORM`。

### [D4-R-073-B] 14.5 Stage 7-9 internal preview response envelope 补表（本轮新增）

| stage | 当前 response 承接 | 必须包含 | 明确禁止 |
|---|---|---|---|
| Stage 7 | `opportunity_pool` internal preview envelope | `surface_id/surface_state/surface_mode/surface_access`、`capability_envelope`、`governance_envelope`、`semantic_envelope`、`formal_object_refs`、`preview_projection`、`decision_states`、`trace_refs` | 不得从 API 层重算 `saleability_status`、推荐结果或 surface envelope |
| Stage 8 | `outreach_workbench` governed preview envelope | `capability_envelope`、`governance_envelope`、`semantic_envelope`、`contact_target/outreach_plan/touch_record` formal refs、preview projection、decision states、trace refs、`blocked_by_default` | 不得把 preview/draft 写成 live send ready，不得在 route 层再推一套 blocked/review/governed |
| Stage 9 | `order_delivery_workbench` internal governed envelope | `capability_envelope`、`governance_envelope`、`semantic_envelope`、`order/payment/delivery/outcome/governance` formal refs、preview projection、decision states、trace refs、`live_execution_enabled=false` | 不得把 draft/writeback endpoint 写成真实 payment / delivery / refund endpoint |

补充说明：
- response envelope 只消费正式对象与正式 trace，不允许在接口层重算主判断；
- `surface_state` 与 `surface_mode` 只用于 internal preview / draft-only 消费，不是第二套业务状态机；
- `surface_state` 必须等于 `semantic_envelope.surface_state`；
- route 级 `draft_created / writeback_ready / compliance_result / preview_generated` 必须来自 `governance_envelope.action_availability[operationId]` 或 `semantic_envelope`，不得再对 `surface_state` 做本地布尔推断。

## 附：Stage 7-9 repository-backed preview / draft loop 补表（本轮）

| 接口组 | 当前正式承接 | repository retrieval 要求 | 明确禁止 |
|---|---|---|---|
| Stage 7 `/saleable-opportunities` | internal preview | 读取 `saleable_opportunity / offer_recommendation / buyer_fit` 及 supporting actor refs 的正式 repository state | 不得只返回空壳 preview envelope |
| Stage 8 `/contact-targets`、`/outreach-plans`、`/touch-records` | governed preview / draft | 读取 `contact_target / outreach_plan / touch_record` 的正式 repository state 与 decision states / traces，并投影 `capability/governance/semantic envelope` | 不得在 route 层重算 contact compliance 或 writeback judgment |
| Stage 9 `/orders`、`/payments`、`/deliveries`、`/opportunity-outcomes`、`/governance-feedback-events` | internal governed preview / writeback | 读取 `order / payment / delivery / outcome / governance feedback` typed repository state，并投影 `capability/governance/semantic envelope` | 不得把 repository retrieval 写成 live payment / live delivery API |
| repository hydration precedence | Stage 7/8/9 persisted readback | 优先使用 persisted `stage_state.typed_object_refs` 及 formal object refs 读回关联正式对象；`work_item.object_refs` 只允许作为 operator loop projection fallback；只有 typed ref 缺失时才允许兼容性 fallback | 不得按 `project_id / opportunity_id` 宽泛回捞覆盖已持久化 formal relation |

补充说明：
- `create*` / `refresh*` 内部接口只允许写入 internal repository boundary，不代表外部执行；
- `list*` preview surface 必须做到“写入后可读回”，但仍然只能消费正式对象 + decision states + traces。

### [D4-R-073-C] 14.6 INTERNAL_PRODUCT_OPERATIONALIZATION_BATCH 补表（本轮新增）

本补表用于把 Stage 7/8/9 internal preview/draft surface 推进成最小 internal operator loop，不改写既有 formal object 语义。

| 类别 | 新增正式承接 | 约束 |
|---|---|---|
| work item queue | `GET /saleable-opportunity-work-items`、`GET /outreach-work-items`、`GET /order-delivery-work-items` | 只返回 repository-backed persisted work item / assignment lifecycle / pending action / action history；不得在读路径自动补建 work item |
| Stage 7 operator action | `POST /saleable-opportunities/{opportunity_id}/operator-actions` | 允许 `stage7_mark_reviewed / stage7_return_for_revision`；`stage7_open_internal_preview` 继续只属于 preview button flow，不再冒充 persisted action transition |
| Stage 8 operator action | `POST /outreach-workbench/{opportunity_id}/operator-actions` | 允许 `stage8_request_governed_review / stage8_approve_draft_progression / stage8_deny_draft_progression / stage8_put_governed_hold / stage8_return_for_revision`；对声明 `requiresApprovalChain=true` 的动作，runtime 必须先验证 resolved reviewer chain，再决定是否允许继续；不得触发真实触达 |
| Stage 9 operator action | `POST /order-delivery-workbench/{opportunity_id}/operator-actions` | 允许 `stage9_submit_draft_writeback / stage9_mark_reviewed / stage9_deny_draft_writeback / stage9_put_governed_hold / stage9_return_for_revision`；同一 `action_id` 若对应多个 button flow，必须由 runtime 结合 `button_flow_id` 消费 formal flow 语义；对声明 `requiresApprovalChain=true` 的动作，approval gate 必须先于 resulting state 推进 |
| operator response envelope | `operational_context_status + persisted_operational_context + transient_preview_context + action_result/error` | 必须显式区分 persisted loop 与 preview fallback；不得把 transient preview 伪装成已入库 work item |

补充说明：
- operator loop 只能消费正式对象、decision states、trace refs、audit refs 与 governed metadata；
- runtime 必须直接消费 `review_action_catalog` / `button_flow_catalog` 的 `allowed transition / resulting state / review requirement / audit requirement / requiresApprovalChain`；
- `requiresApprovalChain=true` 当前最小 runtime 口径固定为：`reviewer_role + reviewer + 非 unassigned resolved_from`；缺任一都必须视为 approval chain 不成立；
- `WORKITEM-404-NOT_FOUND`、`ACTION-409-NOT_PENDING`、`ACTION-409-AUDIT_REQUIRED`、`ACTION-409-APPROVAL_REQUIRED` 必须以结构化错误响应落到 runtime，不得再主要依赖通用异常；
- route 不得改写 `saleability_status / governance_decision / capability mode / outcome taxonomy / release gate` 的主判断；
- 所有 operator action route 必须保持 `internal_only=true`、`live_execution_enabled=false`，并且在 Stage 8/9 保持 `blocked_by_default`。

### [D4-R-073-D] 14.7 PREP-01 transport readiness 真实状态补表（本轮新增）

本补表用于把当前接口 transport readiness 的真实状态写清楚，不改写既有 OpenAPI 目录、路径或 internal preview/draft 语义。

| transport 面 | 当前真实状态 | 当前代码落点 | 正式含义 | 明确禁止 |
|---|---|---|---|---|
| Stage 7 internal preview routes | 已实现 | `src/api/routes/stage7.py` + `src/api/projections.py` + repository boundary | 可作为 internal preview / candidate-only / review-only 表面消费正式对象 | 不得写成 external-ready / implementation-approved |
| Stage 8 internal preview / draft routes | 已实现 | `src/api/routes/stage8.py` + `src/api/projections.py` + repository boundary | 可作为 governed preview / draft-only 表面消费正式对象 | 不得触发真实触达 |
| Stage 9 internal preview / draft / writeback routes | 已实现 | `src/api/routes/stage9.py` + `src/api/projections.py` + repository boundary | 可作为 internal governed preview / draft-only / writeback 表面消费正式对象 | 不得触发真实 payment / delivery / refund |
| Stage 1-6 route registrar | skeleton-only | `src/api/routes/stage1.py` ~ `src/api/routes/stage6.py` | 路径与 operationId 已冻结，但 transport 尚未接通 | 不得宣称这些路由已 runtime-ready |
| app bootstrap / dependency injection | skeleton-only | `src/api/main.py`、`src/api/deps.py` | 当前仓库仍是“route/projection/preview contract ready”，不是完整可启动 API app ready | 不得把 contract-frozen 路径包装成可部署的完整 API 服务 |

补充说明：
- D4 仍然冻结 Stage 1-9 的正式接口目录；但当前 transport readiness 只覆盖 Stage 7-9 internal preview/draft/operator loop 表面。
- Stage 1-6 当前是 contract-ready、transport-not-wired；后续若进入 transport bootstrap 批次，必须先更新 D4、D11、D12 与 release/readiness 口径。
- `register_stage7_routes`、`register_stage8_routes`、`register_stage9_routes` 当前返回 formal route table，不等于 `create_app()` 已可正式启动。

### [D4-R-073-E] 14.8 M7 transport bootstrap 补表（本轮新增）

本补表用于收口 M7 transport bootstrap 完成后的接口状态；不改写既有 OpenAPI 目录、正式对象边界或 internal-only / controlled-opening-required 受控开放边界。

| transport 面 | 当前真实状态 | 当前代码落点 | 正式含义 | 明确禁止 |
|---|---|---|---|---|
| Stage 7-9 app bootstrap | 已接通 | `src/api/main.py`、`src/api/deps.py`、`src/api/routes/stage7.py` ~ `stage9.py` | `create_app()` 已可把既有 Stage 7-9 internal preview / draft surface 暴露为真实 FastAPI transport slice | 不得写成完整业务 API 已 ready，不得写成 external-ready 或 live-ready |
| Stage 7 internal preview transport | 已接通 | FastAPI wrapper + repository hydration | 允许通过 `opportunity_id` 等最小 payload 从已持久化正式对象读回 internal preview surface | 不得重算主判断，不得绕过 formal object |
| Stage 8 internal governed preview / draft transport | 已接通 | FastAPI wrapper + repository hydration | 允许通过最小 payload 读回 governed preview / draft surface，仍保持 `blocked_by_default=true` | 不得触发真实触达，不得放宽审批/quiet-hours/frequency 边界 |
| Stage 9 internal governed preview / draft transport | 已接通 | FastAPI wrapper + repository hydration | 允许通过最小 payload 读回 internal governed preview / draft surface，仍保持 `blocked_by_default=true` | 不得触发真实 payment / delivery / refund |
| Stage 7/8/9 formal ref replay | 已接通 | persisted `stage_state.typed_object_refs` + repository hydration（`work_item.object_refs` 仅 operator loop fallback） | internal transport readback 必须优先遵循已持久化的 typed formal refs，而不是退化成粗粒度 project/opportunity 查找 | 不得因冲突记录、work item 漂移或历史残留导致 replay 取错正式对象 |
| Stage 1-6 route registrar | controlled unavailable | `src/api/routes/stage1.py` ~ `src/api/routes/stage6.py` | 继续保持 contract-ready / transport-not-wired，但不再抛 raw `NotImplementedError` | 不得宣称这些路由已 runtime-ready |

补充说明：
- M7 只接通 Stage 7-9 的 internal preview / draft transport slice，不等于放行完整 API app ready。
- `create_app()` 当前只包装既有 route table / projection / repository hydration；它不引入新的业务判断链。
- Stage 1-6 若未来进入 transport 实现批，仍需单独更新 D4、D11、D12 与 release/readiness 口径。

### 14.9 FF-09-S1 H-08 authoritative payload / human handoff API authority 补表（本轮新增）

本补表用于把 H-08 最小 authoritative payload、optional preview/writeback fields 与 human handoff fields 收口到 Stage 8 -> Stage 9 的单一 API authority；不改写 Stage 9 typed workflow、runtime 或外部放行边界。

| API / surface | sole authority | 必须/可选承接 | fallback / review path | 明确禁止 |
|---|---|---|---|---|
| Stage 9 typed ingest：`POST /orders`、`/payments`、`/deliveries`、`/opportunity-outcomes`、`/governance-feedback-events` | `handoff/stage8_to_stage9/contract.json#authoritative_payload.minimum_required_fields` | 必须消费 `opportunity_id`、`touch_record_id`、`response_status`、`saleability_status`、`crm_owner_state`；缺任一即 `BLOCK/REVIEW_REQUIRED` | 只允许沿 H-08 authoritative payload 进入 Stage 9 typed workflow；若与 `saleable_opportunity/touch_record` formal refs 不一致，必须阻断 | 不得从 Stage 8 route/workbench scattered fields、`project_id` fallback 或 service-local default 回填 |
| Stage 9 governed preview / writeback projection | `handoff/stage8_to_stage9/contract.json#authoritative_payload.optional_preview_writeback_fields` | `plan_status`、`touch_record_state`、`feedback_reason`、`written_back_at_optional`、`governance_decision_state`、`permission_decision_state`、`semantic_decision_state` 仅在 H-08 存在时消费并投影 | optional 字段缺失只允许保持 optional；存在时不得丢弃、不得改写 owner | 不得把 Stage 9 typed object 自身状态反向当成 H-08 source，也不得绕过 H-08 直接读取 Stage 8 raw object field |
| Stage 9 human handoff snapshot | `handoff/stage8_to_stage9/contract.json#authoritative_payload.optional_human_handoff_fields` + `docs/D9_联系对象与销售触达规范.md#D9-R-071-B-2` | `CONNECTED / ORG_ROUTED` 时只允许消费 `human_handoff_next_owner_role_optional`、`human_handoff_sla_hours_optional`、`human_handoff_sla_due_at_optional`、`human_handoff_reason_optional` 作为 governed internal follow-up metadata | 若命中 `CONNECTED / ORG_ROUTED` 但 H-08 未投影 owner/SLA/reason，则只允许 review/hold，不得静默补默认 owner/SLA | 不得把 human handoff 写成 Stage 9 delivery SLA、live execution unlock 或客户承诺 |
| Stage 8 -> Stage 9 response envelope / readback | `capability_envelope`、`governance_envelope`、`semantic_envelope` + H-08 authoritative payload projection | Stage 9 preview/readback 只允许展示 H-08 authoritative snapshot 与已持久化 typed refs 的一致性结果 | 页面/API 只能展示 formal projection；异常时给出 review/block reason | 不得直接暴露 Stage 8 internal scattered fields 作为跨阶段 contract surface |

补充说明：
- H-08 仍保持 `saleable_opportunity + touch_record` 为 critical object set；`outreach_plan` 只作为 optional preview/writeback carrier，不提升为 hard dependency；
- 本补表只收口 API contract authority，不执行 public software release、Stage 8 real execution 或 Stage 9 real payment/delivery/refund。

### 14.10 FF-16-S1 Stage7-9 API/UI/workbench envelope authority closure 补表（本轮新增）

本补表用于把 Stage7-9 API envelope 与 UI/workbench envelope 的 sole authority、fallback path 与 review path 固定到单一 docs/contracts 引用面；不改写既有 formal object、release gate 或 runtime 行为。

| surface / stage | sole docs authority | sole contract authority | fallback / review path | 明确禁止 |
|---|---|---|---|---|
| Stage 7 API preview envelope | `D4-R-073-B` + `D5` 的 FF-16-S1 workbench envelope 补表 + `D7` 的 FF-16-S1 envelope 交付 authority 补表 | `contracts/api/api_catalog.json#stage7To9EnvelopeAuthority` + `#groups[sales_surfaces]`、`contracts/ui/page_surface_states.json#surfaceAuthorityContract` | typed formal refs 缺失时只允许 `review-required`；不得以 route local bool 直接补成 `preview-ready` | 不得从 `release_layer`、`blocked_by_default`、`live_execution_enabled` 拼 capability 语义 |
| Stage 8 API governed preview / draft envelope | `D4-R-073-B` + `D5` 的 FF-16-S1 workbench envelope 补表 + `D7` 的 FF-16-S1 envelope 交付 authority 补表 | `contracts/api/api_catalog.json#stage7To9EnvelopeAuthority` + `#groups[outreach_surfaces]`、`contracts/ui/page_surface_states.json#surfaceAuthorityContract`、`contracts/ui/review_action_catalog.json#actionAvailabilityAuthority` | formal refs 缺失只允许 `review-required`；approval/audit 未闭合只允许 `governed-hold`；明确 policy/release 阻断时只允许 `blocked` | 不得把 `draft-only` 或 `blocked_by_default` 表面写成 live send ready |
| Stage 9 API governed preview / draft / writeback envelope | `D4-R-073-A/B` + 本补表 + `D5` 的 FF-16-S1 workbench envelope 补表 + `D7` 的 FF-16-S1 envelope 交付 authority 补表 | `contracts/api/api_catalog.json#stage7To9EnvelopeAuthority` + `#groups[orders_and_delivery]`、`contracts/ui/page_surface_states.json#surfaceAuthorityContract`、`contracts/ui/review_action_catalog.json#actionAvailabilityAuthority` | formal refs 缺失只允许 `review-required`；approval/audit 未闭合只允许 `governed-hold`；release/policy 阻断只允许 `blocked` | 不得把 draft/writeback endpoint 写成真实 payment / delivery / refund endpoint |
| Stage 7-9 API action availability | `D4-R-073-C/F` | `contracts/ui/review_action_catalog.json#actionAvailabilityAuthority` | `requiresApprovalChain=true` 但 reviewer chain 未 resolved 时必须落 `ACTION-409-APPROVAL_REQUIRED` + `governed-hold/review-required`；audit 缺失必须落 `ACTION-409-AUDIT_REQUIRED` | 不得由按钮是否显示或局部成功响应反推“可继续” |
| Stage 7-9 API/UI shared state semantics | `D4-R-073-B` + 本补表 + `D5` 的 FF-16-S1 workbench envelope 补表 | `contracts/ui/page_surface_states.json#surfaceAuthorityContract` | 顶层 `surface_state / surface_mode / surface_access` 只允许 mirror `semantic_envelope.*`；typed ref 缺失时只允许 review/block，不得本地重算 | 不得再造第二套 `blocked/review/governed/live-ready` 词表 |

补充说明：
- `contracts/api/api_catalog.json` 只负责 Stage7-9 资源、`operationId`、禁止事项与 envelope binding；`surface_state / surface_mode / surface_access / capability_envelope / governance_envelope / semantic_envelope` 的字段语义统一回指 `contracts/ui/page_surface_states.json`；
- `governance_envelope.action_availability[operationId]` 的 sole owner 固定为 `contracts/ui/review_action_catalog.json#actionAvailabilityAuthority`；API 只做引用，不再定义第二套 action availability 口径；
- Stage 8 / Stage 9 的 controlled_opening_boundary 固定为：`internal_only=true`、`live_execution_enabled=false`、`blocked_by_default=true`，且继续 `external blocked`。

## 附：PTL-I100-OPEN-CAPABILITY-BASELINE 能力开放基线补表

本补表只同步 API/live endpoint 开放口径，不新增 endpoint 或 OpenAPI schema。

| 项 | D4 承接口径 |
|---|---|
| policy ref | `control/product_task_library.yaml#open_capability_policy` / `PTL-I100-OPEN-CAPABILITY-BASELINE` |
| API 开放原则 | 真实触达、CRM/Quote、客户可见包、支付与交付 endpoint 是目标能力，但默认只能 internal/readback/sandbox，live endpoint 必须 dedicated current_task 放行。 |
| `controlled-opening-required` | API 返回 controlled-opening-required 只表示 provider config、sandbox、approval、audit、operator action、field allowlist/masking、dedicated current_task 和验收未满足前不能 live，不表示永久不做。 |
| live endpoint 门禁 | 无 provider config、sandbox、approval、audit、operator action、字段白名单/脱敏和运行开关时，API 不得发起真实外部动作。 |
| 自动退款边界 | 自动退款执行 endpoint excluded；退款 API 只允许 `manual exception` / 人工异常记录、manual approval/audit 和 governed review readback。 |









## 附：PTL-I100-143E 自动运营 source strategy 引用补表

本补表用于让本文承接最新能力版图，不改写正文语义。`PTL-I100-143E-autonomous-source-strategy-d-doc-sync` 的正式边界如下：全国聚合平台不是全量实时线索源；北京只作技术回归，不进首批商业试点；首批商业试点省份为四川、江苏、浙江、山东、广东、湖北；城市适配按覆盖缺口和证据价值触发；Stage6/7 商业钩子卖前给价值感但不得泄露可复现完整证据链；LLM 只能辅助抽取、摘要、复核提示和话术草稿。

本文引用该口径时，不得新增第二套 source strategy、客户可见字段、外发门禁、测试验收或模型放行规则。source strategy 边界以 D13-R-075 为准；验收以 D11-R-054 为准；Codex 执行以 D1-R-071 为准。

## 附：PTL-I100-143G 公开网抓取升级与验证码续跑补表

本补表只同步 143F 后续任务口径，不改写正文语义，不实现 runtime。

| 项 | 143G 承接口径 |
|---|---|
| 抓取失败 | 公开网站抓取失败时，系统应优先自动诊断并升级合法采集/解析策略，不把纯人工重跑作为默认路径。 |
| 验证码 | 公开站出现验证码/校验页时，系统应检测 challenge、挂起任务、保留会话与 capture plan、在 operator console 输入后续跑并记录审计；不得自动解验证码、接第三方打码或绕过访问控制。 |
| 复用原则 | 后续实现必须优先复用现有 Stage2 public source adapter、Stage2Service、Stage3 parser、operator console、repository/readback surfaces；不得创建第二套重复链路。 |
| 排序 | 推荐顺序调整为 `144 -> 145 -> 150 -> 151 -> 146 -> 147 -> 148 -> 149`。 |
| 受控开放边界 | 不放开任意 crawler、登录/验证码/反爬绕过、真实 provider、客户下载、真实支付交付、退款或自动退款。 |
