# AI代理开发总路线图 + 7个任务包

## 使用原则

- 一次只允许 AI 代理执行 **1 个任务包**。
- 必须按顺序执行，除非上一个任务包已达到完成标准。
- 不允许 AI 代理自发扩大目标。
- 不允许 AI 代理提前进入 external release / Stage8 live / Stage9 live payment 等被阻断方向。
- 每个任务包都必须先读 control / docs / contracts / 相关 src / tests，再写实施计划，再改代码，再跑测试，再回写结果。
- 每次提交都必须写清：修改文件、修改目的、测试结果、剩余阻断项、是否建议进入下一包。

---

## 总路线图

当前仓库的正确主线不是“马上外部化”，而是先把 **内部 governed 产品做成真正可运营的正式版**。当前状态更接近“内部主链已闭合，但 Stage1-5 仍偏 PARTIAL_RUNTIME，Stage1-6 transport 未全接线，持久化仍偏单机，真实样本运营验收未打透；external/live 仍 blocked”。因此路线分两层：

### 第一层：内部 100% 收口
1. 统一正文 / contracts / runtime 口径
2. Stage1-5 runtime completion
3. Stage1-6 transport / workbench strategy
4. Stage6 产品化
5. Stage8 formal carrier persistence
6. Stage9 受治理回写闭环
7. 正式基础设施 + 真实样本 + 测试/命令入口收口

### 第二层：future unlock（本轮不做）
1. leadpack external delivery
2. source/vendor/export 外部化
3. stage8 live execution
4. external software release
5. stage9 live delivery/payment

---

## 任务包 1：正文 / Contracts / Runtime 对齐包

### 目标
统一 D8 / D9 / D10 正文、contracts/schemas、runtime payload 三层口径，消除字段漂移，形成单一真相源。

### 为什么先做
当前最大的系统性缺口是“正文 -> contracts -> runtime”三层漂移，尤其体现在 Stage7/8/9 字段面不完全一致；如果不先对齐，后面的持久化、产品化、测试样本都会建立在摇摆口径上。 

### 允许修改路径
- `docs/`
- `contracts/`
- `src/shared/`
- `src/stage7_sales/`
- `src/stage8_outreach/`
- `src/stage9_delivery/`
- `tests/`

### 禁止修改路径
- `src/api/`（本包不改 transport）
- `src/storage/`（本包不改持久化结构）
- `scripts/`（除非为了字段对齐补充校验）
- 所有 external unlock 相关 control 文件

### 必做事项
1. 建立字段对齐表：正文字段、schema 字段、runtime 字段三列对照。
2. 对 Stage7/8/9 缺失字段逐项裁决：
   - 是正文下调到 skeleton 口径；还是
   - code/contracts 补到正文口径。
3. 把裁决结果写回正式文档和 schema。
4. 让 runtime payload、validator、builder、测试样本统一采用裁决后字段集。
5. 新增字段漂移测试，防止以后再次分叉。

### 产出物
- 字段对齐裁决表
- 更新后的 D8/D9/D10 文档
- 更新后的 schema/json catalog
- 更新后的 runtime payload builder / validator
- 对应测试用例

### 完成标准
- Stage7/8/9 不再存在“文档要求有，但 schema/runtime 没有”的核心字段漂移。
- 所有新增/删除字段均有裁决说明。
- 形成 1 份简洁的字段基线说明，后续任务包均以此为准。

### 必跑测试
- `python tests/run_tests.py`
- 与 Stage7/8/9 schema/runtime/validator 相关的 targeted tests
- 若仓库允许，再跑：`scripts/validate-contracts.ps1`

### 给 AI 代理的硬约束
不允许为了“方便对齐”直接大量删除正文能力定义；必须逐字段裁决并保留治理理由。

---

## 任务包 2：Stage1-5 真源纵切包

### 目标
先打通 **1 条真实公开源纵切**，把 Stage1 scheduler -> Stage2 fetcher -> Stage3 parser -> Stage4 verifier -> Stage5 rule/evidence 跑成真实来源链，而不是继续主要依赖 payload/fallback。

### 为什么现在做
当前前半链能跑，但还更像 internal runtime / preview engine，不是真正的情报生产线。Stage1 scheduler 还是 skeleton，Stage2 fetchers 为空，真实源没真正落地。

### 允许修改路径
- `src/stage1_tasking/`
- `src/stage2_ingestion/`
- `src/stage3_parsing/`
- `src/stage4_verification/`
- `src/stage5_rules_evidence/`
- `src/shared/`
- `tests/`
- `fixtures/` 或同类样本目录

### 禁止修改路径
- `src/stage7_sales/`
- `src/stage8_outreach/`
- `src/stage9_delivery/`
- `src/storage/`（除非为保存 source snapshot 做最小接口）
- 所有 external unlock / release 相关逻辑

### 必做事项
1. 选定 1 个公开源家族，不许贪多。
2. 把 Stage1 scheduler 从 skeleton 改成最小可解释策略器，能为该源生成稳定任务。
3. 实现 1 个真实 fetcher，支持原始载体固定和基础失败处理。
4. 实现 parser，把原始载体转成结构化片段。
5. 实现 verifier，输出基础核验结果和 evidence slice。
6. 在 Stage5 至少跑通 1 组真实规则，不再只吃 mock flag。
7. 补 1 套 happy case + 1 套 bad case。

### 产出物
- 1 条真实 source blueprint
- 可复跑的真实来源 fixture / snapshot
- 对应 parser / verifier / evidence slice
- 规则命中输出
- targeted tests

### 完成标准
- 不手工塞 payload，也能从真实公开源跑到 Stage5。
- 原始载体、解析结果、核验结果、规则命中之间有可追踪链路。
- 至少 1 个失败场景可复现。

### 必跑测试
- Stage1-5 targeted tests
- `python tests/run_tests.py`
- 若仓库允许：golden / governance 相关最小集

### 给 AI 代理的硬约束
只能做 1 个源家族；不要顺手扩成“多源平台化”。先做成 1 条真的，再考虑复制。

---

## 任务包 3：Stage5 真规则工厂包

### 目标
把 Stage5 从“单规则/flag 驱动”升级为“规则目录批量执行 + evidence slice 引用 + 多规则聚合 + 冲突解释”的最小规则工厂。

### 为什么单独成包
真源纵切只是把水引进来，Stage5 决定这是不是一个真正产证据、产结论的平台。

### 允许修改路径
- `src/stage5_rules_evidence/`
- `src/shared/`
- `contracts/`
- `tests/`
- `docs/`（仅补规则执行说明）

### 禁止修改路径
- `src/api/`
- `src/storage/`（本包不碰正式持久化）
- `src/stage8_outreach/`
- `src/stage9_delivery/`

### 必做事项
1. 设计最小规则目录结构。
2. 支持一次执行多条规则，而不是单 `rule_code`。
3. 每条命中规则必须带 evidence slice 引用。
4. 支持多规则聚合结论与冲突解释。
5. 补规则解释输出，给 Stage6 / 报告层消费。
6. 补样本：命中、部分命中、相互冲突、证据不足。

### 产出物
- 规则目录结构
- 批量执行器
- evidence slice 绑定
- 聚合解释对象
- 测试矩阵

### 完成标准
- Stage5 不再只是“flag shell”，而能批量跑规则并解释结果。
- 下游可直接消费规则聚合输出。
- 失败原因和证据缺口可见。

### 必跑测试
- Stage5 targeted tests
- `python tests/run_tests.py`

### 给 AI 代理的硬约束
不要试图一次把全部规则都写完；先做“规则工厂框架 + 少量高价值规则样本”。

---

## 任务包 4：Stage6 产品化包

### 目标
把 `project_fact / report / review_queue / challenger / legal_action_recommendation` 从“链路里存在”升级成 first-class 产品对象，补齐持久化、workbench、preview、operator loop。

### 为什么必须做
如果 Stage6 不 first-class，产品永远从 Stage7 才开始“能运营”，上游事实中枢就只是计算结果，不是产品台。

### 允许修改路径
- `src/stage6_fact_review/`
- `src/storage/`
- `src/api/`（仅限 Stage6 transport/workbench）
- `src/shared/`
- `contracts/`
- `tests/`
- `docs/`

### 禁止修改路径
- external unlock 相关 control
- `src/stage8_outreach/` / `src/stage9_delivery/` 的 live 执行能力

### 必做事项
1. 给 Stage6 对象定义正式 repository contract。
2. 接入持久化读写。
3. 补 Stage6 preview/workbench/operator loop。
4. 让 Stage7 消费已持久化的 Stage6 对象，而不是只吃链路瞬时对象。
5. 补 replay / review / reopen 场景。

### 产出物
- Stage6 repository
- Stage6 API/workbench
- Stage6 operator 流
- replay / reopen 测试

### 完成标准
- Stage6 对象可独立创建、读取、更新、复核、回放。
- Stage7 对 Stage6 的依赖从“瞬时链路对象”提升为“正式产品对象”。

### 必跑测试
- Stage6 targeted tests
- repository boundary tests
- api transport tests
- `python tests/run_tests.py`

### 给 AI 代理的硬约束
不能跳过持久化直接先做页面；先把对象做实，再补 surface。

---

## 任务包 5：Stage8/9 闭环补全包

### 目标
补齐 Stage8 formal carrier persistence，以及 Stage9 受治理回写闭环，但仍保持 internal-only / governed，不触碰 live unlock。

### 为什么现在做
Stage8 目前已有 schema/runtime/test，但 formal carrier 的专门 repository / persisted record / readback 还不完整；Stage9 仍偏 projected writeback，没有把上游对象纳入受治理回写链。

### 允许修改路径
- `src/stage8_outreach/`
- `src/stage9_delivery/`
- `src/storage/`
- `src/api/`（仅限 internal preview/replay/readback）
- `contracts/`
- `tests/`
- `docs/`

### 禁止修改路径
- `contracts/release/` 中 live unlock 策略
- external delivery / payment 真执行逻辑
- provider/source externalized usage

### 必做事项
1. 给 `contact_candidate_collection / contact_selection_trace` 建正式 repository、持久化、hydration、replay、operator readback。
2. 让 Stage8 多来源 merge / reselect / source conflict 有正式可回放对象，不只是快照。
3. 为 Stage9 设计受治理回写管线，先覆盖：
   - `project_fact`
   - `saleable_opportunity`
   - `contact_target`
   - `review_queue_profile`
   - `sales_lead`
   - `report_record`
4. 回写必须是 internal additive / governed，不得绕过审批边界。
5. 补回写审计与失败恢复。

### 产出物
- Stage8 formal carrier repository
- Stage8 replay/readback 能力
- Stage9 internal writeback pipeline
- audit / recovery tests

### 完成标准
- Stage8 formal carrier 不再只是 runtime 生成物，而是正式产品对象。
- Stage9 不再只有 projected contracts，而有受治理的上游回写闭环。
- 仍保持 internal-only，不触发 live execution。

### 必跑测试
- Stage8 targeted tests
- Stage9 targeted tests
- repository boundary tests
- `python tests/run_tests.py`

### 给 AI 代理的硬约束
任何“真实触达、真实支付、真实交付”能力一律不做；本包只补 internal governed 闭环。

---

## 任务包 6：正式基础设施与全链入口包

### 目标
把单机 JSON 内测底座升级成正式底座，并明确 Stage1-6 transport/workbench 策略，完成内部工作台基础骨架。

### 为什么要有这一包
前面的能力做出来，如果还挂在单机 JSON + 不完整入口上，产品还是半成品，没法稳定团队运营。

### 允许修改路径
- `src/storage/`
- `src/api/`
- `src/shared/`
- `scripts/`
- `docker/` 或部署目录
- `docs/`
- `tests/`
- 配置文件

### 禁止修改路径
- business rules 大规模重写
- external unlock 逻辑
- 真实支付/外部交付逻辑

### 必做事项
1. 把文件型存储迁到正式底座：PostgreSQL + SQLAlchemy + Alembic。
2. 补任务队列/异步基础：Redis + Dramatiq。
3. 补对象存储：MinIO/S3，用于证据固定件、导出物、LeadPack preview。
4. 补 Docker Compose 与最小运行治理。
5. 裁决 Stage1-6 transport/workbench 策略：
   - 接正式 transport；或
   - 给出明确 internal orchestration UI/API。
6. 建立统一 operator / approval / audit 基础语义。

### 产出物
- 正式存储迁移脚本
- 队列与对象存储接线
- compose / dev runtime
- Stage1-6 入口裁决与实现
- 运维与开发说明

### 完成标准
- 默认运行不再依赖 per-process JSON 文件。
- Stage1-6 不再只是“隐式靠 pipeline/test 才能用”。
- 团队可在稳定底座上复跑、回放、审计。

### 必跑测试
- 存储迁移 / repository tests
- api transport tests
- `python tests/run_tests.py`
- 若仓库允许：`check-final-gate.ps1`

### 给 AI 代理的硬约束
不允许“为了上线快”跳过 migration、audit、replay；这个包的意义就是把底座做正式。

---

## 任务包 7：真实样本运营验收包

### 目标
把产品从“回归绿”推进到“实测绿”，建立真实样本矩阵、失败 taxonomy、operator replay、SLA/队列/审计报表。

### 为什么是最后一个内部包
没有真实样本，前面 1-6 包即使代码上完成，也很容易是“看起来可以”。这个包是把产品能力真正压实。

### 允许修改路径
- `tests/`
- `fixtures/`
- `docs/`
- `src/api/`
- `src/storage/`
- `src/stage6_fact_review/`
- `src/stage8_outreach/`
- `src/stage9_delivery/`
- `scripts/`

### 禁止修改路径
- external unlock / live execution
- 大规模重构前半链逻辑
- 临时为过样本而写死业务逻辑

### 必做事项
1. 建真实样本矩阵，至少覆盖：
   - review
   - hold
   - reject
   - reselect
   - quiet hours
   - approval missing
   - source conflict
   - partial delivery
   - feedback writeback
2. 建 operator replay 流。
3. 建失败 taxonomy。
4. 建 SLA / 队列 / 审计报表最小集。
5. 把真实样本纳入回归测试。
6. 形成 1 份 internal pilot 验收结论。

### 产出物
- 样本矩阵
- replay 机制
- 失败分类表
- 报表/审计最小集
- internal pilot 验收记录

### 完成标准
- 不再只有 happy/block 两类测试视角。
- 关键失败/复核/审批场景可重复演练。
- 能支撑内部持续运营，而不是一次性演示。

### 必跑测试
- `python tests/run_tests.py`
- 样本矩阵回归
- 若仓库允许：正式门禁脚本全套

### 给 AI 代理的硬约束
不能为了让样本通过而在代码里硬编码 case 特判；必须抽象成稳定机制。

---

## 执行顺序

严格建议按以下顺序投喂：

1. 任务包 1：正文 / Contracts / Runtime 对齐包
2. 任务包 2：Stage1-5 真源纵切包
3. 任务包 3：Stage5 真规则工厂包
4. 任务包 4：Stage6 产品化包
5. 任务包 5：Stage8/9 闭环补全包
6. 任务包 6：正式基础设施与全链入口包
7. 任务包 7：真实样本运营验收包

---

## 暂时不要开的包

以下方向现在 **禁止启动**：

- external software release
- Stage8 live execution
- Stage9 live delivery
- Stage9 live payment / refund
- 外部 provider/source/vendor 解锁实现
- 花哨 UI 优化优先于主链闭环

这些方向必须等前 7 包完成，并且按仓库既定 unlock 顺序单独立项。

---

## 给 AI 代理的统一回报模板

每次完成一个任务包，必须输出：

1. 本次读取了哪些 control / docs / contracts / src / tests
2. 修改文件清单
3. 每个文件修改目的
4. 新增对象 / 字段 / 接口 / 测试
5. 当前测试结果
6. 当前剩余阻断项
7. 是否建议进入下一任务包
8. 若不建议，最小补齐路径是什么

