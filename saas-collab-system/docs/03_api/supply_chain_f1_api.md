# SC-F1 供应链采购协同 API 合同

> 状态：本机开发合同 `v1`
> 日期：2026-07-25
> 目标运行时：Django/DRF + MySQL 8
> 客户端：Vue 3 内部管理端、供应商网页端、现有原生微信小程序
> 边界：仅限本地开发和虚构/批准的脱敏数据

## 1. 通用约定

- 客户端只访问 Django API，不直连 MySQL 或 Supabase。
- 所有响应使用统一信封：

```json
{
  "success": true,
  "code": "OK",
  "message": "success",
  "data": {}
}
```

- 新建采购单和所有状态动作必须提供 `Idempotency-Key` 请求头。
- 小程序写请求由现有请求底座自动生成幂等键。
- 创建接口按租户保存幂等键和请求哈希；相同键和相同负载返回已有采购单，相同键和不同负载返回 `409`。
- 状态动作按采购单保存幂等事件；重复请求不会重复推进状态或写入进度。
- 服务端按 UTC 保存时间。
- 金额使用 Decimal；本合同中的 `unit_price` 精度为四位小数。

## 2. 通道隔离

| 通道 | 路由 | 身份要求 | 数据范围 |
|---|---|---|---|
| 内部管理端 | `/api/internal/purchasing/supply-orders/` | 内部 JWT，拒绝小程序通道 Token | 租户 + Permission + DataScope |
| 供应商网页端 | `/api/external/supplier/purchase-orders/` | 外部供应商 JWT，拒绝小程序通道 Token | 当前租户 + 当前绑定供应商 |
| 原生小程序 | `/api/miniapp/supply-chain/orders/` | 小程序专用 JWT Channel | 当前租户 + 当前绑定供应商 |

小程序 Token 不能调用内部端或供应商网页端的 SC-F1 API；普通 JWT 不能调用小程序 SC-F1 API。

## 3. 内部端权限

| 权限代码 | 用途 |
|---|---|
| `supply.purchase_order.view` | 查询采购单头、明细、进度和事件 |
| `supply.purchase_order.create` | 新建采购单头和明细 |
| `supply.purchase_order.accept` | 接单 |
| `supply.production.start` | 开始生产 |
| `supply.production.update` | 更新生产进度 |
| `supply.production.complete` | 标记生产完成 |

DataScope 规则：

- `all`：当前租户全部 SC-F1 采购单。
- `own`：当前用户创建的采购单。
- `custom.supplier_ids`：指定供应商。
- `custom.supply_purchase_order_ids`：指定采购单。

## 4. 内部端接口

### 4.1 查询采购单

```http
GET /api/internal/purchasing/supply-orders/
```

查询参数：

- `search`：采购单号、供应商代码/名称或 SKU。
- `status`：状态。
- `supplier_id`：供应商主档 ID。
- `page`、`page_size`：分页。

### 4.2 新建采购单

```http
POST /api/internal/purchasing/supply-orders/
Idempotency-Key: sc-f1-create-unique-key
Content-Type: application/json
```

```json
{
  "order_no": "SC-LOCAL-001",
  "supplier_id": 1,
  "order_date": "2026-07-25",
  "expected_delivery_date": "2026-08-25",
  "currency": "CNY",
  "notes": "本地开发数据",
  "source_system": "supabase-legacy",
  "source_table": "purchase_orders",
  "source_record_id": "source-uuid",
  "source_payload_hash": "64位十六进制哈希",
  "lines": [
    {
      "line_no": 1,
      "sku_id": 1,
      "quantity": 100,
      "unit_price": "12.5000",
      "expected_delivery_date": "2026-08-25",
      "source_record_id": "source-line-uuid"
    }
  ]
}
```

规则：

- 供应商和 SKU 必须属于当前租户。
- 采购单至少有一行，行号必须唯一，数量大于零。
- 创建后状态固定为 `pending`。
- 客户端不能在创建负载中指定状态、完成数量或版本。
- 源系统、源表和源 ID 必须同时提供或同时省略。

### 4.3 查询详情

```http
GET /api/internal/purchasing/supply-orders/{id}/
```

内部详情包含：

- 单头、供应商、状态和时间。
- 采购明细及单价。
- 生产进度记录。
- 状态事件。
- 源系统追踪字段。

创建幂等键和创建请求哈希不在 API 响应中返回。

### 4.4 内部状态动作

```http
POST /api/internal/purchasing/supply-orders/{id}/actions/accept/
POST /api/internal/purchasing/supply-orders/{id}/actions/start-production/
POST /api/internal/purchasing/supply-orders/{id}/actions/update-progress/
POST /api/internal/purchasing/supply-orders/{id}/actions/complete-production/
Idempotency-Key: sc-f1-action-unique-key
```

更新进度负载：

```json
{
  "completed_quantity": 40,
  "note": "本地进度说明"
}
```

动作响应：

```json
{
  "replayed": false,
  "order": {}
}
```

## 5. 供应商网页端接口

```http
GET  /api/external/supplier/purchase-orders/
GET  /api/external/supplier/purchase-orders/{id}/
POST /api/external/supplier/purchase-orders/{id}/actions/{action}/
```

供应商用户不需要内部 Permission，但必须：

- 是当前租户的活动外部用户。
- `ExternalUserProfile.supplier_id` 已绑定当前租户的 `SupplierMaster`。
- 采购单的 `supplier_id` 与用户绑定供应商一致。

越权详情统一返回 `404`，避免泄露对象是否存在。

供应商响应不包含：

- `unit_price`
- `currency`
- 源系统 ID/哈希
- 创建人
- 内部状态事件
- 进度请求 ID
- 进度操作者 ID

## 6. 小程序接口

```http
GET  /api/miniapp/supply-chain/orders/
GET  /api/miniapp/supply-chain/orders/{id}/
POST /api/miniapp/supply-chain/orders/{id}/actions/{action}/
```

小程序复用供应商安全序列化模型，不包含内部或财务字段。

允许动作：

- `accept`
- `start-production`
- `update-progress`
- `complete-production`

本轮不提供：

- 装箱
- 标签
- 货柜/装柜
- 发运
- 报关
- 成本/结算
- 文件上传
- 真实微信通知

## 7. 状态机

```text
pending
  └─ accept
      accepted
        └─ start-production
            in_production
              ├─ update-progress（状态不变，可重复）
              └─ complete-production
                  production_completed
```

规则：

- 进度数量只能单调递增。
- 进度不能超过采购单明细总数量。
- 只有完成数量等于总数量时才能完成生产。
- 采购单接单后，明细行不能再修改或删除。
- 状态字段不能通过普通模型保存、QuerySet `update` 或 PATCH 绕过动作服务。
- 每次成功动作在同一事务中写入采购单事件和 `OperationLog`。

源系统的 `ready_to_ship`、`shipping_review_pending`、`shipping`、`shipped` 值保留在模型枚举中，但不在 SC-F1 开放转换；它们由后续物流波次接管。

## 8. 主要错误

| HTTP | 场景 |
|---|---|
| `400` | 字段、租户主档或幂等键格式错误 |
| `401` | 未认证或 Token 无效 |
| `403` | 权限、DataScope、用户类型或 API 通道不匹配 |
| `404` | 对象不存在或不在授权租户/供应商范围 |
| `409` | 状态冲突、进度倒退、超量或幂等键负载冲突 |
| `422` | 模型业务规则不满足 |

## 9. 本机开发数据

在显式本地数据库中执行：

```powershell
python manage.py seed_supply_chain_local
```

安全限制：

- 仅在 `DEBUG=True` 且数据库名称包含 `local`、`dev` 或 `test` 时执行。
- 数据生成幂等。
- 只创建虚构主档和采购单。
- 两个示例用户均使用不可用密码。
- 不创建真实微信身份，不保存任何真实凭据。
