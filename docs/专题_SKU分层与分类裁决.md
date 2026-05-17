# 专题_SKU分层与分类裁决

**版本**: 2026-05-17 v2

## 1. 定位

本专题从本轮开始升级为 **SKU 重构执行设计单源**。

它的职责不是只做“概念说明”，而是为后续文档、对象、策略、UI、测试和迁移任务提供统一设计依据。

本专题的使用边界：

- 这是 **SKU / 专题 / 深度 / 包装** 设计单源。
- 这不是 readiness 状态源。
- 这不是 schema 已生效声明。
- 这不是 runtime 已完成声明。

如与以下资产冲突，先以当前代码、测试和状态源核实，再回修本专题：

- `control/repo_status.md`
- `control/current_task.yaml`
- `control/milestone_status.yaml`
- `docs/L0.md`
- `docs/D2_正式对象契约与字段字典.md`
- `docs/D8_真实竞争者识别可售对象与销售推进规范.md`
- `docs/D13_公开可查边界能力清单.md`

## 2. 问题定义

当前仓库里至少混用了 4 层不同语义。历史上它们要么都被直接叫成了 `SKU`，要么被 `sku_code` 近似承接：

1. AX9S 历史口径里的 5 个“业务证据方向”
2. L0 的 3 个正式对外 `SKU-A/B/C`
3. `TRIAGE / EVIDENCE_PACK / DEEP_RELEASE_CHECK / CUSTOMER_DELIVERY_READY`
4. 历史旧提法 `LeadPack SKU A/B/C/D`

这会带来 5 个直接问题：

1. Stage1-6 不清楚自己到底在消费“专题”还是“SKU”
2. `offer_recommendation.sku_code` 同时被理解成正式产品分类和商业包装码
3. 历史旧提法 `LeadPack SKU` 与 `正式 SKU` 命名冲突
4. 服务深度与产品类别被混为一层
5. 后续 schema 和策略扩展时，字段职责会继续污染

## 3. 设计目标

本轮 SKU 重构设计的目标固定为：

1. 只保留一层继续叫 `SKU`
2. 让 Stage1-6 消费的是“证据专题”，不是商业 SKU
3. 让 Stage7 才生产正式 SKU、服务深度和包装模板
4. 让 `sku_code` 的字段职责唯一且稳定
5. 为后续 schema/runtime 迁移提供可执行路线，而不是只做概念整理

## 4. 四层模型

### 4.1 L1 业务证据专题层

职责：

- 决定 Stage1-6 查什么
- 决定来源、解析重点、核验目标、规则优先级
- 是能力组织层，不是商业产品层

裁决：

- 不再使用历史旧提法“业务证据 SKU”
- 统一改名为 **业务证据专题**

当前首批 5 个业务证据专题：

1. `TOPIC-CERT-REG-TIME`
   证书/注册单位/时间异常专题
2. `TOPIC-RELEASE-CONFLICT`
   负责人未释放/履约冲突专题
3. `TOPIC-CREDIT-PENALTY`
   信用处罚/监管风险专题
4. `TOPIC-COMPOSITE-OBJECTION`
   综合质疑证据专题
5. `TOPIC-PRE-BID-RESTRICTION`
   投前萝卜标/限制竞争预测专题

辅助专题：

1. `TOPIC-TIMELINE-DEFECT`
   程序时间线/公示流程缺陷专题
2. `TOPIC-COMPETITOR-PATTERN`
   竞争格局/陪标围标线索专题

受限信号专题：

1. `TOPIC-SOCIAL-INSURANCE-SIGNAL`
   社保造假信号专题

说明：

- 它只作为综合质疑专题下的定向解析和人工复核信号
- 当前不单独升级为首批正式专题

### 4.2 L2 正式产品 SKU 层

职责：

- 决定“卖什么产品”
- 承接对外售卖与交付组织方式
- 由 Stage7 生成

裁决：

- 仓库中唯一保留 `SKU-A/B/C` 命名的层级

当前正式 SKU：

1. `SKU-A`
   资格与程序打击包
2. `SKU-B`
   评审与竞争异常包
3. `SKU-C`
   组织行为与履约风险包

说明：

- 这层是产品分类
- 不是 Stage1-6 证据路线输入
- 不是服务深度
- 不是 LeadPack 包装层

### 4.3 L3 服务深度档位层

职责：

- 决定查到多深、交付多深
- 和正式 SKU 正交

裁决：

- 不再使用任何 `SKU` 命名
- 统一改称 **服务深度档位**

当前服务深度档位：

1. `TRIAGE`
2. `EVIDENCE_PACK`
3. `DEEP_RELEASE_CHECK`
4. `CUSTOMER_DELIVERY_READY`

说明：

- 同一正式 SKU 可以搭配不同深度档位
- 深度档位不承载“卖什么产品”的语义

### 4.4 L4 商业封装模板层

职责：

- 决定怎么包装呈现
- 决定交付形态、展示模板、报价带组合

裁决：

- 不再把这一层叫历史旧提法 `LeadPack SKU`
- 统一改称 **商业封装模板** 或 **交付包装模板**

当前建议模板码：

1. `PROJECT_BRIEF`
2. `ANALYSIS_REPORT`
3. `EVIDENCE_PACK`
4. `OBJECTION_DRAFT`

说明：

- `LeadPack A/B/C/D` 可以保留为历史业务术语或 UI 标签层
- 但 formal object / schema / policy 不应再用它承接核心字段

## 5. 命名裁决

| 旧叫法 | 新叫法 | 裁决 |
| --- | --- | --- |
| 历史旧提法：业务证据 SKU | 业务证据专题 | 必须替换 |
| 正式 SKU | 正式 SKU | 保留 |
| 深度 SKU | 服务深度档位 | 必须替换 |
| 历史旧提法：LeadPack SKU | 商业封装模板 / 交付包装模板 | 正式字段层必须替换 |
| D13 A/B/C/D | 能力边界分层 | 不得叫 SKU |

## 6. 对象与字段模型

### 6.1 本轮已固定字段解释

当前正式字段：

- `offer_recommendation.sku_code`
- `saleable_opportunity.recommended_sku`

统一解释为：

- **L2 正式产品 SKU**
- 只允许 `SKU-A / SKU-B / SKU-C`

不得再解释为：

- 业务证据专题
- 服务深度档位
- LeadPack 包装模板
- D13 能力边界层

### 6.2 建议新增字段

本轮只是设计，不代表已落 schema。后续迁移建议新增如下字段：

| 字段 | 所属对象 | 作用 |
| --- | --- | --- |
| `evidence_topic_codes` | `execution_context` | Stage1 启动时指定本次要跑哪些专题 |
| `primary_evidence_topic_code` | `project_fact` | Stage6 归纳的主专题 |
| `resolved_evidence_topic_codes` | `project_fact` | Stage6 已成立或进入复核的专题集合 |
| `service_tier_code` | `offer_recommendation` | Stage7 给出的服务深度档位 |
| `package_template_code` | `offer_recommendation` | Stage7 给出的包装模板 |
| `package_template_code` | `delivery_record` | Stage9 最终使用的交付模板 |

### 6.3 当前字段兼容关系

在新增字段落地前，当前兼容解释固定为：

- `sku_code` = 正式产品 SKU
- `recommended_delivery_form` = 兼容承接包装模板，不再作为主包装字段
- `recommended_quote_band` = 报价带

当前不得再用 `sku_code` 间接表示包装模板。

## 7. Stage1-9 生产与消费关系

| 阶段 | 允许生产 | 允许消费 | 禁止事项 |
| --- | --- | --- | --- |
| Stage1 | `evidence_topic_codes` | 人类输入、路由策略 | 不得生成正式 SKU |
| Stage2 | 专题对应的 capture plan / download scope | `evidence_topic_codes` | 不得生成 SKU |
| Stage3 | 专题相关字段血缘与 parse result | `evidence_topic_codes` | 不得根据解析结果直接包装商业产品 |
| Stage4 | 专题对应 public verification targets / carriers | `evidence_topic_codes` | 不得跳到产品 SKU |
| Stage5 | 专题对应 rule/evidence dual gates | Stage3/4 carriers | 不得生成 `sku_code` |
| Stage6 | `primary_evidence_topic_code`、`resolved_evidence_topic_codes`、`project_fact` | Stage5 dual gates | 不得越权写正式 SKU |
| Stage7 | `sku_code`、`recommended_sku`、`service_tier_code`、`package_template_code` | `project_fact`、buyer fit、commercial policy | 不得重算 Stage1-6 专题事实 |
| Stage8 | 触达计划与包级展示对象 | Stage7 商业对象 | 不得改写 SKU 或专题主结论 |
| Stage9 | 最终交付模板与交付记录 | Stage7/8 商业对象 | 不得回写篡改专题和 SKU 主语义 |

## 8. 默认映射规则

### 8.1 业务证据专题 -> 正式 SKU

这不是硬绑定，只是默认主归属。

| 业务证据专题 | 默认正式 SKU | 可补充并入 |
| --- | --- | --- |
| `TOPIC-CERT-REG-TIME` | `SKU-A` | `SKU-C` |
| `TOPIC-RELEASE-CONFLICT` | `SKU-C` | `SKU-A` |
| `TOPIC-CREDIT-PENALTY` | `SKU-C` | `SKU-A` |
| `TOPIC-COMPOSITE-OBJECTION` | `SKU-A` | `SKU-B` / `SKU-C` |
| `TOPIC-PRE-BID-RESTRICTION` | `SKU-B` | `SKU-C` |
| `TOPIC-TIMELINE-DEFECT` | `SKU-A` | `SKU-B` |
| `TOPIC-COMPETITOR-PATTERN` | `SKU-B` | `SKU-C` |

### 8.2 正式 SKU -> 服务深度档位

三种 SKU 都允许搭配四种服务深度档位：

- `TRIAGE`
- `EVIDENCE_PACK`
- `DEEP_RELEASE_CHECK`
- `CUSTOMER_DELIVERY_READY`

### 8.3 正式 SKU -> 商业封装模板

| 正式 SKU | 更常见的模板倾向 |
| --- | --- |
| `SKU-A` | `OBJECTION_DRAFT` / `EVIDENCE_PACK` |
| `SKU-B` | `ANALYSIS_REPORT` / `EVIDENCE_PACK` |
| `SKU-C` | `ANALYSIS_REPORT` / `PROJECT_BRIEF` |

## 9. 迁移策略

### 9.1 M0 文档冻结

目标：

- 先冻结术语和字段解释
- 暂不改 schema/runtime

DoD：

- 本专题升级为执行设计单源
- 状态板登记其角色
- 后续文档新增内容不得继续把 4 层混叫成 SKU

### 9.2 M1 对象与 schema 收口

目标：

- 在 formal object 层引入缺失字段

范围：

- `execution_context`
- `project_fact`
- `offer_recommendation`
- `delivery_record`
- `schema_catalog`
- `enum_catalog`

DoD：

- `sku_code` 固定为正式 SKU
- `service_tier_code`、`package_template_code`、专题字段有单独落位

### 9.3 M2 Stage7 policy 收口

目标：

- 把 Stage7 的 recommendation/policy 从“一个 sku_code 混承接多层语义”改成“四层分离”

范围：

- `sku_recommendation_policy_catalog.json`
- Stage7 runtime
- `offer_recommendation` 生成逻辑

DoD：

- SKU、深度、包装模板分别产出
- `recommended_delivery_form` 明确保留为兼容字段，不再作为主包装字段

### 9.4 M3 UI 与投影收口

目标：

- 前端不再把正式 SKU、专题和包装混成一栏

范围：

- operator console
- workbench projections
- internal preview cards

DoD：

- UI 至少能分开展示：
  - 主专题
  - 正式 SKU
  - 服务深度
  - 包装模板

### 9.5 M4 回归与清理

目标：

- 清理旧命名
- 补测试
- 统一 contracts / docs / runtime / UI

DoD：

- 现行正式正文不再把业务证据专题直接当作 SKU 层命名；历史提法只保留在迁移说明和对照表
- `LeadPack SKU` 不再作为 formal 字段命名；历史提法只保留在迁移说明和对照表
- docs/contracts/runtime/tests 同步

## 10. 实施任务清单

按当前仓库执行习惯，建议拆成 5 个任务：

1. `SKU-DOC-01`
   冻结四层模型与术语口径
2. `SKU-CONTRACT-02`
   收口对象字段与 schema/catalog
3. `SKU-POLICY-03`
   收口 Stage7 recommendation / policy
4. `SKU-UI-04`
   收口 UI / projection / readback 展示
5. `SKU-CLEANUP-05`
   回归、清理旧命名、修 D2/D8/D13/L0

## 11. 当前明确不做

本轮设计不直接做以下事情：

- 不立即修改 schema
- 不立即修改 enum
- 不立即修改 API
- 不立即修改 Stage7 runtime
- 不立即改变 `sku_code` 当前运行值

本轮只先把**设计、字段归属和迁移顺序**固定下来。

## 12. 最终裁决

1. 当前主业务不是 5 个 SKU，而是 5 个业务证据专题。
2. 当前正式对外 SKU 只有 3 个：`SKU-A/B/C`。
3. 当前服务深度档位有 4 个，并且不再称为 SKU。
4. 当前 LeadPack 只保留为商业封装层概念，不再作为 formal SKU 层。
5. 当前 `sku_code` / `recommended_sku` 只应解释为正式 SKU。
6. Stage1-6 消费专题，Stage7 才生产 SKU / 深度 / 包装。

## 13. 依据

- `docs/AX9S_产品主图与验收总则.md`
- `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md`
- `docs/L0.md`
- `docs/D8_真实竞争者识别可售对象与销售推进规范.md`
- `docs/D13_公开可查边界能力清单.md`
- `contracts/sales/sku_recommendation_policy_catalog.json`
- `contracts/enums/enum_catalog.json`
- `src/stage7_sales/service.py`
- `src/stage7_sales/real_challenger.py`
- `src/shared/policy_executor.py`
