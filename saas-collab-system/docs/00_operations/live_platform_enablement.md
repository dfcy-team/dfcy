# 正式平台受控接入运行手册

任务：`A-REAL-PLATFORM-CONNECTION`。本手册不构成 Production 批准。

## 默认状态与四重门禁

默认使用 synthetic provider，capability 为 `pending/mock`。真实网络必须同时满足：

1. `PLATFORM_NETWORK_MODE=approved-live-test`；
2. `LIVE_PLATFORM_SECURITY_APPROVED=true`；
3. `LIVE_CUSTODY_BACKEND=file` 且使用批准的独立绝对路径，或使用批准的 custody HTTPS 服务；
4. `DEBUG=false`、平台/custody host allowlist 非空、平台合同批准开关为真。

任一条件缺失即 fail closed，不发出真实请求。代码不提供 `connected` 或
`production-enabled` 环境变量捷径。

## Secret 注入路径

```text
Platform Console
  -> Authorized Secret Administrator
  -> Approved Credential Custody / Secret Manager
  -> opaque app-secret / credential / token reference
  -> Application Runtime
```

禁止开发人员通过聊天、文本、`.env`、SQL、日志或 PR 中转 secret。应用数据库只保存引用、掩码、版本、状态、时间戳、scope 与受控错误码。无本地文件 vault fallback。

## 最小配置类别

- 固定制品：Review SHA、artifact SHA、image digest、runtime version。
- 网络：批准的 Shopee、TikTok Shop 与 custody 主机；HTTPS；CA 校验开启。
- 超时：connect/read timeout、重试次数、单次等待及总等待均有上限。
- OAuth：精确 redirect allowlist；平台公开 app/service identifier；App Secret 仅配置 custody reference。
- 合同：Shopee/TikTok 分别设置执行日复核后的合同批准开关。Shopee 当前未冻结正式合同，必须保持关闭。

## 启用与停止

启用顺序：固定远程 SHA与制品 -> custody/网络审批 -> 平台合同复核 -> 部署 -> 扫描 -> 单店试点 -> 独立复审。真实试点前工作区必须干净。

紧急停止顺序：关闭 `PLATFORM_NETWORK_MODE` -> 关闭安全批准开关 -> 阻断平台出口 -> 通过 custody 撤销引用 -> 平台侧撤销授权 -> 保留脱敏审计。禁止从数据库或备份恢复 revoked credential。

## 验证边界

只允许 OAuth、authorized shop/shop identity 与最小只读 metadata。订单、库存、商品全量同步、财务、webhook 正式消费、定时任务、历史回补、RPA 和平台写操作均不在本任务内。
