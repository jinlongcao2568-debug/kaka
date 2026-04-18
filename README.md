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

1. 先看 `docs/L0.md`
2. 再看 `docs/裁决总表.md`
3. 再看 `docs/D13_公开可查边界能力清单.md`、`docs/D2_正式对象契约与字段字典.md`、`docs/D3_正式规则码总表与判定说明书.md`
4. 然后看 `contracts/`、`handoff/`、`scripts/`
5. 最后根据 `docs/正式业务代码开发开工裁决页.md` 判定是否可以正式写代码

## 说明

- 当前产出面包含：文档、contracts、handoff、control、骨架（skeleton）、最小实现设计与受控实现代码。
- `docs/` 下放的是当前现行正式路径。
- `archive/generated_rounds/` 下保留了此前给你的历史生成稿和 round 包，不作为现行正式引用面。


