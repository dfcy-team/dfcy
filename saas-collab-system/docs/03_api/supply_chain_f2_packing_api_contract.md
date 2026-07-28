# SC-F2-2 装箱 API、权限与 DataScope 契约

## 1. 文档控制

| 项目 | 冻结值 |
| --- | --- |
| 工作包 | `SC-F2-2` |
| 契约版本 | `v2-p1-remediated` |
| 状态 | `P1_REMEDIATED_PENDING_RECHECK` |
| 冻结日期 | 2026-07-28 |
| 代码基线 | `71341fb5e85307bdb0ed505ef65c1df2d7a901b9` |
| 目标运行时 | Django/DRF + MySQL 8 |
| 客户端 | Vue 3 内部端、Vue 3 供应商端、原生微信小程序 |
| 执行边界 | 架构员主机本地隔离环境 |
| 生产授权 | 无 |

本契约只冻结后续 API 实现的唯一输入、输出、权限、DataScope、幂等和错误边界。冻结不等于 API 已实现或已开放，不允许提前注册路由、连接线上系统、导入真实数据、修改客户端或发布小程序。

## 2. 继承与排除

### 2.1 继承

- 继承 `SC-F2-0` 装箱领域边界和 `SC-F2-1` 已审核模型、migration、领域服务。
- 复用现有 `CustomUser`、Tenant、RBAC、Role、Permission、DataScope、统一响应、审计和 JWT。
- 复用 SC-F1 的 `SupplyPurchaseOrder`、`SupplyPurchaseOrderLine` 及 `production_completed` 状态。
- 复用现有小程序 `channel=miniapp` Token，不签发第二套小程序身份。
- 目标数据库固定为 MySQL 8，不复制 Supabase SQL、RLS、RPC 或客户端直连模式。

### 2.2 本阶段排除

- 供应商装箱能力配置 API；`set_supplier_packing_capability` 的管理入口需另行冻结并补充乐观锁和持久化幂等记录。
- 货柜、装柜、物流、发运、报关、结算、照片、视频和对象存储。
- 真实打印机、真实文件上传、真实微信通知和第三方平台调用。
- 数据迁移、双写、同步、切流和生产部署。
- 客户端页面实现、联调和发布。

供应商能力读取仅作为服务端授权判断，不在供应商或小程序响应中暴露内部配置记录 ID、修改人或审计细节。

## 3. 统一协议

### 3.1 JSON 成功响应

除 PDF 成功响应外，所有端点使用：

```json
{
  "success": true,
  "code": "OK",
  "message": "success",
  "data": {}
}
```

失败统一为：

```json
{
  "success": false,
  "code": "ERROR_CODE",
  "message": "safe message",
  "data": null
}
```

字段级 `400/422` 可以在 `data` 中返回字段错误；不得返回堆栈、SQL、请求哈希、幂等键、Token、数据库凭据、微信 subject/openid/session_key 或内部异常。

### 3.2 公共类型

- ID：JSON 正整数。
- 数量、版本、分页：JSON 正整数。
- `weight`：字符串 Decimal，最多 9 位整数和 3 位小数，`null` 或大于 0。
- `volume`：字符串 Decimal，最多 6 位整数和 6 位小数，`null` 或大于 0。
- 时间：ISO-8601 UTC 字符串。
- 空文本：统一序列化为 `""`，不同时返回 `null`。
- 列表排序：批次按 `created_at desc, id desc`；箱按 `sequence asc`；箱明细按 `id asc`。

### 3.3 请求严格性

- JSON 写请求必须使用 `Content-Type: application/json`。
- 请求体和查询参数拒绝未知字段，不得静默忽略。
- 禁止客户端提交 `tenant_id`、`supplier_id`、状态、版本结果、批次号、箱号、箱序号、快照文本、事件、审计、创建人、审核人、来源系统字段、请求哈希或响应快照；出现时返回 `400 VALIDATION_ERROR`。
- `Idempotency-Key` 为 1 至 128 个可打印 ASCII 字符，去除首尾空白后不能为空。
- `note/reason/review_note` 最长 1000 字符；`reason` 和驳回 `review_note` 去除首尾空白后至少 1 字符。
- 单批次最多 100 个采购单；单箱最多 500 个明细；单次变更最多 500 个箱、总计最多 5000 个明细。

### 3.4 分页

列表统一使用：

- `page`：默认 1，正整数。
- `page_size`：默认 20，范围 1 至 100。

`data` 固定为：

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": []
}
```

越出有效页返回 `404 RESOURCE_NOT_FOUND`；非法分页返回 `400 VALIDATION_ERROR`。

## 4. API 通道隔离

| 通道 | 固定前缀 | 身份 | 数据边界 |
| --- | --- | --- | --- |
| 内部管理端 | `/api/internal/packing/` | 活动 internal JWT；拒绝 miniapp Token、external、RPA | Tenant + exact Permission + permission-specific DataScope |
| 供应商 Web | `/api/external/supplier/packing/` | 活动 external JWT；拒绝 miniapp Token、internal、RPA | Tenant + 有效供应商绑定 |
| 微信小程序 | `/api/miniapp/supply-chain/packing/` | 活动 external 用户的 `channel=miniapp` JWT | Tenant + 有效供应商绑定 |

通道规则：

1. 小程序 Token 不能调用内部或供应商 Web API。
2. 普通 Web JWT 不能调用小程序 API。
3. 小程序 internal 用户即使拥有内部权限也不能调用装箱小程序 API。
4. RPA Token 和 RPA 用户不得调用任一 F2 API。
5. 供应商 Web 和小程序不读取请求中的 `supplier_id`，只使用可信 `ExternalUserProfile.supplier_id`。
6. 用户、绑定供应商或供应商主档停用后立即拒绝新请求。

## 5. 内部端点与权限

### 5.1 端点矩阵

| 方法与路径 | Exact Permission | 成功状态 | 成功 DTO |
| --- | --- | ---: | --- |
| `GET batches/` | `supply.packing.view` | 200 | 分页 `PackingBatchSummary[]` |
| `POST batches/` | `supply.packing.create` | 201 | `PackingBatchDetail` |
| `GET batches/{id}/` | `supply.packing.view` | 200 | `PackingBatchDetail` |
| `POST batches/{id}/boxes/` | `supply.packing.manage` | 201 | `PackingBatchDetail` |
| `PUT batches/{id}/boxes/{box_id}/` | `supply.packing.manage` | 200 | `PackingBatchDetail` |
| `POST batches/{id}/boxes/{box_id}/actions/remove/` | `supply.packing.manage` | 200 | `PackingBatchDetail` |
| `POST batches/{id}/actions/complete/` | `supply.packing.complete` | 200 | `PackingBatchDetail` |
| `POST batches/{id}/actions/cancel/` | `supply.packing.manage` | 200 | `PackingBatchDetail` |
| `GET batches/{id}/change-requests/` | `supply.packing.view` | 200 | 分页 `PackingChangeRequestDetail[]` |
| `POST batches/{id}/change-requests/` | `supply.packing.manage` | 201 | `PackingChangeRequestDetail` |
| `GET change-requests/` | `supply.packing.change.review` | 200 | 分页 `PackingChangeRequestDetail[]` |
| `GET change-requests/{id}/` | `supply.packing.change.review` | 200 | `PackingChangeRequestDetail` |
| `POST change-requests/{id}/actions/approve/` | `supply.packing.change.review` | 200 | `PackingChangeRequestDetail` |
| `POST change-requests/{id}/actions/reject/` | `supply.packing.change.review` | 200 | `PackingChangeRequestDetail` |
| `POST batches/{id}/actions/generate-label/` | `supply.packing.view` | 200 | PDF |
| `POST boxes/{box_id}/actions/generate-label/` | `supply.packing.view` | 200 | PDF |
| `GET standards/current/` | `supply.packing.view` | 200 | `PackingStandard` |

所有写入和 PDF 生成动作必须携带 `Idempotency-Key`。GET 列表、详情和当前标准不得创建 PackingEvent。

### 5.2 列表查询

内部批次列表允许：

- `search`：批次号、采购单号、供应商编码/名称或 SKU，最长 100 字符。
- `status`：`draft|in_progress|completed|cancelled`。
- `supplier_id`、`order_id`：正整数。
- `created_at_from`、`created_at_to`：ISO-8601，前者不得晚于后者。
- `page`、`page_size`。

过滤只能缩小已授权 QuerySet，不能扩大 DataScope。

批次下变更申请列表只允许 `status/page/page_size`。内部审核队列允许
`status/batch_id/supplier_id/page/page_size`。`status` 为
`pending|approved|rejected`，默认不隐式限制为 pending。

## 6. 供应商 Web 与小程序端点

两个通道使用相同请求和供应商安全 DTO，前缀不同。

| 方法与相对路径 | 能力要求 | 成功状态 |
| --- | --- | ---: |
| `GET batches/` | 有效供应商绑定 | 200 |
| `POST batches/` | `can_self_pack=true`；多订单另需 `can_mix_order_packing=true` | 201 |
| `GET batches/{id}/` | 有效供应商绑定且批次属于绑定供应商 | 200 |
| `POST batches/{id}/boxes/` | `can_self_pack=true` | 201 |
| `PUT batches/{id}/boxes/{box_id}/` | `can_self_pack=true` | 200 |
| `POST batches/{id}/boxes/{box_id}/actions/remove/` | `can_self_pack=true` | 200 |
| `POST batches/{id}/actions/complete/` | `can_self_pack=true` | 200 |
| `GET batches/{id}/change-requests/` | 有效供应商绑定 | 200 |
| `POST batches/{id}/change-requests/` | `can_self_pack=true` | 201 |
| `POST batches/{id}/actions/generate-label/` | 有效供应商绑定 | 200 PDF |
| `POST boxes/{box_id}/actions/generate-label/` | 有效供应商绑定 | 200 PDF |
| `GET standards/current/` | 有效供应商绑定 | 200 |

供应商 Web 和小程序不开放：

- 取消批次；
- 批准或驳回变更；
- 供应商能力配置；
- 内部事件、操作日志和来源字段；
- 其他供应商或其他租户数据。

供应商批次列表允许 `search/status/order_id/page/page_size`，不接受 `supplier_id`。

能力关闭后仍可读取本供应商历史批次和标签；所有新写动作必须拒绝。读取不允许绕过供应商绑定或供应商主档有效性。

## 7. DataScope 冻结规则

### 7.1 Permission-specific 取值

内部请求只读取“实际授予当前 exact permission 的活动角色”所关联的 DataScope。用户在其他角色上拥有的 scope 不得借给当前权限。

- 无 exact permission：`403 PERMISSION_DENIED`。
- 有 permission 但无 scope：`403 DATA_SCOPE_MISSING`。
- scope 类型、配置或值非法：`403 DATA_SCOPE_INVALID`。
- 有效 scope 但创建引用超范围：`403 DATA_SCOPE_FORBIDDEN`。
- 详情或动作目标不在有效范围：`404 RESOURCE_NOT_FOUND`。

### 7.2 ScopeType

| ScopeType | 冻结语义 |
| --- | --- |
| `all` | 当前租户全部 F2 批次、有效供应商和符合条件的 SC-F1 采购单 |
| `own` | 仅 `PackingBatch.created_by=current_user` 的既有批次；不能单独授权创建新批次 |
| `custom` | 使用本节定义的严格配置 |
| `department` | SC-F2 不支持，返回 `DATA_SCOPE_INVALID` |

superuser 视为当前租户 `all`，仍不得跨租户或跨 API 通道。

### 7.3 CUSTOM 配置

唯一允许的键：

```json
{
  "supplier_ids": [1],
  "packing_batch_ids": [10],
  "supply_purchase_order_ids": [100]
}
```

规则：

1. 配置必须是 JSON object，至少包含一个允许键。
2. 禁止未知键。
3. 每个数组为 1 至 500 个互不重复的正整数；空数组、字符串数字、布尔值、null、重复值或超限均非法。
4. 同一个 CUSTOM scope 内，出现的多个维度使用交集：
   - `supplier_ids`：批次供应商必须命中；
   - `packing_batch_ids`：批次 ID 必须命中；
   - `supply_purchase_order_ids`：既有批次的全部历史 `PackingBatchOrder.order_id` 都必须包含在允许集合中，不按 `active_guard` 过滤。
5. 用户从多个授予同一 permission 的角色获得多个有效 scope 时，各 scope 之间使用并集。
6. 任何 invalid scope 使请求安全失败，不得跳过非法 scope 后继续使用其他宽 scope。

### 7.4 创建批次

`supply.packing.create` 必须按自身 permission-specific scope 重新校验：

- `all`：允许当前租户范围。
- `own`：不能授权创建。
- `custom`：必须同时提供非空 `supplier_ids` 和 `supply_purchase_order_ids`；目标供应商必须命中，所有 `order_ids` 必须命中。
- `packing_batch_ids` 对新建没有授权作用。

即使调用者对既有批次拥有 view/manage，也不能替代 create permission 的供应商和采购单范围。

### 7.5 既有资源与跨引用

- 列表先 Tenant 过滤，再应用当前 permission scope，再应用查询条件。
- 详情、箱动作、完成、取消、变更提交和标签必须使用各自 exact permission 重新过滤批次。
- 变更批准/驳回先按 `supply.packing.change.review` scope 过滤关联批次，再读取变更请求。
- `box_id` 必须属于 URL 中的批次；不匹配统一 404。
- 创建和变更拟议布局引用的采购单行必须属于批次活动订单，服务端不得信任快照字段。
- 既有批次的订单 DataScope 授权始终读取全部历史 `PackingBatchOrder.order_id`，覆盖
  `draft`、`in_progress`、`completed` 和 `cancelled`；取消后不得因活动关联集合为空而自动通过。
- `active_guard=TRUE` 只用于创建资格、布局业务校验以及判断采购单是否仍被活动批次占用，不用于既有批次的 DataScope 授权。

### 7.6 全局当前标准端点

`GET standards/current/` 返回全局 `PackingStandardVersion`，不存在 Tenant、supplier、batch 或 order
资源维度，因此采用合法 scope 门禁，不进行资源 ID 交集：

1. 内部端固定要求活动 internal 用户、非 miniapp 通道、exact
   `supply.packing.view`，以及至少一个授予该 permission 的合法 scope。
2. `all`、`own` 和合法 `custom` 只表示合法 scope 门禁已满足；不得要求 CUSTOM
   命中任意 supplier、batch 或 order，也不得因 OWN 当前没有批次而拒绝。
3. 有 permission 但无 scope 返回 `403 DATA_SCOPE_MISSING`；任一关联 scope
   非法（包括 `department`）返回 `403 DATA_SCOPE_INVALID`，即使同时存在合法 scope 也不得跳过。
4. 供应商 Web 和小程序要求活动 external 用户、正确 channel、有效
   `ExternalUserProfile` 供应商绑定及有效供应商主档；不要求 `can_self_pack`。
5. 响应仍只允许第 9.4 节登记的四个 boolean 规则键。

## 8. 请求 DTO

### 8.1 创建批次

```json
{
  "order_ids": [100, 101],
  "note": ""
}
```

`order_ids` 按升序参与请求哈希；重复 ID 返回 `400 VALIDATION_ERROR`，不静默合并。

### 8.2 新增或替换箱

```json
{
  "expected_version": 1,
  "weight": "12.500",
  "volume": "0.125000",
  "note": "",
  "items": [
    {
      "order_line_id": 1000,
      "quantity": 10
    }
  ]
}
```

同一请求中重复 `order_line_id` 返回 `400 VALIDATION_ERROR`，不由 API
静默合并。服务层仍负责最终聚合和超装校验。

### 8.3 移除箱、完成和取消

```json
{
  "expected_version": 2
}
```

移除箱只使用
`POST batches/{id}/boxes/{box_id}/actions/remove/`，由严格 JSON body 承载
`expected_version`。旧 `DELETE batches/{id}/boxes/{box_id}/` 不注册、不兼容、也不保留别名。
内部端固定使用 `supply.packing.manage`；供应商 Web 和小程序固定要求
`can_self_pack=true`。三通道均要求 `Idempotency-Key`，成功返回 200 和冻结的
`PackingBatchDetail`。

### 8.4 提交完成后变更

```json
{
  "expected_version": 3,
  "reason": "Correct carton split",
  "proposed_boxes": [
    {
      "weight": "6.000",
      "volume": null,
      "note": "",
      "items": [
        {
          "order_line_id": 1000,
          "quantity": 10
        }
      ]
    }
  ]
}
```

### 8.5 批准和驳回

批准：

```json
{
  "review_note": ""
}
```

驳回：

```json
{
  "review_note": "Reason for rejection"
}
```

### 8.6 生成标签

```json
{
  "expected_version": 3
}
```

箱标签的 `box_id` 来自路径。只允许 PDF，不接受模板 URL、打印机、外部文件路径或客户端提供的二维码内容。

## 9. 响应 DTO

### 9.1 `PackingBatchSummary`

- `id`
- `batch_no`
- `supplier: {id, code, name}`
- `status`
- `version`
- `standard: {code, version, title}`
- `order_count`
- `box_count`
- `packed_quantity`
- `total_quantity`
- `completed_at`
- `created_at`
- `updated_at`

### 9.2 `PackingBatchDetail`

Summary 全部字段，加：

- `note`
- `orders[]: {id, order_no}`
- `boxes[]: PackingBox`
- `remaining[]: {order_line_id, order_no, sku_code, product_name, ordered_quantity, packed_quantity, remaining_quantity}`
- 内部 DTO 固定增加 `created_by: {id, display_name}`

`PackingBox`：

- `id`
- `box_no`
- `sequence`
- `weight`
- `volume`
- `note`
- `items[]`
- `created_at`
- `updated_at`

箱明细：

- `order_line_id`
- `order_no`
- `sku_code`
- `product_name`
- `quantity`

供应商和小程序 DTO 不包含：

- `created_by/reviewed_by/submitted_by` 用户 ID；
- 内部事件和操作日志；
- 来源系统字段；
- `idempotency_key/request_hash/response_snapshot`；
- 租户 ID；
- 其他采购财务字段。

本阶段不在批次详情中返回 `PackingEvent`。审计事件没有公共 F2 API，
后续如需审计查询必须独立冻结分页、字段最小化和审计权限。

### 9.3 `PackingChangeRequestDetail`

公共字段：

- `id`
- `batch_id`
- `status`
- `expected_version`
- `reason`
- `proposed_boxes`
- `review_note`
- `applied_version`
- `reviewed_at`
- `created_at`

内部 DTO 固定增加
`submitted_by/reviewed_by: {id, display_name}|null`。供应商和小程序 DTO
不包含这两个字段，也不得返回内部审核人 ID。

### 9.4 `PackingStandard`

- `code`
- `version`
- `title`
- `rules`

`rules` 只允许：

- `empty_box_forbidden: boolean`
- `exact_completion_required: boolean`
- `mixed_box_label_items_required: boolean`
- `single_order_single_sku_recommended: boolean`

不得返回数据库内部字段或任意未审核 JSON。

### 9.5 PDF

成功响应：

- `Content-Type: application/pdf`
- `Content-Disposition: attachment; filename="<sanitized>.pdf"`
- `ETag`
- `X-Packing-Batch-Version`
- `Cache-Control: private, no-store`

PDF 和二维码不得包含用户 Token、内部自增查询 URL、数据库凭据、来源哈希或匿名越权 URL。

### 9.6 标签生成与确定性

标签生成必须同时满足：

1. 批次状态仅允许 `in_progress` 或 `completed`，且至少存在一个含明细的非空箱。
   `draft`、`cancelled` 或没有非空箱统一返回 `409 STATE_CONFLICT`。
2. 批次标签固定为每个非空箱一页，按 `PackingBox.sequence asc`；箱标签固定为一页。
   请求空箱返回 `409 STATE_CONFLICT`。
3. 每个箱的二维码为 UTF-8、无空白、键按下列顺序固定的非 URL 规范 JSON：

```json
{"schema_version":"sc-f2-packing-qr-v1","batch_no":"PB-20260728-0001","box_no":"BOX-001","packing_version":3,"standard_code":"PACKING","standard_version":"1.0","content_digest":"<sha256-lower-hex>"}
```

`content_digest` 是该箱冻结标签内容（箱号、sequence、weight、volume，以及按
`order_no, sku_code, product_name` 排序并已聚合的明细）的规范 JSON UTF-8 字节 SHA-256；
摘要输入只使用标签快照中明确列出的字段，不读取或隐含数据库主键。
二维码禁止 tenant ID、数据库主键、Token、内部或外部 URL、来源字段、用户信息、
openid/subject/session_key 及请求/幂等哈希。

4. PDF 只能读取第 10.3 节首次事务内保存的标签快照。页面、箱和明细排序固定；
   字体包、布局、渲染器及其版本固定。PDF CreationDate、ModDate 和业务展示时间均使用
   快照 `event_time`；禁止当前时间、随机 ID、随机文档标识、主机路径或不稳定生成器元数据。
   PDF document ID 固定由标签快照规范 JSON 的 SHA-256 派生。
5. `ETag` 是最终 PDF 字节 SHA-256 的强 ETag：`"<sha256-lower-hex>"`。
   同 key 重放必须返回逐字节相同的 PDF、相同 ETag、文件名、批次版本和 HTTP 状态。
6. 后续布局或渲染器升级必须保留按 `layout_version`、`renderer_version` 和
   `font_bundle_digest` 重建历史 PDF 的兼容能力；不同 key 可按当时活动布局生成新标签版本，
   但不得改变旧 key 的重放结果。

## 10. 幂等与冻结响应

### 10.1 唯一持久化模型

所有 `POST`、`PUT` 和 PDF action 只允许使用
`PackingApiIdempotencyRecord` 持久化 HTTP 冻结结果；不得由各 view 自选
`PackingEvent.response_snapshot`、缓存或活动对象重序列化作为 API 幂等来源。

记录固定包含：

- `tenant_id`；
- 非空 `scope_key`；
- `idempotency_key`；
- `actor_id`；
- `channel`：`internal|supplier_web|miniapp`；
- `action`；
- 非空 `resource_key`；
- `request_hash`；
- `http_status`；
- `response_kind`：`json|label`；
- `response_body`：JSON 成功响应的完整冻结业务信封，label 时为 null；
- `label_snapshot`：label 时使用第 10.3 节 schema，JSON 时为 null；
- `created_at`。

`scope_key` 是服务端构造的非空规范字符串，不读取客户端输入：

- 创建批次：`packing:batches:collection`；
- 批次动作：`packing:batch:<batch_id>`；
- 箱动作：`packing:box:<box_id>`；
- 变更申请集合：`packing:batch:<batch_id>:change-requests`；
- 变更申请动作：`packing:change-request:<change_request_id>`。

MySQL 8 必须建立 `(tenant_id, scope_key, idempotency_key)` 唯一约束。唯一键不得包含
nullable 资源列，也不得把 actor、channel、action 或 request hash 放入唯一约束来规避冲突；
这些字段在命中唯一记录后逐项比较，不一致返回 `409 IDEMPOTENCY_CONFLICT`。

### 10.2 原子边界

API 最外层 `transaction.atomic()` 必须同时覆盖：幂等记录抢占/加锁、领域服务、
业务模型写入、`PackingEvent`、`OperationLog`、响应 DTO 或标签快照序列化，以及
`PackingApiIdempotencyRecord` 保存。现有领域服务的内层事务只能加入该外层事务，
不得先提交领域事务再保存 HTTP 快照。

在领域写入完成后、API 幂等记录保存前发生的任何异常必须回滚全部业务、事件和日志写入。
MySQL 同 tenant、scope 和 key 的并发首次请求只能提交一条业务结果、一组对应事件/日志和
一条 API 幂等记录；竞争方加锁后按首次记录重放，不得再次执行领域动作。

### 10.3 标签快照

`generate_label` 的 `PackingEvent` 与 `PackingApiIdempotencyRecord.label_snapshot`
保存同一份规范 JSON（事件可按既有字段封装，但业务内容必须完全一致）：

```json
{
  "schema_version": "sc-f2-label-snapshot-v1",
  "label_scope": "batch",
  "event_time": "2026-07-28T08:00:00Z",
  "batch_no": "PB-20260728-0001",
  "packing_version": 3,
  "standard": {"code": "PACKING", "version": "1.0", "title": "Packing Standard"},
  "layout_version": "packing-label-v1",
  "renderer_version": "sc-f2-pdf-v1",
  "font_bundle_digest": "<sha256-lower-hex>",
  "filename": "PB-20260728-0001-v3.pdf",
  "boxes": [
    {
      "box_no": "BOX-001",
      "sequence": 1,
      "weight": "12.500",
      "volume": "0.125000",
      "items": [
        {"order_no": "PO-001", "sku_code": "SKU-001", "product_name": "Item", "quantity": 10}
      ],
      "content_digest": "<sha256-lower-hex>",
      "qr_payload": {"schema_version": "sc-f2-packing-qr-v1", "batch_no": "PB-20260728-0001", "box_no": "BOX-001", "packing_version": 3, "standard_code": "PACKING", "standard_version": "1.0", "content_digest": "<sha256-lower-hex>"}
    }
  ]
}
```

`label_scope` 仅为 `batch|box`；箱标签的 `boxes` 恰好一项，批次标签按
`sequence asc` 包含全部非空箱。快照不得保存 PDF 二进制、tenant ID、数据库主键、Token、
URL、来源字段、用户信息或 Idempotency-Key。规范 JSON 使用 UTF-8、键顺序和数组顺序固定、
Decimal 使用第 3.2 节字符串格式。

### 10.4 重放

1. 每次重放先重新执行当前身份、通道、permission、DataScope、供应商绑定和能力校验。
2. 同 actor、channel、action、资源、key 和规范化负载返回首次保存的 HTTP 状态和冻结业务响应。
3. JSON 响应体不得因活动对象已删除、版本变化或后续批准变更而改变。
4. 响应体不包含 `replayed` 字段；可使用 `Idempotency-Replayed: true|false` 响应头。
5. 同 key 的 actor、channel、action、资源或负载不同，返回 `409 IDEMPOTENCY_CONFLICT`。
6. MySQL 1205/1213 返回 `409 STATE_CONFLICT`，客户端只可使用相同 key 重试。
7. 权限或供应商能力已撤销时拒绝重放，不得因历史成功泄露冻结响应。

PDF 重放只根据首次保存的标签快照和其中固定版本的渲染资产生成；不得读取批次后续布局或当前活动布局。

## 11. 错误合同

| HTTP | code | 固定场景 |
| ---: | --- | --- |
| 400 | `VALIDATION_ERROR` | JSON、查询、分页、未知/禁止字段、字段类型/长度/精度、重复项、Content-Type 或 Idempotency-Key 格式错误 |
| 401 | `AUTH_REQUIRED` | Token 缺失、过期、用户停用 |
| 403 | `PERMISSION_DENIED` | 用户类型、通道或 exact permission 不匹配 |
| 403 | `DATA_SCOPE_MISSING` | permission 存在但没有 scope |
| 403 | `DATA_SCOPE_INVALID` | scope 类型、键、数组或值非法 |
| 403 | `DATA_SCOPE_FORBIDDEN` | 创建请求引用超出有效 scope |
| 404 | `RESOURCE_NOT_FOUND` | 对象不存在或不在当前 Tenant/scope/供应商绑定范围 |
| 409 | `IDEMPOTENCY_CONFLICT` | 同 key 的身份、通道、动作、资源或负载不同 |
| 409 | `VERSION_CONFLICT` | `expected_version` 过期 |
| 409 | `STATE_CONFLICT` | 非法状态、超装、活动批次冲突、MySQL 1205/1213 |
| 422 | `BUSINESS_RULE_VIOLATION` | 空箱、未精确装完、非法订单行或变更布局不满足领域规则 |

权限检查必须先于对象存在性查询。跨租户、跨 scope 和跨供应商详情统一 404，不得通过 403/404 差异枚举对象。

## 12. 审计

- 每次成功领域写动作在第 10.2 节同一最外层事务中写业务数据、`PackingEvent`、
  `OperationLog` 和 `PackingApiIdempotencyRecord`。
- 幂等重放不新增第二条业务事件或操作日志。
- 变更批准同时写批准事件和 apply 事件，且与布局替换同事务。
- 标签生成写 `generate_label` 事件，保存第 10.3 节完整冻结标签快照，不保存 PDF 二进制。
- 日志不记录 Token、Idempotency-Key 原值、请求哈希、完整来源负载或小程序身份 subject。
- API 层记录的 IP/User-Agent 必须截断并视为非可信诊断字段，不能参与授权。

## 13. F2/F3 边界

- 完成装箱后采购单仍为 `production_completed`。
- F2 API 不提供 `ready_to_ship`、装柜、发运或物流动作。
- F3 未来只能读取已完成批次和明确版本，不得通过 F2 API 隐式推进物流。
- F2 完成后的批准变更产生新版本；F3 若已消费旧版本，必须使用独立异常/重审契约。

## 14. 实现门禁

在本契约通过独立审核前：

- 不注册任何 F2 URL；
- 不新增 F2 serializer/view；
- 不修改网页端或小程序请求层；
- 不生成真实 PDF；
- 不连接真实微信或线上数据库。

审核通过后的实现至少必须覆盖：

1. 三通道正负权限矩阵；
2. permission-specific ALL/OWN/CUSTOM/非法 scope；
3. 创建时供应商与全部采购单的交集授权，以及四种批次状态下全部历史订单授权；
4. 列表过滤和详情 404 防枚举；
5. 供应商绑定、能力开关和跨供应商拒绝；
6. 首次执行与重放的状态码和响应体一致，API 快照与领域写入同事务；
7. 对象删除、版本变化、权限撤销、布局升级后的重放；
8. 400/401/403/404/409/422 精确 code；
9. MySQL 同键并发创建、箱动作、完成、审批和标签重放，以及快照保存前失败全量回滚；
10. 未知/禁止字段和敏感字段不出响应；
11. PDF 状态门禁、一箱一页、确定性字节/ETag、二维码 schema 和敏感字段负向检查；
12. `standards/current/` 的 ALL/OWN/CUSTOM/缺失/非法 scope 和三通道矩阵；
13. 三通道 remove action、缺失/过期版本及同键重放，且旧 DELETE 路由不可达；
14. SC-F1 状态不被推进及 F3 功能不可达。
