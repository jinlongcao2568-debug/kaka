# AX9S Full Repair Window Closeout Template

> 历史模板说明：本模板只用于 AX9S full-repair 历史/复开窗口。普通当前开发按仓库根 `AGENTS.md` 的 `DIRECT_DEV_DEFAULT` 执行，不因本模板强制小包。

每个批次窗口结束时，必须按以下结构收口：

---

批次：`{{BATCH_ID}}`  
可执行子包：`{{SUBPACKET_ID}}`
状态：`DONE / REVIEW_REQUIRED / BLOCKED`

1. 修改文件清单
2. 每个文件修改摘要
3. 运行的脚本与结果
4. 运行的 focused tests 与结果
5. 当前阻断项
6. 是否满足本批 Definition of Done
7. `control/ax9s_full_repair_status.yaml` 应更新为什么状态
8. 是否允许进入下一批
9. 如果允许，下一批唯一建议批次号
10. 如果不允许，最小补齐路径

---

强制要求：

- 收口前必须写明 required scripts 是否全部执行。
- full-repair 窗口收口前必须写明本窗口实际激活的是哪个 scoped subpacket，而不是只写 batch blueprint。
- 收口后不得自动进入下一批。
- 若状态不是 `DONE`，必须明确阻断根因，而不是泛写“还有问题”。
