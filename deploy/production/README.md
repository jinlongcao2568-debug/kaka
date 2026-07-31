# 客户可见生产发布

该目录提供客户证据包生产交付的正式部署边界。公开入口只暴露客户访问、支付结果页、Stripe 回调和健康检查；操作工作台只能通过本机映射的独立内网入口访问。软件本身不作为公开售卖下载物。

## 强制边界

- 所有应用、工作进程、备份工具、PostgreSQL 和 Caddy 镜像必须使用仓库地址加摘要，禁止生产现场构建。
- 密钥、登录主体和供应商凭据只从仓库外的文件挂载，环境文件只保存路径。
- 自动退款始终关闭。退款必须由所有者申请、独立复核员批准，并等待供应商回调完成对账。
- 客户交付必须先有已对账付款。下载令牌和 8 位访问码必须通过两个独立渠道发送。
- 发布申请人与复核人必须是不同主体；管理员不能批准发布或退款。
- 发布审批绑定当前门禁哈希。配置、告警、恢复证据或供应商证据变化后必须重新申请。

## 上线顺序

1. 分别构建并推送 Dockerfile 的 `api`、`worker`、`browser-worker`、`backup-tools` 目标，记录镜像摘要；同时固定 PostgreSQL 和 Caddy 摘要。
2. 在仓库外创建随机密钥文件、生产登录主体文件和 Stripe 正式密钥文件。Stripe 密钥必须以 `sk_live_` 开头，回调密钥必须以 `whsec_` 开头，并填写预期的 `acct_` 商户编号。
3. 在供应商沙箱和回调验证真实完成后，用 `scripts/create-provider-live-evidence.ps1` 为交付和支付分别生成不可变签名证据。
4. 用 `scripts/backup-production-release.ps1` 生成暂停写入的一致性备份，再用 `scripts/restore-production-release-isolated.ps1` 验证隔离恢复和 RTO。
5. 使用当前和上一版环境文件运行 `scripts/rollback-production-release.ps1`。演练期间公开入口会关闭，上一版通过健康和数据库版本校验后，脚本恢复当前版本并生成回滚报告。
6. 配置真实告警接收端。将 `production.env.example` 复制到仓库外，填写全部引用和镜像摘要；确认发布窗口后才把 `KAKA_PRODUCTION_KILL_SWITCH` 改为 `false`。
7. 运行 `scripts/deploy-production-release.ps1 -EnvironmentFile <绝对路径> -ConfirmProductionDeployment`。脚本只部署、核验 Stripe 正式密钥所属商户和收款/结算状态、执行真实告警投递探针并达到 `READY_FOR_APPROVAL`，不会自行批准客户发布。
8. 所有者通过操作入口提交发布申请，独立复核员核对门禁哈希后批准。随后再运行 `scripts/run-production-release-preflight.ps1 -EnvironmentFile <绝对路径> -RequireActive` 确认发布仍为活动状态。
9. 首批最多按 `KAKA_PRODUCTION_CANARY_CUSTOMER_LIMIT` 交付；监控支付回调、对账、下载、退款、告警和错误率。任何异常立即暂停发布。

Docker Compose 必须支持本项目使用的 `!reset` 和 `!override` 合并标签。所有生产脚本都会先运行 `docker compose config --quiet`，不支持或配置不完整时会失败关闭。

## 与服务器现有 Caddy 共存

服务器的 80/443 已由其他站点使用时，生产栈必须增加
`docker-compose.production.external-host-caddy.yml`。该覆盖文件只把项目公开入口绑定到
`127.0.0.1:${KAKA_PUBLIC_UPSTREAM_PORT:-18080}`，TLS 继续由服务器现有 Caddy 终止；
项目内层 Caddy 仍执行公开路由白名单、请求体限制和安全响应头。

服务器现有 Caddy 增加：

```caddyfile
kaka.example.com {
	reverse_proxy 127.0.0.1:18080
}
```

外层 Caddy 必须把该子域名的完整请求交给项目内层 Caddy，不得只放行
`/healthz`。项目内层 Caddy 会把根路径跳转到 `/customer/access`，并继续负责客户
路由白名单、支付回调、健康检查和默认拒绝；操作工作台不会进入该公网子域名。

部署、回读和回滚演练分别增加 `-ExternalHostCaddy`：

```powershell
scripts/deploy-production-release.ps1 -EnvironmentFile <绝对路径> -ConfirmProductionDeployment -ExternalHostCaddy
scripts/run-production-release-preflight.ps1 -EnvironmentFile <绝对路径> -ExternalHostCaddy
scripts/rollback-production-release.ps1 <其他必需参数> -ConfirmProductionRollbackDrill -ExternalHostCaddy
```

外层 Caddy 生效前先确认 `127.0.0.1:18080/healthz` 返回成功；生效后再确认
`https://kaka.example.com/` 跳转到客户入口、`https://kaka.example.com/healthz`
成功且非白名单路径返回 404。操作入口仍只监听本机 `KAKA_OPERATOR_TLS_PORT`，
不得通过该子域名代理。

## 不能由代码代填的资料

正式域名和 DNS、可信镜像仓库及摘要、Stripe 正式账号和回调端点、真实告警接收端、客户/操作员身份、供应商沙箱与回调证据、发布窗口，以及备份恢复和回滚演练产物必须来自实际运营环境。缺少任一项时，预检保持阻断，不能把内部测试结果写成已上线。
