# Handoff 机器资产包（Round 1）

本包承接 L0 九阶段正式主链、D2 正式对象体系、D3 双闸门与结果语义、D8/D9/D10 商业闭环对象。

本轮交付：

- `handoff/stage_handoff_catalog.json`
- `handoff/integration_matrix.json`
- `handoff/example_payloads.json`
- `handoff/validation_rules.json`

设计原则：

1. 只定义正式阶段间承接，不定义业务代码实现。
2. 顶层主判断不得绕开 `project_fact`。
3. 阶段 1-6 主链优先，阶段 7-9 闭环承接必须建立在阶段 6 正式对象基础上。
4. 任何 handoff 若触发 D 层输入渗透、版本/时钟冲突未解、双闸门缺失或 sale/contact/delivery 越级生成，必须阻断。
5. 示例 payload 仅用于 contract 说明与测试种子，不等于运行时完整报文。
