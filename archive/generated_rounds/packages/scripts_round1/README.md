# scripts round1

本目录提供 开工前第一批标准 PowerShell 脚本入口。

## 目标

这批脚本只负责：

- contracts 结构与 JSON 有效性校验
- golden cases 基本一致性校验
- governance / release 机器资产校验
- 发布前最小检查
- 引用漂移 / 占位值 / 双口径提示
- 环境体检

**这批脚本不承载任何业务语义执行，不生成项目结论，不替代规则判断，不替代治理审批。**

## 文件

- `scripts/validate-contracts.ps1`
- `scripts/run-golden.ps1`
- `scripts/run-governance-contracts.ps1`
- `scripts/check-release.ps1`
- `scripts/lint-drift.ps1`
- `scripts/doctor.ps1`

## 使用方式

在仓库根目录运行：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\doctor.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate-contracts.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-golden.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-governance-contracts.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\lint-drift.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-release.ps1
```

## 约定目录

脚本默认以当前文件所在目录的上一级为仓库根目录，并假定存在以下目录或文件：

- `contracts/`
- `docs/`
- `scripts/`
- `README.md`
- `裁决总表.md`
- `L0` 母版或等价文件

## 输出与退出码

- 成功：退出码 `0`
- 失败：退出码 `1`

## 后续建议

下一轮可继续补：

- `scripts/search.ps1`
- `scripts/run-api-contracts.ps1`
- `scripts/run-ui-contracts.ps1`
- CI / pre-commit / GitHub Actions 集成


