# PR-A2 Marketplace OAuth / Callback 架构规划

## 1. 架构原则

- 业务系统只编排授权，不持有平台凭据。
- OAuth state 是一次性安全凭证，不是 tenant 或用户输入。
- 公网 callback 与 internal API 分区；callback 不因无 JWT 而降低验证要求。
- 外部平台与密钥托管调用属于不可回滚副作用，使用 saga、幂等和补偿，不把它们包装成虚假的数据库原子事务。
- synthetic、Sandbox、Pilot、Production 四个环境独立授权；默认 deny，Production 强制关闭。

## 2. 组件边界

```text
Internal UI
  -> internal authorize API
  -> OAuth orchestration service
      -> one-time state store (hash only)
      -> platform adapter (authorization URL / callback validation)
      -> custody gateway (code exchange / refresh / revoke)
      -> append-only audit

Platform browser redirect
  -> /api/platform/oauth/{platform}/callback/
  -> state consume + callback validation
  -> custody gateway
  -> MarketplaceStoreAuthorization service
  -> allowlisted UI redirect
```

平台 adapter 不得直接写模型；密钥托管 gateway 不得把 Token 返回 view、serializer 或 task payload。所有模型写入由 orchestration/service 层完成。

## 3. OAuth attempt 数据模型

建议新增独立 `MarketplaceOAuthAttempt`：

| 字段 | 规则 |
|---|---|
| tenant/user/session_hash | 必填并受保护；只允许 internal user |
| platform/config/store/region | 必填；tenant、platform 与 A1 主模型一致 |
| state_hash | SHA-256，唯一；不保存原 state |
| redirect_target_code | 固定枚举映射到服务端 URL，不接受原始 URL |
| idempotency_key_hash | tenant + user + action 范围内唯一 |
| status | initiated/callback_received/exchanged/succeeded/failed/expired |
| expires_at/consumed_at | 固定 5 分钟 TTL；消费后不可复用 |
| request_id/last_error_code | 稳定、脱敏、可审计 |
| created_at/updated_at/version | 并发与可观测性元数据 |

不得新增 `authorization_code`、`access_token`、`refresh_token`、`client_secret`、callback 原始 query、Cookie 或 Session 原值字段。

## 4. 状态与事务

合法流程：

```text
initiated -> callback_received -> exchanged -> succeeded
initiated -> expired
initiated/callback_received/exchanged -> failed
failed -> 新建 attempt 重试（不复活旧 state）
```

- callback 使用 `select_for_update` 原子校验并消费 state；重复请求返回稳定冲突/已消费结果，不重复交换 code。
- 创建授权、引用轮换和 attempt 成功状态在本地事务内一致提交。
- 平台/托管外部调用通过 operation ledger 或 outbox 记录脱敏步骤状态；崩溃恢复按幂等 operation ID 查询或补偿。
- 外部撤销成功后本地提交失败时，进入 `REVOCATION_RECONCILE_REQUIRED`，禁止继续使用旧引用并由人工/受控任务恢复。

## 5. Adapter 与密钥托管合同

平台 adapter 最小接口：

- `build_authorization_url(contract, state, callback_url)`：只使用已批准 endpoint/scope。
- `validate_callback(contract, query, attempt)`：返回规范化 code 与平台身份候选；不记录 query。
- 不负责持久化、不返回 Token、不自行改变授权状态。

密钥托管 gateway 最小接口：

- `exchange_and_store(platform, code, operation_id)`。
- `refresh_and_store(token_id, operation_id)`。
- `revoke(credential_id, token_id, operation_id)`。

成功只返回引用元数据：`credential_id/token_id/mask/version/expires_at/revocation_status`；失败只返回稳定错误码。接口实现必须证明日志、异常和 telemetry 已脱敏。

## 6. 网络与运行时门禁

- `MARKETPLACE_OAUTH_NETWORK_ENABLED=false` 为默认值；Production settings 无条件拒绝启用。
- egress 仅允许合同登记的 HTTPS host/port，禁止重定向到未登记 host，DNS 解析结果不得落入 loopback、link-local 或私网地址（获批私有托管端点除外）。
- 固定连接/读取/总超时；429 与可恢复 5xx 使用有上限退避和 jitter，认证/签名错误不自动无限重试。
- callback host、scheme 和 path 由服务端配置生成，不读取 Host header 拼接安全 URL。
- 紧急停止开关必须同时阻断 initiate、exchange、refresh 和新同步；revoke/恢复通道按安全评审决定是否保留。

## 7. 审计与可观测性

审计至少包含：attempt 公共 ID、tenant、platform、store、action、actor、result、稳定错误码、state consumed 标志、operation ID hash、合同版本、request ID 和时间。禁止包含 state、code、Token、Secret、完整 callback query、平台原始响应或 redirect URL 查询串。

指标只统计聚合数量与延迟：initiated/succeeded/failed/expired/replayed、custody failure、429、timeout。日志过滤器和错误上报测试必须使用 canary 值验证不泄漏。

## 8. 发布顺序

1. synthetic/mock：完整合同与负向测试，状态最多为 `mock`。
2. Sandbox：专项安全批准后启用受控网络，完成 JWT、scope、tenant/store、字段和失败态联调；仍不代表 Production。
3. Pilot/Production：不属于 PR-A2；需独立发布方案、回滚、证书、DNS、监控和审批。

