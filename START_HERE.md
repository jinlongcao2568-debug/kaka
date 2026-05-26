# START HERE

本文件是新手和 AI 代理的日常开发入口。先按这里做，不要一上来读完整 `docs/`、`contracts/`、`control/`。

## 1. 默认怎么开发

普通开发默认是 `DEV_MODE`：

1. 先找当前要做的功能入口。
2. 只读相关代码、相关测试和少量导航文档。
3. 做最小可运行改动。
4. 跑相关测试。
5. 说明改了什么、验证了什么、还有什么没验证。

普通开发不要求：

- 先切 `control/current_task.yaml`
- 先写 task packet
- 先同步 D1-D14 全部文档
- 先跑全量 final gate
- 因为出现“触达 / 支付 / 交付 / 退款 / live”关键词就停止开发

## 2. 三种模式

| 模式 | 用途 | 默认权限 |
|---|---|---|
| `DEV_MODE` | 本地开发、功能实现、mock、假数据、UI、普通代码和测试 | 默认允许 |
| `TEST_MODE` | sandbox、dry-run、回归、受控样本、明确授权试点 | 默认允许，但要标记测试态和保留日志 |
| `PROD_LIVE_MODE` | 真实客户、真实触达、真实支付、真实交付、真实退款、真实对外发布 | 必须授权、审批、审计、operator action、对账/回滚 |

生产门禁只管 `PROD_LIVE_MODE`，不要拿来阻断 `DEV_MODE`。

## 3. 最小读序

普通开发只读：

1. `START_HERE.md`
2. `DEV_MODE.md`
3. `README.md`
4. 当前要改的 `src/`、`tests/`、`scripts/` 文件

按需再读：

- Stage1-9 总流程：`docs/AX9S_Stage1-9_执行矩阵与子漏斗.md`
- 当前缺口：`docs/专题_Stage1-9_缺口收口与优先级清单.md`
- Stage4/5 核验：`docs/AX9S_Stage4-5_核验双闸门SOP.md`

只有改正式对象、规则、字段、发布、模型、公开边界时，才回到 `docs/L0.md`、`docs/裁决总表.md` 和 D 文档。

## 4. 推荐验证命令

默认用本地隔离测试环境，避免被本机 PostgreSQL 环境变量污染：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/invoke-local-json-test-env.ps1 python -m unittest <相关测试> -v
```

只在需要正式契约同步时跑：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/validate-contracts.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-state-alignment.ps1
```

## 5. 什么时候才算高风险

只有这些情况进入 `PROD_LIVE_MODE` 或受控窗口：

- 真实对外发布
- 真实客户可见
- 真实触达发送
- 真实支付 / 扣款
- 真实交付 / 下载放行
- 真实退款 / 生产自动退款
- 生产凭证、不可逆 migration、破坏性操作

如果只是 mock、sandbox、dry-run、回归测试或明确授权试点，不按生产 live 阻断。

