# PR-A3 销售与库存离线导入合同

合同版本：`pr-a3-normalized-v1`

状态：development / pending-platform-samples

适用范围：Shopee、TikTok Shop 的 normalized synthetic/offline 数据。

## 1. 安全与能力边界

- 只接受 `source_mode=synthetic_contract`；默认开关 `PR_A3_SYNTHETIC_IMPORT_ENABLED=false`。
- 不解析或保存平台原始响应，不调用真实平台，不包含 webhook、定时任务、历史回补或平台写操作。
- 真实 adapter 在获得经批准的响应样本前固定返回 `PLATFORM_RESPONSE_CONTRACT_PENDING`。
- tenant 来自当前登录用户；platform、店铺和平台主体来自已有 active `MarketplaceStoreMapping`，请求不得提交替换值。
- 禁止在任意层级提交 access/refresh token、authorization code、App/API Secret、Cookie、Session、Bearer 或私钥。
- Shopee 与 TikTok Shop 均保持 `pending/mock`；Production synchronization 保持 OFF。

## 2. API

| Method | Path | exact permission | 用途 |
|---|---|---|---|
| POST | `/api/internal/marketplace-imports/imports/` | `integrations.store.sync` | 执行 normalized synthetic import |
| GET | `/api/internal/marketplace-imports/batches/` | `integrations.store.view` | 查询授权范围内批次 |
| POST | `/api/internal/marketplace-imports/batches/{id}/retry/` | `integrations.store.retry` | 以完全相同合同重试 failed 批次 |
| GET | `/api/internal/marketplace-imports/orders/` | `integrations.store.view` | 查询 normalized 订单及退款 |
| GET | `/api/internal/marketplace-imports/inventory/` | `integrations.store.view` | 查询 normalized 库存快照 |

响应统一使用 `success/code/message/data`。认证、权限、隐藏资源、并发/幂等冲突和合同错误分别使用项目统一的 401、403、404、409、422 边界。不存在普通 PATCH 或 DELETE 导入证据接口。

## 3. 顶层请求

```json
{
  "store_mapping_id": 101,
  "resource_type": "orders",
  "import_mode": "initial",
  "source_mode": "synthetic_contract",
  "idempotency_key": "offline-example-0001",
  "cursor_before": "",
  "cursor_after": "normalized-cursor-1",
  "watermark_after": "2026-08-01T00:00:00Z",
  "contract_version": "pr-a3-normalized-v1",
  "orders": []
}
```

`resource_type=orders` 只允许 `orders`；`resource_type=inventory` 只允许 `inventory`。集合不能为空，单批最多 100 条；单订单最多 100 行。未知字段拒绝。`idempotency_key` 长度 8–160，只保存 SHA-256，不保存原值。

## 4. normalized orders/refunds

订单字段：`platform_order_id`、`status`、`currency`、`total_amount`、`ordered_at`、`platform_updated_at`、`cancelled_at`、`line_items`、`refunds`。

订单状态：`unpaid`、`ready_to_ship`、`shipped`、`completed`、`cancelled`。取消订单必须提供 `cancelled_at`，非取消订单不得提供。行字段为 `platform_line_id`、`platform_variant_id`、`platform_sku`、`quantity`、`unit_price`、`line_amount`。

退款字段：`platform_refund_id`、`status`、`currency`、`amount`、`reason_code`、`platform_updated_at`。状态为 `requested`、`approved`、`rejected`、`completed`、`cancelled`。

本合同仅接受 `PHP`、`THB`、`MYR`；金额为最多 18 位、4 位小数且非负。数量为正整数。store 内 `platform_order_id` 唯一，order 内 `platform_refund_id` 唯一。

## 5. normalized inventory

字段：`platform_variant_id`、`platform_sku`、`on_hand`、`reserved`、`available`、`incoming`、`observed_at`。四个数量必须是 0–2,147,483,647 的整数。

存在当前 store/variant 的 confirmed product mapping 时写入引用并标记 `mapped`；不存在时保留平台 variant 并标记 `unmapped`。不得自动关联其他 tenant/store 的 SKU。

## 6. 幂等、事件与游标

- 相同 key 与相同 normalized payload 返回原 completed batch，不推进 cursor version。
- 相同 key 与不同 payload 返回 409。
- 时间更旧的 order/refund/inventory 事件跳过；相同时间且相同 fingerprint 跳过；相同时间但不同 fingerprint 返回 409。
- completed/cancelled order 以及 rejected/completed/cancelled refund 不得被更新事件恢复或覆盖。
- initial 必须从空 cursor 开始；incremental 的 `cursor_before` 必须精确匹配当前 cursor。
- watermark 不得倒退；整个批次在一个事务中成功后才更新 cursor、watermark 和 version。
- 任一记录失败会回滚该批次的业务记录和游标；failed batch 只记录受控错误码。

## 7. 后续 adapter 插入点

`apps.marketplace_imports.adapters.get_real_response_adapter(platform)` 是唯一预留入口。目前不导入 HTTP 客户端，不执行网络重试；只冻结未来重试上限：最多 3 次、单次/Retry-After 最多 8 秒、总等待最多 15 秒，候选状态仅 429/500/502/503/504。真实字段映射必须等待用户提供并批准的脱敏响应样本后另行复审。
