# 专题_Stage1-9_缺口收口与优先级清单

**版本**: 2026-05-21 v54

## 1. 文档定位

本专题是 **Stage1-9 动态缺口投影板**。

它的作用不是再讲一遍路线，而是：

- 以 `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md` 为目标模型
- 对照代码 / tests / scripts / contracts 投射当前真实缺口
- 作为后续“减少缺口、跑通一段、更新一段”的唯一动态收口面

它不是正式状态源，也不替代：

- `control/repo_status.md`
- `control/current_task.yaml`
- `control/milestone_status.yaml`
- `docs/AX9S_产品主图与验收总则.md`
- `docs/AX9S_Stage4-5_核验双闸门SOP.md`

## 2. 一句话结论

当前真实状态不是“Stage1-9 没做”，而是：

- Stage1-3 主干链路已形成
- Stage4 外部证据链最弱，仍是当前最大短板
- Stage5 双闸门已实现，但真实样本规模和误报/漏报校准仍不足
- Stage1-6 到 P13B 的证据编排状态机已新增第一版，可把真实项目归并到 P13B、原文回溯、A 级强线索、Stage6 事实包 readiness 等状态；一键续跑入口已能从 `P13B_ORIGINAL_BACKTRACE_REQUIRED` 自动生成原文回溯任务并回写状态；原文回溯任务已新增 URL/入口质量分层，能把官方直达 HTML 排在空地址、跳转壳、YGP mapping 之前，避免小预算 live 盲打低质量入口；`batch-triage-table.json` 已能按批次给出继续跑、进入事实包/Stage7 内部预览、D 级内部复核或非主线暂存决策；`EvidenceStage6FactPackage v1` 已能生成内部复核 summary 和 `stage6_review_action_plan_table`，并能把 terminal source gap / no-delta 的 D 级项目标成 `automated_dispatch_allowed=false`，同时把 `manual_hold_state`、停靠原因、重新开启条件和 operator decision options 写入 brief、evidence pack、review summary JSON/Markdown；`Stage6ReviewActionDispatch v1` 已能把 P13B 释放证据、原文回溯重试、设计/测绘资质服务期复核映射成受控续跑任务，同时跳过 manual-only action plan，避免 D 级项目无限自动重试；释放证据 dispatch 现在必须显式携带 `evidence_batch_closeout` 与 `p13b_operational_closeout` 来源引用，缺任一来源会被标为 `BLOCKED_REQUIRED_SOURCE_REFS_MISSING`，runner 也会二次拒绝生成默认路径命令，避免误读旧 tmp 产物；`ReleaseEvidenceAdapterPlan -> GuangdongLocalFieldQueryProbe` 对广东/广州四类释放证据已有最小路由闭环：施工许可定向广州住建施工许可公开 API，竣工验收定向广州住建竣工验收公开 API，合同履约转广东建设信息网合同履约公开页并检查合同系统 SSO，项目经理变更明确标为浏览器/授权运行时必需，不再误打施工许可或竣工 API；2026-05-20 小预算 live canary 已验证广州住建施工许可和竣工验收公开 API 可达且可解析，GDCIC 合同履约/项目经理变更当前正确收口为 `NEEDS_BROWSER`，不会再把 SSO 阻断写成 `NOT_FOUND`；字段任务会输出 `MATCHED / NOT_FOUND / BLOCKED / NEEDS_BROWSER`、目标类型和 B/C/D 下游等级；`Stage6ReviewActionDispatchRunner v1` 已能按任务类型分组执行白名单本地 dispatch 任务，避免多项目重复覆盖输出；`Stage6ReviewActionDispatchReadback v1` 已能把这些任务读回为已产出、等待受控执行、人工跳过或阻断复核状态；`Stage6ReviewActionDispatchCloseout v1` 已能把读回明细按项目收口成可回灌、等待、跳过、阻断的项目级状态，且释放证据 adapter plan 不再直接误标为 evidence state 可回灌；`Stage6ReviewActionResultRouting v1` 已能把 closeout 结果路由到 evidence state rebuild、batch closeout rebuild 或释放证据字段查询的下一条受控任务，并输出结构化 argv；`Stage6ReviewActionResultRunner v1` 已能在 dry-run / `-Execute` 受控模式下执行白名单本地续跑命令，且会跳过重复 argv；`Stage6ReviewCycleRunner v1` 已能把新的 `EvidenceBatchCloseout` 自动串到下一轮 Stage6 fact package、dispatch 和 dispatch runner，且在无自动任务时安全停在 manual-only 复核；`Stage6ReviewLoopRunner v1` 已能把 dispatch runner、readback、closeout、routing、result runner、next cycle 汇总成 `stage6-review-loop-project-status-table.json`，按项目回答当前终态和下一步动作，包括 `MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH`；`run-stage6-review-loop-v1.ps1` 默认可在缺 dispatch 时从 batch closeout bootstrap，并可自动发现最新 batch closeout；若 bootstrap 后没有自动任务，会把 manual-only 项目直接投到项目状态表，而不是误报下游缺文件；`Stage6ReviewLoopOperatorProjection v1` 已能把该状态表投影成 owner 可读的批次状态、项目行、可续跑/人工停机/Stage7 gate、重新开启条件和下一步动作，并通过 `/operator-console/stage6-review-loop-status`、操作台 overview 和独立极简页 `/operator-console/stage6-review-loop` 展示；极简页已把状态、下一步和重新开启条件翻译成中文标签，不再要求 owner 直接读 raw JSON、英文枚举或在大操作台里找状态；默认批次选择已改为 owner 总览策略：若最新产物只是单项目终态，会优先展示最近的多项目批次，同时保留最新单项目批次在历史选择器中；项目卡片也已补 `当前阶段`、`证据等级`、`为什么停/阻断原因` 和 `下一步`，证据等级未投影时会明确提示需回看 batch closeout / evidence state，不会伪装成“没问题”
- GDCIC/browser-authorized readback 已从“只能停在 `NEEDS_BROWSER`”推进到“可消费受控浏览器授权回读产物 + 可执行真实浏览器 canary + 授权状态显式回传”：`GuangdongLocalFieldQueryProbe v1` 新增 `gdcic-browser-authorized-readback-v1.json` 输入，可把合同履约或项目经理变更的授权浏览器 readback 记录转成 `MATCHED` + B/C，或把显式空结果转成 `NOT_FOUND` + D，且继续保留 `query_miss_is_not_clearance=true`；新增 `build-gdcic-browser-authorized-readback-v1.ps1` 和 Playwright 执行器，支持 storage state / user data dir / headed。2026-05-20 真实 canary 打到 GDCIC 合同履约系统登录壳，已修正为 `LOGIN_OR_SSO_REQUIRED_BLOCKED` / `BLOCKED` / D，不再误写成字段未命中；最新 canary 产物额外写入 `authorized_session_input_state=NO_AUTHORIZED_SESSION_INPUT`、`authorization_readiness_state=LOGIN_OR_SSO_REQUIRED`、`field_surface_state=LOGIN_OR_SSO_BLOCKED_BEFORE_FIELD_SURFACE`、`required_runtime_capability=AUTHORIZED_SESSION_STORAGE_STATE_OR_USER_DATA_DIR` 和 `http_dynamic_stealthy_can_replace_login_state=false`，明确 HTTP / Dynamic / Stealthy 只能解决抓取、渲染或挑战面，不能替代登录态；field probe 已能把授权会话输入状态和授权阻断状态带到 `field_summary`，Stage6 loop 项目状态表和 operator projection 也会继续展示 `release_field_query_authorized_session_input_state_counts`、授权状态与下一步动作；尚未取得授权会话后的字段命中样本。
- GDCIC 匿名公开接口已找到并接入 Stage4 字段查询层：GitHub 未命中 `210.76.80.152:8008` 免登录方案，且 `JG/home/Indexht` 实测仍跳 SSO；但官方 `https://skypt.gdcic.net/openplatform/` 前端公开暴露 `/api/openplatform/publicityPeriod/getBaseInfo|getContract|getConstructPermitInfo|getFinishProjectInfo|listApplyProjectPerson`，项目列表命中后可用 `id` 匿名回读。2026-05-20 精确项目 canary 已验证 `project/list` 命中“广州科玛生物科技有限公司日用品”后，`listApplyProjectPerson?id=1573` 返回 `东莞市建工集团有限公司 + 王先耀 + 粤1332006200810171 + 441900202206061001`；代码已把该 follow-up 并入 `guangdong_gdcic_query_probe_v1`，并在 `GuangdongLocalFieldQueryProbe v1` live 模式下直接消费为 `FIELD_READBACK_READY_PUBLIC_SOURCE / MATCHED`，新增 `guangdong_gdcic_openplatform_readback_ready_count` 与 `guangdong_gdcic_openplatform_publicity_period_readback_ready_count`，可回灌 Stage6。GDCIC openplatform 查询已补项目短标题变体策略，长标题“广州科玛生物科技有限公司日用品、化妆品、药品及食品生产建设项目”可自动补查“广州科玛生物科技有限公司日用品”，真实 r2 canary 已从字段查询层直接打到 `publicityPeriod` 并回读目标人员、注册证书和施工许可。合同履约 bridge 默认已从 `GDCIC-HOME` 登录壳切到 `GDCIC-SKYPT-OPENPLATFORM` 匿名合同公开接口；联合体公司会拆分为独立公司变体，但合同/施工许可/竣工等项目级证据必须同时命中目标项目名或项目名变体，只查到同一公司其他项目合同只能作为上下文，不能抬成 B 级增强证据。2026-05-20 live3 project-strict canary 验证前 3 条合同履约均为 `NOT_FOUND/D`，没有把公司其他项目合同误算成本项目合同。Stage6 状态表和 owner projection 已能把 openplatform `MATCHED` 提升为中文公开源读回摘要、来源标签和 PII 脱敏状态，并优先使用 `publicityPeriod` 项目详情记录而不是企业历史样例人员；若只有公开源读回但未形成 B/C/D 等级，会进入 `RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY`，提示先人工补齐证据等级。字段输出已对身份证类字段只保留 hash/脱敏探针，不保存原始身份证号；后续优先走 openplatform 匿名详情接口，只有项目经理变更等 HOME 登录壳才走授权浏览器 readback。
- Stage1-6 批量回归账本已从“只依赖 Stage4-9 pressure summary”推进到“逐候选逐阶段 readiness 表”：`RealPublicStage49PressureReport v1` 现在会输出 `stage1-6-readiness-table.json` 和 `stage1-6-gap-summary-table.json`，按候选列出 Stage1 候选发现、Stage2 详情抓取、Stage3 字段解析、Stage4 公开核验、Stage5 双闸门、Stage6 事实包状态、当前 bottleneck stage、readiness state 和下一步动作；2026-05-20 已跑广州近期 `07` live30：Stage1 从 88 条原始行中取 30 条有效候选，Stage2 详情快照 30/30，Stage3 parse 30/30，15 条进入 Stage4-6 闭环但全部 `REVIEW_REQUIRED`，15 条只作 Stage1 复核暂存；readiness 分布为 Stage1 复核暂存 15、Stage3 负责人角色缺口 5、Stage4 公开源/释放证据链缺口 10。2026-05-20 已补 Stage3 人名质量门，live20 无网络回放确认“厦门重、质量目标、幢游泳馆、投资、年以上、国电电力、万千瓦、陕西榆林”等非自然人误抽取不再产出，RQSG2 `曾凡伟` 和规划测绘 `胡昌华` 等正样本仍保留；Stage4 字段查询结果已可作为独立输入回灌到 Stage6 多项目状态，live8 产物回放生成 15 个项目状态行，全部正确停在释放证据缺口/来源阻断复核。
- Stage4 real_public pressure 主链已新增释放证据 bridge：`RealPublicStage49PressureReport v1` 现在会输出 `stage4-release-adapter-bridge-table.json` 和可直接喂给 `GuangdongLocalFieldQueryProbe` 的 `stage4-release-adapter-bridge-plan.json`，把 `construction_permit`、`contract_public_info`、`completion_filing`、`project_manager_change_notice` 四类缺口转成 plan-only 字段查询任务；广州 live30 attempt-all 重建生成 120 条任务，施工许可/竣工走广州住建，合同履约 30 条走 GDCIC openplatform 匿名公开 API，项目经理变更 30 条仍走 GDCIC HOME 授权浏览器路径；live3 project-strict canary 实际执行合同履约前 3 条后均为 `NOT_FOUND/D`，且已确认公司其他项目合同不会被误写成本项目 B 级增强证据；2026-05-21 live5 title-variants canary 已继续尝试去除 `初步设计`、`监理`、`工程设计施工总承包`、`施工总价承包招标`、二次招标标记等后缀后的工程主体标题，真实请求已覆盖短标题，但前 5 条仍为 `NOT_FOUND/D`，公司维度公开合同/招投标/参建记录只保留为上下文；字段查询 summary 已直接输出 `authorization_readiness_state_counts` 和 `operator_next_action_counts`，继续保持“查不到不是无风险、登录态不能被 HTTP/Dynamic/Stealthy 替代”。
- 项目经理变更释放证据已从“授权浏览器文本命中”推进到“字段结构化”：`GDCICBrowserAuthorizedReadback v1` 对 `project_manager_change_notice` 命中页会抽取 `original_project_manager_name`、`new_project_manager_name`、`change_date`、`change_reason_probe`、`project_manager_change_release_window_interpretation`，并标记查询人员是否为原项目经理或新项目经理；`GuangdongLocalFieldQueryProbe v1` 会把这些字段投到 `project_manager_change_browser_authorized_record`，下游等级保持 `C_REVERSE_EXPLANATION_OFFICIAL_READBACK`。这只说明形成反向解释候选，仍需人工复核来源页面和授权状态，不能直接输出“已释放”。
- 非广东释放证据字段查询已从纯 registry 防误判推进到浙江 + 四川 + 江苏 + 湖北 + 山东 + 湖南 + 河南七个重点省份第一版字段 adapter：浙江定向浙江省建筑市场监管公共服务系统 `PublicWeb` 与 `ProjectInfo/re/GetProjectSGXK / GetProjectHTBA / GetProjectJGYS` 结构化接口，仍禁止把门户首页关键词命中当字段核验成功；2026-05-20 浙江 canary 显示公开页可达但施工许可字段接口在小预算下可能超时阻断或返回空结果，当前只形成 D 级补查结果。四川已接入四川省建筑市场监管公共服务平台 `https://sjfw.scjs.net.cn:8801/xxgx/index.aspx`，按项目名优先、公司名辅助查询 `GetPerjectList`，再用项目 token 回读 `GetProjSgxkzList / GetProjHtbaList / GetProjJgbaList`；2026-05-20 真实 canary 命中“誉川商品混凝土2号生产厂房”的施工许可详情并输出 `MATCHED` + `B_ENHANCEMENT_OFFICIAL_READBACK`。江苏已接入江苏省建筑市场监管与诚信管理一体化平台归属地 adapter 最小闭环，结构化 readback 可解析 JSON/表格行并输出施工许可/合同/竣工 `MATCHED/NOT_FOUND/B/C/D`，项目经理变更先收口为 `NEEDS_BROWSER/D`；2026-05-20 官方入口 live canary 返回 200 但字段面为 HTML 壳，正确归类 `NEEDS_BROWSER/D`。湖北已接入湖北省建筑市场监督与诚信一体化平台归属地 adapter 最小闭环，结构化 readback 可解析 JSON/表格行并输出施工许可/合同/竣工 `MATCHED/NOT_FOUND/B/C/D`，项目经理变更先收口为 `NEEDS_BROWSER/D`；2026-05-20 官方入口 live canary 返回 200 但字段面为 HTML 壳，Scrapling GET bridge 已记录，正确归类 `NEEDS_BROWSER/D`，不把入口可达写成字段命中。山东已接入山东省住房城乡建设服务监管与信用信息综合平台/山东住建厅入口第一版归属地 adapter，结构化 readback 可解析 JSON/表格行并输出施工许可/合同/竣工 `MATCHED/NOT_FOUND/B/C/D`，项目经理变更先收口为 `NEEDS_BROWSER/D`；2026-05-20 live canary 显示 `https://zjt.shandong.gov.cn/` 证书主机名不匹配，HTTP fallback 返回 200 但字段面仍是首页/HTML 壳，正确归类 `NEEDS_BROWSER/D`。湖南已接入湖南省建筑市场监管公共服务平台/智慧住建云第一版归属地 adapter，结构化 readback 可解析 JSON/表格行并输出施工许可/合同/竣工 `MATCHED/NOT_FOUND/B/C/D`，项目经理变更先收口为 `NEEDS_BROWSER/D`；2026-05-20 live canary 显示 `https://www.hunanjs.gov.cn/` 返回 200 且 Stage4 Scrapling GET bridge 已记录，但字段面仍为数字城建档案馆/SPA HTML 壳，正确归类 `NEEDS_BROWSER/D`。河南已接入河南省建筑市场监管公共服务平台第一版归属地 adapter，施工许可优先定向 `electronic/electronicInfo` 电子证照入口，合同/竣工定向 `newTBProjectInfo/projectData` 工程项目数据入口，结构化 readback 可解析 JSON/表格行并输出 `MATCHED/NOT_FOUND/B/C/D`，项目经理变更先收口为 `NEEDS_BROWSER/D`；2026-05-20 live canary 显示平台首页和电子证照入口返回 200，Stage4 Scrapling GET bridge 已记录，但字段面仍为 HTML 壳，正确归类 `NEEDS_BROWSER/D`。安徽等未实现字段 adapter 的地区仍输出 `LIVE_FIELD_QUERY_NEEDS_REGION_ADAPTER` 并保留 `no_fallback_to_guangdong_or_guangzhou=true`
- Scrapling 已从 Stage2 抓取层进一步桥接到 Stage4 字段 readback：`GuangdongLocalFieldQueryProbe v1` 的默认 GET/readback 路由现在会调用 `ScraplingEscalatingRealPublicFetchTransport`，低成本 HTTP fallback、SPA/JS 壳 Dynamic fallback、挑战面 Stealthy fallback 仍按底层 policy 条件触发，并把 `stage4_scrapling_get_bridge_used`、底层 transport、escalation target/reason 写入 `route_attempts`。POST JSON/form、cookie/session 路由不走该桥接，避免破坏广州住建施工许可/竣工等已验证公开 API。2026-05-20 江苏、湖北、山东、湖南、河南 live canary 均显示 GET route 已走 Stage4 readback 桥接；山东 HTTPS 证书阻断后通过 HTTP fallback 到达首页，湖南/河南 HTTPS 入口直接 200，但字段面仍正确收口为 `NEEDS_BROWSER/D`。
- Stage2 已接入 `Scrapling` parser-only snapshot 增强层：`stage2.scrapling_snapshot_parser.v1` 只解析已获取 HTML/snapshot，不发外部请求；能输出 `snapshot_parser_summary`、附件候选、同站链接、关键词命中、`table_extraction_summary`、`table_records`、`field_signal_summary` 和字段候选记录，并已合并进详情页附件发现诊断。新增 `Stage2SnapshotParserComparison v1` 和 `Stage2SnapshotParserReadiness v1` 可读取本地 snapshot manifest/object，对比旧规则与 Scrapling parser 的附件候选差异，并把 Scrapling 字段信号与现有 Stage3 HTML baseline 做覆盖对比；2026-05-20 批量回放 44 个 `stage1-5-limit3-*` 历史目录，其中 9 个有 HTML snapshot、33 个 HTML snapshot 被比较，严格附件候选 9/9 稳定，`legacy_extra_strict_attachment_total=0`、`parser_extra_attachment_total=0`、`no_live_request_all_true=true`；字段信号 `parser_field_candidate_total=331`，表格信号 `parser_table_total=310`、`parser_table_label_value_pair_total=288`、`parser_table_candidate_row_signal_total=825`，旧 Stage3 有效字段名缺口 `stage3_field_name_missing_from_parser_total=0`；剩余 16 个附件差异是旧规则把答疑/日程列表页当附件候选，Scrapling 不复制该宽口径。`stage2.scrapling_adaptive_selector_registry.v1` 已新增本地 selector drift PoC：训练公告标题、正文、附件入口 3 个选择器，重放时原 CSS 全部失效但 adaptive relocate 找回 3 个目标，`no_live_request_all_true=true`。`ScraplingRealPublicFetchTransport`、`ScraplingRealPublicDynamicFetchTransport`、`ScraplingRealPublicStealthyFetchTransport` 已全部新增为受控 transport wrapper；`requirements.txt` 已切到 `scrapling[fetchers]==0.4.8`，当前环境已安装 `curl_cffi 0.15.0`、`playwright 1.59.0`、`patchright 1.59.1`、`browserforge 1.2.4`，并完成 localhost smoke：Dynamic/Stealthy wrapper 均返回 200。`ScraplingBottomLayerEscalationPolicy v1` 已把 owner 授权口径固化到代码，`SCRAPLING_BOTTOM_LAYER_DEFAULT_CALL_STRATEGY` 明确 HTTP 默认自动升级、Dynamic 默认条件触发、Stealthy 不作普通默认只作挑战面触发；`RealPublicEntryFetcher` 默认先普通抓取，再按需要升级 HTTP / Dynamic / Stealthy，并把升级原因写入 `x-ax9s-scrapling-escalation-*`；仍不绕过 allowlist/snapshot/hash/failure taxonomy。2026-05-20 已修正 Scrapling 介入后的两个边界：`scrapling_snapshot_parser_attachment_candidates` 只作为审计/发现信号，不再让完整附件链路降级；广州 YWTB 只把真实下载端点算作附件，普通“投标文件公开”HTML 导航不再被当作附件下载。
- Stage6/7 内部对象和 readback 已存在；设计/测绘 `08` 定向人员档案抽取结果已能生成标准 `stage4_candidate_verification_inputs`，可继续喂给 Stage4 公司优先核验 dry-run/执行，不再只停在“人工应用字段”
- Stage8/9 已有 governed readback 和受控开启语义，但真实 live execution 仍按受控开放边界保持关闭

当前 Stage1-6 近端开发顺序已固化到 `control/stage1_6_priority_execution_plan.yaml`：

1. Stage6 多项目/多批次总览 UI 已完成第一轮 owner 可读化，后续只随真实样本补字段。
2. 当前候选项目实战主线先紧着广东跑通：继续补广州/广东 Stage1-6、GDCIC 授权字段命中、P13B 回灌和 Stage6 可读状态。
3. P13B 命中历史重叠项目后，释放证据按历史项目所在地公开源走；不因当前候选项目在广东就强制查广东。
4. 项目经理业绩、公司/项目经理处罚、信用、投诉监管决定等信息类核验允许跨省/全国扩展。
5. 回头补 Stage1-3 真实列表、详情、附件、OCR 和人员材料页稳定性。
6. 校准 Stage5 A/B/C/D 双闸门，避免把证据不足写成排除性结论。
7. 最后做 Stage1-6 批量实战回归，形成省份、项目类型、附件类型的 readiness 表。

### 2.0 2026-05-20 v45 实战增量

- 已新增显式全候选 Stage1-6 压测开关：`run-guangzhou-real-public-stage4-9-pressure-v1.ps1 -AttemptAllStage16Candidates`。广州近期 `07` live30 复跑后，30/30 候选全部进入 Stage1-6，原来 15 个候选停在 Stage1 未入选的问题已不再是当前批次卡点。
- 本轮 r2 结果：Stage2 详情快照 30/30，Stage3 parse 30/30，Stage1-6 readiness 分布为 Stage3 字段/角色缺口 8、Stage4 公开源/释放证据链缺口 22，Stage4 释放证据 bridge 扩为 120 条任务，客户可售证据包仍为 0/30。
- Stage4 字段核验 live16：广州住建施工许可命中 `MATCHED/B` 1 条，广州公开源 `NOT_FOUND/D` 7 条，GDCIC 合同履约/项目经理变更 `NEEDS_BROWSER/D` 8 条，剩余 104 条因预算延后；Stage6 回灌后 30 个项目都有状态行，其中 1 个 `RELEASE_FIELD_QUERY_REVIEW_READY`、29 个 `RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW`。
- 当前新的主卡点不是 Stage1，而是 Stage3 负责人/角色补全和 Stage4 释放证据真实源命中；GDCIC 仍需要授权 `storage_state` 或 `user_data_dir` 才能验证登录后字段面，HTTP / Dynamic / Stealthy 不能替代登录态。

### 2.1 2026-05-20 v46 实战增量

- 广州 YWTB 附件下载卡点已用受控 Playwright challenge resolver 打通：`stage2-ywtb-attachment-challenge-canary-20260520` 对 `中标候选人公示函.pdf` 返回 `FETCHED`、`application/pdf`、1.89MB，`automated_challenge_resolution_state=RESOLVED_AND_SNAPSHOT_CAPTURED`。
- 针对 live30 r2 中 8 个 Stage3 角色缺口项目，`stage2-ywtb-attachment-resolved-gap8-20260520` 已实际抓取 23/23 个同站附件，全部为 `RESOLVED_AND_SNAPSHOT_CAPTURED`；说明本轮主要卡点已从“附件下不来”转为“PDF/表格负责人抽取质量”。
- 已修复广州候选人表格中 `详见投标文件` 占位导致负责人漏抽的问题，并修复 `_enrich_candidate` 只用真值覆盖旧状态造成的 stale gap：真实复用回放 `stage2-ywtb-namegate-live2-r6-20260520` 中，`PROJ-CN-GD-JG2026-11373` 已稳定得到 `广东省建筑工程监理有限公司 + 谯锋`，`responsible_role_gap_code` 清空，4/4 附件保留。
- 已增强负责人姓名质量门，阻断 `姓名`、`工期`、`按要`、`按要求`、`对应`、`总监`、`总工`、`万元`、`平方米`、`公里`、`值抽取`、`年养护` 等 OCR/表格/工程规模碎片；`PROJ-CN-GD-JG2026-11386` 真实复用回放不再产出假姓名，正确停在 `B_CHIEF_SUPERVISION_ENGINEER_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY`。
- `run-guangzhou-real-public-stage4-9-pressure-v1.ps1` 已新增 `-EnableAttachmentChallengeResolver`、`-ChallengeTimeoutMs`、`-ChallengeBrowserHeaded`，后续压力流可显式开启广州附件挑战解析，不再靠人工临时设置环境变量。
- 未完成风险：8 项目全量复用重解析在本轮因大附件/PDF 文本处理超时中止，已停止本轮孤儿进程；下一步应做分批/单项目 reparse 和 PDF 文本缓存，避免批量回归被单个大附件拖死。

### 2.2 2026-05-20 v47 实战增量

- 已新增 Stage2 附件文本缓存：新抓取会把附件解析文本以 `attachment_text_cache_records` 写入 `detail_fields`；复用已有 capture 时先校验附件 snapshot 仍可回放，再用缓存/旧 `attachment_text_probes` 与 `qualification_text_candidate_blocks` 重建字段解析输入，不再重复跑 PDF/OCR。
- 已验证缓存不会绕过证据链：如果附件 snapshot 在当前 object repository 不可回放，仍按 `ATTACHMENT_SNAPSHOT_READBACK_MISSING` 降级，不会用旧缓存伪造附件存在。
- `stage2-ywtb-gap8-reparse-cache-r2-20260520` 已完成 8 项目全量复用回放：8/8 复用既有 capture，23/23 附件 snapshot 保留，8/8 命中缓存复用，耗时约 5 秒；之前的批量超时卡点已收口。
- gap8 最新分布：`ROLE_PRESENT_OR_NOT_REQUIRED` 1 个（11373 `广东省建筑工程监理有限公司 + 谯锋`），`B_CHIEF_SUPERVISION_ENGINEER_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY` 1 个（11386 正确停在总监缺失补证），`A_ROLE_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY` 5 个，`C_DESIGN_SURVEY_RESPONSIBLE_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY` 1 个。
- 新暴露并修复一处 OCR/表格碎片误抽：`附表` 不再被当作负责人姓名；11386 不再错绑第二候选人 `山东高速工程项目管理有限公司`，回到第一候选人 `广东华路交通科技有限公司` + B 类补证。

### 2.3 2026-05-20 v48 业务优先级修正

- 已修正执行口径：广东优先指“当前候选项目实战主线优先广东”，不是“释放证据只能广东”。近期开发继续围绕广东/广州 Stage1-6、GDCIC 授权字段命中、P13B 回灌和 Stage6 可观测性收口。
- P13B 命中同一负责人/同一主体/时间窗口重叠后，B/C/D 释放证据按历史重叠项目所在地公开源查询；非广东历史项目仍走归属地 adapter，不得回退到广东/广州源，也不得因为当前候选项目在广东而强制查广东。
- 项目经理业绩、企业/项目经理行政处罚、信用黑名单、投诉监管决定、人员/企业公开信息属于信息类核验，可继续跨省/全国扩展；这些扩展不等于切换当前候选项目主线到山东/湖北等地区。

## 2.4 当前五项进展快照

| 优先级 | 当前完成度 | 代码与实战判断 |
|---|---:|---|
| Stage6 可观测性 | 94%-96% | 多项目/多批次总览、历史 run、中文标签、当前阶段、证据等级、阻断原因、下一步和 Stage7 gate 已完成第一轮 owner 可读化；Stage4 字段查询结果现在可单独导入 Stage6 状态表，live16 回放生成 30 个项目状态行，1 个 `RELEASE_FIELD_QUERY_REVIEW_READY`、29 个 `RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW`，并把 `LOGIN_OR_SSO_REQUIRED` 和 operator next actions 投影到中文 owner 视图；GDCIC openplatform `MATCHED` 现在会投影为公开源读回摘要、来源标签和 PII 脱敏状态，公开源读回但未形成 B/C/D 等级时使用 `RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY`，不再误写成待浏览器/授权；Stage6 摘要已优先读取 `publicityPeriod` 项目详情记录，真实 canary 可显示 `王先耀 + 粤1332006200810171 + 441900202206061001`，不再显示泛企业样例人员；Stage1-6 readiness 行已补 `stage1_6_bottleneck_stage` 与 `next_recommended_action` 兼容字段，后续随真实样本补字段。 |
| Stage4 广东当前项目核验 / P13B 证据链 | 96%-98% | 广东/广州施工许可、竣工验收 live canary 已可达可解析；GDCIC openplatform 匿名详情已能在 Stage4 字段查询层直接形成 `MATCHED`，真实 canary 命中项目经理、注册证书号和施工许可证号；项目名策略已补短标题变体，长标题能自动补查短标题并触发 `publicityPeriod` 详情 follow-up；合同履约 bridge 默认已切到 GDCIC openplatform 匿名公开 API，联合体公司会拆分为独立公司变体，且项目级证据必须匹配目标项目名，live3 project-strict 验证前 3 条合同履约均 `NOT_FOUND/D`，不会把公司其他项目合同误算成本项目增强证据；GDCIC HOME/browser-authorized readback 产物消费和真实浏览器执行器仍保留，未授权登录壳实测会落 `BLOCKED`/D，并显式回传授权状态、字段面状态、所需登录态能力，以及 HTTP/Dynamic/Stealthy 不能替代登录态；项目经理变更授权回读已能结构化原项目经理、新项目经理、变更日期、变更原因和责任窗口解释；浙江、四川、江苏、湖北、山东、湖南、河南七个重点省份第一版字段 adapter 已接入；Stage4 real_public pressure 已能把释放证据缺口桥接成 plan-only 字段查询任务，广州 live30 attempt-all 生成 120 条 bridge 任务，并已回灌到 Stage6 多项目状态；当前候选项目主线继续广东优先，历史重叠项目释放证据按所在地，业绩/处罚/信用信息核验可跨省扩展；Stage4 GET/readback 已桥接 Scrapling escalation，POST/cookie/session 路径保持原逻辑。 |
| Stage1-3 实战稳定性 | 76%-82% | Stage2 已新增 Scrapling parser-only snapshot 增强、单目录 comparison 和多目录 readiness 回放脚本；44 个历史目录中 9 个有 HTML snapshot、33 个 HTML snapshot 被比较，严格附件候选 9/9 稳定；2026-05-20 广州 live30 里 Stage2 详情快照 30/30、Stage3 parse 30/30，说明广州主链可批量跑；广州 YWTB 附件 challenge resolver 已实战抓取 23/23 个 gap8 同站附件，压力脚本也已有显式开关；Stage2 附件文本缓存已把 gap8 全量 reparse 从超时降到约 5 秒，并保持 23/23 附件证据回链；Stage3 人名质量门已补 live20、live2 和 gap8 cache-r2 误抽词拦截，`PROJ-CN-GD-JG2026-11373` 已从角色缺口推进到 `广东省建筑工程监理有限公司 + 谯锋`，11386 正确停在 B 类总监缺失补证，同时保留 `曾凡伟`、`胡昌华` 等正样本；剩余缺口是更多省份/附件/OCR/复杂表格压测。 |
| Stage5 规则门校准 | 50%-60% | A/B/C/D 与“查不到不是没问题”口径已固化；仍缺 20-50 个真实样本误判/漏判校准。 |
| Stage1-6 批量实战回归 | 65%-72% | 已跑广州近期 `07` live30 attempt-all 复跑：30 条候选全部进入 Stage1-6，Stage2 详情 30/30，Stage3 parse 30/30，readiness 分布 Stage3 字段/角色缺口 8、Stage4 公开源/释放证据链缺口 22；客户可售证据包 0/30。Stage4 主链接入释放证据 bridge 已完成第一版并经 live16 验证；Stage3 负责人误抽已完成第一轮硬化和 live20 无网络回放；字段查询结果已回灌 Stage6 多项目状态。下一步不切换当前候选项目主线到山东/湖北，而是继续广东/广州 GDCIC 授权会话命中样本、P13B 回灌和广东 Stage1-6 闭环；非广东只在历史项目所在地释放证据或业绩/处罚/信用信息类核验触发时扩展。 |

## 3. 投影方法

当前缺口投影固定按四个来源交叉判断：

1. `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md`
2. 当前代码与正式对象 / contracts
3. 关键 tests 与脚本结果
4. 当前受控开放边界和 repo status

## 4. Stage1-9 动态缺口投影

| 阶段 | 矩阵目标 | 当前代码 / 测试 / 脚本投影 | 当前缺口判断 | 优先级 |
|---|---|---|---|---|
| Stage1 候选发现 | 多省多城真实候选稳定发现 | `operator` 搜索入口、region adapter、real candidate discovery 已存在；GD/SC/JS/ZJ 路径较清楚 | SD/HB discoverer 和真实列表解析回归仍不足 | P1 |
| Stage2 公开采集 | 列表/详情/附件可回放、可审计 | 快照、hash、来源 URL、失败 taxonomy 已进入正式链路；Scrapling parser-only snapshot 增强已接入详情页 metadata、附件候选诊断和字段信号；Scrapling adaptive selector registry 已能在本地 selector drift PoC 中找回标题、正文和附件入口；`run-stage2-snapshot-parser-comparison-v1.ps1`、`run-stage2-snapshot-parser-readiness-v1.ps1` 和 `run-stage2-scrapling-adaptive-selector-poc-v1.ps1` 已能输出回放/PoC 产物 | SPA 壳、验证码、超大附件、长尾下载阻断、adaptive selector 对真实站点批量训练/回放仍要继续打磨 | P1 |
| Stage2.5 AnalysisStrategyPlan | 下载和解析前先做策略分流 | 双线文档和 contracts 已固定口径 | 需要继续防止长尾实现绕过策略层 | P2 |
| Stage3 字段血缘 | 主流载体字段抽取与 lineage | HTML/PDF/Word/Excel 主链已通；负责人误抽质量门已完成 live20 第一轮硬化 | OCR、复杂表格、多候选行绑定、`08` 定向解析和跨省样本仍未完全稳 | P1 |
| Stage4 公开核验 | 多源公开核验与释放证据链 | 广东/广州已有部分 query/readback；`ResponsiblePersonEarlyProbe`、`MajorRegionQueryProbe`、`GuangdongLocalVerificationProbe` 已存在 | 多省地方源、项目经理变更释放、命中后的释放证据深查仍最弱 | P0 |
| Stage5 双闸门 | `rule_gate_decision` + `evidence_gate_decision` 稳定运行 | 双闸门框架、规则运行、evaluator tests 已存在 | 真实样本校准深度不够，SKU 级 PASS/REVIEW/BLOCK 还要继续磨 | P1 |
| Stage6 统一事实 | `project_fact` / report / review queue 可回放 | Stage6 聚合、internal orchestration、product package 基础已在 | 真实候选仍常被 Stage4 缺口卡住，formal real_public 链还需继续收紧 | P0 |
| Stage7 商业钩子 | saleable / buyer_fit / offer 承接真实事实 | Stage7 runtime、hook、buyer fit、offer 已存在 | `real_public_sellable_gate_ready=false` 经常受 Stage4 缺口拖住；仍需继续控卖前泄露 | P1 |
| Stage8 触达准备 | governed preview / draft / approval 边界清楚 | Stage8 internal/governed readback 已存在，真实发送默认关闭 | 不是当前主产品缺口，但 provider sandbox / live pilot 仍是后续 controlled opening 任务 | P2 |
| Stage9 交付治理 | order / payment / delivery / refund 治理链可回放 | Stage9 ledger/readback 已存在；真实 payment / delivery 默认关闭；自动退款执行继续 EXCLUDED | 不是当前主产品缺口，但真实下载、真实支付、真实交付仍是后续 controlled opening 任务 | P2 |

## 5. 当前 P0 缺口

### P0-1 Stage4 释放证据链闭环

- 现状：Stage4 是当前最大短板。身份核验和部分公开源 readback 已有，但“许可/合同/竣工/项目经理变更/处罚”多源交叉后的释放证据链仍不完整。
- 当前进展：`GuangdongLocalFieldQueryProbe v1` 已把来自 `ReleaseEvidenceAdapterPlan v1` 的字段查询任务纳入统一 A/B/C/D 汇总；广东/广州最小查询闭环已按四类目标分流，施工许可和竣工验收可走广州住建公开 API fake-live 与小预算 live 回读，合同履约默认走 GDCIC openplatform 匿名合同公开接口，项目经理变更仍走 GDCIC HOME 授权浏览器路径；合同、施工许可、竣工等项目级记录必须匹配目标项目名或项目名变体，按公司查到的其他项目合同只作为上下文，不形成 B 级增强证据；GDCIC/browser-authorized readback 产物消费和真实浏览器执行器已接入，项目经理变更可以在有受控浏览器产物时进入 `MATCHED` 或显式 `NOT_FOUND`，未授权登录壳则进入 `BLOCKED` / D，不再误写成字段未命中，且现在会明确输出 `required_runtime_capability=AUTHORIZED_SESSION_STORAGE_STATE_OR_USER_DATA_DIR` 与 `http_dynamic_stealthy_can_replace_login_state=false`；项目经理变更授权回读已能抽取原项目经理、新项目经理、变更日期、变更原因和责任窗口解释，并投到 Stage4 字段记录形成 C 级反向解释候选；最新 readback 产物会显式写出授权状态、字段面状态和 operator 下一步动作，field probe、Stage6 loop 项目状态表和 operator projection 都已带出这些状态，因此后续 UI/状态机不用从 blocker 字符串反推；非广东归属地 adapter registry 已能被字段查询层读回并阻止入口门户关键词误判，浙江第一版字段 adapter 已能定向 `ProjectInfo/re/GetProjectSGXK / GetProjectHTBA / GetProjectJGYS`，四川第一版字段 adapter 已能定向 `GetPerjectList` + `GetProjSgxkzList / GetProjHtbaList / GetProjJgbaList`，江苏、湖北、山东、湖南、河南第一版字段 adapter 已能接入各自一体化平台/住建信用监管/智慧住建云/电子证照链路并解析结构化 JSON/表格 readback；2026-05-20 四川真实 canary 已命中施工许可详情并输出 B 级增强证据，浙江 canary 仍只形成 D 级补查结果，江苏和湖北官方入口 live canary 返回 200 但字段面为 HTML 壳并正确输出 `NEEDS_BROWSER/D`，山东 live canary 显示 HTTPS 证书主机名不匹配、HTTP fallback 返回 200 但字段面仍为首页/HTML 壳并正确输出 `NEEDS_BROWSER/D`，湖南 live canary 显示 HTTPS 入口返回 200 但字段面仍为数字城建档案馆/SPA HTML 壳并正确输出 `NEEDS_BROWSER/D`，河南 live canary 显示平台首页和施工许可电子证照入口返回 200 但字段面仍为 HTML 壳并正确输出 `NEEDS_BROWSER/D`，这些结果都不形成排除性结论；`Stage6ReviewLoopRunner v1` 已能在项目状态表里直接显示释放证据字段查询的 `MATCHED / NOT_FOUND / BLOCKED / NEEDS_BROWSER` 和 B/C/D 下游结果；释放证据 dispatch / runner 已收紧输入约束，必须显式带 `evidence_batch_closeout` 与 `p13b_operational_closeout` 来源引用，防止回退到默认旧产物。
- 新增进展：`RealPublicStage49PressureReport v1` 已把 real_public pressure 的 Stage4 缺口桥接到释放证据任务层，会输出 `stage4-release-adapter-bridge-table.json` 与 `stage4-release-adapter-bridge-plan.json`；广州 live30 attempt-all 重建得到 120 条 plan-only 任务，字段查询 dry-run 可消费 120 条；其中合同履约 30 条已全部切到 GDCIC openplatform 匿名公开 API，项目经理变更 30 条仍保留 GDCIC HOME 授权浏览器路径。2026-05-20 live3 project-strict 验证合同履约前 3 条均为 `NOT_FOUND/D`，且公司其他项目合同被保留在 `context_source_specific_records`，不会进入 `source_specific_records` 或 B 级增强；`GuangdongLocalFieldQueryProbe v1` 顶层 summary 已补授权状态和 operator next action 汇总；`Stage6ReviewLoopRunner v1` 已支持把独立 `guangdong-local-field-query-probe-v1.json` 导入项目状态表。
- 直接症状：
  - `项目经理变更释放` 在矩阵里仍为 `MISSING_RUNTIME`
  - 真实候选经常落到 `PARTIAL_SOURCE_COVERAGE`
  - Stage6/7 常被 Stage4 缺口卡住
- 完成标准：
  - 命中重叠信号后，能稳定补查 `construction_permit`、`contract_public_info`、`completion_filing`、`project_manager_change_notice`
  - 释放证据链可回放，且不会把“未命中/源阻断”写成“无风险”
  - 下一步仍需补 GDCIC 授权会话后的真实字段命中样本，并继续用广东/广州近期 `07` 做 Stage1-6 闭环回归；山东/湖北等地区暂不切换为当前候选项目主线，只在历史项目所在地释放证据或业绩/处罚/信用信息核验触发时使用。现在 readiness 表只是批量回归账本能力，不能因为广州住建 API 已通、GDCIC 未授权浏览器 canary 已能 BLOCKED、项目经理变更字段抽取已结构化、浙江/四川/江苏/湖北/山东/湖南/河南第一版 adapter 已接入，就误判四类释放证据都已实战稳定

### P0-2 Stage6/7 真实候选 formal real_public 闭环

- 现状：Stage6/7 内部对象已存在；`evidence_orchestration_state_machine_v1` 已能消费 Stage1-6 storage、公司优先补证、P13B 和原文回溯产物，生成 `evidence-state-table`、`adapter-job-table`、`stage6-fact-package-readiness-table` 和 `batch-triage-table`；设计/测绘候选已由 `DesignSurveyResponsibleAdapterPlan v1` 从纯暂存改为可生成 Stage4 负责人/资质/服务期计划；`Flow08TargetAttachmentParse v1` 抽到人员档案后，可由 `DesignSurveyFlow08Stage4Inputs v1` 生成标准 Stage4 输入并进入 `build-company-first-stage4-execution-v1.ps1` dry-run/执行；`EvidenceStage6FactPackage v1` 已补 `stage6-review-summary`、`stage6_review_action_plan_table` 和每项目 `stage6-review-action-plan.json`，并能把 terminal source gap / no-delta 项目标记为 manual-only，进一步输出 `Manual Hold` 段落、重新开启条件和 operator decision options；`Stage6ReviewActionDispatch v1` 已能把动作计划映射到 `build-release-evidence-adapter-plan-v1.ps1`、`run-evidence-orchestration-continuation-v1.ps1`、`build-design-survey-public-registry-readback-v1.ps1` 三类受控续跑任务，同时不再派发 terminal D/no-delta action plan；`Stage6ReviewActionDispatchRunner v1` 已能把两个 RQSG 原文续跑任务合并成一次 continuation runner，把规划测绘 registry readback 单独执行；`Stage6ReviewActionDispatchReadback v1` 已能读回续跑产物或记录等待、跳过、阻断状态；`Stage6ReviewActionDispatchCloseout v1` 已能生成项目级收口视图，样本中 dispatch runner 执行后 3 个任务均可进入 closeout；`Stage6ReviewActionResultRouting v1` 已把原文 continuation run 路由到 `build-evidence-batch-closeout-v1.ps1 -ContinuationRunJson <result_json_path> -EvidenceStateRoot <state_after_root>`，把设计测绘 readback 路由到 evidence state rebuild，并把重复 continuation run 命令交给 result runner 去重；`Stage6ReviewActionResultRunner v1` 已能执行 result routing 中的白名单本地命令；`Stage6ReviewCycleRunner v1` 已能从 result runner 产出的 batch closeout 继续生成下一轮 Stage6 fact package 与 dispatch，并在真实三项目样本中用短路径执行 1 个非 live dispatch 组；`Stage6ReviewLoopRunner v1` 现在会额外输出 `stage6-review-loop-project-status-table.json`，按项目列出 readback、closeout、routing、result runner、next cycle dispatch/manual-only 的当前状态、终态和下一步建议；但真实候选仍常被 Stage4 释放证据链缺口挡在 formal real_public 闭环之前，且无 snapshot 的设计测绘 registry readback 会正确回到 adapter/snapshot required，而不是误判通过。
- 直接症状：
  - `real_public_sellable_gate_ready=false`
  - formal real_public 路径存在，但常因 source coverage、原文回溯和释放证据链不足停下
- 完成标准：
  - 真实候选能更稳定进入 Stage5 双门、Stage6 `project_fact`、Stage7 `saleable_opportunity`
  - 编排状态能自动指向下一步 adapter job，并通过批次决策表、Stage6 action plan、Stage6 dispatch task、dispatch readback、dispatch closeout 和 result routing 标出继续、暂存、复核、等待、跳过、阻断、字段查询和可回灌路径，避免真实项目“生成任务后靠人工记忆续跑”
  - 不因内部 preview 存在就误判“正式可售已经完成”

## 6. 当前 P1 缺口

### P1-1 非广东候选发现器补齐（后置，不抢当前广东主线）

- 现状：SD/HB 主要还是入口 profile、挑战观察和解析回归不足。
- 完成标准：
  - SD/HB 有专门 discoverer
  - 有真实列表结构解析回归
  - 不再以“观察态/挑战态”长期停留

### P1-2 Stage2/3 长尾文件链补强

- 现状：主流文件已通；Stage2 已新增 Scrapling parser-only snapshot 增强，能对已采集 HTML 进行更稳的 title/h1、link、attachment candidate、keyword、表格、项目编号、公告日期、候选单位、负责人和时间窗口信号 readback，并在失败时退回 stdlib parser；`Stage2SnapshotParserComparison v1` / `Stage2SnapshotParserReadiness v1` 已用本地历史 snapshot 验证严格附件候选稳定，且字段信号覆盖现有 Stage3 HTML 有效字段名；`Stage2ScraplingAdaptiveSelectorPoC v1` 已验证 selector drift 后仍可从本地 HTML 找回公告标题、正文和附件入口；2026-05-20 已补 live20 负责人误抽质量门，并修正 Scrapling 审计信号/广州 YWTB 附件导航边界；但 OCR、复杂表格、多候选行绑定、`08` 定向解析、adaptive selector 对真实站点批量训练/回放仍未完全稳。
- 完成标准：
  - OCR 状态机更清楚
  - 多候选行和联合体绑定不串行
  - `08` 继续保持 strategy-driven，不默认全量深解析

### P1-3 Stage5 真实样本校准

- 现状：规则已存在，但更接近“第一刀 + 内部复核规则”。
- 完成标准：
  - 50+ 真实项目样本校准
  - 有误报/漏报修订记录
  - SKU 级 PASS/REVIEW/BLOCK 边界更稳定

## 7. 当前 P2 缺口

### P2-1 Stage1-5 独立 API 面

- 现状：真正可用入口还是 `operator` 搜索入口和 Stage6 internal orchestration。
- 说明：这不是 bug，但如果目标是“Stage1-5 每阶段都可独立 API 运行”，当前仍未完成。

### P2-2 Stage8/9 controlled opening 后续任务

- Stage8：governed readback 已有，但 provider sandbox / live pilot 仍是后续受控开放任务
- Stage9：ledger/readback 已有，但真实 payment / delivery / refund live execution 仍默认关闭
- 自动退款执行继续 `EXCLUDED`

这两项属于**后续受控开放任务**，不是当前 Stage1-7 产品主链 bug，但也不能误判成“已经开放”。

## 8. 不应误判为已完成的项

- 不能因为 Stage1-3 可跑，就说客户可售证据已稳定形成
- 不能因为 Stage5 测试全绿，就说规则已达稳定商用品质
- 不能因为 Stage6/7 对象齐全，就说真实可售链已闭环
- 不能因为 Stage8/9 readback 已存在，就说真实发送、真实支付、真实交付已放开
- 不能因为 challenge taxonomy 存在，就说真实第三方风控站点都已跑通

## 9. 更新规则

以后每次减少缺口或打通一段，不去更新 `AX9S_当前主线导航图` 的动态内容，而是直接更新本专题：

- 哪个阶段缺口减少了
- 用什么代码 / 测试 / 脚本证据证明减少
- 当前优先级有没有变化

## 10. 直接依据

- `docs/AX9S_Stage1-9_执行矩阵与子漏斗.md`
- `docs/AX9S_Stage4-5_核验双闸门SOP.md`
- `docs/AX9S_产品主图与验收总则.md`
- `control/repo_status.md`
- `control/product_operability_gap_matrix.yaml`
- `control/stage1_6_priority_execution_plan.yaml`
- `control/operator_user_acceptance_gap_matrix.json`
- `contracts/evaluation/evaluation_coverage_requirements.json`
- `src/stage1_tasking/region_adapters.py`
- `src/stage1_tasking/real_candidate_discovery.py`
- `src/stage2_ingestion/public_source_adapters.py`
- `src/stage3_parsing/ocr_text.py`
- `src/stage4_verification/provider_handlers.py`
- `src/api/routes/operator_customer_access.py`
