# AGENTS

本文件只规定 AI 代理在本仓库的默认工作方式。项目状态、路线图、业务细节和 readiness 不写在这里。

## 默认工作方式

- 默认中文回答，直接、简洁、务实。
- 人类当前明确指令优先；代码、测试、脚本和实际运行结果优先于历史文档。
- 普通开发默认走 `DEV_MODE`：定位影响面、最小实现、相关验证、汇报结果。
- 普通功能、bug、测试、UI、API、mock、fixture、脚本和局部文档修正，不要求先建 task packet。
- `sandbox`、`mock`、`dry-run`、回归测试和明确授权试点，不因“触达 / 支付 / 交付 / 退款 / live”关键词自动进入生产门禁。

## 最小读序

普通开发先读：

1. `START_HERE.md`
2. `DEV_MODE.md`
3. `MINIMAL_PRODUCT_PATH.md`
4. 当前要改的 `src/`、`tests/`、`scripts/` 文件

需要仓库导航时再读 `README.md`。只有改正式对象、规则、字段、交付、发布、模型或公开边界时，才按需读取 `docs/`、`contracts/`、`handoff/`、`control/`。

Stage1-6 direct-dev 当前 focus 以 `control/stage1_6_priority_execution_plan.yaml#current_focus` 为准。

## 生产边界

以下才进入 `PROD_LIVE_MODE` 或受控窗口：

- 真实对外 release
- 真实客户可见状态
- 真实触达发送
- 真实支付 / 扣款
- 真实交付 / 下载放行
- 真实退款 / 生产自动退款
- 生产凭证、不可逆 migration、破坏性操作

进入 `PROD_LIVE_MODE` 时，必须有明确目标授权、审批/审计链、operator action，以及必要的对账、回滚或暂停路径。

测试态可以开发和验证触达、支付、交付、退款、自动退款能力，但不得把测试成功写成生产 live 成功。

## 不做的事

- 不把内部可用误写成客户可用。
- 不把入口可达、未命中、源阻断或证据不足写成“无风险”。
- 不为了绕开现有体系新造第二套对象、枚举、门禁或路径。
- 不把 `archive/*` 当成当前默认入口。
