# TikTok Shop 正式平台合同对齐记录

复核日期：2026-08-07。来源为 TikTok Shop Partner Center 当前官方文档；执行真实试点当日仍须在获批应用控制台复核 market、scope 与 redirect。

## 已对齐合同

- Seller authorization：US/ROW 使用各自官方授权域名；请求使用 `service_id` 与一次性 `state`。
- callback：平台返回 `code`、`state`（或错误）；shop identity 不取自浏览器 callback。
- code exchange：`GET https://auth.tiktok-shops.com/api/v2/token/get`，`grant_type=authorized_code`。
- refresh：`GET https://auth.tiktok-shops.com/api/v2/token/refresh`，`grant_type=refresh_token`。
- authorized shops：`GET /authorization/202309/shops`，从平台响应取得 `shop_id` 与 `shop_cipher`。
- 最小 metadata：`GET /seller/202309/permissions`，仅验证批准的只读 scope。
- Open API：请求使用 `x-tts-access-token`；签名排除 `sign`/`access_token`，按官方顺序拼接 path、参数及适用 body，并以 App Secret 执行 HMAC-SHA256。

## 尚未冻结

当前官方材料中未确认可供本应用使用的 server-side revoke endpoint。`LIVE_TIKTOK_REVOKE_PATH` 不得填猜测值；缺少获批合同即 fail closed。应用/试点 seller、market、redirect、scopes、revoke 合同和真实响应均未提供，因此真实流程仍为 BLOCKED。

App Secret、access/refresh token 与 code 只在 provider/custody 请求内存中短暂使用；业务层只接收 opaque reference 与 mask。真实 OAuth、authorized shop、refresh、revoke、reauthorization 和最小 API 未使用固定制品验证前：TikTok Shop capability = `pending/mock`。
