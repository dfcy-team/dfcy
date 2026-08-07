# Shopee 正式平台合同对齐记录

状态：`BLOCKED / contract not frozen`，复核日期：2026-08-07。

Shopee 当前详细开发者合同需经获批 Open Platform 控制台访问。本工作区没有获批应用、正式合同版本、试点店铺、redirect 登记或 revoke 合同证据，因此 `LIVE_SHOPEE_CONTRACT_APPROVED` 必须为 false，provider 在任何网络调用前 fail closed。

正式启用前由平台管理员与架构/安全复核人填写并签署：

- Developer application 与 Partner ID mask；
- application status、region、精确 redirect URL；
- 最小只读 scopes/APIs；
- OAuth initiate、code exchange、authorized shop/shop identity、refresh、revoke、签名与 timestamp 合同版本/日期；
- 正式 API hosts、限流与 Retry-After 合同；
- 批准的试点 shop mask 与出口要求。

代码中 Shopee endpoint 均为受控配置，不能以旧博客、历史代码或本文件占位符作为批准证据。callback 只接受平台合同字段，不接受前端 token、tenant、user 或内部 store 替换值。App Secret 仅以 custody reference 解析。

在上述证据齐备、固定制品部署并完成真实 OAuth/refresh/revoke/最小只读验证前：Shopee capability = `pending/mock`，不得标记 `connected`。
