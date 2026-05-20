# 专题_Stage1-9_缺口收口与优先级清单

**版本**: 2026-05-20 v18

## 1. 文档定位

本专题是 **Stage1-9 动态缺口投影板**。

它的作用不是再讲一遍路线，而是：

- 以 `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` 为目标模型
- 对照代码 / tests / scripts / contracts 投射当前真实缺口
- 作为后续“减少缺口、跑通一段、更新一段”的唯一动态收口面

它不是正式状态源，也不替代：

- `control/repo_status.md`
- `control/current_task.yaml`
- `control/milestone_status.yaml`
- `docs/AX9S_产品主图与验收总则.md`
- `docs/AX9S_Stage4-5_核验双闸门SOP.md`

## 2. 一句话结论

当前真实状态不是“Stage1-9 没做”，而是：

- Stage1-3 主干链路已形成
- Stage4 外部证据链最弱，仍是当前最大短板
- Stage5 双闸门已实现，但真实样本规模和误报/漏报校准仍不足
- Stage1-6 到 P13B 的证据编排状态机已新增第一版，可把真实项目归并到 P13B、原文回溯、A 级强线索、Stage6 事实包 readiness 等状态；一键续跑入口已能从 `P13B_ORIGINAL_BACKTRACE_REQUIRED` 自动生成原文回溯任务并回写状态；原文回溯任务已新增 URL/入口质量分层，能把官方直达 HTML 排在空地址、跳转壳、YGP mapping 之前，避免小预算 live 盲打低质量入口；`batch-triage-table.json` 已能按批次给出继续跑、进入事实包/Stage7 内部预览、D 级内部复核或非主线暂存决策；`EvidenceStage6FactPackage v1` 已能生成内部复核 summary 和 `stage6_review_action_plan_table`，并能把 terminal source gap / no-delta 的 D 级项目标成 `automated_dispatch_allowed=false`，同时把 `manual_hold_state`、停靠原因、重新开启条件和 operator decision options 写入 brief、evidence pack、review summary JSON/Markdown；`Stage6ReviewActionDispatch v1` 已能把 P13B 释放证据、原文回溯重试、设计/测绘资质服务期复核映射成受控续跑任务，同时跳过 manual-only action plan，避免 D 级项目无限自动重试；`Stage6ReviewActionDispatchRunner v1` 已能按任务类型分组执行白名单本地 dispatch 任务，避免多项目重复覆盖输出；`Stage6ReviewActionDispatchReadback v1` 已能把这些任务读回为已产出、等待受控执行、人工跳过或阻断复核状态；`Stage6ReviewActionDispatchCloseout v1` 已能把读回明细按项目收口成可回灌、等待、跳过、阻断的项目级状态，且释放证据 adapter plan 不再直接误标为 evidence state 可回灌；`Stage6ReviewActionResultRouting v1` 已能把 closeout 结果路由到 evidence state rebuild、batch closeout rebuild 或释放证据字段查询的下一条受控任务，并输出结构化 argv；`Stage6ReviewActionResultRunner v1` 已能在 dry-run / `-Execute` 受控模式下执行白名单本地续跑命令，且会跳过重复 argv；`Stage6ReviewCycleRunner v1` 已能把新的 `EvidenceBatchCloseout` 自动串到下一轮 Stage6 fact package、dispatch 和 dispatch runner，且在无自动任务时安全停在 manual-only 复核；`Stage6ReviewLoopRunner v1` 已能把 dispatch runner、readback、closeout、routing、result runner、next cycle 汇总成 `stage6-review-loop-project-status-table.json`，按项目回答当前终态和下一步动作，包括 `MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH`；`run-stage6-review-loop-v1.ps1` 默认可在缺 dispatch 时从 batch closeout bootstrap，并可自动发现最新 batch closeout；若 bootstrap 后没有自动任务，会把 manual-only 项目直接投到项目状态表，而不是误报下游缺文件；`Stage6ReviewLoopOperatorProjection v1` 已能把该状态表投影成 owner 可读的批次状态、项目行、可续跑/人工停机/Stage7 gate、重新开启条件和下一步动作，并通过 `/operator-console/stage6-review-loop-status`、操作台 overview 和独立极简页 `/operator-console/stage6-review-loop` 展示；极简页已把状态、下一步和重新开启条件翻译成中文标签，不再要求 owner 直接读 raw JSON、英文枚举或在大操作台里找状态；默认批次选择已改为 owner 总览策略：若最新产物只是单项目终态，会优先展示最近的多项目批次，同时保留最新单项目批次在历史选择器中；项目卡片也已补 `当前阶段`、`证据等级`、`为什么停/阻断原因` 和 `下一步`，证据等级未投影时会明确提示需回看 batch closeout / evidence state，不会伪装成“没问题”
- Stage6/7 内部对象和 readback 已存在；设计/测绘 `08` 定向人员档案抽取结果已能生成标准 `stage4_candidate_verification_inputs`，可继续喂给 Stage4 公司优先核验 dry-run/执行，不再只停在“人工应用字段”
- Stage8/9 已有 governed readback 和受控开启语义，但真实 live execution 仍按受控开放边界保持关闭

当前 Stage1-6 近端开发顺序已固化到 `control/stage1_6_priority_execution_plan.yaml`：

1. Stage6 多项目/多批次总览 UI 已完成第一轮 owner 可读化，后续只随真实样本补字段。
2. 当前继续做 Stage4 释放证据主链，把施工许可、竣工验收、项目经理变更、合同履约收成统一 adapter job。
3. 回头补 Stage1-3 真实列表、详情、附件、OCR 和人员材料页稳定性。
4. 校准 Stage5 A/B/C/D 双闸门，避免把证据不足写成排除性结论。
5. 最后做 Stage1-6 批量实战回归，形成省份、项目类型、附件类型的 readiness 表。

## 3. 投影方法

当前缺口投影固定按四个来源交叉判断：

1. `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md`
2. 当前代码与正式对象 / contracts
3. 关键 tests 与脚本结果
4. 当前受控开放边界和 repo status

## 4. Stage1-9 动态缺口投影

| 阶段 | 矩阵目标 | 当前代码 / 测试 / 脚本投影 | 当前缺口判断 | 优先级 |
|---|---|---|---|---|
| Stage1 候选发现 | 多省多城真实候选稳定发现 | `operator` 搜索入口、region adapter、real candidate discovery 已存在；GD/SC/JS/ZJ 路径较清楚 | SD/HB discoverer 和真实列表解析回归仍不足 | P1 |
| Stage2 公开采集 | 列表/详情/附件可回放、可审计 | 快照、hash、来源 URL、失败 taxonomy 已进入正式链路 | SPA 壳、验证码、超大附件、长尾下载阻断仍要继续打磨 | P1 |
| Stage2.5 AnalysisStrategyPlan | 下载和解析前先做策略分流 | 双线文档和 contracts 已固定口径 | 需要继续防止长尾实现绕过策略层 | P2 |
| Stage3 字段血缘 | 主流载体字段抽取与 lineage | HTML/PDF/Word/Excel 主链已通 | OCR、复杂表格、多候选行绑定、`08` 定向解析仍未完全稳 | P1 |
| Stage4 公开核验 | 多源公开核验与释放证据链 | 广东/广州已有部分 query/readback；`ResponsiblePersonEarlyProbe`、`MajorRegionQueryProbe`、`GuangdongLocalVerificationProbe` 已存在 | 多省地方源、项目经理变更释放、命中后的释放证据深查仍最弱 | P0 |
| Stage5 双闸门 | `rule_gate_decision` + `evidence_gate_decision` 稳定运行 | 双闸门框架、规则运行、evaluator tests 已存在 | 真实样本校准深度不够，SKU 级 PASS/REVIEW/BLOCK 还要继续磨 | P1 |
| Stage6 统一事实 | `project_fact` / report / review queue 可回放 | Stage6 聚合、internal orchestration、product package 基础已在 | 真实候选仍常被 Stage4 缺口卡住，formal real_public 链还需继续收紧 | P0 |
| Stage7 商业钩子 | saleable / buyer_fit / offer 承接真实事实 | Stage7 runtime、hook、buyer fit、offer 已存在 | `real_public_sellable_gate_ready=false` 经常受 Stage4 缺口拖住；仍需继续控卖前泄露 | P1 |
| Stage8 触达准备 | governed preview / draft / approval 边界清楚 | Stage8 internal/governed readback 已存在，真实发送默认关闭 | 不是当前主产品缺口，但 provider sandbox / live pilot 仍是后续 controlled opening 任务 | P2 |
| Stage9 交付治理 | order / payment / delivery / refund 治理链可回放 | Stage9 ledger/readback 已存在；真实 payment / delivery 默认关闭；自动退款执行继续 EXCLUDED | 不是当前主产品缺口，但真实下载、真实支付、真实交付仍是后续 controlled opening 任务 | P2 |

## 5. 当前 P0 缺口

### P0-1 Stage4 释放证据链闭环

- 现状：Stage4 是当前最大短板。身份核验和部分公开源 readback 已有，但“许可/合同/竣工/项目经理变更/处罚”多源交叉后的释放证据链仍不完整。
- 当前进展：`GuangdongLocalFieldQueryProbe v1` 已把来自 `ReleaseEvidenceAdapterPlan v1` 的字段查询任务纳入统一 A/B/C/D 汇总；`Stage6ReviewLoopRunner v1` 已能在项目状态表里直接显示释放证据字段查询的 `MATCHED / NOT_FOUND / BLOCKED / NEEDS_BROWSER` 和 B/C/D 下游结果。
- 直接症状：
  - `项目经理变更释放` 在矩阵里仍为 `MISSING_RUNTIME`
  - 真实候选经常落到 `PARTIAL_SOURCE_COVERAGE`
  - Stage6/7 常被 Stage4 缺口卡住
- 完成标准：
  - 命中重叠信号后，能稳定补查 `construction_permit`、`contract_public_info`、`completion_filing`、`project_manager_change_notice`
  - 释放证据链可回放，且不会把“未命中/源阻断”写成“无风险”

### P0-2 Stage6/7 真实候选 formal real_public 闭环

- 现状：Stage6/7 内部对象已存在；`evidence_orchestration_state_machine_v1` 已能消费 Stage1-6 storage、公司优先补证、P13B 和原文回溯产物，生成 `evidence-state-table`、`adapter-job-table`、`stage6-fact-package-readiness-table` 和 `batch-triage-table`；设计/测绘候选已由 `DesignSurveyResponsibleAdapterPlan v1` 从纯暂存改为可生成 Stage4 负责人/资质/服务期计划；`Flow08TargetAttachmentParse v1` 抽到人员档案后，可由 `DesignSurveyFlow08Stage4Inputs v1` 生成标准 Stage4 输入并进入 `build-company-first-stage4-execution-v1.ps1` dry-run/执行；`EvidenceStage6FactPackage v1` 已补 `stage6-review-summary`、`stage6_review_action_plan_table` 和每项目 `stage6-review-action-plan.json`，并能把 terminal source gap / no-delta 项目标记为 manual-only，进一步输出 `Manual Hold` 段落、重新开启条件和 operator decision options；`Stage6ReviewActionDispatch v1` 已能把动作计划映射到 `build-release-evidence-adapter-plan-v1.ps1`、`run-evidence-orchestration-continuation-v1.ps1`、`build-design-survey-public-registry-readback-v1.ps1` 三类受控续跑任务，同时不再派发 terminal D/no-delta action plan；`Stage6ReviewActionDispatchRunner v1` 已能把两个 RQSG 原文续跑任务合并成一次 continuation runner，把规划测绘 registry readback 单独执行；`Stage6ReviewActionDispatchReadback v1` 已能读回续跑产物或记录等待、跳过、阻断状态；`Stage6ReviewActionDispatchCloseout v1` 已能生成项目级收口视图，样本中 dispatch runner 执行后 3 个任务均可进入 closeout；`Stage6ReviewActionResultRouting v1` 已把原文 continuation run 路由到 `build-evidence-batch-closeout-v1.ps1 -ContinuationRunJson <result_json_path> -EvidenceStateRoot <state_after_root>`，把设计测绘 readback 路由到 evidence state rebuild，并把重复 continuation run 命令交给 result runner 去重；`Stage6ReviewActionResultRunner v1` 已能执行 result routing 中的白名单本地命令；`Stage6ReviewCycleRunner v1` 已能从 result runner 产出的 batch closeout 继续生成下一轮 Stage6 fact package 与 dispatch，并在真实三项目样本中用短路径执行 1 个非 live dispatch 组；`Stage6ReviewLoopRunner v1` 现在会额外输出 `stage6-review-loop-project-status-table.json`，按项目列出 readback、closeout、routing、result runner、next cycle dispatch/manual-only 的当前状态、终态和下一步建议；但真实候选仍常被 Stage4 释放证据链缺口挡在 formal real_public 闭环之前，且无 snapshot 的设计测绘 registry readback 会正确回到 adapter/snapshot required，而不是误判通过。
- 直接症状：
  - `real_public_sellable_gate_ready=false`
  - formal real_public 路径存在，但常因 source coverage、原文回溯和释放证据链不足停下
- 完成标准：
  - 真实候选能更稳定进入 Stage5 双门、Stage6 `project_fact`、Stage7 `saleable_opportunity`
  - 编排状态能自动指向下一步 adapter job，并通过批次决策表、Stage6 action plan、Stage6 dispatch task、dispatch readback、dispatch closeout 和 result routing 标出继续、暂存、复核、等待、跳过、阻断、字段查询和可回灌路径，避免真实项目“生成任务后靠人工记忆续跑”
  - 不因内部 preview 存在就误判“正式可售已经完成”

## 6. 当前 P1 缺口

### P1-1 山东、湖北候选发现器补齐

- 现状：SD/HB 主要还是入口 profile、挑战观察和解析回归不足。
- 完成标准：
  - SD/HB 有专门 discoverer
  - 有真实列表结构解析回归
  - 不再以“观察态/挑战态”长期停留

### P1-2 Stage2/3 长尾文件链补强

- 现状：主流文件已通，但 OCR、复杂表格、多候选行绑定、`08` 定向解析仍未完全稳。
- 完成标准：
  - OCR 状态机更清楚
  - 多候选行和联合体绑定不串行
  - `08` 继续保持 strategy-driven，不默认全量深解析

### P1-3 Stage5 真实样本校准

- 现状：规则已存在，但更接近“第一刀 + 内部复核规则”。
- 完成标准：
  - 50+ 真实项目样本校准
  - 有误报/漏报修订记录
  - SKU 级 PASS/REVIEW/BLOCK 边界更稳定

## 7. 当前 P2 缺口

### P2-1 Stage1-5 独立 API 面

- 现状：真正可用入口还是 `operator` 搜索入口和 Stage6 internal orchestration。
- 说明：这不是 bug，但如果目标是“Stage1-5 每阶段都可独立 API 运行”，当前仍未完成。

### P2-2 Stage8/9 controlled opening 后续任务

- Stage8：governed readback 已有，但 provider sandbox / live pilot 仍是后续受控开放任务
- Stage9：ledger/readback 已有，但真实 payment / delivery / refund live execution 仍默认关闭
- 自动退款执行继续 `EXCLUDED`

这两项属于**后续受控开放任务**，不是当前 Stage1-7 产品主链 bug，但也不能误判成“已经开放”。

## 8. 不应误判为已完成的项

- 不能因为 Stage1-3 可跑，就说客户可售证据已稳定形成
- 不能因为 Stage5 测试全绿，就说规则已达稳定商用品质
- 不能因为 Stage6/7 对象齐全，就说真实可售链已闭环
- 不能因为 Stage8/9 readback 已存在，就说真实发送、真实支付、真实交付已放开
- 不能因为 challenge taxonomy 存在，就说真实第三方风控站点都已跑通

## 9. 更新规则

以后每次减少缺口或打通一段，不去更新 `AX9S_当前主线导航图` 的动态内容，而是直接更新本专题：

- 哪个阶段缺口减少了
- 用什么代码 / 测试 / 脚本证据证明减少
- 当前优先级有没有变化

## 10. 直接依据

- `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md`
- `docs/AX9S_Stage4-5_核验双闸门SOP.md`
- `docs/AX9S_产品主图与验收总则.md`
- `control/repo_status.md`
- `control/product_operability_gap_matrix.yaml`
- `control/stage1_6_priority_execution_plan.yaml`
- `control/operator_user_acceptance_gap_matrix.json`
- `contracts/evaluation/evaluation_coverage_requirements.json`
- `src/stage1_tasking/region_adapters.py`
- `src/stage1_tasking/real_candidate_discovery.py`
- `src/stage2_ingestion/public_source_adapters.py`
- `src/stage3_parsing/ocr_text.py`
- `src/stage4_verification/provider_handlers.py`
- `src/api/routes/operator_customer_access.py`
