# Shopee 正式平台合同对齐记录

状态：`OFFLINE CONTRACT ALIGNED / LIVE NOT RUN`，复核日期：2026-08-10。

当前官方 Open Platform《Authorization and Authentication》（页面更新日期 2026-07-19）已离线复核：seller authorization 使用 `https://open.shopee.com/auth`，请求字段为 `partner_id`、`auth_type=seller`、精确 `redirect_uri`、`response_type=code` 与一次性 `state`。callback 返回一次性 `code` 及 `shop_id`/`main_account_id`；code exchange 与 refresh 分别使用 `/api/v2/auth/token/get` 和 `/api/v2/auth/access_token/get`。官方页面：`https://open.shopee.com/developer-guide/12`。

代码已在 `c3307626affdae78c14db66dc19ad7c65744ae39` 对齐上述 initiate 参数，并由 fake transport 测试证明构造授权 URL 不解析 App Secret、不发网络请求。获批应用控制台、试点店铺、精确 scopes、平台侧 cancel/revoke 操作与真实响应仍未固定，因此 `LIVE_SHOPEE_CONTRACT_APPROVED` 必须为 false，provider 在任何网络调用前 fail closed。

正式启用前由平台管理员与架构/安全复核人填写并签署：

- Developer application 与 Partner ID mask；
- application status、region、精确 redirect URL；
- 最小只读 scopes/APIs；
- OAuth initiate、code exchange、authorized shop/shop identity、refresh、revoke、签名与 timestamp 合同版本/日期；
- 正式 API hosts、限流与 Retry-After 合同；
- 批准的试点 shop mask 与出口要求。

API endpoint 仍为受控配置，不能以旧博客、历史代码或本文件作为应用批准证据。callback 只接受平台合同字段，不接受前端 token、tenant、user 或内部 store 替换值。App Secret 仅以 custody reference 解析。

在上述证据齐备、固定制品部署并完成真实 OAuth/refresh/revoke/最小只读验证前：Shopee capability = `pending/mock`，不得标记 `connected`。
