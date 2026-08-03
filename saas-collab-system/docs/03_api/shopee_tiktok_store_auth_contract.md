# Shopee / TikTok Shop 门店授权基础合同

## 1. 合同状态

- 合同版本：`A-01-v1`
- 冻结日期：`2026-08-03`
- 适用平台：`shopee`、`tiktok`
- 当前能力状态：合同与模型 `pending`，合成凭据引用服务 `mock`
- 本合同不授权 OAuth 跳转、callback、Token 交换/刷新、撤销、真实同步或任何平台 HTTP 请求。

官方依据（访问日期均为 `2026-08-03`）：

- Shopee Open Platform：`https://open.shopee.com/documents?module=63&type=2`。公开页面需要平台账户/应用权限才能查看完整细节，本合同只冻结可公开确认的 Open Platform v2 边界；未核实字段不作推断。
- TikTok Shop Authorization Overview：`https://partner.tiktokshop.com/docv2/page/authorization-overview-202407`
- TikTok Shop Get Authorized Shops：`https://partner.tiktokshop.com/docv2/page/call-get-authorized-shops`
- TikTok Shop API Entity Tags：`https://partner.tiktokshop.com/docv2/page/api-entity-tags`
- TikTok Shop Rate Limits：`https://partner.tiktokshop.com/docv2/page/rate-limits`
- TikTok Shop Common Errors：`https://partner.tiktokshop.com/docv2/page/common-errors`

## 2. 平台、版本和区域

| 平台 | API 版本策略 | 区域策略 | 弃用策略 |
|---|---|---|---|
| Shopee | Open Platform `v2`；具体 path 必须由 A-04 的官方端点清单登记 | 本 PR 生产区域允许列表为空；区域取自 `StoreMaster.country_code`，A-04 按已批准应用逐区放行 | 官方宣布弃用后先新增兼容版本和迁移窗口，禁止原地替换 |
| TikTok Shop | OAuth 使用官方 v2 token 流程；业务 API 使用端点自身的日期版本，例如授权门店 `202309`，禁止假设全局版本 | US 与 ROW 主机分区；本 PR 生产区域允许列表为空 | 日期版本并存，调用方必须显式声明版本，旧版下线前完成双版本验证 |

`sandbox` 和 `production` 都不得在本 PR 发起网络请求。所有区域、host 和 redirect URI 只能由后续受审配置提供，不能写入代码或数据库示例。

## 3. 授权主体、scope 和身份

### 3.1 逻辑 scope

本系统冻结以下最小逻辑 scope：`shop.read`、`order.read`、`product.read`、`inventory.read`。写 scope 默认不申请。平台官方 scope key 必须在 A-04 从已批准应用控制台逐项映射；映射缺失、授权返回缺项或出现额外高风险 scope 时授权失败。数据库只保存平台返回 scope 名称的非敏感副本，不保存 Token。

### 3.2 Shopee

- 授权主体是 seller shop；`shop_id` 标识店铺，`merchant_id` 标识商家主体，两者不得互换。
- callback 必须同时校验一次性 `state`、授权 code、平台返回 shop/merchant 身份和预绑定内部 store。
- 全局身份键：`shopee:{region}:{shop_id}`。`merchant_id` 作为主体一致性字段，不作为同一门店跨 tenant 重复绑定的绕过条件。

### 3.3 TikTok Shop

- seller access token 代表卖家授权主体；本地店铺 API 还需要 `shop_cipher`。
- `shop_id` 是授权门店返回的稳定标识；`shop_cipher` 是调用 Shop entity API 的不透明路由标识，不得由前端构造。
- 全局身份键：`tiktok:{region}:{shop_id}`。`shop_cipher` 只保存为非敏感平台身份元数据，不替代 `shop_id`。
- callback 使用一次性、限时 `auth_code` 和 `state`；授权门店列表必须由官方接口取得后再绑定。

全局身份键在所有 tenant 间唯一。内部 `StoreMaster`、授权记录和 `PlatformIntegrationConfig` 的 tenant、平台类型必须一致。

## 4. 凭据边界

- 业务库只保存外部密钥系统返回的 `credential_id`、`token_id`、掩码、引用版本、状态和过期时间。
- 禁止保存或回显 `credentials`、`access_token`、`refresh_token`、Secret、Cookie、Session 或其新密文。
- 测试只接受 `mock-credential-*` 和 `mock-token-*` 引用。
- 引用轮换必须在事务中锁定记录、递增版本并追加脱敏 `IntegrationAuditLog`。
- 发现旧 `credential_ciphertext` 非空时，迁移必须阻断并要求先迁入外部密钥系统；不得删除或打印原值。

## 5. 限流、重试和认证失败

- 限流键至少包含平台、应用配置、授权门店；TikTok Shop 按官方 `App ID x Authorized Shop` 动态 QPS 处理。
- `429` 使用带随机抖动的指数退避，默认最多 5 次；尊重平台返回的重试提示。`401`、Token 无效、scope 不足或身份不匹配不自动重试，转为授权错误并等待人工处理。
- `503` 可按瞬时故障退避重试；签名、时间戳、参数、业务校验错误不得盲目重试。
- 当前 SyncJob 的 Mock 重试不代表平台重试已实现。

## 6. 分页、游标和标准化

- Shopee v2 的 offset/page_size、cursor 或 time-range 以具体端点合同为准，不跨端点猜测。
- TikTok Shop 的 page_size/page_token 或 endpoint cursor 以具体日期版本合同为准。
- 增量游标按 `tenant + integration_config + store + resource_type` 隔离，只有整页校验和持久化成功后才推进。
- 游标失效、版本变化或平台拒绝时停止任务并记录脱敏错误；禁止自动全量回扫。
- 平台时间统一解析为带时区时间并存 UTC；展示时使用门店时区。币种标准化为大写 ISO 4217；未知枚举保留原值并标记质量异常。

## 7. 签名、state、webhook 和错误

- Shopee v2 请求签名、TikTok Shop `sign` 及 token header 只能在后端连接器内生成；密钥来自外部密钥系统。
- OAuth `state` 必须一次性、绑定 tenant/user/config/store、设置短期过期并在成功或失败后消费。
- webhook 必须验证平台签名、时间窗口、来源和事件唯一标识；去重键为 `tenant + platform + event_id`。校验失败不得进入业务处理。
- 平台错误转换为稳定内部错误码和脱敏 message；请求日志不得保存 header、Token、完整 callback query 或原始敏感 payload。

## 8. 后续内部路由

以下路由仅冻结名称，均为 `pending`，本 PR 不注册 handler：

| 能力 | 方法与路径 | exact permission | 状态 |
|---|---|---|---|
| 发起授权 | `POST /api/internal/integrations/store-authorizations/authorize/` | `integrations.store.authorize` | pending |
| OAuth callback | `GET /api/internal/integrations/store-authorizations/callback/{platform}/` | 服务端 state | pending |
| 刷新授权 | `POST /api/internal/integrations/store-authorizations/{id}/refresh/` | `integrations.store.authorize` | pending |
| 撤销授权 | `POST /api/internal/integrations/store-authorizations/{id}/revoke/` | `integrations.store.revoke` | pending |
| 触发同步 | `POST /api/internal/integrations/store-authorizations/{id}/sync/` | `integrations.store.sync` | pending |
| 重试 | `POST /api/internal/integrations/store-authorizations/{id}/retry/` | `integrations.store.retry` | pending |
| 凭据引用轮换 | `POST /api/internal/integrations/store-authorizations/{id}/credential-reference/rotate/` | `integrations.credential.rotate` | pending |

只读门店授权列表/详情用于验证模型、tenant 和 scope，仍标记 `pending`；HTTP 200 不构成 `connected`。
