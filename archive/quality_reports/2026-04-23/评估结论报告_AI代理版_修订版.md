# 质量评估结论报告（AI代理版·修订）

## 一、总判断

截至当前批次，仓库的真实状态应收敛为：

- `Stage1-9` 内部主链已经存在，并可通过内部链路跑通
- 当前定位是 **内部 LeadOps 开发 / 内部 governed 运营**，不是 external release
- `Stage7-9` 是当前最成熟的内部 governed 内核
- `Stage1-6` 仍偏 runtime / pipeline，尚未达到与 `Stage7-9` 同等级的产品化完成度
- `Stage1-6` 的 FastAPI transport 仍未正式挂载；正式 API 面当前主要挂载 `Stage7/8/9`
- `Stage8/9` 当前仍是 governed / preview / approval-gated / internal-only 口径，不是 fully live execution
- `Stage9` 当前是 **projected writeback / additive internal only**，不是真实 live upstream mutation
- 外部软件发布、Stage8 real execution、Stage9 real payment / delivery / refund 仍处于正式治理阻断状态
- 当前正式门禁与全量测试结果为 **全绿**；测试章节不应再把历史失败批次当作当前状态结论

更准确的定位是：

> 内部 LeadOps 主线已基本闭合，当前可用于内部 governed 开发、验收与运营；但尚未达到“前半链完全产品化、正式基础设施落地、外部化解锁”的完成态。

---

## 二、当前能力现状

### 1. 主链已存在，不是假能力

当前仓库已经具备真实的 `Stage1-9` 内部链路，不是“只有代码绿”的空壳，也不是纯文档仓。

现状包括：

- `pipeline` 可串起 `Stage1` 到 `Stage9`
- handoff / schema / enum / guard / semantic validation 已接入运行时
- `Stage6` 的 `project_fact` 已作为统一事实入口存在，并被后续链路依赖
- `Stage7` 已能产出并持久化：
  - `saleable_opportunity`
  - `buyer_fit`
  - `offer_recommendation`
  - actor / competitor 相关对象
- `Stage8` 已具备 schema、运行时生成和测试覆盖，能够生成：
  - `contact_candidate_collection`
  - `contact_selection_trace`
  - `contact_target`
  - `outreach_plan`
  - `touch_record`
- `Stage9` 已能生成：
  - `order_record`
  - `payment_record`
  - `delivery_record`
  - `opportunity_outcome_event`
  - `governance_feedback_event`

### 2. 当前最成熟的是 Stage7-9

`Stage7-9` 已具备：

- preview / draft / operator loop / workbench
- repository replay / typed lifecycle / capability guard / release gate
- impact executor / writeback projection 等治理化机制
- internal transport / internal slice 已较成型

### 3. Stage1-6 仍未达到同等级产品化

现状是：

- `Stage1-6` 更像 runtime / pipeline 层，而不是完整产品面
- FastAPI 正式 transport 当前只真正挂了 `Stage7-9`
- `Stage1-6` 仍是 `CONTROLLED_UNAVAILABLE` / `TRANSPORT_NOT_WIRED` / `PARTIAL_RUNTIME` 口径
- `Stage6` 虽然已有事实中枢和复核逻辑，但还没有成为 first-class 的正式产品台

### 4. Stage1 scheduler 仍是骨架

当前 `Stage1 scheduler` 仍属 skeleton-only 口径，尚未成为正式的可解释调度器。

---

## 三、核心缺口

### 1. 前半链成熟度不足：Stage1-5 仍非稳定运营级

当前前半链的问题不在“有没有代码”，而在：

- 能跑，但还不是稳定运营级
- 仍存在 skeleton / placeholder / TODO 残留
- `Stage1 scheduler` 仍是骨架态
- `Stage1-5` 更像“内部 runtime / 合同驱动链路”，不是“成熟的一线产品化能力面”

### 2. 真源生产尚未落地

当前前半链大量事实仍主要来自：

- payload
- contract fallback
- fixture / 样例链路
- internal preview / runtime simulator 逻辑

而不是真正意义上的：

- `Stage1` 真调度
- `Stage2` 真抓取
- `Stage3` 真解析
- `Stage4` 真核验
- `Stage5` 真规则工厂

当前更准确的判断是：

> 系统已经有 formal runtime / internal preview engine，但还不是完整的真实情报生产线。

### 3. 真规则生产仍偏薄

`Stage5` 虽然已有 gate 与 contract closure，但仍偏向：

- 单规则 / flag 驱动
- 围绕单个 `rule_code` 运转
- 不是从真实文本与证据切片出发的完整规则目录批量执行体系

当前更接近 gate shell，而不是成熟规则工厂。

### 4. Stage6 未正式产品化

当前：

- `project_fact / report / review_queue / challenger / legal_action_recommendation` 主要存在于链路中
- 尚未成为完整的仓储对象、工作台对象、正式持久化对象
- 产品真正可运营的起点仍偏向 `Stage7`，而不是从 `Stage6` 就开始

结果是：

1. 上游事实中枢没有正式 product surface
2. 复核与法律行动建议队列没有 first-class 运营面

### 5. Stage8 formal carrier 已有 schema/runtime/test，但专门 persistence 仍未完整产品化

当前：

- `contact_candidate_collection`
- `contact_selection_trace`

已经具备：

- 正式 schema
- 运行时生成
- 测试覆盖

当前缺的不是“完全没有打穿”，而是：

- 专门 repository
- formal persisted record
- 更完整的 persistence / hydration / replay / operator readback 产品化闭环

因此更准确的结论是：

> Stage8 formal carrier 已经进入 schema 与运行时层，但尚未完成专门持久化与正式产品化闭环。

### 6. Stage9 当前是 internal-only projected writeback，不是真实上游 mutation 闭环

`Stage9` 已能产出：

- `impact_mutations`
- `projected_contracts`
- `advisories`

但当前口径应精确表述为：

- internal-only
- projected writeback
- additive internal only
- executor 不直接持久化目标 mutation

因此当前并未形成完整的上游真实 mutation pipeline，仍然缺少：

- 误判回收
- 结果回写
- 持续校正
- 对 `Stage6/7` 上游核心对象的真实受控回写

### 7. 文档正文、contracts、runtime 三层未收口

当前最大缺口之一，是：

> 正文文档 -> schema / contracts -> runtime payload 三层没有完全收口。

重点体现在 `D8 / D9 / D10` 字段面上。

#### Stage7 字段面缺口

- `saleable_opportunity` 缺 `requires_manual_review`
- `sales_lead` 缺 `lead_lane / blocking_reasons`
- `buyer_fit` 缺 `fit_status / fit_blocking_reasons`
- 两类 actor 缺 `*_basis_refs / requires_manual_review`

#### Stage8 字段面缺口

- `contact_target` 缺
  `account_context_id_optional / contact_role_reason / source_document_ref_optional / source_slice_ref_optional / approval_state_optional`
- `outreach_plan` 缺
  `fallback_channel_family_optional / primary_message_summary / message_goal / value_angle / legal_basis_snapshot / frequency_snapshot / quiet_hours_snapshot / opt_out_snapshot / created_by_role / last_revalidated_at`
- `touch_record` 缺
  `touch_direction / touch_result_family / followup_due_at_optional / operator_role / audit_ref / message_snapshot_ref_optional / feedback_summary_optional`

#### Stage9 字段面缺口

- `order_record` 缺
  `account_context_id / recommended_sku / contract_value_band / discount_policy_state / delivery_scope_summary / offer_version_ref / release_state / audit_ref`
- `payment_record` 缺
  `payment_method_family / currency_code / payment_due_at_optional / payment_audit_ref`
- `delivery_record` 缺
  `delivery_template_id / delivered_by_role / delivery_audit_ref / delivery_risk_state / rework_state`
- outcome / governance 相关对象也缺部分正文要求的回写与审计字段

这组字段缺口应被视为后续整改的一号输入。

### 8. 持久化后端仍偏单机 / 内测态

当前持久化核心仍偏本地文件存储，适合：

- internal replay
- operator loop
- 单机验证

但不适合：

- 正式多用户
- 长生命周期
- 持续运营
- 正式并发场景

### 9. 平台基础设施尚未正式落地

技术路线已经冻结为：

- `PostgreSQL + SQLAlchemy + Alembic`
- `Redis + Dramatiq`
- `MinIO/S3`
- `Docker Compose`

但当前实际仍主要运行在文件型存储与内测式基础设施上。

这意味着技术方向已经明确，但正式平台底座还没有真正落到运行面。

### 10. 入口一致性不足

当前：

- `Stage7-9` 有 transport / workbench / preview surface
- `Stage1-6` 没有对等的产品入口

导致全链操作面不统一，内部 orchestration 仍显隐式。

### 11. 真实样本与实操验收仍不足

当前仍缺：

- 真实项目链路
- 真实竞争者样本
- `Stage8 dry_run / approval_run / real_run` 实操面
- `Stage9` 沙箱交付 / 回写实测
- operator replay / trace / pending actions / blocked reasons 的真实场景打磨
- review / partial payment / refund / reject / reselect / quiet hours / frequency / approval missing 等例外样本矩阵

当前更接近：

> 内部 governed 演练可用，而不是全量真实运营场景已打透。

### 12. 文档状态仍未最终冻结

当前：

- `D8 / D9 / D10 / D11 / D13` 等仍为 `DRAFT`
- `D1-D14` individually 仍未完全冻结
- 但文档包与机器资产包已在一定意义上成为 current formal package

这说明当前是：

- 运行能力先行
- 治理口径正在收口
- 但还没有到“语义冻结”的正式状态

### 13. 外部化与 live 执行仍被治理性压住

当前：

- `leadpack_external_delivery` 仍需审批、审计、signoff、prep
- `stage8_live_execution` 仍 blocked / approval-gated / dry-run by default
- `stage9_live_delivery_execution` 与 `stage9_live_payment_execution` 仍 blocked / shadow mode / deny by default
- `external_software_release` 仍 blocked
- future unlock 仍在 decision / prep，而不是 implementation / open

---

## 四、当前验证结论

当前批次的正式验证结论应直接写为：

- `python tests/run_tests.py`：全部 PASS
- `check-final-gate`：PASS
- `doctor`：PASS
- `check-task-packet`：PASS
- `validate-contracts`：PASS
- `check-state-alignment`：PASS
- `run-golden`：PASS
- `run-governance-contracts`：PASS
- `lint-drift`：PASS
- `check-handoff-dependencies`：PASS

因此测试章节应收敛为：

> 当前正式门禁全绿，历史失败批次仅作为背景信息，不再作为当前状态结论。

---

## 五、范围与状态源说明

当前 `docs/quality/*` 应视为：

- 评估稿
- 未跟踪内容
- 非当前 tracked 仓库正式状态源

因此应明确：

> `docs/quality/*` 可作为评估输入，但不能替代 `control/*`、正式 contracts、正式 scripts 与实际运行结果，作为仓库当前状态的唯一权威来源。

---

## 六、统一优先级

### 第一优先级：先把“内部 100%”收口

#### 1. 前半链补齐为真实 runtime / product surface
优先补：

- `Stage1 scheduler`
- `Stage1-6 transport / bootstrap`
- `Stage1-5` placeholder / TODO / skeleton 收口
- 失败回放、人工介入点、统一 trace、统一 operator 语义

#### 2. 打通真数据纵切
先选 1 个 A 层公开源家族，打通：

`Stage1 scheduler -> Stage2 fetcher -> Stage3 parser -> Stage4 verifier -> Stage5 rule/evidence`

不先做这条，后半链再成熟，也仍是“吃样例的内测型 runtime”。

#### 3. 把 Stage5 升级成规则工厂
从“单规则 / flag 驱动”升级到：

- 规则目录批量执行
- slice 级 evidence 引用
- 多规则聚合
- 冲突解释
- 从真实文本/证据切片批量生产规则结论

#### 4. Stage6 产品化
要把以下对象提升为 first-class 运营对象：

- `project_fact`
- `report`
- `review_queue`
- `challenger`
- `legal_action_recommendation`

并补：

- workbench
- preview
- operator loop
- 正式持久化

#### 5. 文档 / contracts / runtime 字段面收口
优先对齐：

- `D8`
- `D9`
- `D10`
- `contracts/schemas/*`
- runtime payload / typed records

原则只有二选一：

- 要么把正文正式下调到 skeleton 口径
- 要么把 code / contracts 补到正文口径

不能继续双口径共存。

#### 6. 补 Stage8 formal carrier 产品化闭环
正式补齐：

- repository
- persisted record
- persistence
- hydration
- API replay
- operator readback

重点对象：

- `contact_candidate_collection`
- `contact_selection_trace`

#### 7. 补 Stage9 真回写闭环
把当前 projection-only / additive-internal-only 进一步升级成：

- 受治理控制的真实 upstream mutation pipeline
- 对 `Stage6/7` 上游关键对象的真实受控回写

至少覆盖：

- `project_fact`
- `saleable_opportunity`
- `contact_target`
- `review_queue_profile`
- `sales_lead`
- `report_record`

### 第二优先级：平台化底座落地

#### 8. 替换单机文件型存储
按既定路线落地：

- `PostgreSQL + SQLAlchemy + Alembic`
- `Redis + Dramatiq`
- `MinIO/S3`
- `Docker Compose`

#### 9. 统一全链入口
需要明确决定 `Stage1-6` 是否接入正式 transport / workbench。
如果不接，也必须给出明确的 internal orchestration UI/API，而不是继续隐式依赖 pipeline / tests / 手工运行。

#### 10. 保持正式门禁持续稳定全绿
当前状态不是“测试不稳待复核”，而是“当前批次已全绿，应维持这一状态并防止回退”。

重点包括：

- 统一测试入口
- 保持命令字符串发布与执行一致性
- 防止跨测试污染回归
- 保证全量门禁可重复稳定全绿

### 第三优先级：真实样本运营验收

#### 11. 建立真实样本矩阵
至少补齐：

- real project chain
- competitor review
- approval missing
- review hold
- reject
- partial payment
- refund
- reselect
- quiet hours
- frequency control
- operator replay
- blocked reasons / hold reasons / pending actions

#### 12. 完成内部运营验收包
应优先完成当前内部运营验收包，把以下内容在真实内部样本上验收完：

- operator / workbench
- blocked / hold / review reasons
- trace / replay
- pending actions

### 第四优先级：future unlock 程序

当前不支持直接冲 external / live。

推荐顺序：

1. `leadpack_external_delivery`
2. `source_vendor_externalized_usage`
3. `external_export_surface`
4. `model_provider_externalized_usage`
5. `stage8_live_execution`
6. `external_software_release`
7. `stage9_live_delivery_execution`
8. `stage9_live_payment_execution`

原则：

- 不先做 external software release
- 不先做 `Stage8/9 live`
- 先把 internal 100%、平台化、实测矩阵收口
- 再按审批、审计、signoff、activation prep 逐层推进 unlock

---

## 七、可直接执行的任务定义

### 主任务标题
`内部 100% 收口主线`

### 范围
- `Stage1 scheduler completion`
- `Stage1-6 transport strategy / bootstrap`
- `Stage1-5 runtime / model / schema 收口`
- 真数据纵切
- 真规则工厂
- `Stage6` 产品化
- `D8 / D9 / D10` 与 contracts / runtime 对齐
- `Stage8` formal carrier persistence / repository / readback 闭环
- `Stage9` 真回写闭环
- 正式底座替换
- 真实样本矩阵
- 测试 / 门禁持续全绿

### 不包含
- `external_software_release`
- `Stage8 live real execution`
- `Stage9 live payment / delivery / refund`
- 高风险外部 provider 全量解锁

---

## 八、一句话结论

> 这套仓库已经有真实的内部 `1-9` governed 主链，`Stage7-9` 内核已成型；当前最重要的不是再写零散功能，而是把前半链真实生产化、把 `D8/D9/D10` 与 contracts/runtime 收口、把 Stage8 formal carrier 与 Stage9 writeback 做成正式闭环、把正式底座落地，并在保持当前门禁全绿的前提下完成内部运营验收，再进入后续 unlock program。
