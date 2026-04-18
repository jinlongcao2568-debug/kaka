# AX9S 高+中任务包蓝图

> 说明：本文件是高优先级与中优先级修复的任务包蓝图。  
> 它不是正式状态源，不替代 `control/current_task.yaml -> currentTask.task_packet`。  
> 正式激活方式：从本蓝图或 `control/task_packet_library.yaml` 选中一个包，复制到 `currentTask.task_packet` 后执行。

## 使用规则

1. 一次只能激活一个任务包。
2. 不允许把两个根因混进同一个任务包。
3. 任务包 scope 发生变化时，必须开新包或升版，不得在原包里扩写。
4. 每个任务包执行完 `required_scripts` 后必须停机汇报。
5. `AX9S_开发执行路由图.md` 只做导航，不承载任务包实时状态。
6. 每个任务包的 `non_goals` 必须包含固定防漂项 `not an external unlock implementation`，用于满足 release / R6 防漂断言。
7. 任何需要激活到 `control/current_task.yaml -> currentTask.task_packet` 的任务包，`change_domains` 默认必须包含 `automation_control_core`，用于满足 review-gate / release check 断言。
8. `control/current_task.yaml` 不属于业务修改范围，但属于 activation/closeout 控制面；允许仅为激活任务包、closeout 任务包、兼容 gate 命名而最小修改。
9. 只要任务包允许修改 `docs/D12`、`docs/D13`、`docs/D14`、`docs/技术实现决策页.md`、`docs/正式业务代码开发开工裁决页.md`、`docs/文档与资产状态板.md`、`docs/AX9S_开发执行路由图.md`、`control/repo_status.md`、`control/milestone_status.yaml`、`control/release_manifest.yaml`、`control/model_release_manifest.yaml`，`change_domains` 默认还必须包含 `future_external_unlock_prereq_core`。
10. 只要任务包允许修改 `src/shared/capability_runtime.py`、`src/shared/policy_executor.py`、`src/shared/runtime_validator.py`、`src/shared/contracts_runtime.py` 或 `src/shared/pipeline.py`，`change_domains` 默认还必须包含 `shared_runtime_core`。
11. 所有 `MANDATORY_HUMAN_REVIEW` 任务包都必须显式写入：
   - `human_review_required: true`
   - `review_evidence.declared: true`
   - `review_evidence.signoff_required: true`
   - `review_evidence.signoff_status: REQUESTED_NOT_APPROVED`
12. 只要任务包命中 `governance_release_core / future_external_unlock_prereq_core / future_external_unlock_decision`，`owner_reviews_required` 默认必须包含 `release_approver`。
13. 只要任务包命中 `provider_vendor_source_policy_core / future_external_unlock_prereq_core / future_external_unlock_decision`，`owner_reviews_required` 默认必须包含 `model_governance_owner`。
14. 只要任务包命中 `automation_control_core`，`owner_reviews_required` 默认必须包含 `automation_owner`。

## 推荐顺序

| 顺序 | 任务包 | 目标 |
|---|---|---|
| 1 | `PKT-P0-01-review-queue-window-scoring` | 收口 Stage6 复核优先级与窗口评分 |
| 2 | `PKT-P0-02-stage7-buyer-fit-value-derivation` | 收口 buyer fit 与价值评分来源 |
| 3 | `PKT-P0-03-stage7-price-competitor-resolution` | 收口价格归一、报价带、竞争者排序 |
| 4 | `PKT-P0-04-stage8-compliance-lattice` | 统一 Stage8 合规判定 |
| 5 | `PKT-P0-05-stage8-contact-enrichment-merge` | 收口 contact enrichment merge 与候选冲突 |
| 6 | `PKT-P0-06-stage9-writeback-contract-core` | 统一 Stage9 writeback contract |
| 7 | `PKT-P0-07-stage9-upstream-feedback-loop` | 闭合 Stage9 上游反馈回流 |
| 8 | `PKT-P0-08-formal-route-map-split` | 把正式路线图与历史导航拆层 |
| 9 | `PKT-P1-01-stage12-rollout-precedence` | 补齐 Stage1-2 rollout 与 precedence |
| 10 | `PKT-P1-02-capability-canonicalization` | capability canonical source 收口 |
| 11 | `PKT-P1-03-api-ui-capability-envelope` | API/UI canonical capability envelope |
| 12 | `PKT-P1-04-generated-assertions-cadence-ladder` | 断言生成化与多渠道 ladder |
| 13 | `PKT-P1-05-validator-anti-drift-semanticization` | validator anti-drift 语义化收口 |

## 高优先级任务包摘要

### `PKT-P0-01-review-queue-window-scoring`
- 只解决：`review_queue_priority_score / review_queue_bucket / window influence`
- 关键完成标准：
  - Stage6 不再用默认 `80`
  - queue priority 公式 machine-readable
  - D8/D11/window policy 保持一致

### `PKT-P0-02-stage7-buyer-fit-value-derivation`
- 只解决：buyer fit 输入来源、project/lead/opportunity value derivation、expected bands
- 关键完成标准：
  - `buyer_fit_scorecard` 不再只是权重壳
  - `expected_*_band` 不再主要是 `UNKNOWN`

### `PKT-P0-03-stage7-price-competitor-resolution`
- 只解决：价格归一、报价带、competitor entity resolution、TopN 排序
- 关键完成标准：
  - 价格冲突、历史参考、税口径正式化
  - competitor ranking 不再主要靠 code helper

### `PKT-P0-04-stage8-compliance-lattice`
- 只解决：Stage8 candidate/compliance/stop/runtime 语义统一
- 关键完成标准：
  - `contact_compliance_matrix`、`touch_stop`、runtime 语义单一
  - quiet hours/frequency/approval 不再多口径

### `PKT-P0-05-stage8-contact-enrichment-merge`
- 只解决：contact enrichment merge、dedupe、冲突裁决、人类接管 next owner/SLA
- 关键完成标准：
  - contact candidate 多来源 merge 有 formal policy
  - `CONNECTED / ORG_ROUTED` 后的人类接管正式化

### `PKT-P0-06-stage9-writeback-contract-core`
- 只解决：outcome/governance/payment/delivery 四路 writeback target 语义统一
- 关键完成标准：
  - `projected / persisted / trace-only` 全部显式
  - additive 与 authoritative 不再混写

### `PKT-P0-07-stage9-upstream-feedback-loop`
- 只解决：Stage9 结果如何影响上游推荐、对象与复核
- 关键完成标准：
  - `sales_lead / report_record / buyer_fit / challenger_candidate_profile` 都有正式回流口径

### `PKT-P0-08-formal-route-map-split`
- 只解决：正式阶段路线图与历史修复导航拆层
- 关键完成标准：
  - 路线图只表达正式主线
  - 历史 `M* / R6 / activation prep` 不再污染阶段 1-9 正式版

## 中优先级任务包摘要

### `PKT-P1-01-stage12-rollout-precedence`
- 目标：把 Stage1-2 从 minimum baseline 提升到 rollout/backlog + precedence

### `PKT-P1-02-capability-canonicalization`
- 目标：收口 capability vocabulary / current mode / future unlock 的 canonical source

### `PKT-P1-03-api-ui-capability-envelope`
- 目标：让 preview surface 直接暴露 canonical capability envelope

### `PKT-P1-04-generated-assertions-cadence-ladder`
- 目标：把部分 policy 断言生成化，并补多渠道 ladder

### `PKT-P1-05-validator-anti-drift-semanticization`
- 目标：把 `validate-contracts.ps1` 的 Stage9 writeback 检查从 brittle token 匹配收口到当前 contract/resolution 语义检查

## 激活协议

1. 选中一个任务包。
2. 把该包复制到 `control/current_task.yaml -> currentTask.task_packet`。
3. 同步更新：
   - `currentTask.task_id`
   - `currentTask.title`
   - `currentTask.linked_docs`
   - 确认 `currentTask.task_packet.non_goals` 包含 `not an external unlock implementation`
   - 确认 `currentTask.task_packet.change_domains` 包含 `automation_control_core`
   - 若任务包触及 `src/shared/*` 运行时主骨架，还要确认 `currentTask.task_packet.change_domains` 包含 `shared_runtime_core`
   - 若任务包触及 D12/D13/D14/技术实现决策页/状态板/路线图/control 状态源，还要确认 `currentTask.task_packet.change_domains` 包含 `future_external_unlock_prereq_core`
   - 确认 `currentTask.task_packet.human_review_required=true`
   - 确认 `currentTask.task_packet.review_evidence` 三个硬字段齐全
   - 根据 domains 确认 `owner_reviews_required` 至少包含 `release_approver / model_governance_owner / automation_owner` 的默认要求
   - `currentTask.task_id` 可以包含 `AUTHORITY_CONVERGENCE` workstream token，或包含当前 `task_packet.packet_id`；至少要满足 release / semantic gate 兼容要求
4. 先做只读重入：

```powershell
pwsh -NoProfile -Command "Get-Content -LiteralPath 'D:\Base One\kaka\AGENTS.md' -Raw"
pwsh -NoProfile -Command "Get-Content -LiteralPath 'D:\Base One\kaka\control\current_task.yaml' -Raw"
pwsh -NoProfile -ExecutionPolicy Bypass -File D:\Base One\kaka\scripts\check-automation-readiness.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File D:\Base One\kaka\scripts\check-semantic-alignment.ps1
```

5. 执行任务包。
6. 跑完 `required_scripts` 后停机汇报，不连跑下一个包。

## 与现有仓库规则的关系

- 正式 machine-readable 激活入口仍只有 `control/current_task.yaml -> currentTask.task_packet`
- 本文件与 `control/task_packet_library.yaml` 只是蓝图/库，不是状态源
- 如蓝图与上位文档冲突，以 `L0 / 裁决总表 / D1-D14 / current_task` 为准
