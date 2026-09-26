# 内部系统只读 API v1（基础档案首批）

本接口只允许内部系统查询，不接受业务写入。管理页面仍展示全部可配置数据块，但只有 `GET /api/internal-readonly/v1/capabilities/` 返回的 `ready_resources` 可实际读取；`pending_resources` 不对应业务数据路由。

## 管理员配置与审核

1. 在“API 数据接入 → 内部系统数据接口”新增调用系统，选择模块和数据块，填写来源 IP/CIDR、限流、分页上限、有效期。保存时一次性领取 `client_id` 与 `client_secret`，调用方初始为“待审核、停用”。
2. 另一位具有 `integrations.internal_api_client.approve` 权限的本租户管理员，在同一菜单的调用系统列表执行“审核通过”或“驳回”。创建或最近修改配置的人不能自审；驳回必须填写原因。
3. 审核通过后，具有 `integrations.internal_api_client.manage` 权限的管理员单独点击“启用”。修改任何配置会重新变为待审核且停用；轮换密钥不改变授权范围，但旧密钥立即失效。
4. 现存调用方在迁移时统一转为待审核且停用，必须按上面流程重新审核。管理员可在“审计”查看配置变更、审批、启停和轮换记录。

## 调用方式

仅在 HTTPS 下使用 HTTP Basic：用户名为 `client_id`，密码为一次性 `client_secret`。服务端同时校验审批、启用状态、有效期、来源 IP、所选数据块、租户隔离、分钟限流和分页上限。默认仅信任直连地址 `REMOTE_ADDR`，忽略调用方伪造的 `X-Forwarded-For`。如果业务网关或 Nginx 转发真实来源 IP，部署方必须将实际代理网段配置到 `INTERNAL_READONLY_TRUSTED_PROXY_CIDRS`，并确保代理覆盖而非透传不可信请求头；服务端仅在直连代理可信时，从转发链右侧剥离可信代理，取第一个非代理地址。不得把公网段整体配置为可信代理。

```http
GET /api/internal-readonly/v1/products/?limit=100&cursor=0
Authorization: Basic base64(client_id:client_secret)
```

返回 `data.resource`、`data.items`、`data.next_cursor`、`data.has_more`；有下一页时将 `next_cursor` 传入下一次请求。字段以能力目录中各数据块的 `fields` 为准。不提供任意字段查询、跨租户查询、删除传播或历史增量水位保证。

首批实际接入：`products`（SPU）、`product_details`（SKU）、`product_categories`、`platforms`、`country_sites`（国家档案）、`suppliers`、`stores`、`warehouses`。商品成本、商品映射、广告以及其他目录数据块仍待接入。业务路由不提供 POST、PUT、PATCH、DELETE。
