# 标准仓库总包

本仓库服务于**内部线索运营平台 / 情报生产平台 / 销售作战平台**，对外交付的是线索包、机会包、情报包与销售推进结果，不交付客户可见软件平台本体。

本压缩包已经把当前 的正式文档、机器资产、handoff、scripts、control、archive 按统一仓库架构整理好。你解压后，不需要再手动按 round 包拆分。

## 顶层目录

- `docs/`：L0、裁决总表、D1-D14、清单、状态板、体检报告
- `contracts/`：正式机器契约层
- `handoff/`：stage1-stage9 handoff 机器资产
- `scripts/`：统一校验/回归/发布前检查入口
- `control/`：owner、current task、审批链、例外链、引用索引
- `archive/`：历史生成稿、round 包、zip 导出、迁移说明

## 使用顺序

1. 先看根目录 `AGENTS.md`，确认当前执行方式与人类最新指令。
2. 再看 `docs/L0.md`、`docs/裁决总表.md` 与本次改动直接相关的 D 文档。
3. 涉及对象、规则、字段、交付、发布、模型、公开边界时，再看对应 `contracts/`、`handoff/`、`control/`、`scripts/`。
4. 普通内部开发默认按 `DIRECT_DEV_DEFAULT` 直接定位、实现、验证；`docs/正式业务代码开发开工裁决页.md` 只作为内部 LeadOps 开发 conditional-go 历史裁决面，不作为普通开发前置门槛。
5. 触及对外/live、release gate、approval/audit 语义、schema/migration 或机器契约大批量治理时，才切回 controlled task packet / scoped subpacket。

## 说明

- 当前产出面包含：文档、contracts、handoff、control、骨架（skeleton）、最小实现设计与受控实现代码。
- `docs/` 下放的是当前现行正式路径。
- `archive/generated_rounds/` 下保留了此前给你的历史生成稿和 round 包，不作为现行正式引用面。


