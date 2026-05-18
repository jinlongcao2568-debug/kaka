# AX9S 产品主图与验收总则

**版本**: 2026-05-17 v3

## 0. 目的

本文件是 AX9S 的 **L1 产品主图 / 总口径 / 当前能力快照**。

它只回答 4 个问题：

1. 产品到底是什么
2. 当前默认业务入口是什么
3. Stage1-9 主链做到什么才算完成
4. 当前最大的能力缺口在哪

本文件不替代 `docs/L0.md`、D2-D14、`handoff/stage_handoff_catalog.json` 和 `control/product_runtime_architecture_map.yaml`；如有冲突，以这些权威源为准。

验收口径固定为：

- 本文件验收的是 **`docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` 所覆盖的 Stage1-9 全链产品闭环是否成立**
- `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` 验收的是 **各阶段模块、输入/输出、PASS/REVIEW/BLOCK 与补证回退是否成立**
- `docs/专题_Stage1-9_缺口收口与优先级清单.md` 负责把上述目标模型投射成当前真实缺口，不另起第二套验收体系

## 0.1 文档分工

| 文档 | 作用 | 不替代什么 |
| --- | --- | --- |
| `AGENTS.md`、`README.md` | 入口、执行方式、边界、最小读序 | 不冻结当前任务状态 |
| `docs/业务方向_候选公示后证据包与投前预测双线契约.md` | 双线业务方向和输出禁令 | 不展开完整 Stage1-9 工程漏斗 |
| `docs/AX9S_产品主图与验收总则.md` | 产品运行总地图、当前能力快照、L1 验收原则 | 不替代 `control/*` 动态状态源 |
| `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` | 每阶段输入、分支、PASS/REVIEW/BLOCK 和补证回退 | 不替代双线业务方向契约 |
| `docs/AX9S_Stage4-5_核验双闸门SOP.md` | Stage4 公开核验和 Stage5 双闸门的 L3/L4 细则 | 不直接生成客户结论 |
| `docs/专题_Stage1-9_缺口收口与优先级清单.md` | 当前真实缺口投影、减少缺口和优先级 | 不另起第二套产品目标或验收体系 |

## 0.2 当前开发口径

当前阶段不是“马上卖证据包”，而是把证据生产系统的能力全部做扎实。每一步能力都必须经过真实公开源、真实项目、真实附件、真实失败场景验证，并留下可回放产物。

这意味着：

1. SKU 是能力验收方向，不是当前必须立即外发销售的动作。
2. 没有 Stage2/3 的可回放采集、下载、解析和字段血缘，后续 Stage4-9 都不能产生稳定价值。
3. 查不到、源阻断、字段缺失、同名未消歧、附件失败，都只能进入 taxonomy / review，不能写成“无风险”或“已排除”。
4. 对外触达、真实交付、收款、客户下载和 release 仍属于受控开放能力，必须走审批、审计、operator action 和对应 gate。

## 0.3 SKU 只是反推能力的验收靶

当前主业务不是 5 个正式 SKU，而是 5 个**业务证据专题**。`LeadPack 商业封装档位 A/B/C` 只决定 Stage7 后商业包装，不等于 Stage1-6 的证据路线。

当前首批业务证据专题：

- 证书/注册单位/时间异常包
- 负责人未释放/履约冲突包
- 信用处罚/监管风险包
- 综合质疑证据包
- 投前萝卜标/限制竞争预测包

辅助方向：

- 程序时间线/公示流程缺陷包
- 竞争格局/陪标围标线索包

受限信号：

- 社保造假不单独作为首批 SKU，只作为综合质疑证据包里的 `08` 定向解析和人工复核信号，不单独作为首批 SKU

负责人未释放/履约冲突包必须拆成两个子漏斗：

1. `证书/注册单位/时间异常包 -> 负责人未释放/履约冲突宽筛`
2. 负责人未释放深查只在宽筛命中同人/同主体/时间窗口疑似重叠后触发

这条链不得默认全量下载 01-12，也不得默认解析 `08`。

## 0.4 当前能力快照

这是当前 L1 人类可读快照，动态 readiness 仍以 `control/repo_status.md`、`control/current_task.yaml`、`control/milestone_status.yaml` 为准。

- Stage1-9 内部运营主链已成型，144-149 自主机会发现、来源蓝图、公开采集加固、验证码/挑战续跑、证据风险、商业钩子、买家排序和操作台 readback 已完成内部闭环。
- 广州候选后链路已多轮验证，广州不是当前主要阻塞点，不应无目的回头大改主链。
- YGP 广东其他城市基础链已具备城市发现、01-12 项目流程矩阵、附件下载门禁；但这不等于广东全省 fully covered，也不等于 YGP 恢复为广州主源。
- 负责人未释放/履约重叠宽筛已能用 `data.ggzy` 公司历史成交和 `bid_show` 做第一层宽筛；`bid_show` 已有负责人和合同/交付/履约时间时直接进入时间窗口复核，字段不足时才走原文链接和 YGP readback；未命中不等于无风险。
- Stage4 路桥设计证书补充已能走全国公路建设市场监督管理系统路线，补四库/JZSC 不覆盖的人证路径。
- Stage8/9 已有内部受控 readback 语义，但不代表绕过审批审计和 operator action 自动外发或交付。

## 0.5 能力完成标准

一个阶段或分支不能只因为“有代码”或“测试绿”就算完成。完成必须同时满足：

1. 能用真实公开样本跑出输入、输出和失败形态。
2. 产物有来源 URL、采集时间、snapshot/readback、hash、字段血缘和脚本/adapter 版本。
3. PASS、REVIEW、BLOCK 三类路径都有明确条件，失败 taxonomy 不为空。
4. 输出能被下游正式对象消费，而不是只显示在 UI 或临时 JSON。
5. 客户可见前经过字段策略、脱敏、禁语、审批、审计和交付版本控制。

## 1. 产品目标一句话

AX9S 是 owner 内部使用的真实公开市场机会发现和证据包商业化运营系统。系统要从真实公开来源发现工程类机会，抓取详情和附件，解析关键字段，做公开核验和规则证据判断，形成统一事实、可售机会、买家适配和商业钩子，最后在审批、审计、支付、交付治理下把证据包作为成交后的交付物输出。

系统每天自动找工程项目里的可售硬伤，但这个“自动”只指公开发现、公开核验、产品化编排和受控 readback，不指自动外发、自动收款、自动交付或自动法律定性。

### 1.1 默认业务入口

招投标分析默认按 `docs/业务方向_候选公示后证据包与投前预测双线契约.md` 和 `contracts/evaluation/business_direction_strategy_contract.json` 执行双线产品路由。

- 核心商业主线是候选公示后证据包分析：默认先从近期 `07 中标候选人公示` 入池，再回溯同一项目的招标公告、招标文件、答疑澄清、开标、投标文件公开、候选和结果材料；评标结果、开标记录、中标结果、合同和异常材料不是默认入口。近期 07 项目通常没有 11 合同和 12 异常，缺 11/12 不阻断当前证据包销售窗口。
- 辅助产品线是投前预测分析：只适用于 `02 招标文件公示`、`03 招标公告/关联公告`、`04 答疑澄清/补遗` 且投标截止/开标未过的项目；若已经出现 `05 开标信息`，投前预测不再适用。
- `AnalysisStrategyPlan v1` 是 Stage2 附件清单和 Stage3 解析之间的必经策略层。
- `tender_file` smoke 只验证文件链路、snapshot 和解析，不是最终业务入口，只验证文件链路。

### 1.2 Stage1-9 逐阶段优化评估与漏斗展开总表

| 阶段 | 核心问题 | 当前产物 | 当前主缺口 |
| --- | --- | --- | --- |
| Stage1 候选池 | 哪些真实项目值得进入证据生产线 | candidate pool、source blueprint、skip taxonomy | 多省多城真实候选发现仍需稳定化 |
| Stage2 公开载体 | 材料是否可回放、可审计、可归属 | flow matrix、attachment manifest、snapshot/readback、hash | 继续补附件失败、SPA 壳、验证码、限流、超大附件 defer |
| Stage2.5 AnalysisStrategyPlan | 先决定产品线、流程范围、解析深度 | product analysis strategy plan | 防止“发现文件就全量深解析” |
| Stage3 字段血缘 | 能否抽出可核验字段 | project_base、bidder_candidate、field_lineage_record | 继续强化 08 定向解析、OCR 和复杂表格 |
| Stage4 公开核验 | 字段是否与公开记录匹配 | public verification carrier、source readback | 多省地方 source adapter 与释放证据补查仍弱 |
| Stage5 双闸门 | 规则是否命中、证据是否足够 | rule_gate_decision、evidence_gate_decision、review_request | 真实 PASS/REVIEW/BLOCK 样本还不够 |
| Stage6 project_fact | 哪些线索能进入统一事实和复核队列 | project_fact、report_record、review_queue | 继续把真实候选 formal real_public 链强制回 Stage4-9 |
| Stage7 商业钩子 | 这条线索未来卖给谁、卖什么版本 | saleable_opportunity、buyer_fit、offer_recommendation | 继续限制卖前泄露和“说过头” |
| Stage8 触达准备 | 未来如何合规触达但不泄密 | contact candidate、outreach plan、touch record | 真实发送仍 gated |
| Stage9 交付治理 | 成交后如何交付可复核证据并回写 | order / payment / delivery / feedback | 当前不放开真实支付、真实下载、自动退款 |

## 2. 目标运行图

`Stage1-9 逐阶段优化评估` 的目标不是让 owner 手工挑 URL，而是形成可回放的产品闭环：

`市场扫描 -> 来源蓝图 -> 公开采集 -> 解析/字段血缘 -> 公开核验 -> 双闸门 -> project_fact -> 商业钩子 -> 触达准备 -> 交付治理`

### 2.1 系统执行大脑摘要

系统执行大脑只负责把 Stage1-9 串成自主产品链，不替代 parser、公开核验 adapter 或销售治理模块。

| 组件 | 当前职责 | 若缺失会怎样 |
| --- | --- | --- |
| run controller | 维护 `run_id`、批次上下文和阶段推进入口 | 系统退回手工挑 URL |
| stage state machine | 定义 `NEXT / REVIEW / BLOCK / SUSPEND / DONE` | review / block taxonomy 漂移 |
| decision planner | 负责市场扫描、来源蓝图、SKU 证据路线和核验深度选择 | 所有来源和文件会被一股脑全跑 |
| transition guard | 阻止弱证据、未审批 provider、客户可见泄露继续推进 | REVIEW / BLOCK 被误升级成正式结论 |
| operator intervention gate | 需要人工复核、审批或审计时暂停等待 operator action | 高风险路径无法受控 |
| audit replay ledger | 记录每一步输入、输出、判断、下一步和阻断原因 | owner 无法回放链路 |

## 3. 商业钩子线索与披露层级

商业钩子线索是 Stage6/7 的产品化摘要层，不是完整证据包。核心原则不变：**卖前给价值感，不给可复现路径**。

| 等级 | 使用场景 | 允许表达 | 必须 withheld |
| --- | --- | --- | --- |
| L0 内部 | owner / 复核人 | 完整项目、证据链、原始载体、核验路径 | 不外发 |
| L1 钩子 | 初次触达 | 缺陷大类、证据强度、紧迫性、行动收益 | `source_url`、完整负责人身份、完整冲突项目、原始快照、完整核验路径 |
| L2 意向 | 深度沟通 | 部分脱敏摘要、风险说明、交付轮廓 | 仍不提供可复现原件和内部评分逻辑 |
| L3 交付解锁 | 付款 / 审批后交付 | 客户可见证据包、版本、交付说明 | 仍不暴露内部黑箱策略和非客户白名单字段 |

## 4. 来源策略与试点边界

`PTL-I100-143E-autonomous-source-strategy-d-doc-sync` 固定了两条上位口径：

1. 全国聚合平台只作为一级发现，不当成全量实时源或唯一核验源。
2. 北京不进入首批商业线索试点，只做技术回归和公开页面可达性验证。

补充：

- 公开网抓取失败自动升级由 `PTL-I100-150-public-web-adaptive-capture-hardening-and-failure-escalation` 承接
- 自动验证码 / 挑战续跑由 `PTL-I100-151-public-web-captcha-automated-resolution-and-resume` 承接
- Stage1 自主市场扫描与机会发现由 `PTL-I100-144-market-scan-opportunity-discovery-engine` 起步
- 当前真实样本 acceptance 闭环以 `PTL-I100-149-real-sample-autonomous-opportunity-acceptance` 为历史能力锚点

## 5. 高维剩余缺口评估

当前系统不是白做，也不是完全实战可交付。真正还需要继续收敛的是：

1. **执行大脑仍需持续压测**
   真实来源、失败 taxonomy 和 replay 仍要继续磨。
2. **Stage4 外部证据链仍最弱**
   尤其是负责人未释放 / 履约重叠命中后的释放证据深查。
3. **证据质量与解析核验仍会制造 review 噪音**
   弱证据、同名、缺 source slice 仍会推高人工复核成本。
4. **商业价值与钩子转化仍要继续控泄露**
   不让内部摘要误变成卖前可复现证据。
5. **外部执行与客户交付仍是受控开放**
   真实发送、真实支付、真实下载、自动退款仍不能误写成已开放。

## 6. 总则级契约摘要

本节只保留 L1 总则，不维护每阶段完整输入、输出和失败枚举。逐阶段 PASS/REVIEW/BLOCK、补证回退和子漏斗，以 `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` 为准；Stage4/5 公开核验和双闸门操作细节，以 `docs/AX9S_Stage4-5_核验双闸门SOP.md` 为准。

- Stage1-3：候选必须来自真实公开源，采集、快照、解析和字段血缘必须可回放
- Stage4/5：公开核验只产出可回放 carrier；Stage4/5 公开核验和双闸门操作细节看 `docs/AX9S_Stage4-5_核验双闸门SOP.md`
- Stage6：`project_fact` 是内部事实中枢
- Stage7-9：商业钩子、触达准备和交付治理只在受控边界内推进，不代表自动外发

## 7. 当前结论

当前最值得继续做的，不是泛 UI 优化，也不是重写路线，而是：

- 用真实候选继续压测 Stage4-9 formal readback
- 补强 Stage4 公开核验源和释放证据链
- 按业务证据专题持续补 Stage5 规则 / 证据双闸门样本
- 在保证受控边界的前提下，把这些能力稳定收成可回放、可复核、可销售承接的内部产品链

## 8. 长稿归档

2026-05-17 瘦身前长稿已归档到：

- `archive/non_current_docs/AX9S_产品主图与验收总则_2026-05-17瘦身前长稿.md`

当前现行版只保留 L1 产品主图摘要；长稿保留旧表格、长解释和历史细枝末节，供历史复核使用。
