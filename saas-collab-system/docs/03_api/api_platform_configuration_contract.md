# API 平台连接配置合同

状态：开发实现，真实平台能力仍为 `pending/live-validation`。

## 安全边界

- 配置页面支持 Shopee 与 TikTok Shop；平台、环境、地区、公开标识、Callback、最小 scope 和超时由后端 Schema 返回或校验。
- App Secret、Partner Key、Access Token、Refresh Token 等字段仅可发送到独立凭据 action，Serializer 为 `write_only`。
- 业务数据库只保存托管引用、固定掩码 `********`、引用版本、状态和时间元数据。
- 普通创建/更新接口拒绝凭据字段；空值不会清除旧引用，清除必须使用独立 action 和二次确认。
- Production 同步、平台写操作、订单/库存导入、Webhook 消费和定时任务均不由本合同开启。

## 接口

```text
GET    /api/internal/integrations/platform-schemas/{platform}/?environment=sandbox&region=PH
GET    /api/internal/integrations/configs/
POST   /api/internal/integrations/configs/
GET    /api/internal/integrations/configs/{id}/
PATCH  /api/internal/integrations/configs/{id}/
POST   /api/internal/integrations/configs/{id}/credentials/rotate/
POST   /api/internal/integrations/configs/{id}/credentials/clear/
POST   /api/internal/integrations/configs/{id}/verify/
POST   /api/internal/integrations/configs/{id}/disable/
GET    /api/internal/integrations/configs/{id}/audit/
```

更新非敏感配置和凭据 action 均使用当前 `version`。版本不一致返回 `409 STATE_CONFLICT`。凭据 action 还要求 12–200 字符的 `Idempotency-Key`；同一租户内不得跨配置或跨 action 重用。

凭据替换请求示例仅使用占位符：

```json
{
  "version": 1,
  "reason": "approved credential replacement",
  "credentials": {
    "app_secret": "<WRITE_ONLY_VALUE>"
  },
  "verify_after_save": false
}
```

响应不含 `credentials` 或任何原值，只返回 `credential_status`、`credential_mask`、`credential_reference_version`、`config_version` 和时间元数据。

## Exact permissions

```text
integrations.config.view
integrations.config.create
integrations.config.update
integrations.config.verify
integrations.config.disable
integrations.credential.rotate
integrations.credential.clear
integrations.audit.view
```

所有资源查询先限定当前 tenant，再应用 platform/environment/region/config data scope。跨 tenant 详情统一表现为 404。

## 平台 Schema

- Shopee：`partner_id`、可选组织引用、PH/TH/MY、v2 合同、write-only App Secret/Partner Key。
- TikTok Shop：`app_key`、可选组织引用、PH/TH/MY、202407 授权合同、最小只读 scope `seller.authorization.info`。
- TikTok authorized shop 使用 `/authorization/202309/shops` 的返回标识与 `shop_cipher`；前端不允许提交内部门店替换值。
- Pilot/Production 配置只有在 Callback allowlist 已配置时才可保存；真实网络还受独立服务端开关、合同批准和托管可用性控制。

合同核对入口：

- Shopee Open Platform v2 授权文档：<https://open.shopee.com/documents?module=63&type=2>
- TikTok Shop Authorization Overview 202407：<https://partner.tiktokshop.com/docv2/page/authorization-overview-202407>
- TikTok Shop Get Authorized Shops 202309：<https://partner.tiktokshop.com/docv2/page/get-authorized-shops>
- TikTok Shop API entity tags / `shop_cipher`：<https://partner.tiktokshop.com/docv2/page/api-entity-tags>
