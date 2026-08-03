# Shopee / TikTok Shop API 对齐矩阵

合同版本：`A-01-v1`，核对日期：`2026-08-03`。本矩阵不包含真实 host 凭据、账号或请求样例。

| 领域 | Shopee Open Platform | TikTok Shop Open Platform | 内部映射 | 当前状态 |
|---|---|---|---|---|
| API 版本 | Open Platform v2；端点清单待批准应用核实 | OAuth v2；业务端点使用日期版本 | `platform_api_version` 合同元数据，代码不硬编码 host | pending |
| 区域 | 按批准应用和门店国家逐区启用 | US/ROW 分区 | `StoreMaster.country_code` + 受审允许列表 | pending |
| 授权主体 | seller shop；merchant 为上层主体 | seller；shop 为 Shop entity | `merchant_subject_id` + 内部 `store_id` | pending |
| 门店标识 | `shop_id`，辅助 `merchant_id` | `shop_id`，调用标识 `shop_cipher` | `platform_store_id` + `shop_cipher` 元数据 | pending |
| 全局唯一键 | `shopee:{region}:{shop_id}` | `tiktok:{region}:{shop_id}` | SHA-256 规范键，跨 tenant 唯一 | mock/model |
| OAuth scope | 平台官方 key 待批准应用控制台核实 | `granted_scopes` 与 API scope | 逻辑最小集 `shop/order/product/inventory.read` | pending |
| Token 存储 | 外部密钥系统 | 外部密钥系统 | 仅 `credential_id/token_id` 引用 | mock |
| Token 刷新 | v2 refresh，细节待 A-04 官方核实 | OAuth v2 refresh | 后端服务，前端不可见 | pending |
| 请求签名 | v2 HMAC 签名，字段按端点官方合同 | `sign` + timestamp + token header | 后端连接器专属 | pending |
| 分页 | offset/cursor/time range 按端点 | page token/cursor 按日期端点 | `SyncCursor` 按门店和资源隔离 | pending |
| 限流 | 官方应用/门店/端点限额待控制台核实 | 动态 QPS，App ID x Authorized Shop | 429 指数退避 + jitter，最多 5 次 | pending |
| 认证错误 | Token、签名、scope、主体不匹配不重试 | Token、shop_cipher、scope、签名不匹配不重试 | 脱敏错误 + 人工处理 | pending |
| webhook | 签名、时间窗、事件去重 | Authorization header 签名、HTTPS、事件去重 | 复用 `WebhookEvent` | pending |
| 数据标准化 | 平台枚举、时间和币种逐端点映射 | 平台枚举、时间和币种逐端点映射 | UTC、ISO 4217、未知枚举质量告警 | pending |

## 差异处理

1. TikTok Shop 的 `shop_cipher` 是 Shop entity 路由标识，不能当作稳定 `shop_id` 或凭据。
2. Shopee 的 `merchant_id` 与 `shop_id` 层级不同，唯一约束以区域和 `shop_id` 为核心。
3. 两个平台的 scope 名称、分页和签名参数不做错误统一；连接器在统一内部合同下分别实现。
4. 官方文档或批准应用控制台无法核实的字段保持 `pending`，不得用博客、SDK 或历史经验替代正式冻结。
5. A-04/A-05 完成平台 sandbox、权限失败态和字段验证前，任何条目都不得标记 `connected`。
