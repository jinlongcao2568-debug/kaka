# AX9S Full Repair Window Bootstrap Template

用法：新窗口只替换 `{{BATCH_ID}}`，其余文本保持不变。

---

你现在执行 AX9S 全量修复批次：`{{BATCH_ID}}`。

先读取并遵守：

1. 仓库根 `AGENTS.md`
2. `docs/L0.md`
3. `docs/裁决总表.md`
4. `docs/D1_研发_Codex执行手册.md`
5. `control/repo_status.md`
6. `control/current_task.yaml`
7. `control/milestone_status.yaml`
8. `control/ax9s_full_repair_plan.yaml`
9. `control/ax9s_full_repair_status.yaml`
10. `control/ax9s_full_repair_coverage_matrix.yaml`
11. `control/ax9s_validation_matrix.yaml`
12. `control/ax9s_review_escalation_matrix.yaml`
13. `control/ax9s_scoped_task_packet_template.yaml`
14. `control/task_packets/{{BATCH_ID}}.yaml`

执行纪律：

- 本窗口只允许执行 `{{BATCH_ID}}`，不得进入下一批。
- 若 `control/ax9s_full_repair_status.yaml` 中 `next_batch_recommended` 不是 `{{BATCH_ID}}`，先停下汇报。
- 先用 `control/ax9s_full_repair_coverage_matrix.yaml` 确认 `{{BATCH_ID}}` 覆盖的问题域，不得自行改批次目标。
- `control/task_packets/{{BATCH_ID}}.yaml` 是 batch blueprint，不得直接复制进 `control/current_task.yaml`。
- 在开始代码修改前，必须基于 `control/ax9s_scoped_task_packet_template.yaml` 从 `{{BATCH_ID}}` blueprint 派生一个 executable scoped subpacket。
- 这个 scoped subpacket 必须满足 `control/automation_task_packet_rules.yaml` 的字段和 scope 限制。
- 只有 executable scoped subpacket 才允许激活到 `control/current_task.yaml#currentTask.task_packet`。
- 只允许修改 scoped subpacket 中的 `allowed_modification_paths`。
- 不得修改 scoped subpacket 中的 `forbidden_modification_paths`。
- 不得新造第二套对象、第二套状态源、第二套 capability/opening 语义。
- 先修 canonical source，再修 runtime，再修 tests/scripts，再修 surface。
- 必须先在汇报中列出：`subpacket_id`、`declared_changed_paths`、`allowed_modification_paths`、`required_scripts`。
- 必须运行 scoped subpacket 和 `control/ax9s_validation_matrix.yaml` 中为 `{{BATCH_ID}}` 声明的 required scripts。
- 运行 `validate-contracts` / `run-golden` / `run-governance-contracts` / `check-release` 后必须停下汇报，不得继续下一批。
- 如果发现前置依赖未满足、需要新对象/新枚举/新 release gate 语义、或范围跨到下一批，立即停止并汇报阻断。

输出必须包含：

1. 修改文件清单
2. 每个文件修改了什么
3. 当前脚本/校验结果
4. 当前阻断项
5. 是否建议进入下一步
6. 若不建议，最小补齐路径

---

说明：

- `control/current_task.yaml` 是正式活动任务源。
- `control/ax9s_full_repair_status.yaml` 是 full-repair 程序状态账本。
- `control/task_packets/{{BATCH_ID}}.yaml` 是蓝图，不是直接执行包。
- 不得用聊天总结代替状态账本、蓝图包或 scoped subpacket。
