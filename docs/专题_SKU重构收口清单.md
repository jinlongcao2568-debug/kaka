# 专题_SKU重构收口清单

**版本**: 2026-05-17 v1

## 1. 目的

本专题用于给当前 SKU 重构提供一份短平快收口清单，回答三个问题：

1. 哪些已经完成
2. 哪些是刻意保留的兼容层
3. 哪些还要在后续阶段继续做

本清单是执行辅助面，不是状态源。

配套设计单源：

- `docs/专题_SKU分层与分类裁决.md`

## 2. 已完成

### 2.1 术语分层已冻结

- `业务证据 SKU` 已冻结为历史旧提法，现行统一使用 `业务证据专题`
- `正式 SKU` 保留为唯一 SKU 层
- `服务深度档位` 已与 SKU 分离
- `LeadPack 商业封装档位` 已与 SKU 分离

### 2.2 对象字段边界已冻结

- `offer_recommendation.sku_code` 只承接正式 SKU
- `saleable_opportunity.recommended_sku` 只承接正式 SKU
- `execution_context.evidence_topic_codes` 已落位
- `project_fact.primary_evidence_topic_code` 已落位
- `project_fact.resolved_evidence_topic_codes` 已落位
- `offer_recommendation.service_tier_code` 已落位
- `offer_recommendation.package_template_code` 已落位
- `delivery_record.package_template_code` 已落位

### 2.3 Stage7 policy 已拆成四层输出

- `sku_code`
- `service_tier_code`
- `package_template_code`
- `recommended_quote_band`

### 2.4 展示层已拆开

Stage7 preview / workbench / operator 详情已开始拆开展示：

- 主专题
- 专题集合
- 正式 SKU
- 服务深度
- 包装模板

## 3. 兼容保留

### 3.1 允许继续保留的兼容字段

- `recommended_delivery_form`

当前定位：

- 兼容字段
- 继续给现有 runtime / UI surface 使用
- 不再作为 contract 主包装字段
- 不再承担“正式 SKU”语义

### 3.2 允许继续保留的历史术语

以下旧词只允许出现在迁移说明、对照表或历史问题描述中：

- `业务证据 SKU`
- `LeadPack SKU`

不允许继续出现在现行正式正文的命名层定义里。

### 3.3 允许继续保留的历史标识

以下历史标识当前先不改，以避免无必要扰动回归稳定性：

- `contracts/testing/regression_manifest.json` 中的历史 `suite_id`
  - `REG-BIZ-LEADPACK-SKU-OFFER`
  - `REG-P2-SKU-RECOMMENDATION`

裁决：

- 这些 id 当前视为**历史稳定标识**
- 可以继续保留
- 但不再代表现行术语口径

## 4. 后续仍需完成

### 4.1 文档层

- 继续吸收 SKU 重构结论到：
  - `L0`
  - `D2`
  - `D8`
  - `D13`
- 后续新文档不得再创造第二套 SKU 术语

### 4.2 schema / contract 层

- 明确哪些新字段未来要从 optional 提升为强约束
- 明确 `package_template_code` 与 `recommended_delivery_form` 的长期关系

### 4.3 runtime / policy 层

- 继续清理“把包装模板误当 SKU 的逻辑”
- 后续如有 Stage8/9 下游消费 `recommended_delivery_form`，逐步迁到 `package_template_code`

### 4.4 UI / projection 层

- 把四层分离展示扩展到更多页面，而不只限于 Stage7 preview/workbench

## 5. 当前硬规则

1. Stage1-6 只能生产和消费专题，不得直接生产正式 SKU。
2. Stage7 才允许正式生产：
   - `sku_code`
   - `service_tier_code`
   - `package_template_code`
3. `recommended_delivery_form` 是兼容层，不是新的主语义中心。
4. 不得再把 `LeadPack 商业封装档位` 写成正式 SKU。

## 6. 当前建议

如果后续继续推进，推荐顺序是：

1. 清理剩余兼容显示面
2. 在下游 surface 完成兼容迁移后，再决定 `recommended_delivery_form` 是否降为更弱兼容字段
3. 持续让 `package_template_code` 成为主包装字段
