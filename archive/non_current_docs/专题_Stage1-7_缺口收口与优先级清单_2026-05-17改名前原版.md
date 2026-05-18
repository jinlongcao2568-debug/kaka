# 专题_Stage1-7_缺口收口与优先级清单

**版本**: 2026-05-17 v1

## 1. 文档目的

本专题用于把当前仓库 Stage1-7 的主要缺口重新收口成一份可直接落仓库的 closeout 文稿，避免后续代理重复从聊天记录拼接结论。

本文档是**缺口快照和优先级清单**，不是正式状态源，也不替代：

- `control/repo_status.md`
- `control/current_task.yaml`
- `control/milestone_status.yaml`
- `docs/AX9S_产品主图与验收总则.md`
- `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md`
- `docs/AX9S_Stage4-5_核验双闸门SOP.md`

## 2. 一句话结论

当前 Stage1-7 的真实状态不是“前面没做”，而是：

- Stage1-3 主干链路已形成。
- Stage4 外部证据链最弱，是当前最大短板。
- Stage5 双闸门已实现，但真实样本规模和误报/漏报校准还不够。
- Stage6/7 内部对象和 internal readback 已存在，但真实候选常被 Stage4 的源覆盖和释放证据链卡在 `PARTIAL_SOURCE_COVERAGE`。

## 3. 已跑通

| 能力块 | 当前状态 | 说明 |
| --- | --- | --- |
| Stage1 市场扫描与来源蓝图主干 | 已跑通 | `operator` 搜索入口、地区/类型/金额输入归一、候选批量分流、来源蓝图和运行记录已形成内部闭环。 |
| Stage1 重点地区主路径 | 已跑通 | 广东、四川、江苏、浙江已有较明确的候选发现路径和 region adapter 主路径。 |
| Stage2 公开链主干 | 已跑通 | 列表页、详情页、附件快照、hash、来源 URL、失败 taxonomy 已进入正式链路。 |
| Stage2 fail-closed 挑战分类 | 已跑通 | 登录、验证码、反爬、指纹、Cookie、滑块、OCR challenge 都已有 taxonomy 和 resume context。 |
| Stage3 主流文件解析链 | 已跑通 | HTML、PDF、Word、Excel、字段血缘、候选/负责人/报价等主流抽取链已可运行。 |
| Stage5 双闸门框架 | 已跑通 | `rule_gate_decision` 和 `evidence_gate_decision` 已实现并有测试覆盖。 |
| Stage6/7 内部对象链 | 已跑通 | `project_fact`、`saleable_opportunity`、`buyer_fit`、`multi_competitor_collection`、`commercial_hook` 等对象和 internal readback 已存在。 |
| Stage1-6 internal orchestration | 已跑通 | Stage6 内部编排入口可串联 Stage1-6，适合作为 owner 内部运行入口。 |

## 4. 半跑通

| 能力块 | 当前状态 | 主要问题 |
| --- | --- | --- |
| Stage4 广东/广州外部源 | 半跑通 | 广东三库一平台、合同履约、审批、处罚、信用广东、广州施工许可/竣工等已有部分 query/readback，但还没形成稳定的释放证据闭环。 |
| P13B 负责人未释放/履约重叠 | 半跑通 | `data.ggzy`、`bid_show`、原文链接、YGP readback 的第一层宽筛已成形；命中后的释放证据深查还不稳定。 |
| Stage1/2 山东、湖北覆盖 | 半跑通 | 已有入口 profile 和观察状态，但缺专门候选发现器、真实列表解析回归和稳定 discoverer。 |
| Stage2/3 文件长尾 | 半跑通 | 主流文件能处理，但扫描件 OCR、复杂表格、多候选行绑定、`08 投标文件公开` 定向解析仍未稳定。 |
| Stage4-9 真实候选 formal readback | 半跑通 | 路径已存在，但真实候选常落到 `PARTIAL_SOURCE_COVERAGE`，尚不能稳定形成客户可售证据。 |
| Stage7 内部 saleable 链 | 半跑通 | 内部可售对象和商业钩子能生成，但经常受 Stage4 缺口影响，`real_public_sellable_gate_ready=false`。 |

## 5. 未跑通

| 能力块 | 当前状态 | 直接证据 |
| --- | --- | --- |
| 项目经理变更释放 runtime adapter | 未跑通 | `项目经理变更释放` 在矩阵里仍是 `MISSING_RUNTIME`；`project_manager_change_notice_runtime_adapter_not_implemented` 仍在代码中。 |
| 多省地方硬伤源 live adapter | 未跑通 | 浙江、四川、江苏、湖北、山东、湖南、河南等重点省份目录默认仍是 `PLAN_ONLY_UNTIL_REGION_ADAPTER_VERIFIED`。 |
| P13B 命中后的释放证据深查闭环 | 未跑通 | 目前能生成 release trigger 和补查任务，但还不是稳定 runtime 执行链。 |
| 50+ 真实项目 snapshot 样本账本 | 未跑通 | `REQ-REAL-PROJECT-SNAPSHOT` 当前仍是 `MISSING`，要求最少 50 个真实项目样本。 |
| Stage1-5 独立 HTTP 运行入口 | 未跑通 | Stage1-5 route registrar 仍是 `controlled unavailable`，不是独立 API 运行面。 |

## 6. P0 缺口

### P0-1 Stage4 释放证据链闭环

- 现状：Stage4 是当前最大短板。身份核验、部分公开源 readback 已有，但“许可/合同/竣工/项目经理变更/处罚”多源交叉后的释放证据链仍不完整。
- 直接症状：
  - `项目经理变更释放` 在矩阵中仍为 `MISSING_RUNTIME`
  - 真实候选经常落到 `PARTIAL_SOURCE_COVERAGE`
  - `real_public_sellable_gate_ready=false`
- 影响：Stage6/7 内部对象虽已存在，但真实候选不能稳定升级为客户可售证据。
- 完成标准：
  - 命中重叠信号后，能稳定补查 `construction_permit`、`contract_public_info`、`completion_filing`、`project_manager_change_notice`
  - 释放证据链可回放，且不会把“未命中/源阻断”写成“无风险”
  - `project_manager_change_notice` 从 plan/readback 升级为稳定 runtime adapter

### P0-2 真实项目 snapshot 样本账本

- 现状：覆盖审计仍显示 `REQ-REAL-PROJECT-SNAPSHOT = MISSING`，当前 `0/50`。
- 影响：Stage4/5/6 的真实样本校准深度不够，很多能力只能算“结构存在”而不是“真实样本稳定”。
- 完成标准：
  - 采集 50-100 个真实项目公告/附件 snapshot
  - 样本覆盖 `07` 候选、`03/04` 回溯、附件、失败 taxonomy、Stage4 readback
  - 不用假样本或 seed 伪造填平

## 7. P1 缺口

### P1-1 山东、湖北候选发现器补齐

- 现状：SD/HB 目前主要还是入口 profile、挑战观察和解析回归不足。
- 影响：首批试点省份看起来是 6 省，但真实成熟度并不均衡。
- 完成标准：
  - SD/HB 有专门 discoverer
  - 有真实列表结构解析回归
  - 在操作台和文档里不再以“观察态/挑战态”存在

### P1-2 P13B 从宽筛走到深查

- 现状：目前宽筛已能稳定输出 overlap signal 和 release trigger table。
- 影响：只能说“发现疑似重叠线索”，不能说“释放证据链已查清”。
- 完成标准：
  - 命中同一负责人/公司/时间窗口时，自动进入定向深查
  - 深查结果能输出为 Stage4 carrier 和 Stage5 dual-gate 输入
  - YGP/地方源阻断时保持 fail-closed，不误推无风险

### P1-3 Stage2/3 长尾文件链补强

- 现状：PDF/Word/Excel/OCR 主链已通，但长尾仍不稳。
- 重点项：
  - 扫描件 OCR
  - 复杂表格
  - 多候选行绑定
  - `08 投标文件公开` 定向解析
- 完成标准：
  - 扫描件能区分“已识别”“需 OCR”“OCR 引擎不可用”“OCR 失败”
  - 多候选行和联合体绑定不串行
  - `08` 仍保持 strategy-driven，不默认全量深解析

### P1-4 Stage5 真实样本校准

- 现状：`TAILORED/FATAL/PRICE/REMEDY` 规则已存在，但更接近“第一刀 + 内部复核规则”。
- 影响：误报/漏报尚未经过足够真实样本压测。
- 完成标准：
  - 50+ 真实项目样本校准
  - 有明确的误报/漏报修订记录
  - SKU 级规则形成稳定 PASS/REVIEW/BLOCK 边界

## 8. P2 缺口

### P2-1 Stage1-5 独立 API 面

- 现状：真正可用入口还是 `operator` 搜索入口和 Stage6 internal orchestration。
- 说明：这不是 bug，但如果目标是“Stage1-5 每阶段都可独立 API 运行”，那就还没开发完。
- 完成标准：
  - Stage1-5 不再只是 `controlled unavailable`
  - 每阶段都有正式 transport 入口和 readback

### P2-2 状态资产一致性

- 现状：
  - `control/repo_status.md` 和 2026-05-16 的 AX9S 文档已按 144-149 后内部闭环完成来表述
  - `control/operator_user_acceptance_gap_matrix.json` 仍停留在 2026-05-01 口径
- 风险：后续代理容易误判成“真实候选 Stage4-9 formal readback 完全没接入”
- 建议收口：
  - 把该矩阵从“未接入 Stage4-9 formal readback”改成“路径已存在，但真实候选常因 Stage4 外部源和 sellable gate 停在 `PARTIAL_SOURCE_COVERAGE`”
  - 明确它是旧验收快照，不是当前唯一缺口判断源

## 9. 不应误判为已完成的项

- 不能因为 Stage1-3 可跑，就说客户可售证据已稳定形成。
- 不能因为 Stage5 测试全绿，就说规则已达稳定商用品质。
- 不能因为 Stage6/7 对象齐全，就说真实可售链已闭环。
- 不能因为 challenge taxonomy 存在，就说真实第三方风控站点都已跑通。
- 不能因为广州/广东部分源已有 query/readback，就说 Stage4 多省释放证据链已完成。

## 10. 推荐执行顺序

1. 先补 50-100 个真实项目 snapshot 样本账本。
2. 再补 Stage4 释放证据链，优先项目经理变更、合同、竣工、许可。
3. 再把 P13B 从宽筛推进到命中后的稳定深查。
4. 再补 SD/HB discoverer 和真实回归。
5. 最后做 Stage5 真实样本校准和 Stage1-5 独立 API 面。

## 11. 直接依据

- `docs/AX9S_产品主图与验收总则.md`
- `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md`
- `docs/AX9S_Stage4-5_核验双闸门SOP.md`
- `control/repo_status.md`
- `control/product_module_registry.yaml`
- `control/product_operability_gap_matrix.yaml`
- `control/operator_user_acceptance_gap_matrix.json`
- `contracts/evaluation/evaluation_coverage_requirements.json`
- `src/stage1_tasking/region_adapters.py`
- `src/stage1_tasking/real_candidate_discovery.py`
- `src/stage2_ingestion/public_source_adapters.py`
- `src/stage3_parsing/ocr_text.py`
- `src/stage4_verification/provider_handlers.py`
- `src/api/routes/operator_customer_access.py`
