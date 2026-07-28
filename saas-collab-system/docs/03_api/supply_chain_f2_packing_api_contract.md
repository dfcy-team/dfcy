# SC-F2-2 装箱 API、权限与 DataScope 契约

## 1. 文档控制

| 项目 | 冻结值 |
| --- | --- |
| 工作包 | `SC-F2-2` |
| 契约版本 | `v1-local-review` |
| 状态 | `FROZEN_FOR_LOCAL_REVIEW` |
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
| `DELETE batches/{id}/boxes/{box_id}/` | `supply.packing.manage` | 200 | `PackingBatchDetail` |
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
| `DELETE batches/{id}/boxes/{box_id}/` | `can_self_pack=true` | 200 |
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
   - `supply_purchase_order_ids`：批次所有活动关联采购单都必须包含在允许集合中。
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

### 8.3 删除箱、完成和取消

```json
{
  "expected_version": 2
}
```

DELETE 请求也使用该 JSON body。

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

## 10. 幂等与冻结响应

### 10.1 适用范围

`POST/PUT/DELETE` 和 PDF 生成必须持久化：

- tenant；
- actor；
- API channel；
- action 与资源 ID；
- Idempotency-Key；
-规范化请求哈希；
- HTTP 状态；
- 成功响应 DTO 或标签生成快照；
- 创建时间。

### 10.2 重放

1. 每次重放先重新执行当前身份、通道、permission、DataScope、供应商绑定和能力校验。
2. 同 actor、channel、action、资源、key 和规范化负载返回首次保存的 HTTP 状态和冻结业务响应。
3. JSON 响应体不得因活动对象已删除、版本变化或后续批准变更而改变。
4. 响应体不包含 `replayed` 字段；可使用 `Idempotency-Replayed: true|false` 响应头。
5. 同 key 的 actor、channel、action、资源或负载不同，返回 `409 IDEMPOTENCY_CONFLICT`。
6. MySQL 1205/1213 返回 `409 STATE_CONFLICT`，客户端只可使用相同 key 重试。
7. 权限或供应商能力已撤销时拒绝重放，不得因历史成功泄露冻结响应。

PDF 重放根据首次保存的标签快照生成同版本内容；不得读取批次后续活动布局。

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

- 每次成功领域写动作在业务事务中写 `PackingEvent` 和 `OperationLog`。
- 幂等重放不新增第二条业务事件或操作日志。
- 变更批准同时写批准事件和 apply 事件，且与布局替换同事务。
- 标签生成写 `generate_label` 事件，保存批次版本、标签范围和冻结标签快照，不保存 PDF 二进制。
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
3. 创建时供应商与全部采购单的交集授权；
4. 列表过滤和详情 404 防枚举；
5. 供应商绑定、能力开关和跨供应商拒绝；
6. 首次执行与重放的状态码和响应体一致；
7. 对象删除、版本变化、权限撤销后的重放；
8. 400/401/403/404/409/422 精确 code；
9. MySQL 并发创建、箱动作、完成、审批和标签重放；
10. 未知/禁止字段和敏感字段不出响应；
11. PDF 内容、文件名、二维码和缓存头安全；
12. SC-F1 状态不被推进及 F3 功能不可达。
