# 标准仓库总包

本仓库服务于**真实公开市场机会发现 + 证据包商业化的运营系统**：系统目标是从真实公开来源发现项目候选，完成候选解析、证据核验、商业价值判断、证据包生成和销售推进。内部/样本链路只作为开发回归与安全演练环境，不再作为产品实战完成标准。对外交付的是线索包、机会包、情报包与销售推进结果，不交付客户可见软件平台本体。

当前仓库已经按统一正式路径整理好：文档、机器资产、handoff、scripts、control、archive 都在现行目录下，不需要再按历史 round 包拆分理解。

## 顶层目录

- `docs/`：L0、裁决总表、D1-D14、清单、状态板、体检报告
- `contracts/`：正式机器契约层
- `handoff/`：stage1-stage9 handoff 机器资产
- `scripts/`：统一校验/回归/发布前检查入口
- `control/`：owner、current task、审批链、例外链、引用索引
- `archive/`：历史生成稿、round 包、zip 导出、迁移说明

## 使用顺序

默认不要遍历 `docs/` 全部文件。普通开发、补功能、修功能或跑验证，先按这套最小读序走：

1. `AGENTS.md`、`README.md`、`ARCHITECTURE_NOTE.md`
   只看入口规则、边界、目录导航和脚本用法。
2. `docs/专题_Stage1-9_缺口收口与优先级清单.md`
   用来判断“接下来先做什么”。
3. `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md`
   用来判断“这个功能做到什么算完成”。
4. `docs/AX9S_Stage4-5_核验双闸门SOP.md`
   只有在做 Stage4/5 时再读。
5. `docs/专题_SKU分层与分类裁决.md`
   只有在改 Stage7 商业层、SKU、服务深度、包装字段与展示时再读。

补充：

- 原“专题_SKU重构收口清单.md”已退出现行引用面；历史内容并入 `docs/专题_SKU分层与分类裁决.md`，原版只保留在 `archive/non_current_docs/专题_SKU重构收口清单_2026-05-17瘦身前原版.md`。

扩展读序只在以下情况进入：

- 需要理解当前招投标产品方向时，再看 `docs/业务方向_候选公示后证据包与投前预测双线契约.md` 和 `contracts/evaluation/business_direction_strategy_contract.json`
- 需要理解产品总图、Stage1-9 漏斗和当前能力缺口时，再看 `docs/AX9S_产品主图与验收总则.md`
- 涉及 Stage1/2 来源、城市适配、采集路由、附件和 readback 时，再看 `docs/专题_Stage1-2_来源覆盖与采集路由.md`
- 需要做 Stage4-5 双闸门规则资料吸收、投前预测辅助线、增强模块 / 标书内审、字段候选或表达边界收口时，统一看 `docs/专题_投前预测_Stage1-9 全链规则与判定资料池.md`
- 只有涉及正式对象、规则、字段、交付、发布、模型、公开边界时，才看 `docs/L0.md`、`docs/裁决总表.md` 和直接相关 D 文档
- `archive/non_current_docs/*` 不是普通开发默认入口；只在历史复核、task packet / scoped subpacket 或文档治理时读取

文档角色有疑问时，以 `docs/文档与资产状态板.md` 的 `AX9S / 专题文档单源归属表` 为准：L1 产品主图只讲总口径，L2 矩阵只讲验收和回退，L3 SOP 只讲 Stage4/5 操作细节，导航图只负责阅读入口提示，不决定执行顺序或任务源，专题文档只负责各自专题边界。

## 本地运行与测试存储后端

- 默认 direct-dev、`unittest`、脚本回归都走 `json-file`，不要依赖当前 shell 里遗留的 `KAKA_STORAGE_DATABASE_URL`。
- `local-postgres` 是显式 opt-in 路径，只在你明确要验证 PostgreSQL / Alembic / `app-postgres` profile 时使用。
- 如果要用 PostgreSQL，必须先启动对应 profile，并先完成 migration，再做 app bootstrap。

### 默认 direct-dev / unittest（推荐）

统一通过本地隔离脚本执行，它会强制注入 `json-file` + `process` 存储环境，并清掉 `KAKA_STORAGE_DATABASE_URL`：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/invoke-local-json-test-env.ps1 python -m unittest tests.test_real_sample_autonomous_opportunity_acceptance -v
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/invoke-local-json-test-env.ps1 python tests/run_tests.py
```

### opt-in `local-postgres`（受控路径）

先启动 PostgreSQL profile，再在 `app-postgres` 容器里显式跑 migration，最后再做 bootstrap：

```powershell
docker compose --profile local-postgres up -d postgres
docker compose --profile local-postgres run --rm -e KAKA_STORAGE_BACKEND=postgresql -e KAKA_STORAGE_DATABASE_URL=postgresql+psycopg://kaka_local:local_dev_placeholder_not_secret@postgres:5432/kaka_local app-postgres python -m alembic upgrade head
docker compose --profile local-postgres run --rm app-postgres
```

如果你要在宿主机 PowerShell 里直连 PostgreSQL，必须自己显式设置一条**可达**的 `KAKA_STORAGE_DATABASE_URL`；仓库不会为了本地方便而对 PostgreSQL 不可达做 silent fallback。

## 当前招投标业务方向

- 核心商业主线是候选公示后证据包：默认从工作日 72 小时内的近期 `07 中标候选人公示` 入池；投前预测只用于工作日 72 小时内的 `02/03/04`，一旦出现 `05 开标信息`，投前预测已经来不及，必须转开标后/候选后路线；近期 `07` 项目缺 11/12 不阻断当前证据包销售窗口。
- 下载和解析前必须先做 `AnalysisStrategyPlan v1`；不得因为发现文件就全部深解析。候选后负责人核验必须先走 `ResponsiblePersonEarlyProbe v1`：多候选人、联合体按候选行绑定；缺证书号先公司优先补证，再姓名枚举兜底；`08` 不默认下载或解析。公开注册信息只能回答“是否匹配”，不能判断“是不是本人”。
- 广东/重点省份核验按 `GuangdongLocalVerificationProbe v1` 和 `MajorRegionQueryProbe v1` 收口：重点省份为浙江、四川、江苏、湖北、山东、湖南、河南，默认 `PLAN_ONLY_UNTIL_REGION_ADAPTER_VERIFIED`；只能生成任务和可达性诊断，不得推断无风险。
- 负责人未释放宽筛按 `PRIOR_AWARD_AND_CANDIDATE_OVERLAP_TRIAGE`：先查 `data.ggzy.gov.cn` 和 `bid_show`；`bid_show` 已有项目负责人/项目经理 + 合同/交付/履约时间时直接进入时间窗口复核，字段不足或歧义时才用原文链接、原文 readback 定向回溯；不得一开始全省施工许可、竣工、合同备案全量扫描。B/C/D 释放证据默认只查历史重叠项目所在地住建局或住建主管部门公开源；全国四库只作身份/地区发现和辅助交叉验证，省工程审批系统只作辅助或人工挑战路线。YGP 只作为原文 readback 和广东其他城市适配基础；`YGP CityDiscovery v1`、`YGP_FULL_CHAIN_VERIFICATION_V1` 都基于 `search/v2/items` 和项目流程矩阵，读取 `nodeList` / `detail` / `dsList`；广州主源仍是广州交易集团，不恢复为广州主采集源。
- 项目负责人未释放 / 在建履约冲突必须走官方证据链：当前候选证据 + 中标/施工许可/合同/履约公开记录 + 时间窗口 + 释放证据。缺竣工、缺备案、源阻断或未命中只能形成“项目负责人未释放风险线索/证据不足”，不得直接写“无在建”或“无风险”。
- 正式证据包与后续协作只输出事实、线索、证据、反向解释和建议核验事项；必须保留来源 URL、采集时间、snapshot/readback、SHA-256/hash、脱敏日志等证据固化链。可信时间戳、收费举报、付费沉默、AI 一键定性都不是当前已实现或允许的对外路径。
- 方向契约：`docs/业务方向_候选公示后证据包与投前预测双线契约.md`。
- 机器契约：`contracts/evaluation/business_direction_strategy_contract.json`。

## 说明

- 当前产出面包含：文档、contracts、handoff、control、骨架（skeleton）、最小实现设计与受控实现代码。
- `docs/` 下放的是当前现行正式路径。
- `archive/generated_rounds/` 下保留了此前给你的历史生成稿和 round 包，不作为现行正式引用面。


