# API / UI 机器资产（round1）

本目录承接 的 D4（OpenAPI 接口契约）与 D5（页面、导出与人工复核规范）正式语义，
只生成机器可读 catalog，不生成业务 API 实现、页面实现、数据库迁移或业务流水线代码。

## 目录

- `contracts/api/api_catalog.json`：正式接口目录
- `contracts/api/permission_matrix.json`：角色 × 资源 × 动作 权限矩阵
- `contracts/api/error_code_catalog.json`：正式错误码目录
- `contracts/ui/workbench_catalog.json`：正式页面 / 工作台目录
- `contracts/ui/button_flow_catalog.json`：按钮流 / 动作流目录
- `contracts/ui/export_template_catalog.json`：导出模板目录

## 设计原则

1. 顶层结论接口只能优先消费 `project_fact` 与 `legal_action_recommendation`
2. 中间对象默认只作为解释、追溯、复核或治理消费面
3. D8 / D9 / D10 未正式放行的能力，在 API 与 UI 层只能保留为受限占位或保留态
4. 客户可见返回与导出必须受字段策略、对象级交付矩阵、release gate 与审批链共同约束
5. 本目录不反向改写 D2 / D3 / D4 / D5 / D6 / D7 / D13 语义
