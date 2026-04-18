# contracts 核心包（第一轮）

本目录是“开工前总清单”之后的第一轮机器承接资产，只覆盖最核心的 4 个 catalog：

- `schemas/schema_catalog.json`
- `enums/enum_catalog.json`
- `rules/rule_catalog.json`
- `gates/gate_policies.json`

定位：

1. 把 D2 / D3 / D13 的核心正式口径转成机器可读承接层；
2. 为后续 `api`、`ui`、`governance`、`release`、`testing`、`handoff` 包提供单一语义源；
3. 作为“正式业务代码开工前”的最低 contracts 起点，而不是示意草稿。

当前范围：

- 覆盖阶段 1-9 + 跨阶段治理隔离层的主要正式对象；
- 覆盖核心正式枚举；
- 覆盖首版正式规则目录；
- 覆盖双闸门与全局优先序。

下一轮建议：

- `contracts/governance/*`
- `contracts/release/*`
- `contracts/testing/*`
- `handoff/*`
