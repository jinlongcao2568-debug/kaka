# 迁移说明（最终收口模板）

## 1. 当前迁移目标

将多轮生成的正式文档、机器资产、控制资产，收口到仓库正式路径中，并停止使用中间 round 包命名。

## 2. 建议迁移顺序

1. 固定根目录 README、状态板、裁决总表
2. 将 D1-D14 终版放入 `docs/`
3. 将 contracts 核心包、api/ui、governance/release、exceptions/sales、testing 放入 `contracts/`
4. 将 handoff 资产放入 `handoff/`
5. 将 scripts 放入 `scripts/`
6. 将 control 模板放入 `control/`
7. 将中间 round 包移入 `archive/`
8. 执行 doctor / validate / golden / governance / release 全链检查

## 3. 必须人工确认的项

- owner 真实值
- current task 真实值
- approval chain 真实值
- exception chain 真实值
- 文档状态板最终状态
- 是否满足 Go / No-Go 条件

## 4. 禁止事项

- 不得边迁移边改写正式语义
- 不得保留双路径同时作为正式引用面
- 不得在未跑检查脚本前宣称 ready
