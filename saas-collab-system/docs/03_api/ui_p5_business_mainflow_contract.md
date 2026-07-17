# UI-P5 业务主链路接口与权限合同

## 1. 范围

UI-P5 接入商品市调、商品主数据、采购订单和供应商任务/出货主链路。库存继续使用阶段3只读指标、预警与补货建议；刊登、价格和销售订单因后端业务资源尚未实现，保持 `pending/mock`。

## 2. 响应合同

成功响应统一使用 `success/code/message/data`。列表 `data` 必须包含 `count/next/previous/results`。错误响应使用统一异常处理，覆盖 400、401、403、404、409 和 422。

## 3. 已接入接口

| 模块 | 方法与路径 | 权限/身份 | data_scope | 状态 |
|---|---|---|---|---|
| 新品市调 | `GET /api/internal/products/research/` | `products.research.view` | `ALL/OWN/research_ids/platforms` | connected |
| 新品市调详情 | `GET /api/internal/products/research/{id}/` | `products.research.view` | 同列表 | connected |
| 新品市调维护 | `POST/PATCH` 同资源路径 | `products.research.manage` | 创建需 `ALL/OWN`，更新按范围；`approval_status` 只读 | connected |
| SPU/SKU | `GET /api/internal/products/spus/`、`skus/` | `products.master.view` | `ALL/spu_ids/sku_ids` | connected |
| SPU/SKU维护 | `POST/PATCH` 同资源路径 | `products.master.manage` | 创建需 `ALL`，更新按范围；SPU 的 `lifecycle_status/sales_status` 只读 | connected |
| 编码冻结 | `POST /api/internal/products/spus/{id}/freeze-code/` | `products.master.freeze` | `ALL/spu_ids` | connected |
| 采购订单 | `GET /api/internal/purchasing/orders/`及详情 | `purchasing.orders.view` | `ALL/OWN/purchase_order_ids/supplier_ids` | connected |
| 采购订单维护 | `POST/PATCH` 同资源路径 | `purchasing.orders.manage` | 创建需 `ALL/OWN`，更新按范围；`status/approval_status` 只读 | connected |
| 供应商任务 | `GET /api/external/supplier/tasks/`及详情 | external 会话 | 强制 `tenant_id + supplier_id` | connected |
| 供应商反馈 | `PATCH /api/external/supplier/tasks/{id}/feedback/` | external 会话 | 强制 `tenant_id + supplier_id` | connected |
| 供应商出货 | `GET/POST /api/external/supplier/shipments/`及详情 | external 会话 | 强制 `tenant_id + supplier_id` | connected |

通用 POST 会忽略客户端提交的受控状态并采用模型安全默认值；通用 PATCH 显式提交受控状态时返回 400。审批、采购确认、生命周期和销售状态变化必须进入独立动作权限或工作流，不得通过资料维护接口完成。

所有列表允许任意有效正整数页码，`page_size` 最大为 100。供应商提交 `status=completed` 时，`completed_quantity` 必须等于 `production_quantity`。

## 4. 待接入合同

- `listings.sites`、`listings.templates`、`pricing.prices`：`pending/mock`，API 模式不发送不存在的网络请求。
- 销售订单：无后端资源和页面合同，保持 `pending`。
- 库存：仅允许查看指标、预警和补货建议，不提供库存修改动作。

## 5. 高风险边界

UI-P5 不自动创建正式采购订单，不自动通知真实供应商，不自动刊登、改价、清仓或修改库存，不触发真实 RPA。编码冻结仅冻结编码字段；供应商反馈仅更新自身任务允许字段。商品审批、采购确认、生命周期和销售状态不得通过通用 PATCH 修改。所有真实平台和高风险动作仍需专项评审与人工确认。
