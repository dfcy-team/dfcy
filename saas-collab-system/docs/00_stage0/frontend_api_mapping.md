# 前后端接口对接清单

## 说明

- 本清单用于阶段 0 前端页面与后端 API 的后续对接跟踪。
- 当前不表示后端接口已经完成。
- 当前状态仅使用 `mock` 或 `pending`。
- 后续后端负责人暂以 `待定` 标注。

| 页面名称 | 页面路径 | 需要的API | 请求方式 | 请求参数 | 返回字段 | Mock文件位置 | 后续后端负责人 | 当前状态 |
|---|---|---|---|---|---|---|---|---|
| 登录页 | `/login` | `/api/internal/auth/login/`、`/api/internal/auth/me/` | `POST`、`GET` | `username`、`password`；无 | `user_id`、`username`、`user_type`、`tenant_id`、`roles`、`permissions` | `frontend/src/mock/currentUser.js` | 待定 | mock |
| 首页 | `/dashboard` | `/api/internal/dashboard/` | `GET` | 时间范围、租户上下文 | `summary`、`todo_count`、`warning_count`、`recent_tasks` | 页面内 mock：`frontend/src/views/dashboard/Index.vue` | 待定 | pending |
| 新品市调列表 | `/products/research` | `/api/internal/products/research/` | `GET` | `keyword`、`platform`、`status`、`page`、`page_size` | `research_no`、`product_name`、`platform`、`competitor_url`、`estimated_sales`、`estimated_gross_profit`、`status`、`creator`、`created_at` | 页面内 mock：`frontend/src/views/products/ResearchList.vue` | 待定 | mock |
| 新品市调详情 | `/products/research/detail` | `/api/internal/products/research/{id}/` | `GET` | `id` | `research_no`、`product_name`、`platform`、`estimated_sales`、`estimated_gross_profit`、`status`、`competitors`、`attachments` | 页面内 mock：`frontend/src/views/products/ResearchDetail.vue` | 待定 | mock |
| 商品主数据列表 | `/products/master` | `/api/internal/products/master/` | `GET` | `keyword`、`sales_status`、`lifecycle_status`、`page`、`page_size` | `product_code`、`spu`、`sku`、`product_name`、`category`、`lifecycle_status`、`sales_status`、`archived` | 页面内 mock：`frontend/src/views/products/ProductMasterList.vue` | 待定 | mock |
| 商品主数据详情 | `/products/master/detail` | `/api/internal/products/master/{id}/` | `GET` | `id` | `product_code`、`spu`、`sku`、`product_name`、`category`、`size`、`material`、`selling_points`、`carton_weight`、`images` | 页面内 mock：`frontend/src/views/products/ProductMasterDetail.vue` | 待定 | mock |
| 采购订单列表 | `/purchasing` | `/api/internal/purchasing/orders/` | `GET` | `po_no`、`supplier_id`、`status`、`approval_status`、`page`、`page_size` | `po_no`、`product_code`、`sku`、`supplier`、`quantity`、`unit_price`、`delivery_date`、`status`、`approval_status` | 页面内 mock：`frontend/src/views/purchasing/PurchaseOrderList.vue` | 待定 | mock |
| 采购订单详情 | `/purchasing/detail` | `/api/internal/purchasing/orders/{id}/` | `GET` | `id` | `po_no`、`supplier`、`delivery_date`、`status`、`payment_method`、`approval_status`、`items` | 页面内 mock：`frontend/src/views/purchasing/PurchaseOrderDetail.vue` | 待定 | mock |
| 供应商任务列表 | `/suppliers/tasks` | `/api/internal/suppliers/tasks/` | `GET` | `task_no`、`supplier_id`、`status`、`overdue`、`page`、`page_size` | `task_no`、`supplier`、`product_code`、`production_quantity`、`completed_quantity`、`expected_ship_date`、`status`、`overdue` | 页面内 mock：`frontend/src/views/suppliers/SupplierTaskList.vue` | 待定 | mock |
| 供应商任务详情 | `/suppliers/tasks/detail` | `/api/internal/suppliers/tasks/{id}/` | `GET` | `id` | `task_no`、`supplier`、`product_code`、`production_quantity`、`completed_quantity`、`expected_ship_date`、`status`、`feedback_rows`、`exception_note` | 页面内 mock：`frontend/src/views/suppliers/SupplierTaskDetail.vue` | 待定 | mock |
| 多国家刊登资料列表 | `/listings/site-profiles` | `/api/internal/listings/site-profiles/` | `GET` | `product_code`、`sku`、`platform`、`country`、`store_id`、`listing_status`、`page`、`page_size` | `product_code`、`sku`、`platform`、`country`、`store`、`title`、`category`、`listing_status`、`price_status` | 页面内 mock：`frontend/src/views/listings/SiteProfileList.vue` | 待定 | mock |
| 多国家刊登资料详情 | `/listings/site-profiles/detail` | `/api/internal/listings/site-profiles/{id}/` | `GET` | `id` | `product_code`、`sku`、`platform`、`country`、`store`、`title`、`keywords`、`description`、`size_rule`、`platform_category`、`images` | 页面内 mock：`frontend/src/views/listings/SiteProfileDetail.vue` | 待定 | mock |
| 价格列表 | `/pricing` | `/api/internal/pricing/prices/` | `GET` | `product_code`、`sku`、`country`、`approval_status`、`page`、`page_size` | `product_code`、`sku`、`country`、`purchase_cost`、`logistics_cost`、`platform_commission`、`exchange_rate`、`suggested_price`、`approved_price`、`page_price` | 页面内 mock：`frontend/src/views/pricing/PriceList.vue` | 待定 | mock |
| RPA任务列表 | `/rpa` | `/api/rpa/tasks/` | `GET` | `task_type`、`status`、`agent`、`business_type`、`page`、`page_size` | `task_no`、`task_type`、`business_type`、`business_id`、`agent`、`status`、`retry_count`、`created_at`、`finished_at` | 页面内 mock：`frontend/src/views/rpa/RPATaskList.vue`；样例：`docs/04_rpa/examples/` | 待定 | mock |
| RPA任务详情 | `/rpa/detail` | `/api/rpa/tasks/{id}/` | `GET` | `id` | `task_no`、`task_type`、`business_type`、`business_id`、`agent`、`status`、`retry_count`、`payload`、`result`、`step_logs`、`screenshots`、`error_reason` | 页面内 mock：`frontend/src/views/rpa/RPATaskDetail.vue`；样例：`docs/04_rpa/examples/` | 待定 | mock |
| API同步任务列表 | `/integrations/tasks` | `/api/internal/integrations/sync-tasks/` | `GET` | `platform`、`store_id`、`sync_type`、`status`、`page`、`page_size` | `task_no`、`platform`、`store`、`sync_type`、`status`、`last_sync_at`、`next_sync_at`、`retry_count` | 页面内 mock：`frontend/src/views/integrations/APISyncTaskList.vue` | 待定 | mock |
| API同步日志列表 | `/integrations/logs` | `/api/internal/integrations/sync-logs/` | `GET` | `log_no`、`platform`、`sync_type`、`status`、`started_at_range`、`page`、`page_size` | `log_no`、`platform`、`sync_type`、`status`、`started_at`、`ended_at`、`error_message`、`quality_check_result` | 页面内 mock：`frontend/src/views/integrations/APISyncLogList.vue` | 待定 | mock |
| 操作日志列表 | `/audit/operation-logs` | `/api/internal/audit/operation-logs/` | `GET` | `operator`、`module`、`action`、`object_type`、`object_id`、`time_range`、`page`、`page_size` | `operator`、`module`、`action`、`object_type`、`object_id`、`ip`、`operated_at` | 页面内 mock：`frontend/src/views/audit/OperationLogList.vue` | 待定 | mock |
