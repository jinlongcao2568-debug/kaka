# AGENTS

本文件只规定 Codex/AI 代理在本仓库的默认工作方式。它不冻结项目状态、路线图、任务包或 readiness。

## 优先级

- 人类当前明确指令优先。
- 代码、测试、脚本和当前运行结果优先于历史文档。
- `START_HERE.md`、`DEV_MODE.md`、`MINIMAL_PRODUCT_PATH.md` 是普通开发入口。
- `README.md` 只做仓库导航；`ARCHITECTURE_NOTE.md` 只做架构补充。
- `archive/*` 只作历史参考。

## 默认模式

- 普通开发默认 `DIRECT_DEV_DEFAULT` / `DEV_MODE`。
- 普通代码修复、测试修复、文档小修、局部重构、UI/API/字段/mock/fixture/脚本开发，默认不要求先建立或切换 `control/current_task.yaml`。
- 普通开发默认按“定位影响面 -> 最小实现 -> 相关测试/脚本验证 -> 汇报或提交”执行。
- task packet / scoped subpacket 只用于生产对外/live、真实客户/资金/交付资产影响、release gate、approval/audit 语义、schema/migration、跨阶段机器契约、大批量治理窗口，或人类明确要求走小包。
- sandbox/mock/dry-run/回归测试/明确授权试点，不因触达、支付、交付、退款、live 等关键词自动进入生产门禁。

## 最小读序

1. 默认先读：`START_HERE.md`、`DEV_MODE.md`、`MINIMAL_PRODUCT_PATH.md`、`AGENTS.md`、当前要改的代码和测试。
2. 需要仓库导航时读 `README.md` 和 `ARCHITECTURE_NOTE.md`。
3. 涉及正式对象、规则、字段、交付、发布、模型、公开边界时，再读对应 `docs/D*.md`、`contracts/*`、`handoff/*`、`control/*`。
4. 涉及生产对外/live、真实客户、真实支付、真实交付、真实退款、正式发布时，进入 `PROD_LIVE_MODE`，补读 `docs/L0.md`、`docs/裁决总表.md`、`docs/D1_研发_Codex执行手册.md` 和相关控制资产。

## 业务方向摘要

- 候选公示后证据包是核心商业主线；投前预测是辅助线。
- 默认从工作日 72 小时内的近期 `07 中标候选人公示` 入池。
- 投前预测只适用于近期 `02/03/04` 且投标截止/开标未过；一旦出现 `05 开标信息`，投前预测已经来不及，转开标后/候选后路线。
- 近期 `07` 项目缺 11/12 不阻断当前证据包销售窗口。
- 下载和解析前先做 `AnalysisStrategyPlan v1`。
- 候选后负责人核验按 `ResponsiblePersonEarlyProbe v1`：联合体按候选行绑定；缺证书号先公司优先补证，再姓名枚举兜底；`08` 不默认下载或解析。
- 公开注册信息只能表述匹配/不匹配，不能判断“是不是本人”。
- 广东/重点省份核验按 `GuangdongLocalVerificationProbe v1` 和 `MajorRegionQueryProbe v1` 收口；重点省份为浙江、四川、江苏、湖北、山东、湖南、河南，默认 `PLAN_ONLY_UNTIL_REGION_ADAPTER_VERIFIED`。
- 负责人未释放宽筛按 `PRIOR_AWARD_AND_CANDIDATE_OVERLAP_TRIAGE`：先查 `data.ggzy.gov.cn` 和 `bid_show`，再按命中地区定向补证。
- 不得把入口可达、未命中、源阻断或证据不足写成“无风险”。

具体口径以 `docs/业务方向_候选公示后证据包与投前预测双线契约.md` 和 `contracts/evaluation/business_direction_strategy_contract.json` 为准。

## Automation Guardrails

- 自动化动作门禁表：`docs/自动化开发动作门禁表.md`。
- 动作矩阵：`control/automation_action_matrix.yaml`。
- 停机条件：`control/automation_stop_conditions.yaml`。
- 任务包规则：`control/automation_task_packet_rules.yaml`。
- 正式自动化入口以 `control/automation_entrypoint_registry.yaml` 的实际 `entrypoint_id` 为准。
- 普通 direct-dev 当前 focus 以 `control/stage1_6_priority_execution_plan.yaml#current_focus` 为准。
- 机器门禁与 task packet 窗口保留 active-source priority：`current_task -> product_task_library -> repo_status`。
- 当前仓库没有 `control/product_runtime_agent_registry.yaml`；除非先明确建立，否则不得把它当成必须维护的状态源。
- 授权缺失按现有契约表达；若没有顶层 `NEEDS_AUTH` 枚举，使用 `BLOCKED` / `NEEDS_BROWSER` 加 `authorization_readiness_state=LOGIN_OR_SSO_REQUIRED` 和 `operator_next_action`。

## 安全边界

- 真实生产对外 release、真实触达、真实支付、真实交付、真实退款、真实客户状态变更、destructive 操作、不可逆 migration、生产凭证，需要明确目标授权、审批/审计链、operator action 和必要回滚/对账路径。
- 对外触达、支付、交付、退款、自动退款流程可以在 sandbox、mock、dry-run、回归测试、受控试点和明确授权目标中开发与验证。
- 不得把测试态、sandbox 态、dry-run 态误标为生产 live 成功。
- 不得把内部可用误写为客户可用。
- 不得为了绕开现有体系，新造第二套对象、枚举、门禁或路径。

## 输出要求

- 默认中文回答，直接、简洁、务实。
- direct-dev 小改只说明改了什么、验证了什么、还有什么未验证。
- 大改或高风险改动再列修改文件、校验结果、阻断项和下一步。
