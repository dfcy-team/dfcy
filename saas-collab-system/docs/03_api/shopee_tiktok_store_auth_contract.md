# Shopee / TikTok Shop 门店授权基础合同

## 1. 范围与状态

本合同冻结 A-01 至 A-03 的平台身份、授权元数据、凭据引用、安全审计和未来接口边界。当前仅实现数据模型、引用式凭据服务和只读内部查询；不实现 OAuth、callback、Token 刷新、webhook 处理、平台 SDK/HTTP、SKU 映射或销售库存导入。

| 能力 | 状态 | 说明 |
|---|---|---|
| 合同、模型、迁移、权限、审计 | pending | 代码存在不等于真实平台已连接 |
| synthetic 凭据引用与状态迁移 | mock | 只接受 `synthetic-*` 引用，不保存或解析平台凭据 |
| Shopee/TikTok OAuth 与平台请求 | pending | PR-A2 及后续专项安全评审范围 |
| 真实 Sandbox、Pilot、Production | pending | 本 PR 禁止执行 |

任何能力在完成真实 Sandbox 请求、JWT、权限、tenant/store、失败态和字段验证前不得标记为 `connected`。

## 2. 平台版本、区域与弃用

| 平台 | 合同版本策略 | 区域身份 | 弃用策略 |
|---|---|---|---|
| Shopee | 以 Open Platform v2 为基线；具体 endpoint/version 在应用控制台批准后逐端点冻结 | `region + shop_id`，授权主体同时记录 `merchant_id` | 不自动跟随新版本；先更新合同、兼容测试和迁移窗口，再切换 |
| TikTok Shop | 以 Open Platform 按资源发布的日期版本为基线，当前参考 `202309`；不得假设所有资源同版 | `region + shop_id`，请求路由另使用 `shop_cipher` | 每个资源独立登记版本；弃用公告触发合同变更，不静默升级 |

Shopee 的精确 scope 名称、endpoint 配额和区域域名需从已批准应用控制台与官方文档复核，当前均为 `pending`，代码不得猜测固定值。TikTok Shop 的配额为动态分配，不硬编码固定 QPS。

## 3. 授权与身份

### 3.1 授权主体

- Shopee：平台门店标识为 `shop_id`，授权主体标识为 `merchant_id`。
- TikTok Shop：平台门店标识为 `shop_id`，授权主体标识为商家主体 ID；门店请求路由标识为 `shop_cipher`。
- 系统内部店铺只复用 `masterdata.StoreMaster`，不创建第三套店铺模型。
- `PlatformIntegrationConfig` 是唯一连接配置主模型；`APIIntegrationConfig` 为 legacy，只做旧数据兼容。

### 3.2 全局身份键

门店全局身份键固定为 `SHA-256(lower(platform) + ":" + upper(region) + ":" + platform_store_id)`。数据库以 `platform + platform_identity_key` 全局唯一，禁止同一平台门店绑定到不同 tenant。内部唯一关系为 `tenant + platform + store`。

### 3.3 OAuth 与 callback（未来合同，pending）

- scope 必须采用平台批准的最小只读集合；未经合同更新不得扩展写权限。
- callback 不接受前端提交的 Token、Secret 或通用 `credentials`。
- `state` 必须短时有效、一次性消费，并绑定 tenant、用户、平台、发起会话及重定向目标。
- callback 必须校验 state、平台签名、授权主体和门店身份；失败只记录稳定错误码。
- 本 PR 不注册 authorize、callback、refresh 或 webhook 业务路由。

## 4. 凭据托管

- 业务数据库只保存密钥系统返回的 `credential_id`、`token_id`、展示掩码、引用版本、状态和时间元数据。
- 新 API 拒绝 `access_token`、`refresh_token`、`secret`、`api_key`、`api_secret`、`credentials`、Cookie 或 Session。
- Mock/CI 只允许格式受控的 `synthetic-*` 引用；它不是 RPA Agent token，也不可用于真实平台请求。
- 引用轮换必须在事务内 `select_for_update`，原子替换引用和版本，并追加旧引用撤销审计。
- 审计仅保存引用 ID、掩码、状态、错误码和操作者；禁止保存凭据、完整平台响应或可还原密文。

旧字段迁移只判断字段是否为空并在内存中验证是否为明确 synthetic/mock 内容；不打印、不复制、不写日志。未知或非 Mock 内容会中止迁移并要求密钥托管审批。完成 synthetic 转换后删除 `credential_ciphertext`、`api_key_encrypted`、`api_secret_encrypted` 持久化列。

## 5. 状态机

固定状态为 `pending`、`active`、`expired`、`revoked`、`error`。

| 当前状态 | 允许目标 |
|---|---|
| pending | active、revoked、error |
| active | active（引用轮换）、expired、revoked、error |
| expired | active（重新授权后）、revoked、error |
| error | active（批准重试后）、revoked、expired |
| revoked | 无，终态 |

状态只能经 integrations 服务层修改。普通 `save()`、QuerySet `update()`、`bulk_create()`、`bulk_update()` 和删除操作不得绕过状态及不可变审计规则。

## 6. 请求、限流与恢复合同（未来连接器）

- 所有请求必须使用 HTTPS、平台规定签名、UTC 时间戳和受控超时。
- 签名密钥只在密钥托管边界内使用，禁止进入业务模型、异常或日志。
- nonce/请求 ID 需唯一并设置重放窗口；TikTok Shop 时间戳窗口按官方错误合同校验为过去 5 分钟至未来 30 秒，Shopee 精确窗口待应用合同复核。
- 429、网络错误和可恢复 5xx 使用有上限的指数退避与随机抖动；认证错误不无限重试。
- TikTok Shop 按 App x Authorized Shop 动态隔离配额，不设置固定 QPS；Shopee 配额按 endpoint/应用控制台值配置，当前 pending。
- 分页优先使用平台游标/page token；仅在完整批次落库后推进游标。
- webhook 必须先验签、校验时间窗口，再以平台事件 ID 去重；缺少稳定事件 ID 时使用平台、店铺、事件类型和规范化载荷摘要组合键。

## 7. 标准字段映射

| 标准字段 | Shopee 来源 | TikTok Shop 来源 | 规则 |
|---|---|---|---|
| `platform_store_id` | `shop_id` | `shop_id` | 字符串保存，不做整数截断 |
| `merchant_subject_id` | `merchant_id` | 平台商家主体 ID | 不用于界面明文展示 |
| `shop_cipher` | 不适用 | `shop_cipher` | 仅路由标识，不是凭据 |
| `currency` | 订单/门店币种 | 订单/结算币种 | 大写 ISO 4217；未知值隔离 |
| `ordered_at` | 平台订单创建时间 | 平台订单创建时间 | 解析为 UTC，保留来源时区元数据 |
| `updated_at_source` | 平台更新时间 | 平台更新时间 | 增量游标候选，不替代唯一键 |
| `platform_order_id` | 订单 ID | 订单 ID | tenant + platform + store 内唯一 |
| `platform_line_id` | 订单明细 ID | 订单明细 ID | 与订单 ID 组合幂等 |
| `refund_id/status/amount` | 退款资源字段 | return/refund 资源字段 | 金额使用 Decimal，不使用 float |
| `available/reserved/in_transit` | 库存资源字段 | 库存资源字段 | 缺失维度记 unknown，不推算为 0 |

精确订单、退款和库存 endpoint 及枚举映射属于 A-07/A-08，当前均为 `pending`。

## 8. 内部 API 与权限

统一响应为 `success/code/message/data`；列表 `data` 为 `count/next/previous/results`。

| 方法与路径 | 权限 | 状态 |
|---|---|---|
| `GET /api/internal/integrations/store-authorizations/` | `integrations.store.view` | pending |
| `GET /api/internal/integrations/store-authorizations/{id}/` | `integrations.store.view` | pending |
| authorize/revoke/rotate/sync/retry action | 对应 exact action permission | pending，未注册 |

权限固定为：`integrations.store.view`、`integrations.store.authorize`、`integrations.store.revoke`、`integrations.store.sync`、`integrations.store.retry`、`integrations.credential.rotate`。CUSTOM scope 允许 `platforms` 与 `store_ids`；未知 key、空数组、非法 ID、非法平台或无授权 scope 统一拒绝。跨 tenant/store 详情返回 404。

## 9. 错误与审计

| HTTP | 稳定语义 |
|---|---|
| 401 | 未认证 |
| 403 | 用户类型、exact permission 或 data scope 拒绝 |
| 404 | 资源不存在或跨 tenant/store 隐藏 |
| 409 | 重复绑定、终态操作或版本冲突 |
| 422 | tenant/platform/store、状态或引用格式非法 |

审计动作至少覆盖 `authorize`、`activate`、`rotate_reference`、`revoke`、`expire`、`error`、`retry`。审计只追加，禁止更新和删除；错误详情使用稳定 `last_error_code`，不保存原始平台响应。

## 10. 官方依据与待确认项

- Shopee Open Platform 文档入口：`https://open.shopee.com/documents`。具体应用 scope、限流和区域 endpoint 必须在 PR-A2 开工前由获批应用控制台复核。
- TikTok Shop Authorization：`https://partner.tiktokshop.com/docv2/page/authorization-overview-202407`。
- TikTok Shop Rate limits：`https://partner.tiktokshop.com/docv2/page/rate-limits`。
- TikTok Shop Common errors：`https://partner.tiktokshop.com/docv2/page/common-errors`。
- TikTok Shop Request signing：`https://partner.tiktokshop.com/docv2/page/sign-your-api-request`。
- TikTok Shop Webhooks：`https://partner.tiktokshop.com/docv2/page/tts-webhooks-overview`。

官方示例中的任何 Token、Secret、店铺或请求数据都不得复制到仓库、测试或报告。
