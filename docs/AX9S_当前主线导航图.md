# AX9S 当前主线导航图

> 本文件是**纯导航图**，也是**候选导航资产**（candidate navigation asset），只负责阶段 1-9 的静态导航摘要。
> 本文件**非当前任务源**、**非状态源**、**非执行日志**、**非完整 backlog**。本文件不是状态源，也不是执行顺序源。
> `control/current_task.yaml` 负责 task packet / scoped subpacket 窗口的唯一**当前 active 执行任务**；普通 direct-dev 不要求先切换当前包。
> `control/product_task_library.yaml` 只负责下一候选来源。
> `scripts/check-state-alignment.ps1` 对本文件的同步仍保持 `suggestion-only`。
> 本文件不改写 `L0.md`、`裁决总表.md`、`D1-D14`、`contracts/*`、`handoff/*` 的正式语义。
> 从 2026-05-17 起，**动态推进、当前缺口、缺口减少和优先级** 统一更新到 `docs/专题_Stage1-9_缺口收口与优先级清单.md`；本文件只保留静态导航。
> 本文件只作导航提示，不决定执行顺序。

## 1. 导航口径

- 本图承接 `PTL-I100-OPEN-CAPABILITY-BASELINE`。
- 关键历史边界锚点保留为：`PTL-I100-111F-open-capability-registry-route-doc-sync`、`PTL-I100-112-production-platform-infrastructure`、`PTL-I100-118R-final-product-operational-reacceptance`。
- `controlled-opening-required` 表示未通过 provider config、sandbox、approval、audit、operator action、field allowlist/masking、controlled-opening gate 与验收前不能 live，不表示永久不做。
- 涉及受控开放、release、live execution 或跨阶段机器契约时，必须进入 `manual_planning_review` / task packet 窗口；普通 direct-dev 不因阅读本导航图自动切包。
- 招投标方向以 `docs/业务方向_候选公示后证据包与投前预测双线契约.md` 和 `contracts/evaluation/business_direction_strategy_contract.json` 为准；当前核心商业主线是 **候选后证据包**。
- 下载解析前必须先生成 `AnalysisStrategyPlan v1`；若出现 `05 开标信息`，投前预测即转开标后 / 候选后路线。
- 普通开发默认最小读序：`AGENTS.md` -> `专题_Stage1-9_缺口收口与优先级清单.md` -> `AX9S_Stage1-9_执行矩阵与子漏斗.md`；只有做 Stage4/5 时再读 `AX9S_Stage4-5_核验双闸门SOP.md`，只有做 Stage7 商业层时再读 `专题_SKU分层与分类裁决.md`。

## 2. 阶段主链

本节只告诉代理“该去哪里读”，不重复 L1 产品主图、L2 执行矩阵或 L3 SOP 的正文。阶段输入、输出、失败回退和验收细节分别以对应文档为准。

| Stage | 看哪份主文档 | Handoff | 当前导航候选 |
|---|---|---|---|
| Stage1 来源/候选池 | `docs/专题_Stage1-2_来源覆盖与采集路由.md`、`docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` | `handoff/stage1_to_stage2/contract.json` | Stage1-2 来源/路由展开 |
| Stage2 公开采集/流程矩阵 | `docs/专题_Stage1-2_来源覆盖与采集路由.md`、`docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` | `handoff/stage2_to_stage3/contract.json` | Stage1-2 来源/路由展开 |
| Stage3 解析/字段血缘 | `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` | `handoff/stage3_to_stage4/contract.json` | L2 主矩阵 |
| Stage4 公开核验 | `docs/AX9S_Stage4-5_核验双闸门SOP.md`、`docs/专题_投前预测_Stage1-9 全链规则与判定资料池.md` | `handoff/stage4_to_stage5/contract.json` | Stage4-5 规则与核验展开 |
| Stage5 规则证据双闸门 | `docs/AX9S_Stage4-5_核验双闸门SOP.md`、`docs/专题_投前预测_Stage1-9 全链规则与判定资料池.md` | `handoff/stage5_to_stage6/contract.json` | Stage4-5 规则与核验展开 |
| Stage6 统一事实/报告 | `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` | `handoff/stage6_to_stage7/contract.json` | L2 主矩阵 |
| Stage7 商业承接 | `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md`、D8/D10、`docs/专题_SKU分层与分类裁决.md` | `handoff/stage7_to_stage8/contract.json` | Stage7 商业层设计 |
| Stage8 触达准备 | D9/D13 与自动化动作门禁 | `handoff/stage8_to_stage9/contract.json` | 受控开放治理 |
| Stage9 交付治理 | D10/D13 与自动化动作门禁 | 无 | 受控开放治理 |

## 3. 动态信息去哪里看

本文件不再维护动态推进记录。要看“当前做到了哪里、还差什么、最近缺口有没有减少”，统一去这些位置：

- 当前真实缺口、减少缺口和优先级：`docs/专题_Stage1-9_缺口收口与优先级清单.md`
- 当前正式状态源：`control/repo_status.md`、`control/current_task.yaml`、`control/milestone_status.yaml`
- 当前产品总图和全链验收口径：`docs/AX9S_产品主图与验收总则.md`
- 历史 PTL 顺序、完成态和 committed refs：`control/product_task_library.yaml`、`control/product_module_registry.yaml` 和 `archive/non_current_docs/*`

主线闭合提示：本文件只保留静态导航；不提供状态源、执行顺序源、完整 backlog 或 release 放行。`external release`、`Stage 8 real execution`、`Stage 9 real payment / delivery / refund` 受控开放要求不变；controlled-opening-required 只表示受控开放条件未满足前不能 live，不表示真实触达、支付或交付永久不做。自动退款执行不实现。
