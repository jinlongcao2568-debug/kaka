# START HERE

日常开发从这里开始。目标是先动起来，不把普通功能开发变成全仓库审判。

## 默认做法

普通开发默认是 `DEV_MODE`：

1. 先找当前要做的功能入口。
2. 只读相关代码、相关测试和必要导航。
3. 做最小可运行改动并跑相关测试。
4. 汇报改动、验证和未覆盖风险。

普通开发不要求：

- 先切 `control/current_task.yaml`
- 先写 task packet
- 先同步 D1-D14 全部文档
- 先跑全量 final gate
- 因为出现“触达 / 支付 / 交付 / 退款 / live”关键词就停止开发

生产门禁只管 `PROD_LIVE_MODE`，不要拿来阻断 `DEV_MODE`。

## 最小读序

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

## 推荐验证

默认用本地隔离测试环境，避免被本机 PostgreSQL 环境变量污染：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/invoke-local-json-test-env.ps1 python -m unittest <相关测试> -v
```

只在需要正式契约同步时跑：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/validate-contracts.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-state-alignment.ps1
```

详细模式边界只看 `DEV_MODE.md`。
