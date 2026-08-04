# PR-A2 Shopee / TikTok Shop OAuth / Callback API 合同

## 1. 状态与版本

本合同当前实现为 `synthetic/mock`，真实平台 endpoint、scope、API 版本、区域域名、签名字段和配额仍为 `pending`，必须由获批应用控制台与官方文档共同确认后登记；未登记时真实 adapter 必须 fail closed。

官方入口：

- Shopee Open Platform：`https://open.shopee.com/documents`。
- TikTok Shop Authorization：`https://partner.tiktokshop.com/docv2/page/authorization-overview-202407`。
- TikTok Shop Request signing：`https://partner.tiktokshop.com/docv2/page/sign-your-api-request`。
- TikTok Shop Rate limits：`https://partner.tiktokshop.com/docv2/page/rate-limits`。

规划生成时自动抓取通道无法读取上述页面正文，因此本合同不声称已复核具体值；A2-00 控制台证据是实现真实 Sandbox adapter 的阻断项。

## 2. Internal API

### 2.1 发起授权

`POST /api/internal/integrations/store-authorizations/oauth/initiate/`

- 权限：`integrations.store.authorize`。
- scope：permission-specific `platforms/store_ids`。
- header：`Idempotency-Key`，16 至 128 字符。
- body：`integration_config_id:int`、`store_id:int`、`platform:shopee|tiktok`、`region:string`、`redirect_target_code:string`。
- 201 data：`attempt_id`、`authorization_url`、`expires_at`、`request_id`、`status=initiated`。
- 禁止 body：state、callback URL、Token、Secret、Cookie、Session、credentials 或任意 redirect URL。
- 当前实现使用 `/api/internal/integrations/store-authorizations/oauth/initiate/`，只生成 `synthetic.invalid` 授权地址；真实网络开关默认关闭且 Production 强制关闭。

### 2.2 查询授权 attempt

`GET /api/internal/integrations/oauth-attempts/{id}/`

- 权限：`integrations.store.authorize`。
- scope：attempt 对应 `platforms/store_ids`。
- data：`id/platform/store_id/status/expires_at/consumed_at/last_error_code/request_id/created_at/updated_at`。
- 不返回 state hash、session hash、idempotency hash、code、引用原值、平台原始响应或 callback query。

### 2.3 刷新、撤销和重试

| 路径 | 权限 | 结果 |
|---|---|---|
| `POST /api/internal/integrations/store-authorizations/{id}/refresh/` | `integrations.credential.rotate` | 新掩码、引用版本、expires_at、状态 |
| `POST /api/internal/integrations/store-authorizations/{id}/revoke/` | `integrations.store.revoke` | revoked/reconcile_required、稳定错误码 |
| `POST /api/internal/integrations/store-authorizations/{id}/retry/` | `integrations.store.retry` | 新 attempt ID；旧 state 不复用 |

三个动作均要求 `Idempotency-Key`、目标资源 scope、行锁、版本检查和不可变审计。

当前 synthetic 实现只返回脱敏引用和稳定状态，不发送 Shopee/TikTok Shop 请求；真实 Sandbox 联调仍为 `pending`。

## 3. Public callback

`GET /api/platform/oauth/{platform}/callback/`

- 无 JWT；只允许 `shopee|tiktok` 路径枚举。
- query 参数必须与已登记平台合同完全匹配；未知参数默认拒绝，平台明确声明的扩展字段需合同版本化。
- 必须验证 state 存在、hash 匹配、未过期、未消费，并绑定 tenant、user、session、platform、config、store、region 和 redirect target。
- 必须验证平台要求的签名/错误字段、授权主体和门店身份；不得信任前端提交身份。
- code 仅在请求内存中交给密钥托管 gateway，处理后立即丢弃。
- 成功或失败均只 302 到 allowlisted redirect target；查询参数限定为 `oauth_result`、`attempt_id`、`error_code`，不得回显平台 query。

## 4. 响应与错误

Internal API 使用统一 `success/code/message/data`。Public callback 使用 302；callback 无法安全确定 allowlisted redirect 时返回最小 JSON 错误且不包含输入回显。

| HTTP | code | 场景 |
|---|---|---|
| 400 | `OAUTH_CALLBACK_INVALID` | callback 结构或平台错误字段非法 |
| 401 | `NOT_AUTHENTICATED` | internal API 未认证 |
| 403 | `DATA_SCOPE_*` / `PERMISSION_DENIED` | 用户类型、exact permission 或 scope 拒绝 |
| 404 | `RESOURCE_NOT_FOUND` | 跨 tenant/store 隐藏或 attempt 不存在 |
| 409 | `OAUTH_STATE_CONSUMED` / `STATE_CONFLICT` | state 重放、幂等冲突、版本冲突 |
| 422 | `OAUTH_STATE_INVALID` / `OAUTH_REDIRECT_INVALID` | state 绑定、redirect target 或字段规则错误 |
| 429 | `PLATFORM_RATE_LIMITED` | 平台限流，不无限重试 |
| 502 | `PLATFORM_RESPONSE_INVALID` | 平台响应无法按冻结合同解析 |
| 503 | `CUSTODY_UNAVAILABLE` / `PLATFORM_UNAVAILABLE` | 托管、网络或平台暂不可用 |

错误 message 不包含 state、code、Token、Secret、完整 URL、平台原始响应或身份原值。

## 5. 前端消费

- 发起授权前展示平台、店铺、只读 scope 摘要和环境；用户确认后调用 internal initiate。
- 使用后端返回的 `authorization_url` 导航，不在前端构造 endpoint、state 或 callback URL。
- callback 回到 allowlisted 页面后，以 attempt ID 调用状态查询；URL 结果码仅用于提示，不作为授权成功事实来源。
- loading、pending、success、expired、failed、replayed、forbidden、offline 均有明确状态。
- 不在 localStorage、sessionStorage、路由 state、错误监控或 analytics 中保存授权 URL、state 或 callback query。

## 6. 实现状态与 connected 门槛

synthetic 全通过最多标记 `mock`。当前页面和 API 映射均为 `mock/pending`。真实 Sandbox 通过仍标记 `sandbox_verified` 或现有等价受控状态；只有独立 Pilot/Production 安全评审、真实 JWT 与 permission/data_scope E2E、密钥托管、监控、回退和固定制品全部通过后，才可另行评估 `connected`。PR-A2 不直接授予该状态。
