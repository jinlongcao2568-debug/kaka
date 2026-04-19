# AX9S 开发执行路由图（受控路线图导航资产；FF-18-S1 closeout 后）

> 说明：本文件是**受控路线图导航资产**，服务于“正式阶段 1-9 主线当前按什么顺序推进、进入条件是什么、哪些边界仍 blocked”。  
> 它不是上位裁决源，不替代 `L0.md`、`裁决总表.md`、`D1-D14`、`control/repo_status.md`、`control/current_task.yaml`、`control/milestone_status.yaml` 与 `docs/正式业务代码开发开工裁决页.md`。  
> 为保持 machine-readable 状态分层清晰，`control/reference_index.json` 中仍把本文件标记为**候选导航资产**；该标记只表示“不是正式状态源”，不表示本文件可以继续混用历史修复批、future unlock 历史导航或 activation prep 历史段。

## 1. 路线图角色

### 1.1 本文件负责什么

- 用当前正式状态源给出**正式阶段 1-9 主线**的导航顺序；
- 明确每一段 formal route 的进入条件、主要产出与仍 blocked 的边界；
- 把“当前 formal mainline”与“历史修复 / future unlock 历史导航”拆层表达；
- 把后续推进与 `task packet / review gate / automation gate` 接起来。

### 1.2 本文件不负责什么

- 不定义新的 phase/readiness；
- 不改写 L0、D2-D14 的正式业务语义；
- 不放宽 external release、Stage 8/9 高风险执行或高限制字段红线；
- 不替代 `control/current_task.yaml`、`control/repo_status.md` 与 `control/milestone_status.yaml` 的正式状态表达；
- 不把历史 `M* / R5 / R6 / activation prep / implementation decision readiness` 写成当前 implementation approval。

## 2. 当前受控状态快照

### 2.1 当前正式状态来源

- 正式权威 / 裁决源：`L0.md`、`裁决总表.md`、`D1-D14`
- 正式状态源：`control/repo_status.md`、`control/current_task.yaml`、`control/milestone_status.yaml`、`docs/文档与资产状态板.md`
- 条件开工裁决页：`docs/正式业务代码开发开工裁决页.md`
- 技术实现边界支撑：`docs/技术实现决策页.md`

### 2.2 当前阶段与作用域

- 当前 phase：`PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT`
- 当前仓库总体 readiness：`READY_FOR_POST-REPAIR_MAINLINE_SELECTION`
- 当前 conditional-go：`READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT`
- 当前导航状态：`CONTROLLED_ROUTE_MAP_RESTORED`
- 当前 FF 主链结论：`FF-01~FF-18 主链完成`
- 当前是否 candidate-gap：`否`
- 当前是否 strategic-branch：`否`
- 当前 closure review：`已关闭`
- 当前 mainline selection：`就绪`
- 当前 formal implementation mainline：`未选定`

作用域拆分：
- `READY_FOR_POST-REPAIR_MAINLINE_SELECTION` 只表示 post-repair authority convergence 已完成，可以进入 formal mainline selection；不表示任何 implementation batch 已自动获批。
- `READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT` 只表示内部 LeadOps 正式开发可继续，不等于 external-ready。
- `READY_FOR_POST-R6_CANDIDATE_GAP_BATCH` 与 `READY_FOR_POST-R6_STRATEGIC_BRANCH_BATCH` 只保留为历史 R6-path 语义，不再是当前 repo readiness。
- 本文件只负责导航，不是新的 phase/readiness 生成器。
- 本文件的 formal route 只看第 3-5 节；历史 `M* / R5 / R6 / activation prep` 只保留在第 6 节历史导航附录。

### 2.3 当前仍然有效的 blocked / governed 边界

- `external software release` 继续 `BLOCKED`
- 线索包外发继续要求审批链 + 审计链
- Stage 8 real execution 不是默认开放，仍为 governed / approval-gated / blocked by default
- Stage 9 real payment / delivery / refund 不是默认开放，仍为 governed / approval-gated / blocked by default
- model / provider / tool / source 的真实外部接入仍受 capability + review gate + governance 约束
- 高限制字段仍受更严格规则，不得因路线图拆层而放宽

## 3. 正式阶段 1-9 单一主线表达

正式阶段主链固定为：

1. Stage 1：任务编排与来源/路由治理
2. Stage 2：公开链采集、窗口期、版本/时钟裁决
3. Stage 3：结构化解析与关键对象抽取
4. Stage 4：关键对象定向公开核验与冲突预判
5. Stage 5：规则与证据双闸门
6. Stage 6：`project_fact / report_record / review_queue_profile / challenger_candidate_profile`
7. Stage 7：`saleable_opportunity / buyer_fit / legal_action_recommendation / recommendation`
8. Stage 8：`contact_target / outreach_plan / touch_record`
9. Stage 9：`order_record / payment_record / delivery_record / outcome / governance feedback`

补充说明：
- Stage 1-9 的正式顺序、对象边界与消费方向仍以 L0、D2、D3、D11、D13 为准。
- Stage 3-5 当前继续依赖现行 formal object / handoff / gate baseline；本文件不再把历史修复批当成 Stage 3-5 的替代路线表达。
- route map 只表达“当前 formal mainline 导航”，不表达历史 closeout 批次。

## 4. 当前 formal implementation route（navigation only）

### 4.1 当前 formal route 片段

| 路线图片段 | 覆盖阶段 | 主要目标 | 允许推进的实现形态 | 进入条件 | 仍 blocked / governed 边界 |
|---|---|---|---|---|---|
| R0 Stage 1-2 rollout / precedence | Stage 1-2 | 收紧 source rollout、default/fallback route、version/clock precedence 与 handoff authority | docs/contracts/control 驱动的 rollout / precedence 收口；不得越权改写 L0 | 当前 readiness 维持 `READY_FOR_POST-REPAIR_MAINLINE_SELECTION`；必须先走 task packet；不得引入真实外部源默认开放 | external source live enable 不开；不得把 rollout 写成全国默认覆盖 |
| R1 Stage 6 / 7 商业对象与输入闭合 | Stage 6-7 | 收紧 `project_fact -> legal_action_recommendation -> challenger_candidate_profile -> saleable_opportunity` 的 producer/consumer 闭合 | 受控实现、typed object 厚化、internal recommendation surfaces | 前序 guardrails 持续通过；对应 task packet 已声明 change class / review；不得改写 D2-D10 正式语义 | external release 不开；商业对象仍不得越过 `project_fact` |
| R2 Stage 8 schema / plan / writeback 厚化 | Stage 8 | 厚化 `contact_target / outreach_plan / touch_record`，完善 governed internal preview / draft-only 承接 | internal preview、draft generation、governed writeback、schema/plan/type 厚化 | R1 不得回退；Stage 8 高风险路径必须继续受 permission/governance/semantic 三层约束；必须走 task packet | real execution 默认不开；高限制字段与外部触达仍受审批链 |
| R3 Stage 9 typed workflow / internal governed execution skeleton | Stage 9 | 厚化 `order/payment/delivery/outcome/governance` typed workflow，形成 internal governed execution skeleton | typed workflow、internal preview、governed writeback、draft-only execution skeleton | R2 稳定；Stage 9 仍只允许 internal governed，不得把 preview/draft 写成 live | real payment/delivery/refund 默认不开；external release 不开 |
| R4 Internal surfaces / preview / draft-only 承接 | Stage 6-9 消费面 | 让 internal surfaces 清晰消费 Stage 6-9 正式对象，不新增第二套主判断 | internal workbench / preview / draft-only surface 收口 | R0-R3 对象闭合与 guardrail 持续通过；页面/接口只允许消费正式对象 | client/external surfaces 仍受 release/delivery/approval 门禁 |

### 4.2 当前 formal route 解释

- R0 是正式阶段 1-2 当前唯一新增导航入口；它不替代 Stage 3-9，只补齐 Stage 1-2 的 rollout / precedence 正式化。
- R1-R4 继续承接当前 Stage 6-9 formal object / handoff / preview consumption 的单一主线。
- future unlock、activation prep、implementation decision readiness 不属于当前 formal implementation route。

## 5. Formal Route Entry Rules

### 5.1 共通进入条件

进入任一 formal route 片段前，必须同时满足：
- `check-automation-readiness / check-semantic-alignment / check-release / lint-drift` 等当前 required scripts 全部通过；
- 不新增第二套对象、第二套状态源、第二套主判断；
- route segment 对应 `task packet` 已声明允许范围、禁止范围、change class、owner reviews；
- 若触及 shared runtime / governance / release / Stage 8/9 高风险域，必须按 `MANDATORY_HUMAN_REVIEW` 进入。

### 5.2 R0 Stage 1-2 rollout / precedence

进入前必须同时满足：
- Stage 1-2 authority drift 已保持关闭；
- source / route / default_route / precedence 仍受现行 formal object + handoff 约束；
- 不把 rollout / precedence 收口误写成 external source capability 放开。

### 5.3 R1-R4 Stage 6-9 当前 formal route

进入前必须同时满足：
- Stage 6-9 继续保持 formal object single-source consumption；
- internal preview / draft-only / governed writeback 边界未被放宽；
- Stage 8 / Stage 9 live execution 与 external release 继续 blocked/governed。

## 6. 历史导航附录（非当前 formal stage 1-9 route）

### 6.1 历史修复批

- `M1 / M7 / M2 / M3 / M4 / M5 / M6 / M8` 已完成；它们只保留为历史修复导航，不再充当当前 selected packet、formal implementation mainline 或 readiness source。
- 这些历史修复批的作用是说明 guardrail / repair / baseline 曾如何收口，不再表达“下一步正式阶段 1-9 按什么顺序开发”。

### 6.2 future unlock 历史导航

- `R5 external unlock prerequisites`、`R6 future unlock decision`、`Post-R6 candidate gap`、`LeadPack candidate activation prep`、`LeadPack activation design / implementation prep`、`LeadPack implementation decision readiness signoff` 只保留为 future unlock history。
- 这些条目可作为 history / decision lookup，但不构成当前 approval、implementation approval、activation approval，也不构成当前 repo readiness。
- `candidate / deny / blocked` 仍有效，但只属于 future unlock decision vocabulary；不得被回写成当前 formal route 或当前 readiness。

## 7. 路线图推进方式

### 7.1 一律先走 task packet

后续路线图推进不得再靠聊天临时判断，必须先形成 machine-readable task packet：
- 正式位置：`control/current_task.yaml -> currentTask.task_packet`
- 模板：`docs/自动开发任务包模板.md`

### 7.2 高风险段必须走 review gate

以下路线图片段默认按高风险处理：
- 触及 `shared_runtime_core`
- 触及 `governance_release_core`
- 触及 `provider_vendor_source_policy_core`
- 触及 `stage8_stage9_high_risk_execution`
- 触及 `automation_control_core`

要求：
- 至少 `MANDATORY_HUMAN_REVIEW`
- 命中 `STOP_AND_ESCALATE` 时立即停机
- 不得把 governed / preview / approval-required 降级成 default live

### 7.3 统一引用链

- 动作门禁：`docs/自动化开发动作门禁表.md`
- task packet 模板：`docs/自动开发任务包模板.md`
- 执行纪律：`docs/D1_研发_Codex执行手册.md`
- 验收 / 发布前检查：`docs/D11_测试验收与金标回归清单.md`

## 8. 当前最小结论

- 当前仓库已经恢复到**受控路线图可导航、可推进**状态；
- 这不等于业务全链 ready，更不等于 external-ready；
- `FF-18-S1` 只完成状态源与导航源 closeout；本窗结束后停机，不自动进入任何新任务；
- `FF-01~FF-18` 主链完成，但当前 formal implementation mainline 仍由人工另行选择；
- 当前 formal implementation mainline 仍未选定；route map 只保留 formal stage 1-9 单一主线表达；
- 历史 `M* / R5 / R6 / activation prep / implementation decision readiness` 已拆到历史导航附录，不再污染当前 formal route；
- route map 继续只是 navigation asset，不是 readiness source。
