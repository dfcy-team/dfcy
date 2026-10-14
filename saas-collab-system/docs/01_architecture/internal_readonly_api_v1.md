# 内部系统只读 API v1

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

商品图片由 `product_details`（商品明细数据）的 `image_url` 返回。站内 `/media/product-images/` 路径转换为当前接口站点的完整 URL；外部 HTTP(S) 图片地址保持原值，无图片或无效地址返回 `null`。调用方取得地址后自行 GET 图片。图片元数据沿用商品明细数据授权，现有站内图片服务的访问规则保持不变；接口不代理下载外部图片，也不触发图片上传或修改。

旧编码随商品数据返回：`products` 提供 `legacy_spu_code`（旧 SPU 编码），`product_details` 提供 `legacy_sku_code`（旧 SKU 编码）。SKU 的 `spu_id` 对应商品主数据的 `id`，调用方可据此关联旧 SPU；旧编码未登记时返回空字符串，不用新编码代填。

服务端显式发布的数据块以实时 `capabilities/` 为准。基础档案首批 8 块之外，增量接入商品属性、颜色、映射、组合关系、平台商品、产品市调、开发项目、采购订单、销售订单、退款退货、库存快照、达人档案、建联任务和送样履约；本次候选再增加商品成本，共 23 块。每块只返回服务端公布的字段；联系电话、邮箱、请求负载、密钥等字段不随模型整表输出。广告及其他未接入的目录项仍待接入。业务路由不提供 POST、PUT、PATCH、DELETE。历史盘点见 [数据块接入审计](internal_readonly_resource_audit_20260929.md)，不代表当前部署状态。

## 商品成本只读合同（本次候选）

```http
GET /api/internal-readonly/v1/product_costs/?limit=100&cursor=0
Authorization: Basic base64(client_id:client_secret)
```

管理员勾选“基础档案 → 商品成本”，默认授权该数据块服务端定义的全部可读字段，无需逐字段配置。新增或修改调用方仍须另一位管理员审核通过后单独启用。仅授权商品主数据、商品明细或平台商品明细，不会获得商品成本读取权限。发布后，原已批准并启用且已勾选商品成本的调用方可使用原凭据读取；本次代码不修改调用方授权、审批状态、密钥或启用状态。正式环境是否已接入，必须查询该环境的 `capabilities/`，不能依据本文或配置勾选推断。

数据源为 `ProductCostVersion` 成本版本事实，不是 SKU 的采购价字段，也不是销售“价格中心”。每条记录的字段如下：

- 关联：`id`、`sku_id`、`spu_id`、`sku_code`、`legacy_sku_code`、`spu_code`、`legacy_spu_code`、`product_name`。
- 仓库：`warehouse_id`、`warehouse_code`、`warehouse_name`、`warehouse_country_code`；未指定仓库时均为 `null`。
- 版本：`version_no`、`status`（`pending` / `confirmed`）、`source`（`manual` / `system` / `import`）、`currency`。
- 金额：`purchase_cost`（采购成本）、`freight_cost`（运费）、`duty_cost`（关税）、`packaging_cost`（包装费）、`other_cost`（其他费用）、`system_cost`（系统成本）、`confirmed_cost`（确认成本）。金额为四位小数的字符串，未登记的系统或确认成本为 `null`，不以零或采购价代填。
- 时间与说明：`effective_from`、`effective_to`、`reason`、`created_at`。`effective_to = null` 表示没有截止时间；成本版本没有 `updated_at` 字段。

接口返回授权租户的全部成本版本，包括历史和待确认版本，按 `id` 升序分页。它不自动选取“当前成本”；调用方需要使用 `status = confirmed`、币种、SKU、仓库和 `[effective_from, effective_to)` 生效区间判断业务时点适用的确认成本。不能仅取最大 `id` 或最高版本号作为当前成本。没有成本记录时返回空列表，不制造成本版本。

关联 SKU、SPU 和非空仓库也必须属于调用方租户；异常的跨租户关联记录不会返回。不提供成本写入、确认审批、导入或删除能力，不返回创建人账号、密码或角色权限。分页、来源地址校验、凭据有效期和分钟限流沿用已有接口。

旧配置中的 `product_id`、`sku`、`amount`、`effective_at`、`updated_at` 仅用于兼容旧字段列表的配置提交，保存后规范化为上面的完整数据块字段。实际响应不返回这些占位字段；已有调用方的旧字段列表也只表示数据块授权，不构成逐字段读取限制。调用方应以实时能力目录中的字段为准。
