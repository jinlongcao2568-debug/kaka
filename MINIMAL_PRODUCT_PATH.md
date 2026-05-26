# MINIMAL PRODUCT PATH

本文件只回答一个问题：接下来怎样先做出一个能用的最小产品。

## 1. 先做什么

先做“候选公示后证据包”最小闭环：

1. 输入一个公开项目候选。
2. 采集或导入公开来源快照。
3. 解析关键字段。
4. 做最小公开核验。
5. 生成内部证据包。
6. 在操作台显示证据包和下一步动作。
7. 用 mock / sandbox 模拟交付、支付和退款状态。

先不做：

- 多租户 SaaS
- 完整生产发布
- 全渠道真实触达
- 真实扣款
- 真实客户下载
- 生产自动退款
- 全省全量采集

## 2. 每天怎么推进

每天只选一个小目标：

| 小目标 | 判断完成 |
|---|---|
| 让一个输入能进系统 | 有 fixture 或页面表单能提交 |
| 让一个字段能解析 | 测试里能看到字段值 |
| 让一个核验能返回状态 | 返回 `MATCHED / NOT_FOUND / REVIEW / BLOCKED` 之一 |
| 让一个证据包能生成 | 页面或 JSON 能看到证据摘要 |
| 让一个操作台按钮能工作 | 点击后有可读结果或错误 |
| 让一个 mock 支付/交付/退款状态可见 | 状态可回放，不冒充生产 live |

做完一个就提交一个小进展，不等全部完美。

## 3. 默认验证

优先跑和本次改动相关的测试：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/invoke-local-json-test-env.ps1 python -m unittest <相关测试> -v
```

只有改了 contracts/control/docs 同步语义，才补跑：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/validate-contracts.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-state-alignment.ps1
```

## 4. 当前主线判断

如果不知道下一步做什么，优先检查：

1. 操作台能不能看到真实候选或样本候选。
2. Stage2 快照有没有。
3. Stage3 字段有没有。
4. Stage4 核验状态有没有。
5. Stage6 证据包能不能展示。

这五项比继续扩写治理文档更重要。

