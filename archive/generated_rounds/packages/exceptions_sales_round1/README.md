# Exceptions / Sales 机器资产（round1）

本目录承接：

- D7：对象级交付矩阵、release gates、例外治理
- D8：真实竞争者识别、可售对象与销售推进
- D9：联系对象与销售触达
- D10：订单、支付、交付、治理反馈（其中与商业对象和前置触达相关的部分）

本轮只生成机器可读 catalog，不生成业务实现代码。

## 目录

- `contracts/exceptions/exception_policy_catalog.json`
- `contracts/sales/challenger_profile_catalog.json`
- `contracts/sales/buyer_fit_scorecard.json`
- `contracts/sales/opportunity_policy_catalog.json`
- `contracts/sales/contact_policy_catalog.json`

## 设计原则

1. 受控例外只允许降级、限制、延后，不允许提升 D 层为正式公开依据
2. 私有补证默认隔离，不得直接渗入真相层或客户版主结论
3. `saleable_opportunity` 只能来源于阶段 6 正式对象
4. `contact_target` 只能来源于公开、授权或合规接入联系源
5. 自然人高限制联系对象默认 `requires_manual_review = true`
6. 商业对象、触达对象、负结果回写必须能与 D8 / D9 / D10 正式语义一一对应
