# AX9S 自动运营决策架构与商业钩子方案

本文承接 `PTL-I100-143D-business-decision-architecture-and-hook-lead-roadmap-sync`。它不是 runtime 实现说明，而是后续 `144-149` 的产品运行契约：系统不能退化成手工选 URL 或零散 carrier，而必须自主发现可售工程异议机会。

## 一、产品运行目标

AX9S 销售的不是软件，也不是普通招投标信息查询服务，而是公开证据驱动的工程异议线索包和证据包。

系统每天应自动回答这些问题：

1. 今天哪些市场和公告值得扫？
2. 哪些公开源组合最适合当前市场和规则目标？
3. 哪些项目有疑似硬伤？
4. 证据是否公开可复核？
5. 这个硬伤是否有异议价值？
6. 谁最可能买？
7. 销售前能透露到什么程度？
8. 什么必须付款、审批、交付后才能给？
9. 哪些内容必须人工复核？
10. 哪些动作必须阻断？

## 二、核心运行图

```mermaid
flowchart TD
  A["每日市场扫描批次"] --> B["机会发现引擎<br/>地区、行业、金额、公告阶段、异议窗口"]
  B --> C["公开源蓝图编排<br/>交易平台、政采、四库一平台、信用、企信、主管备案"]
  C --> D["Stage2 采集计划<br/>入口页、列表页、详情页、附件、重试、频控"]
  D --> E["公开快照固定<br/>HTML/PDF/附件、hash、source lineage"]
  E --> F["Stage3 解析<br/>字段候选、source slice、confidence、UNVERIFIED"]
  F --> G["Stage4 公开核验<br/>企业、人员、资质、信用、许可、合同、履约"]
  G --> H["Stage5 硬伤规则<br/>项目经理在建、资质、信用、业绩、程序瑕疵"]
  H --> I["Stage6 产品化<br/>异议价值、证据强度、可售判断、钩子线索"]
  I --> J["Stage7 买家识别<br/>真实竞争者、buyer fit、报价、LeadPack"]
  J --> K["Stage8 受控触达<br/>模板、审批、频控、退订、provider gate"]
  J --> L["Stage9 订单交付账本<br/>订单、支付、发票、交付、对账、人工退款异常"]
  K --> M["Owner 操作台<br/>机会队列、证据、钩子、复核、下一步"]
  L --> M
  M --> N["客户材料门户<br/>审批后客户可见版本、下载授权、审计"]
```

## 三、判断方式分工

| 阶段 | 判断内容 | 主要方式 | LLM 边界 |
|---|---|---|---|
| 市场扫描 | 哪些地区、工程类型、金额区间、公告阶段值得扫 | 规则 + 算力 | 不需要 |
| Source 编排 | 哪些公开源组合要跑 | 规则 | 不需要 |
| 公开采集 | URL 是否合规、是否降级、是否去重 | 规则 + 算力 | 不需要 |
| Stage3 解析 | 从公告/附件抽字段候选 | parser + LLM 辅助 | 只能辅助候选抽取 |
| Stage4 核验 | 企业/人员/信用/备案是否公开匹配 | 规则 | LLM 不得下事实结论 |
| Stage5 规则 | 是否命中硬伤 | 规则 | 只能解释草稿 |
| Stage6 产品化 | 是否值得卖、证据强弱、钩子披露等级 | 规则 + 算力 + LLM 摘要辅助 | 不得生成客户确定结论 |
| Stage7 销售 | 谁最可能买、报价、话术 | 算力 + 规则 + LLM 话术辅助 | 话术必须过白名单和禁语过滤 |
| Stage8 触达 | 能不能触达、何时触达 | 规则 + 审批 | 不得自动发送 |
| Stage9 交付 | 能不能交付、交付什么版本 | 规则 + 审计 | 不需要 |

## 四、Stage1-9 逐阶段优化评估

已有 `112-143` 不是白做，它们提供了受控入口、真实公开快照、解析、核验、规则、产品包、销售对象、触达/支付/交付 readback 和操作面基础。现在缺的是把这些能力串成“系统自主决策”的产品运行链，而不是让 owner 手工挑 URL、手工判断值不值得卖。

| 阶段 | 当前基础 | 仍需优化的自主决策 | 判断方式 | 后续承接 |
|---|---|---|---|---|
| Stage1 任务编排 | 内部调度、任务入口、readback 已有 | 自动选择地区、工程类型、金额区间、公告阶段、异议窗口和 source blueprint batch | 规则 + 算力 | `144`、`145` |
| Stage2 公开采集 | 公开 URL/附件 fetcher、snapshot、hash、lineage 已有 | 根据 Stage1 计划自动决定入口页、详情页、附件、去重、重试、降级，不走手工 URL 主流程 | 规则 + 算力 | `145`、`149` |
| Stage3 解析 | 真实快照进入 parser pilot 已有 | 自动选择 parser、抽字段候选、识别 source slice、冲突字段和复核原因 | parser + 算力 + LLM 候选辅助 | `146`、`149` |
| Stage4 公开核验 | 企业/人员/资质/信用/许可/合同/履约 carrier 和在建冲突切片已有 | 自动决定查哪些公开核验源、如何做同名消歧、如何处理弱证据和冲突 | 规则 | `146` |
| Stage5 规则证据 | catalog-aware rule factory 已有 | 自动优先跑高商业价值硬伤，输出 promote/review/block 原因并喂给 Stage6 | 规则，LLM 只写解释草稿 | `146`、`147` |
| Stage6 产品化 | product package readiness 已有 | 判断线索值不值得卖，生成商业钩子、披露等级、withheld fields、leakage risk | 规则 + 算力 + LLM 摘要辅助 | `147`、`148` |
| Stage7 销售 | 真实竞争者、buyer fit、offer、LeadPack readback 已有 | 从商业钩子选择买家、报价、销售话术、禁语过滤、CRM/quote gate | 算力 + 规则 + LLM 话术辅助 | `147`、`148` |
| Stage8 触达 | approved provider execution readback 已有 | 根据钩子生成触达计划、模板、频控、退订、quiet hours 和 provider gate | 规则，LLM 只写话术草稿 | `148`、`149` |
| Stage9 交付 | 订单、支付、交付、人工退款异常 readback 已有 | 根据审批/付款/交付 gate 解锁客户版本，记录下载、对账、回滚，自动退款继续排除 | 规则 + 审计 | `148`、`149` |

结论：每个阶段都有优化空间，但优化方向不是重写，而是把已有受控能力接成自主产品决策链。LLM 只进入候选抽取、摘要、复核提示和销售话术草稿；事实判断、公开核验、规则命中、客户结论、触达发送、支付交付和退款都不能交给模型直接决定。

## 五、系统执行大脑

现在仓库里已经有一些执行零件：

- `Stage1Scheduler`：能创建内部调度任务、执行窗口、重试/暂停/恢复、Stage2 intent。
- `worker_queue`：能持久化 queue item、lease、heartbeat、retry、timeout、suspend、dead-letter、audit replay。
- Stage1-6 internal orchestration：能跑 sanitized/offline 内部链路，并把 Stage6 readback 持久化。
- operator action / workbench：能记录人工复核、审批、下一步动作和 readback。

但这还不是完整“系统大脑”。当前 bootstrap 仍明确显示 `stage1_scheduler_enabled=false`、`executes_real_orchestrator=false`。也就是说，系统有队列、调度和操作台基础，但还没有一个产品级 autonomous run controller 自动把 Stage1 推到 Stage9。

后续必须补的执行大脑如下：

| 组件 | 职责 | 如何推动下一步 |
|---|---|---|
| run controller | 拥有 `run_id`、stage graph、全局状态机 | 根据上一步结果创建下一阶段 queue item |
| stage state machine | 定义 Stage1-9 的 allowed states 和 transitions | 输出 `NEXT / REVIEW / BLOCK / SUSPEND / DONE` |
| decision planner | 做市场扫描、source mix、硬伤策略、商业价值、钩子披露判断 | 给下一阶段 executor 生成明确 payload |
| work queue dispatcher | lease 到期任务并调用允许的 stage executor | 成功则推进，失败则 retry/suspend/dead-letter |
| transition guard | 防止弱证据、未审批 provider、客户可见泄露继续推进 | fail closed 到 review/block/operator action |
| operator intervention gate | 需要人工复核/审批/审计时暂停 | 只有 repository-backed operator action 才能 resume |
| audit replay ledger | 记录每一步输入、输出、判断、下一步和阻断原因 | 操作台和验收能回放，不靠人工口头解释 |

因此 144 不能只做“扫描规则”，还要建立第一版 autonomous run controller 和 stage state machine；145-149 再逐步把 source、parser、verification、rule、Stage6 钩子、Stage7 销售、Stage8 触达、Stage9 交付挂到这个控制器上。

每一步靠什么推动：

1. 定时/手动启动 run controller，生成 market scan batch。
2. Stage1 decision planner 选择值得分析的机会，写入 queue。
3. worker dispatcher lease 任务，调用对应 stage executor。
4. stage executor 写入 repository-backed result。
5. transition guard 读取 result，决定 `NEXT / REVIEW / BLOCK / SUSPEND / DONE`。
6. 如果是 `NEXT`，创建下一阶段 queue item。
7. 如果是 `REVIEW`，创建 operator action，操作台显示需要人工处理。
8. 如果是 `BLOCK/SUSPEND`，停止推进并记录原因。
9. 所有动作进入 audit replay ledger，供验收和回放。

这个大脑不能依赖 Codex 或人手工挑每个 URL，也不能让 LLM 直接决定事实、核验、触达、支付、交付或退款。

## 六、商业钩子线索

Stage6/Stage7 必须增加一个产品层概念：商业钩子线索。它不是完整证据包，而是销售前给客户感知价值的受控摘要。

核心原则：

> 卖前给价值感，不给可复现路径；付款或审批后，才给完整证据链。

### 6.1 三个版本

| 版本 | 使用者 | 内容范围 |
|---|---|---|
| 内部完整版 | owner / 复核人 | 完整项目、第一名、硬伤、URL、快照、核验、规则命中、风险 |
| 销售钩子版 | 销售触达 | 地区、项目类型、金额区间、公告阶段、硬伤大类、证据强度、紧迫性 |
| 客户交付版 | 付款/审批后客户 | 完整公开证据链、来源、hash、核验说明、交付版本、风险说明 |

### 6.2 销售前禁止泄露

销售钩子不得泄露：

- 具体 source URL
- 完整项目经理姓名 + 注册编号组合
- 完整冲突项目名称
- 完整时间重叠区间
- 原始快照或附件
- 完整核验路径
- 内部评分模型
- 买家排序逻辑
- 未复核推断

### 6.3 销售前可以表达

销售钩子可以表达：

- 某地区、某工程类型、某金额区间
- 某公告阶段仍有时间窗口
- 第一候选人存在某类公开可查风险
- 证据强度为高/中/需复核
- 你方作为落选或竞争方可能有直接利益
- 完整证据包需确认购买或审批后交付

### 6.4 披露等级

| 等级 | 用途 | 可说 | 不可说 |
|---|---|---|---|
| L0 内部 | 内部复核 | 全量证据 | 不外发 |
| L1 钩子 | 初次触达 | 大类、价值、紧迫性 | 不给可复现证据链 |
| L2 意向 | 深度沟通 | 部分脱敏摘要、风险说明 | 不给完整路径和原件 |
| L3 交付 | 付款/审批后 | 客户可见证据包 | 仍不暴露内部黑箱 |

## 七、高维剩余缺口评估

从产品能自主运营的标准看，剩余缺口不是“再补几个字段”，而是下面七类：

| 维度 | 当前状态 | 如果不补会怎样 | 后续承接 |
|---|---|---|---|
| 执行大脑 | 有 scheduler / queue / orchestration / operator action 零件，但不是自运行控制器 | 系统仍靠 Codex 或 owner 判断下一步 | `144` |
| 市场与公开源策略 | 有真实公开 fetcher 和样本验证，但 source strategy 还没产品化 | owner 仍像人工研究员一样选站点和 URL | `144`、`145` |
| 证据质量与解析核验 | 有真实快照、parser、verification pilot | 弱证据、同名、缺 source slice 可能变成错误商业信号 | `146`、`149` |
| 商业价值与钩子转化 | 有 Stage6 package、Stage7 buyer fit/readback | 系统能发现问题，但不能稳定生成可销售且不泄密的钩子 | `147` |
| owner 可操作性 | 有操作台入口和 readback | owner 仍要看 raw JSON 或找 Codex 判断 | `148` |
| 外部执行与客户交付 | provider、支付、交付、下载都已 gated/readback | 如果不绑定 run，会变成零散审批动作，不是产品闭环 | `148`、`149` |
| 真实样本验收 | 有受控真实公开 pilot | 测试绿但不能证明真实样本能自主跑到商业钩子 | `149` |

判断一件事是否真的补齐，不能只看测试绿，要问：

1. 系统能不能自己决定下一步？
2. owner 是否不用 raw API 也能看懂和操作？
3. 弱证据是否会自动 review/block？
4. 销售钩子是否能引流但不泄露完整证据路径？
5. 真实公开样本能否从市场扫描跑到可售钩子和交付候选？
6. 所有 provider、触达、支付、交付、下载是否仍走审批、审计、operator action 和 replay？

## 八、后续实施路线

1. `PTL-I100-144-market-scan-opportunity-discovery-engine`  
   做第一版执行大脑和机会发现：run controller、stage state machine、market scan decision planner，系统自动判断哪些公告值得分析。

2. `PTL-I100-145-source-blueprint-orchestration-and-capture-plan`  
   做公开源蓝图编排：系统自动选择公开源组合并生成 Stage2 采集计划。全国聚合平台只作为一级发现、去重和补充查询面，不按全量实时源验收；首批商业试点不选北京，北京仅保留为技术回归/页面可达性样本。首批商业试点省份默认从四川、江苏、浙江、山东、广东、湖北开始，城市适配只按省级覆盖缺口、附件/详情缺失、监管投诉/备案证据、项目价值或 SPA 弱正文触发。

3. `PTL-I100-146-evidence-risk-and-hard-defect-verification-strategy`  
   做硬伤核验策略：系统自动决定查项目经理在建、资质、信用、业绩、许可、合同、履约等。

4. `PTL-I100-147-commercial-value-buyer-fit-and-hook-lead-engine`  
   做商业价值、买家识别和商业钩子：系统判断能不能卖、卖给谁、怎么不泄露地引流。

5. `PTL-I100-148-productized-autonomous-operator-workbench`  
   做产品化操作台：展示机会队列、证据强度、买家排序、钩子话术、复核项、下一步动作。

6. `PTL-I100-149-real-sample-autonomous-opportunity-acceptance`  
   用真实公开样本验收：从市场扫描到可售钩子和交付候选，证明系统不是手工 URL 工具。

## 九、红线

仍保持：

- 不抓 private / gray / 登录后 / 验证码 / 反爬内容
- 不把 LLM 输出当事实或法律结论
- 不把未复核推断直接给客户
- 不自动外发法律文书
- 不自动投诉举报
- 不无审批触达、支付或交付
- 不实现自动退款程序
