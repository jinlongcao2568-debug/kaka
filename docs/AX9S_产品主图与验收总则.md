# AX9S 产品主图与验收总则

**版本**: 2026-05-16 v2

**目的**
- 本文件用于定义 AX9S 目标产品的产品主图，并把图纸落到当前仓库代码、正式对象、验收门和已知缺口。
- 本文件不替代 `docs/L0.md`、D2-D14、`handoff/stage_handoff_catalog.json` 和 `control/product_runtime_architecture_map.yaml`；如有冲突，以这些权威源为准。
- 本文件的作用是避免后续修复只按局部 UI 感受或单个测试结果推进，必须按真实公开市场发现到证据包商业化闭环验收。
- 本文件同时作为新 AI 代理接手时的产品地图：先理解 Stage1-9 主链、两条招投标产品线、当前已验证能力和下一步漏斗缺口，再做代码改动。

## 0. 文档地图和当前开发口径

### 0.1 文档分工

| 文档 | 作用 | 不能替代什么 |
| --- | --- | --- |
| `AGENTS.md`、`README.md` | 入口、执行方式、关键安全边界 | 不冻结当前任务状态 |
| `docs/业务方向_候选公示后证据包与投前预测双线契约.md` | 招投标双线产品方向和输出禁令 | 不展开完整 Stage1-9 工程漏斗 |
| `docs/AX9S_产品主图与验收总则.md` | 产品运行总地图、当前能力快照、Stage1-9 漏斗和验收原则 | 不替代 `control/*` 动态状态源 |
| `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` | 每个阶段的分支动作、PASS/REVIEW/BLOCK 和修复优先级 | 不替代业务方向契约 |
| `docs/AX9S_Stage4-5_核验双闸门SOP.md` | Stage4 公开核验和 Stage5 双闸门的 L3/L4 操作规程 | 不直接生成客户结论 |
| `control/repo_status.md`、`control/current_task.yaml`、`control/milestone_status.yaml` | 当前 phase、readiness、active task 和动态状态 | 不定义新的业务口径 |

### 0.2 当前开发口径

当前阶段不是“马上卖证据包”，而是把证据生产系统的能力全部做扎实。每一步能力都必须经过真实公开源、真实项目、真实附件、真实失败场景验证，并留下可回放产物。

这意味着：

1. SKU 是能力验收方向，不是当前必须立即外发销售的动作。
2. 没有 Stage2/3 的可回放采集、下载、解析和字段血缘，后续 Stage4-9 都不能产生稳定价值。
3. 每个阶段都要能说明：输入来自哪里、输出写到哪里、失败如何归类、下一步由什么触发。
4. 查不到、源阻断、字段缺失、同名未消歧、附件失败，都只能进入 taxonomy/review，不能写成“无风险”或“已排除”。
5. 对外触达、真实交付、收款、客户下载和 release 仍属于受控开放能力，必须走审批、审计、operator action 和对应 gate。

### 0.3 SKU 只是反推能力的验收靶

| SKU / 产品形态 | 价值问题 | 必须具备的系统能力 | 当前输出边界 |
| --- | --- | --- | --- |
| 负责人未释放/履约冲突包 | 拟派负责人是否存在公开可查的时间窗口重叠或释放证据缺口 | `07` 候选绑定、负责人/证书身份消歧、历史中标/候选宽筛、`bid_show` + 原文地址定向回溯负责人/工期/服务期/释放证据、施工许可/合同/竣工/变更补查 | 输出“未释放风险线索/时间窗口疑似重叠线索/证据不足/需补查”，不得写“在建冲突成立” |
| 证书/注册单位/时间异常包 | 候选公示或 `08` 文件中的人员、证书、企业是否与公开注册信息不一致 | 四库/JZSC、全国公路建设市场监督管理系统、地方注册人员源、公司优先补证、姓名枚举、`08` 定向解析 | 输出“公开注册信息匹配/不匹配/源阻断/需复核”，不得写“是不是本人” |
| 信用处罚/监管风险包 | 企业处罚、失信、监管处理是否与招标文件时间线或资格要求发生冲突 | 信用中国/信用广东/地方处罚公示/住建处罚/投诉监督决定 readback，招标文件条款解析，时间线比对 | 输出“处罚或监管记录与资格/时间线疑似冲突线索”，不得写“违法成立” |
| 综合质疑证据包 | 招标文件、候选公告、`08` 投标文件公开中是否存在可质疑的不合规点 | 03/04/07 重点解析、08 register-only 后定向解析、社保/资格/业绩/响应字段抽取、规则证据双门 | 输出“综合质疑线索、证据缺口和建议补查”，不得输出终局法律定性 |
| 投前萝卜标/限制竞争预测包 | 截止/开标前是否存在定制条件、限制竞争、废标或投标价值风险 | 02/03/04 时钟判断、澄清补遗版本链、资格/评分/参数/合同条款解析、投前风险指数 | 输出“风险预测/建议澄清/建议谨慎投”，不得写“控标成立” |

SKU 必须分三层理解，避免后续代理把“卖什么证据”和“怎么报价包装”混在一起：

1. 业务证据专题：上表这些证据方向，用来决定 Stage1-6 要跑什么来源、抽什么字段、过什么规则。
2. 服务深度档位：`TRIAGE`、`EVIDENCE_PACK`、`DEEP_RELEASE_CHECK`、`CUSTOMER_DELIVERY_READY`，用来决定查到什么深度。
3. `LeadPack 商业封装档位 A/B/C`：D8/D10 里的商业封装、交付形态和报价带，不等于业务证据专题，也不等于证据强度。

负责人未释放/履约冲突包要拆成两个子漏斗：

1. 宽筛：当前项目 `07` 候选负责人/企业 -> `data.ggzy` 公司历史成交 -> `bid_show` 正文 -> 原文地址定向 readback，目标只抽项目负责人、公司/联合体成员、工期/服务期、合同履行期限和中标日期。
2. 深查：只有宽筛发现同一负责人/公司/联合体成员且时间窗口疑似重叠，才按命中地区或行业补施工许可、合同、竣工/验收、项目经理变更、许可变更、停工或分段/分期例外等释放证据。

这条链不得默认全量下载 01-12，也不得默认解析 `08`。01-12 项目流程矩阵在负责人未释放/履约重叠宽筛中的作用是定位“哪个阶段可能含负责人、工期/服务期或释放证据”，而不是把全部阶段当成下载和深解析任务。

当前 SKU 设计裁决：

1. 首批能力验证保留五个业务证据专题：证书/注册单位/时间异常包、负责人未释放/履约冲突包、信用处罚/监管风险包、综合质疑证据包、投前萝卜标/限制竞争预测包。
2. 新增两个辅助方向，但不作为首批主 SKU：程序时间线/公示流程缺陷包、竞争格局/陪标围标线索包。前者可作为综合质疑包的低成本补强，后者需要历史供应商网络、报价异常、长期陪标组合、文件相似度等能力稳定后再做。
3. “社保造假”暂不单独作为首批 SKU，只作为综合质疑证据包里的 `08` 定向解析和人工复核信号；未形成可回放证据前只能写“社保材料疑似需复核/证据不足”，不得写造假成立。
4. 当前能力压测顺序固定为：证书/注册单位/时间异常包 -> 负责人未释放/履约冲突宽筛 -> 信用处罚/监管风险包 -> 综合质疑证据包 -> 投前预测包。负责人未释放深查只在宽筛命中同人/同主体/时间窗口疑似重叠后触发。

### 0.4 当前能力快照

本节是 2026-05-16 的人类可读快照；动态 readiness 仍以 `control/repo_status.md`、`control/current_task.yaml`、`control/milestone_status.yaml` 为准。

| 能力块 | 当前已验证状态 | 仍不能宣称 |
| --- | --- | --- |
| Stage1-9 内部运营主链 | 控制面记录显示 144-149 自主机会发现、来源蓝图、公开采集加固、验证码/挑战续跑、证据风险、商业钩子、买家排序和操作台 readback 已完成内部闭环 | 不等于真实对外触达、真实收款、真实客户交付已放开 |
| 广州候选后链路 | 广州交易集团独立适配已完成多轮 P1-P13A/P12/P11 验证，10 项目稳定性记录为 26 个真实候选组、流程阻断 0、08 定向解析 0 | 广州不是当前主要开发阻塞点，不应无目的回头大改主链 |
| YGP 广东其他城市基础链 | 三城 440400/440500/440600 和 16 城小覆盖已验证城市发现、01-12 项目流程矩阵、附件下载门禁；fake attachment 为 0，08 默认未下载 | 不等于广东全省所有城市 fully covered，不等于 YGP 恢复为广州主源 |
| 负责人未释放/履约重叠宽筛（内部历史代号 `P13B`） | 已用 data.ggzy 公司历史成交、bid_show、原文链接和 YGP readback 做第一层宽筛；当前 closeout 未触发释放证据补查 | 未命中不等于无风险，source limit / YGP unsupported / 原文 readback 缺口仍需处理 |
| Stage4 路桥设计证书补充 | 已有全国公路建设市场监督管理系统 `MOT_HIGHWAY_MARKET_PERSON_TITLE_QUERY` 路线，补四库/JZSC 不覆盖的公路/路桥/交通工程设计人员和职称证书 | 不是泛称“交通系统”，也不能替代地方许可、合同、竣工和履约释放证据 |
| Stage8/9 触达交付治理 | 邮件、企微、CRM、报价、支付、交付等在内部受控 readback/沙盒语义下有基础 | 不代表可以绕过审批审计和 operator action 自动外发或交付 |

### 0.5 能力完成标准

一个阶段或分支不能只因为“有代码”或“测试绿”就算完成。完成必须同时满足：

1. 能用真实公开样本跑出输入、输出和失败形态。
2. 产物有来源 URL、采集时间、snapshot/readback、hash、字段血缘和脚本/adapter 版本。
3. PASS、REVIEW、BLOCK 三类路径都有明确条件，失败 taxonomy 不为空。
4. 输出能被下游正式对象消费，而不是只显示在 UI 或临时 JSON。
5. 客户可见前经过字段策略、脱敏、禁语、审批、审计和交付版本控制。

## 1. 产品目标一句话

AX9S 是 owner 内部使用的真实公开市场机会发现和证据包商业化运营系统。系统要从真实公开来源发现工程类机会，抓取详情和附件，解析关键字段，做公开核验和规则证据判断，形成统一事实、可售机会、买家适配和商业钩子，最后在审批、审计、支付、交付治理下把证据包作为成交后的交付物输出。

客户不使用工作台。客户最终只收到受控交付的证据包、线索包、机会包、情报包或销售推进结果。

系统每天自动找工程项目里的可售硬伤，但这个“自动”只指公开发现、公开核验、产品化编排和受控 readback，不指自动外发、自动收款、自动交付或自动法律定性。

### 1.1 默认业务入口

招投标分析默认按 `docs/业务方向_候选公示后证据包与投前预测双线契约.md` 和 `contracts/evaluation/business_direction_strategy_contract.json` 执行双线产品路由。

- 核心商业主线是候选公示后证据包分析：默认先从近期 `07 中标候选人公示` 入池，再回溯同一项目的招标公告、招标文件、答疑澄清、开标、投标文件公开、候选和结果材料；评标结果、开标记录、中标结果、合同和异常材料是回溯/支撑或历史复盘阶段，不是默认入口。近期 07 项目通常没有 11 合同和 12 异常，缺 11/12 不阻断当前证据包销售窗口。
- 辅助产品线是投前预测分析：只适用于 `02 招标文件公示`、`03 招标公告/关联公告`、`04 答疑澄清/补遗` 且投标截止/开标未过的项目，输出是否值得投、控标/定制标预测、废标风险和澄清/质疑建议；标准销售窗口为截止/开标前 168 小时以上，72-168 小时只做限时快筛，少于 72 小时不作为正常投前预测销售；若已经出现 `05 开标信息`，投前预测不再适用，必须转入开标后核验或候选后证据包路线。
- `AnalysisStrategyPlan v1` 是 Stage2 附件清单和 Stage3 解析之间的必经策略层：先定产品线、流程范围、下载范围、解析深度、规则核验和大模型触发条件，再下载和解析文件。
- `tender_file` smoke 只验证文件链路、文件下载、snapshot、MarkItDown/解析和项目级审计链路，不是最终业务入口，也不代表候选公示后证据包主线完成。

### 1.2 Stage1-9 逐阶段优化评估与漏斗展开总表

| 阶段 | 漏斗问题 | 子环节 | 核心产物 | 当前主要缺口/下一步 |
| --- | --- | --- | --- | --- |
| Stage1 机会发现与来源蓝图 | 哪些真实项目值得进入证据生产线 | 地区/行业/金额/公告阶段/时间窗选择；近期 07 和投前 02/03/04 分流；来源 profile 选择；无候选和跳过原因记录 | market scan plan、candidate pool、source blueprint、skip taxonomy | 继续把多省/多城真实候选发现做成稳定批量入口，不用人工挑 URL |
| Stage2 公开采集与流程回溯 | 项目材料是否可回放、可审计、可归属 | 列表、详情、附件、01-12 流程矩阵、03/04/07 默认下载、08 register-only、时钟/版本链、challenge taxonomy | public_chain、flow matrix、attachment manifest、snapshot/readback、hash | 继续补附件失败、SPA 壳、验证码、限流、超大附件 defer 的自动诊断和续跑 |
| Stage3 解析与字段血缘 | 能否从材料中抽出可核验字段 | HTML/PDF/DOC/XLS/ZIP inventory；候选组/联合体/负责人/证书/报价/排名抽取；OCR fallback；字段血缘 | project_base、bidder_candidate、project_manager / responsible person、field_lineage_record | 继续强化 08 定向解析、扫描件 OCR、复杂表格和多候选行绑定 |
| Stage4 公开核验 | 字段是否与公开注册、信用、履约、历史记录匹配 | 四库/JZSC、全国公路建设市场监督管理系统、信用中国/地方信用、地方许可/合同/竣工/处罚、data.ggzy 历史中标宽筛 | public verification carrier、source readback、evidence grade、review reason | 补多省地方 source adapter 和负责人未释放/履约重叠宽筛命中后的释放证据定向补查 |
| Stage5 规则证据双闸门 | 规则是否命中，证据是否足够 | 注册单位/证书/时间异常；信用处罚与资格要求重合；负责人未释放/履约重叠；程序/资格/响应缺陷；rule gate + evidence gate | rule_hit、rule_gate_decision、evidence_gate_decision、review_request | 继续补 SKU 对应规则包和真实 PASS/REVIEW/BLOCK 样本 |
| Stage6 统一事实与内部证据包 | 哪些线索可进入人工复核和证据包候选 | project_fact 聚合；证据包 manifest；可读报告；禁语/措辞初筛；补证任务 | project_fact、report_record、review_queue、internal evidence pack | 继续把真实候选 formal real_public 链强制回到 Stage4-9，不让内部预览冒充正式事实 |
| Stage7 买家适配与商业钩子 | 这条线索未来卖给谁、卖什么版本 | 二/三候选、落标人、律师顾问识别；buyer fit；报价区间；卖前可讲/不可讲和 withheld fields | saleable_opportunity、buyer_fit、offer_recommendation、commercial hook | 当前只作为能力建设和内部评审方向，不代表马上触达销售 |
| Stage8 触达准备与审批 | 未来怎么合规触达但不泄密 | 组织级联系方式、邮件/企微模板、频控、退订、审批、审计、operator action | contact_candidate_collection、outreach_plan、touch_record | 首单仍人工审核；真实发送必须 gated，不自动外发 |
| Stage9 交付治理与反馈 | 成交后如何交付可复核证据并回写 | 客户版脱敏、水印、版本、下载审计、支付/交付记录、退款人工异常、复盘反馈 | order_record、payment_record、delivery_record、governance_feedback_event | 交付能力要做，但当前不放开真实支付、真实下载、自动退款 |

## 2. 目标运行图

```mermaid
flowchart LR
  UI["Owner 操作台<br/>地区多选/类型多选/金额区间/时间窗口"] --> S0["真实公开来源候选发现<br/>省级入口优先, 全国聚合补充"]
  S0 --> S1["Stage1 市场扫描<br/>候选/评标/结果优先分流, tender_file 作为投前或回溯材料"]
  S1 --> BP["来源蓝图编排<br/>按地区/类型/金额选择公开源组合"]
  BP --> S2["Stage2 公开采集<br/>列表/详情/附件/快照/时钟版本"]
  S2 --> S3["Stage3 结构化解析<br/>project_base/field_lineage/bidder/project_manager"]
  S3 --> S4["Stage4 公开核验<br/>企业/资质/信用/项目/人员/冲突"]
  S4 --> S5["Stage5 规则证据双门<br/>rule_gate + evidence_gate"]
  S5 --> S6["Stage6 统一事实<br/>project_fact/report/review"]
  S6 --> S7["Stage7 可售机会<br/>真实竞争者/买家/报价/商业钩子"]
  S7 --> S8["Stage8 触达计划<br/>联系人/话术/审批/审计"]
  S8 --> S9["Stage9 订单交付治理<br/>支付/证据包/交付/回写"]
  S5 --> R["复核/补证/降级<br/>REVIEW/BLOCK/UNKNOWN"]
  R --> S2
  S9 --> WB["Owner 工作台读回<br/>机会/证据包/缺口/日志/状态"]
```

### 2.1 系统执行大脑摘要

`系统执行大脑` 是把 Stage1-9 串成自主产品链的最小控制面。它不替代具体 parser、公开核验 adapter 或销售治理模块，但负责把“下一步应该跑什么、什么时候 review、什么时候 block”收口成统一运行逻辑。

| 组件 | 当前职责 | 若缺失会怎样 |
| --- | --- | --- |
| `run controller` | 拥有 `run_id`、批次上下文和阶段推进入口 | 系统会退回手工挑 URL、手工点阶段 |
| `stage state machine` | 定义 `NEXT / REVIEW / BLOCK / SUSPEND / DONE` | review/block taxonomy 会漂，阶段结果无法统一 |
| `decision planner` | 负责市场扫描、来源蓝图、SKU 证据路线和核验深度选择 | 会把所有来源和文件一股脑全跑，摩擦过大 |
| `dispatcher` | 把任务派发给 Stage executor 并维持可回放执行顺序 | 实际运行只能靠人盯着重跑 |
| `transition guard` | 阻止弱证据、未审批 provider、客户可见泄露继续推进 | REVIEW/BLOCK 会被误升级成正式结论 |
| `operator intervention gate` | 需要人工复核、审批或审计时暂停并等待 operator action | 真实外部动作和高风险判断无法受控 |
| `audit replay ledger` | 记录每一步输入、输出、判断、下一步和阻断原因 | owner 无法回放链路，也无法解释“为什么这样判断” |

### 2.2 商业钩子线索与披露层级

`商业钩子线索` 是 Stage6/7 的产品化摘要层，不是完整证据包。核心原则不变：卖前给价值感，不给可复现路径。

| 等级 | 使用场景 | 允许表达 | 必须 withheld |
| --- | --- | --- | --- |
| `L0 内部` | owner / 复核人 | 完整项目、证据链、原始载体、核验路径 | 不外发 |
| `L1 钩子` | 初次触达 | 缺陷大类、证据强度、紧迫性、行动收益 | `source_url`、完整负责人身份、完整冲突项目、原始快照、完整核验路径 |
| `L2 意向` | 深度沟通 | 部分脱敏摘要、风险说明、交付轮廓 | 仍不提供可复现原件和内部评分逻辑 |
| `L3 交付解锁` | 付款/审批后交付 | 客户可见证据包、版本、交付说明 | 仍不暴露内部黑箱策略和非客户白名单字段 |

| Stage7 正式字段 | 作用 |
| --- | --- |
| `withheld_fields` | 明确卖前不能泄露的字段和证据链部分 |
| `allowed_sales_talking_points` | 明确卖前可讲范围，避免临场过界 |
| `forbidden_sales_claims` | 明确不能说成“已违法”“已确认”之类的定性 |

### 2.3 来源策略与试点边界

`PTL-I100-143E-autonomous-source-strategy-d-doc-sync` 固定了两条上位口径：

1. 全国聚合平台只作为一级发现、去重和补充查询，不当成全量实时源或唯一核验源。
2. 北京不进入首批商业线索试点，只做技术回归和公开页面可达性验证。

## 3. 状态分层

| 状态 | 含义 | 能做什么 | 不能说什么 |
| --- | --- | --- | --- |
| `NO_CANDIDATES` | 没有真实公开候选 | 展示来源尝试、失败原因、地区和筛选条件 | 不能生成机会 |
| `REAL_PUBLIC_CANDIDATES_CAPTURED` | 真实候选已进入 Stage1-3 | 内部分析、查看候选、看详情快照和解析结果 | 不能说正式可售 |
| `REAL_PUBLIC_REVIEW_REQUIRED` | Stage4-6 或双门未闭合 | 进入 owner 复核，补核验源、补字段、补证据 | 不能生成客户交付结论 |
| `REAL_PUBLIC_RESTRICTED_SALEABLE` | Stage6/7 形成受限销售承接，但 D8-plus、交付或外部治理未闭合 | 内部证据包预览、商业钩子草稿、受限买家适配、受限报价 | 不能包装成完整正式销售推进 |
| `REAL_PUBLIC_INTERNAL_READY` | 真实快照已进入 Stage4-7，Stage5 双门、Stage6 project_fact、Stage7 受控 saleability 均可回放 | 内部证据包预览、正式对象读回、受控销售准备 | 不能直接外发或客户交付 |
| `CUSTOMER_DELIVERY_READY` | D6/D7 字段策略、审批审计、支付交付治理完成 | 受控交付证据包 | 不能绕过审批、审计、operator action |

## 4. 总则级契约摘要

本节只保留 L1 总则，不维护每阶段完整输入、输出和失败枚举。逐阶段 PASS/REVIEW/BLOCK、补证回退、子漏斗和验收动作，以 `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` 为准；Stage4/5 公开核验和双闸门操作细节，以 `docs/AX9S_Stage4-5_核验双闸门SOP.md` 为准。

| 阶段段落 | L1 总则 | 细节单源 |
| --- | --- | --- |
| Stage1-3 进料与字段血缘 | 候选必须来自真实公开源，采集、快照、解析和字段血缘必须可回放。 | L2 执行矩阵、Stage1-2 来源专题 |
| Stage4-5 核验与双闸门 | 公开核验只产出可回放 carrier；规则门和证据门缺一不可，REVIEW/BLOCK 不得升级结论。 | L3 Stage4/5 SOP |
| Stage6 统一事实 | `project_fact` 是内部事实中枢，客户可见前仍需复核、脱敏、禁语和审批。 | L2 执行矩阵、D5-D7 |
| Stage7-9 商业承接与治理 | 商业钩子、触达准备和交付治理只在受控边界内推进，不代表自动外发、自动收款或客户下载放开。 | L2 执行矩阵、D8-D10、自动化动作门禁 |

## 5. 当前代码映射

| 模块 | 当前代码入口 | 已核实用途 |
| --- | --- | --- |
| Owner 实战搜索入口 | `src/api/routes/operator_customer_access.py::run_operator_autonomous_opportunity_search` | 接收地区、类型、金额区间，调用真实候选发现、Stage2 capture、Stage1 market scan 和后续闭环 |
| 通用 Stage1-9 链 | `src/shared/pipeline.py::run_internal_chain` | 按 Stage1 到 Stage9 顺序运行并做 handoff 校验 |
| Stage1 服务 | `src/stage1_tasking/service.py::Stage1Service` | 任务编排和正式 Stage1 bundle |
| Stage1 市场扫描 | `src/stage1_tasking/market_scan.py::Stage1MarketScanEngine` | 对候选做中标候选公示/异议窗口分流，并保留金额、类型、公告阶段、字段完整度评分和复核原因 |
| 来源蓝图编排 | `src/stage1_tasking/source_blueprint.py` | 按地区、来源家族和项目类型形成 Stage2 capture plan |
| 真实候选发现 | `src/stage1_tasking/real_candidate_discovery.py::RealPublicCandidateDiscoveryService` | 从登记公开源发现真实候选，当前 GD/JS/ZJ/SC 有专门 API 路径，SD/HB 仍需补齐 |
| 地区适配器 | `src/stage1_tasking/region_adapters.py` | 登记首批试点地区 SC/JS/ZJ/SD/GD/HB 和全国/北京边界 |
| Stage2 服务 | `src/stage2_ingestion/service.py::Stage2Service` | 公开链和 raw source fetch |
| Stage2 真实候选 capture | `src/stage2_ingestion/real_candidate_capture.py::RealCandidateStage2CaptureService` | 给真实候选补详情快照、附件快照和部分字段 |
| 真实公开入口/附件 fetcher | `src/stage2_ingestion/real_public_url_fetcher.py` | 登记真实来源 profile，抓入口、详情、附件 |
| Stage3 服务 | `src/stage3_parsing/service.py::Stage3Service` | 结构化解析、field lineage 和 parsed carrier |
| Stage4 服务 | `src/stage4_verification/service.py::Stage4Service` | 通用 Stage4 和 `verify_public_parsed_carrier` 真实公开核验读回 |
| Stage5 服务 | `src/stage5_rules_evidence/service.py::Stage5Service` | 规则证据和 public verification readback |
| Stage6 real public | `src/stage6_fact_review/service.py::Stage6Service.run_real_public_rule_evidence_readback` | 要求 Stage4 公开核验 refs、公开边界、双门和 product package readiness |
| Stage7 real public | `src/stage7_sales/service.py::Stage7Service.run_real_public_product_package_readback` | 要求 Stage6 real_public summary、leadpack、commercial hook、真实竞争者状态 |
| Stage8 real public | `src/stage8_outreach/service.py::Stage8Service.run_real_public_sales_execution_readback` | 生成真实公开销售执行读回，但不执行真实外发 |
| Stage9 real public | `src/stage9_delivery/service.py::Stage9Service.run_real_public_outreach_delivery_readback` | 生成真实公开交付治理读回，但不执行真实支付、下载、退款 |
| Owner UI | `src/api/routes/operator_frontend.py` | 展示搜索、阶段总览、机会、证据包、验收契约、缺口矩阵 |

## 6. 已核实落地性

这些不是愿景，当前仓库已经有基础：

1. `run_internal_chain` 确实串起 Stage1 到 Stage9，并在阶段间做 handoff 校验。
2. 操作台实战搜索入口已经支持地区列表、项目类型列表、金额区间，并且默认不会合成离线样本。
3. 真实候选发现服务已经存在，广东、江苏、浙江、四川有专门候选发现实现路径；这代表代码路径存在，不代表每次公网请求都能实时成功。
4. 真实候选 Stage2 capture 已经存在，能尝试抓详情页、附件页并写入 snapshot refs。
5. Stage4 到 Stage9 已经存在 real_public readback 专用函数。
6. Owner UI 已经能展示搜索运行、候选明细、阶段总览、机会详情、内部证据包预览和验收缺口。

## 7. 高维剩余缺口评估

这些缺口按当前代码和运行产物重新表述为“能力建设缺口”。它们不是说系统没有任何链路，而是说明哪些地方还不能被包装成稳定客户交付能力。

| 维度 | 当前状态 | 未补风险 | 当前下一步 |
| --- | --- | --- | --- |
| 执行大脑 | 已有调度、队列、operator action 和第一版自主编排 | 真实来源/分支容易退回人工判断 | 用真实样本继续压测状态机、guard 和 replay |
| 市场与公开源策略 | 已有真实候选发现、来源蓝图和试点省份口径 | 新地区和新 source family 仍会缺 profile / adapter | 继续补多省多城真实候选发现和来源覆盖 |
| 证据质量与解析核验 | 已有 Stage2-5 readback、parser、公开核验和双门 | 弱证据、同名、缺 source slice 仍会制造 review 噪音 | 继续补 SKU 规则样本和公开源补查 |
| 商业价值与钩子转化 | 已有商业钩子、buyer fit、offer 建议和受限机会 | 卖前泄露和“说过头”风险仍在 | 收紧 L0-L3 披露层级和人工审核 |
| owner 可操作性 | 已有工作台、阶段总览、缺口和 readback | 复杂缺口仍可能让接手代理绕路读旧稿 | 把高价值内容吸收到 L1/L2/状态板 |
| 外部执行与客户交付 | provider、支付、交付、下载都仍 gated | 容易被误解为“已经可外发/可交付” | 继续维持 controlled-opening 边界 |
| 真实样本验收 | 已有真实公开样本 acceptance | 少数成功样本会掩盖长尾失败 taxonomy | 扩地区、扩附件、扩失败样本覆盖 |

1. **真实候选 Stage4-9 formal readback 已有入口，但还要按真实项目持续压测**
   - 当前代码已有 `_build_real_public_stage4_9_readback_from_candidate`，可把真实详情/附件/parser readback 送入 `Stage4Service.verify_public_parsed_carrier`，再进入 Stage5 双门、Stage6 product package、Stage7 商业钩子和 Stage8/9 受控读回。
   - 仍需继续验证的是：不同来源、不同附件形态、不同字段缺失和不同 source blocker 下，链路是否稳定进入 `INTERNAL_READY`、`REVIEW_REQUIRED`、`PENDING_DETAIL_CAPTURE`、`PENDING_TIME_BUDGET` 等状态，而不是只在少数样本上可跑。

2. **时钟字段存在误判风险**
   - Stage1 会按 `objection_deadline_at_optional` 判断窗口。
   - Stage2 候选 capture 需要严格区分公告发布日期、发布时间、投标截止、异议截止、质疑截止和项目编号。公告日期或编号片段不能被当成截止时间。

3. **机会状态需要分层**
   - UI 可以查看机会，但真实候选被选中不等于正式 `saleable_opportunity`。
   - 必须拆成线索、内部可复核、受限可售、正式可售、客户交付就绪五层。

4. **证据包仍是内部预览**
   - 当前证据包预览和下载适合 owner 验收 UI 和内容。
   - 但客户交付前必须补 D6/D7 字段策略、审批审计、水印、版本、delivery_record 和 release checklist。

5. **试点地区实现不均衡**
   - SC/JS/ZJ/GD 有专门候选发现路径。
   - SD/HB 已登记入口 profile，但缺专门候选发现实现和真实列表解析回归。

6. **核验目标自动生成仍要按 SKU 细化**
   - Stage4 real_public 能力存在，但真实候选进入 Stage4 时还需要按 SKU 自动生成更细核验目标：企业、人员、资质、信用处罚、项目经理未释放、地方许可、合同履约、竣工释放、公告/投标文件响应冲突等。

7. **Stage7/8 正式中间对象必须纳入验收**
   - Stage7 不只是 `saleable_opportunity`，还需要 `multi_competitor_collection`、双 actor 对象和选择 trace。
   - Stage8 不只是 `contact_target`，还需要 `contact_candidate_collection` 和 `contact_selection_trace`，否则联系人选择会退回散输入。

8. **模型治理不能隐含**
   - 如果后续接入大模型，模型只能辅助摘要、解释、草稿、排序。
   - 任何进入正式对象、证据包、法律建议或触达执行的模型输出都需要 `model_governance_record`。

## 8. 反幻觉检查规则

后续任何修复必须通过这些问题，否则图纸不算落地：

1. 这个阶段的输入是不是来自上游正式对象，而不是 UI 临时状态、销售备注或模型总结？
2. 这个阶段的输出是不是写入正式对象或正式 readback，而不是只显示在页面上？
3. 真实候选有没有原始来源 URL、snapshot id、source slice 和字段血缘？
4. Stage5 是否同时有 `rule_gate_decision` 和 `evidence_gate_decision`？
5. Stage6 是否有唯一 `project_fact`，并且后续销售不重算主结论？
6. Stage7 是否有真实竞争者、`multi_competitor_collection`、双 actor 拆分、买家适配、报价策略和 withheld fields？
7. Stage8 是否先形成 `contact_candidate_collection` 和 `contact_selection_trace`，再形成 `contact_target`？
8. Stage9 是否有审批、审计、水印、版本、支付交付状态和 provider 回写？
9. 当前状态是不是内部回归、内部预览、正式可售、客户交付就绪之一，不能混说？
10. 测试是否只维护旧口径，还是按本图纸验证真实链路？

## 9. Stage4/5 核验细节单源

Stage4 项目负责人、证书、注册单位、履约窗口、释放证据、信用处罚和双闸门细节不再在 L1 维护。L1 只保留总则：公开核验必须有 readback、字段血缘和失败 taxonomy；Stage4 不输出客户结论；Stage5 必须同时通过 rule gate 与 evidence gate。

细节单源见 `docs/AX9S_Stage4-5_核验双闸门SOP.md`，包括：

1. 项目负责人企业优先补证、同名消歧、证书/注册单位匹配。
2. 负责人未释放/履约重叠宽筛与命中后的释放证据定向补查。
3. 四库/JZSC、全国公路建设市场监督管理系统、地方许可/合同/竣工/变更、信用处罚等多源核验链。
4. Stage5 `rule_gate_decision` 与 `evidence_gate_decision` 的 PASS/REVIEW/BLOCK 输出边界。

## 10. 修复顺序

按落地效率和产品风险，后续修复顺序应为：

1. **真实候选 Stage4-9 formal readback 压测与缺口收敛**
   - 目标：真实详情快照、附件快照和 Stage3 parser readback 稳定进入 Stage4 公开核验，再进入 Stage5/6/7/8/9 readback，并对每种失败形态给出 taxonomy。
   - 验收：不能用少数成功样本冒充普遍稳定；`REVIEW_REQUIRED`、`PENDING_DETAIL_CAPTURE`、`PENDING_TIME_BUDGET`、`SOURCE_BLOCKED` 等状态必须能被 UI 和产物读回。

2. **截止时间和时钟字段解析修复**
   - 目标：公告发布日期、发布时间、投标截止、异议截止、质疑截止、项目编号全部分清。
   - 验收：没有明确截止标签时进入 review/unknown，不能制造过期或未过期结论。

3. **状态分层和 UI 显示修复**
   - 目标：候选已进料、需复核、受限可售、正式可售、客户交付就绪分开显示。
   - 验收：owner 不会把内部预览误认为客户可交付。

4. **山东、湖北候选发现器补齐**
   - 目标：SD/HB 从入口登记升级为真实列表候选发现和解析回归。
   - 验收：6 个商业试点省的能力状态按真实实现显示，不做同等可跑假象。

5. **证据包正式对象绑定**
   - 目标：证据包预览绑定 field lineage、dual gates、project_fact、source snapshots 和 release state。
   - 验收：证据包能解释为什么值钱、为什么能卖、哪些不能卖前泄露。

6. **provider sandbox / live pilot**
   - 目标：真实触达、支付、交付服务商进入 sandbox、健康检查、审批审计和小样本 pilot。
   - 验收：真实外部动作仍需 operator action；自动退款继续排除。

## 11. 当前结论

当前系统不是白做，也不是完全实战可交付。它已经有 Stage1-9 内部链路、真实候选进料、详情/附件 capture、UI 读回、real_public Stage4-9 readback、商业钩子和操作台基础。真正需要继续收敛的是：把这些能力按 SKU 和真实公开源持续压测，把成功、复核、阻断、待补源和待定向解析状态分清，并确保每条证据都有来源 URL、snapshot/readback、hash、字段血缘和失败 taxonomy。

因此下一轮不应继续做泛 UI 优化，应从 **真实候选 Stage4-9 formal readback 压测、Stage4 公开核验源补强、Stage5 SKU 规则双闸门样本化** 开始。
