# Control / Archive Round 1

本目录承接开工前总清单中的 **control 包** 与 **archive 包**。

## 目录说明

- `control/owners.yaml`：正式责任人、审批责任链、SoD 最小责任面
- `control/current_task.yaml`：当前激活任务、当前准备批次、当前阻断与下一动作
- `control/approval_chain_state.yaml`：审批链当前激活状态、是否允许正式放行
- `control/exception_chain_state.yaml`：受控例外链当前状态、是否存在未回收例外
- `control/reference_index.json`：单一母版、裁决总表、D1-D14、核心 contracts 包、testing 包、handoff 包的统一索引
- `archive/README.md`：归档规则、保留规则、废止规则
- `archive/migration_notes.md`：从历史稿迁移到当前正式终版的迁移说明

## 设计原则

1. 只承接正式控制面，不承接业务功能。
2. 只允许表达“当前状态、当前责任、当前引用关系”，不得反向定义对象、规则、边界或结果语义。
3. 所有文件均服务于：
   - 单一事实源
   - 单一裁决索引面
   - 受控例外可追溯
   - 开工前状态可审计
   - 归档迁移可回看

## 当前用途

- 作为 D1 / D11 / D12 / D13 的控制面机器资产起点；
- 作为仓库新接手者、AI / Codex 执行代理、评审者的统一入口；
- 作为“是否满足开工前总清单”的控制态检查基础。
