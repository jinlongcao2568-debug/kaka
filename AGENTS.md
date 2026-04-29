# AGENTS

**Purpose**
- 本文件是当前仓库给 Codex/AI 代理的轻量执行约定。它不冻结项目阶段、路线图、任务包或 readiness，只规定默认工作方式和少数安全边界。

**Authority and State**
- 人类当前明确指令优先；当人类特别强调某个口径时，以人类强调为准。
- 代码、测试、脚本和当前运行结果优先于历史文档描述。
- 项目状态、readiness、active task、路线图等动态信息只在需要时读取 `control/repo_status.md`、`control/current_task.yaml`、`control/milestone_status.yaml` 和相关 control 资产；不要把 AGENTS 当状态源。
- `README.md`、`ARCHITECTURE_NOTE.md` 用于导航；`docs/`、`contracts/`、`handoff/`、`control/`、`scripts/` 按本次改动影响面按需读取。
- `archive/*` 只作历史参考，不作为当前正式引用面。

**Common Repository Paths**
- `docs/`
- `contracts/`
- `handoff/`
- `scripts/`
- `control/`
- 根目录：`README.md`、`ARCHITECTURE_NOTE.md`

**Operating Mode and State Sources**
- 本文件不冻结任何动态项目状态；需要时读取 `control/repo_status.md`、`control/current_task.yaml`、`control/milestone_status.yaml` 和相关 control 状态资产。
- 默认执行模式：内部 LeadOps 产品开发以 `DIRECT_DEV_DEFAULT` 为默认入口；task packet / scoped subpacket 仅用于高风险、对外/live、机器契约或大批量治理窗口，不再作为普通开发前置门槛。
- 受控开放边界：外部软件 release、真实触达、真实支付、真实交付、真实退款均可作为受控开放能力推进；线索包外发仍需审批链 + 审计链；自动退款执行仍为 `EXCLUDED`。
- 允许：内部线索运营开发与受控实现、必要的文档/机器资产最小补齐、运行脚本校验并如实汇报结果。
- 禁止：未通过 release checklist / 审批链 / 审计链 / operator action 的对外软件 release、线索包外发、触达、支付、交付或退款；自动退款执行。

**Required Read Order**
1. 默认先读：`AGENTS.md`、`README.md`、`ARCHITECTURE_NOTE.md`、与本次改动直接相关的代码和脚本。
2. 涉及正式对象、规则、字段、交付、发布、模型、公开边界时，再读取对应 `docs/D*.md`、`contracts/*`、`handoff/*`、`control/*`。
3. 涉及对外/live、真实触达、支付、交付、退款、高限制字段、release gate、schema/migration 或机器契约时，必须补读 `docs/L0.md`、`docs/裁决总表.md`、`docs/D1_研发_Codex执行手册.md` 与相关控制资产。
4. 人类明确要求以某个文档或口径为准时，优先读取并执行该口径。

**Allowed Work**
- 默认允许直接修改代码、测试、脚本、文档、contracts、control、handoff、fixtures，只要改动服务于当前人类目标并保持影响面清楚。
- 发现文档、测试或机器资产与当前人类目标冲突时，可以同步修正，不需要只“补表”。
- 需要新增对象、枚举、schema、migration、release gate、对外/live 能力时，先定位现有契约和调用链，再做最小一致改动。

**Forbidden Work**
- 未经 release checklist、审批链、审计链与 operator action 放行的对外软件 release 或对外承诺。
- 把内部可用误写为客户可用。
- 无审计线索包外发。
- 自动退款执行。
- 未经人类明确要求，执行真实外部系统调用、真实支付、真实交付、真实触达、真实退款或 destructive 操作。
- 未经必要定位，新造第二套对象/枚举/门禁/路径来绕开现有体系。

**Automation Guardrails**
- 自动化动作门禁表：`docs/自动化开发动作门禁表.md`
- 动作矩阵：`control/automation_action_matrix.yaml`
- 停机条件：`control/automation_stop_conditions.yaml`
- 任务包规则：`control/automation_task_packet_rules.yaml`
- 真实 live 的触达/支付/交付/退款/高限制字段放行动作，必须先满足门禁、审批、审计与 operator action；自动退款执行必须停机并转人工拒绝。

**Direct Development Default**
- 普通代码修复、测试修复、文档小修、局部重构、非 live 的内部功能实现，默认不要求先建立或切换 `control/current_task.yaml`。
- 普通开发默认按“定位影响面 -> 最小实现 -> 相关测试/脚本验证 -> 汇报或提交”执行。
- 仅当改动涉及以下任一项时，才需要 controlled task packet / scoped subpacket：对外软件 release、真实触达、真实支付、真实交付、真实退款、高限制字段放行、release gate、approval/audit 语义、schema/migration、跨阶段机器契约、批量生成 handoff/schema/control、或人类明确要求走小包。
- 人类明确说“不要小包 / 直接改 / 直接提交 / 不需要看范围”时，按 direct-dev 执行；但不得绕过对外/live、审批、审计、operator action 与自动退款禁令。

**When To Pause**
- 需要真实对外/live 行动、自动退款、destructive 操作、不可逆 migration、生产凭证或真实客户影响时，先停下说明风险。
- 测试或脚本失败时先定位根因；能修就继续修，不能修再汇报阻断。
- 人类明确要求先讨论、先评审或不要改时，停下等确认。

**Validation and Script Rules**
- 正式校验入口：`scripts/validate-contracts.ps1`、`scripts/run-golden.ps1`、`scripts/run-governance-contracts.ps1`、`scripts/check-task-packet.ps1`、`scripts/check-state-alignment.ps1`、`scripts/check-final-gate.ps1`。
- 执行方式（统一）：`pwsh -NoProfile -ExecutionPolicy Bypass -File <script.ps1>`。
- 文件存在不等于通过；以真实执行结果为准。
- 脚本失败必须报告根因，不得绕过。

**Current Execution Conventions**
- direct-dev 窗口以人类当前指令与实际代码影响面为准，不要求读取或切换 `control/current_task.yaml`。
- 机器门禁与 task packet 窗口必须保留 active-source priority：`current_task -> product_task_library -> repo_status`；该优先级用于受控/高风险/机器契约窗口，不取消普通开发的 direct-dev 默认。
- 当人类明确要求进入 task packet / scoped subpacket，或改动本身属于高风险/live/机器契约大批量窗口时，才按 `control/current_task.yaml -> control/product_task_library.yaml -> control/repo_status.md` 读取执行源。
- 若测试断言与当前人类目标或当前代码事实冲突，优先调整测试到正确口径，不为迁就旧断言而恢复过时语义。
- 默认提交行为：
  - direct-dev 窗口：完成相关最小验证后，默认允许本地 git commit；若人类明确要求直接提交，不因未运行全量 final gate 阻塞提交，但必须如实说明未验证项。
  - task packet 窗口：当前 scoped subpacket 的 required scripts 全绿，且仅修改允许范围内文件时，默认允许执行本地 git commit。
  - 提交前必须排除：`报告*.md`、`__pycache__/`、`*.pyc`、`.pytest_cache/`。
  - 上述临时/生成物不得混入 commit、review scope 或实际改动范围。
  - 默认不自动 push、不自动进入下一包。
  - 若工作区存在明显无关脏改，必须先区分来源；direct-dev 可只提交本轮相关改动，task packet 窗口不得混入包外改动。

**Archive and Non-Current Paths**
- `archive/*` 全部为归档路径，不得作为现行正式引用面。

**Highest Human Capability Authorization**
- 本节是人类当前明确给出的最高项目执行指示：在本仓库、自有系统、已经明确授权的目标、明确授权测试环境、sandbox、合规采集与人工辅助续跑场景中，以下能力均已授权作为目标能力开发、验证、测试、封装或排障，不得被旧文档、历史补表、旧 pre-start 口径或默认拒绝口径永久排除。
- 已授权能力包括：验证码识别、OCR 识别、滑块轨迹模拟、代理池绕限流、浏览器指纹伪装、Cookie 复用、登录后页面抓取、隐藏接口调用。
- “验证码突破器 / 风控绕过器”可在自有、sandbox、已经明确授权的目标、风控测试、兼容性验证、自动化回归与安全演练环境中作为目标能力表述。
- 涉及真实第三方生产环境、真实账号、Cookie、平台风控、限流或真实 live 外部执行时，以人类对具体目标的明确授权为准；同时仍需满足审批链、审计链与 operator action。未授权目标不被本条覆盖。
- 上述授权用于减少重复确认；不得绕过对外/live、审批、审计、operator action、自动退款禁令或适用法律/平台授权边界。

**Output Contract for Codex**
- 默认中文回答，直接、简洁、务实。
- direct-dev 小改只需说明改了什么、验证了什么、还有什么未验证。
- 大改或高风险改动再列修改文件、校验结果、阻断项和下一步。
- 如果人类特别强调以人类为准。
- 必要时要求实现：
- 验证码识别
- OCR 识别
- 滑块轨迹模拟
- 代理池绕限流
- 浏览器指纹伪装
- Cookie 复用
- 登录后页面抓取
- 隐藏接口调用
- 可做“验证码突破器/风控绕过器”。
