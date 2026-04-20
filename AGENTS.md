# AGENTS

**Purpose**
- 本文件是对 L0/D1/README/ARCHITECTURE_NOTE/control 的执行性压缩承接，用于约束 Codex/AI 代理在当前仓库的可执行范围。

**Authority Order**
- `docs/L0.md` 为唯一上位总纲。
- `docs/裁决总表.md` 为唯一裁决索引。
- `docs/D1_研发_Codex执行手册.md` 与 `docs/D2`~`docs/D14` 仅展开 L0，不得反向改写 L0。
- `contracts/*`、`handoff/*`、`control/*` 为机器承接层。
- `scripts/*` 为正式校验入口。
- `README.md`、`ARCHITECTURE_NOTE.md` 仅做仓库导航与结构说明。
- `archive/*` 非现行正式引用面。

**Current Formal Paths**
- `docs/`
- `contracts/`
- `handoff/`
- `scripts/`
- `control/`
- 根目录：`README.md`、`ARCHITECTURE_NOTE.md`

**Current Repository Phase**
- 当前 phase：`PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT`。
- 当前 repo readiness：`READY_FOR_POST-REPAIR_MAINLINE_SELECTION`。
- 当前 conditional-go：`READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT`。
- 当前执行模式：内部 LeadOps 产品开发小包模式（task packet / scoped subpacket），不是“开工前准备态 / 只补齐准备资产”。
- 当前阻断：外部软件 release 仍为 `BLOCKED`；线索包外发仍需审批链 + 审计链。
- 允许：内部线索运营开发与受控实现、必要的文档/机器资产最小补齐、运行脚本校验并如实汇报结果。
- 禁止：对外软件 release、无审批的线索包外发、无审计的触达或交付。

**Required Read Order**
1. `docs/L0.md`
2. `docs/裁决总表.md`
3. `docs/D1_研发_Codex执行手册.md`
4. `README.md`
5. `ARCHITECTURE_NOTE.md`
6. `docs/正式业务代码开发开工裁决页.md`
7. `control/repo_status.md`
8. `control/*`
9. `contracts/*`
10. `handoff/*`
11. `scripts/*`

**Allowed Work**
- 文档修订与机器承接层同步补齐（docs/contracts/handoff/testing/governance/control）。
- 生成或完善 skeleton（无真实逻辑）。
- 最小实现设计。
- 受控实现（受门禁约束）。
- 运行脚本校验并如实汇报结果。
- 对以下文档仅允许补表，不得改正文：
  `docs/D1_研发_Codex执行手册.md`、`docs/D2_正式对象契约与字段字典.md`、`docs/D3_正式规则码总表与判定说明书.md`、`docs/D6_字段策略字典与客户交付字段规范.md`、`docs/D7_对象级交付矩阵与外发治理规范.md`、`docs/D8_真实竞争者识别可售对象与销售推进规范.md`、`docs/D9_联系对象与销售触达规范.md`、`docs/D10_订单支付交付与治理反馈规范.md`、`docs/D11_测试验收与金标回归清单.md`、`docs/D12_部署发布与运行治理规范.md`、`docs/D13_公开可查边界能力清单.md`、`docs/D14_AI模型治理规范.md`。

**Forbidden Work**
- 对外软件 release 或对外承诺。
- 把内部可用误写为客户可用。
- 无审计线索包外发。
- 数据库真实表结构或 migration。
- 外部系统调用或集成。
- 新造第二套对象/枚举/门禁/路径。
- 未获授权改写 D 文档正文或 L0 语义。

**Automation Guardrails**
- 自动化动作门禁表：`docs/自动化开发动作门禁表.md`
- 动作矩阵：`control/automation_action_matrix.yaml`
- 停机条件：`control/automation_stop_conditions.yaml`
- 任务包规则：`control/automation_task_packet_rules.yaml`
- 任何触达/支付/交付/高限制字段相关自动化动作，必须按门禁停机并转人工。

**Batch Stop Rules**
- 完成一轮 control 真实值补齐后必须停下汇报。
- 完成一轮骨架生成后必须停下汇报。
- 完成一轮 enum 冻结补表后必须停下汇报。
- 完成一轮 handoff/schema 批量生成后必须停下汇报。
- 运行 `validate-contracts` / `run-golden` / `run-governance-contracts` / `check-release` 后必须停下汇报。

**Human Confirmation Gates**
- 新枚举集合、新对象、新 release gate、新 exception 语义。
- 新模型使用边界与放行口径。
- 从骨架阶段进入最小实现设计。
- 从最小实现设计进入真实实现。
- 任何对外承诺、上线或外发动作。

**Validation and Script Rules**
- 正式校验入口：`scripts/validate-contracts.ps1`、`scripts/run-golden.ps1`、`scripts/run-governance-contracts.ps1`、`scripts/check-release.ps1`。
- 执行方式（统一）：`pwsh -NoProfile -ExecutionPolicy Bypass -File <script.ps1>`。
- 文件存在不等于通过；以真实执行结果为准。
- 脚本失败必须报告根因，不得绕过。

**Current Execution Conventions**
- 当前产品开发小包模式固定按以下口径执行：
  1. `control/current_task.yaml`：锁定当前 active task / scoped subpacket，是唯一当前执行源。
  2. `control/task_packet_library.yaml`：只用于选择下一包或候选包，不替代当前执行源，也不决定当前执行顺序。
  3. `control/repo_status.md`、`control/milestone_status.yaml`：当前 phase / readiness / 状态维度真源。
  4. `docs/AX9S_开发执行路由图.md`：只负责导航，不决定当前执行顺序，也不是状态源、裁决源、执行日志或完整 backlog。
- 历史蓝图、历史修复包与历史语汇（如 `R5 / R6 / Post-R6`）不得作为当前任务来源；它们只允许保留在历史 / 决策 / 状态资产中。
- 若测试断言与当前主线路线图正文定位冲突，优先调整测试到正确的历史 / 决策资产，不得为迁就旧断言而把历史语义重新写回当前主线正文。
- 默认提交行为：
  - 当前 scoped subpacket 的 required scripts 全绿，且仅修改允许范围内文件时，默认允许执行本地 git commit。
  - 提交前必须排除：`报告*.md`、`__pycache__/`、`*.pyc`、`.pytest_cache/`。
  - 上述临时/生成物不得混入 commit、review scope 或 task packet 实际改动范围。
  - 默认不自动 push、不自动进入下一包。
  - 若工作区存在不属于当前包的脏改，必须先停下汇报，不得混入提交。

**Archive and Non-Current Paths**
- `archive/*` 全部为归档路径，不得作为现行正式引用面。

**Output Contract for Codex**
- 每轮输出必须包含：
  1. 修改文件清单
  2. 每个文件修改了什么
  3. 当前脚本/校验结果
  4. 当前阻断项
  5. 是否建议进入下一步
  6. 若不建议，最小补齐路径
