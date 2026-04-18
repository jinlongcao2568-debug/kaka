# testing package round 1

本包是开工前总清单中的 **testing 包第一轮**，承接 `D11`、`L0` 断言、`D6/D7/D13/D14` 的关键阻断口径。

## 包内文件

- `testing/l0_assertions.json`：L0 关键断言与一票阻断检查
- `testing/golden_cases.json`：首版 golden cases
- `testing/regression_manifest.json`：最小回归套件与触发条件
- `testing/release_checklist.json`：发布前检查清单

## 使用原则

1. 该包是开工前 readiness 机器资产，不替代 D11 正文。
2. 任何 formal upgrade、client/external release、natural-person outreach release 均必须通过对应阻断检查。
3. 本轮先冻结最小 load-bearing 断言，后续增量扩展而不是平行重造。
