# governance / release 包（第一轮）

本目录是“开工前总清单”之后的第二轮机器承接资产，专门承接 **D6 / D7 / D13** 的正式治理与放行口径。

本轮交付：

- `governance/public_boundary_registry.json`
- `governance/coverage_registry.json`
- `governance/field_policy_dictionary.json`
- `governance/approval_chain_catalog.json`
- `release/delivery_matrix.json`
- `release/release_gates.json`

定位：

1. 把 D13 的 A/B/C/D 公开边界落成机器可读 registry；
2. 把 D6 的字段分类、脱敏、审批链落成机器可读 policy；
3. 把 D7 的对象级交付矩阵与 release gate 落成机器可读目录；
4. 为后续 `api`、`ui`、`testing`、`handoff`、`control` 包提供单一治理约束源。

当前范围：

- 覆盖公开边界、coverage、字段策略、审批链、对象交付矩阵与 release gate；
- 已和 `contracts_core_round1` 的 schema / enum / rule / gate catalog 对齐；
- 默认仍为 DRAFT，用于“正式业务代码开工前”的治理准备，不作为示意稿使用。

下一轮建议：

- `contracts/testing/*`
- `handoff/*`
- `control/*`
- `archive/*`
