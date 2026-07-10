# 阶段1前后端接口对接清单

本清单用于阶段1前端页面、Mock fallback 和后端接口边界对齐。未真实联调的接口不得标记为 `connected`。

## 接口路径边界

- 内部后台页面使用 `/api/internal/*`。
- 供应商外部页面使用 `/api/external/*`。
- 财务页面使用 `/api/finance/*`。
- 报表页面使用 `/api/report/*`。
- RPA前端管理后台页面不直接使用 RPA Agent 执行接口。
- 若后端尚未实现 `/api/internal/rpa/tasks/` 管理查询接口，RPA前端管理页面状态标记为 `pending`，并保留 Mock fallback。
- 不允许把 `/admin/` 当业务接口。
- 供应商页面不得访问 `/api/internal/*`。
- RPA管理页面不得访问 `/api/finance/*`。

## 状态标记规则

- `connected`：已真实调用后端且路径存在。
- `mock`：未真实联调但有 Mock fallback。
- `pending`：后端暂未提供接口或管理查询接口。

## 对接清单

| 页面名称 | 页面路径 | 需要的API | 请求方式 | 请求参数 | 返回字段 | Mock文件位置 | 当前状态 |
|---|---|---|---|---|---|---|---|
| 登录页 | `/login` | `/api/internal/auth/login/` | POST | `username`、`password` 占位 | `success`、`code`、`message`、`data.user` | `frontend/src/mock/auth.js` | mock |
| 首页 | `/` | `/api/internal/dashboard/summary/` | GET | `tenant_id`、`date_range` | `summary` | `frontend/src/mock/reports.js` | pending |
| 新品市调列表 | `/products/research` | `/api/internal/products/research/` | GET | `research_no`、`product_name`、`platform`、`approval_status` | `research_no`、`product_name`、`platform`、`competitor_url`、`estimated_sales`、`estimated_gross_margin`、`risk_points`、`approval_status` | `frontend/src/mock/products.js` | mock |
| 新品市调详情 | `/products/research/:id` | `/api/internal/products/research/{id}/` | GET | `id` | `research_no`、`product_name`、`platform`、`competitor_url`、`estimated_sales`、`estimated_gross_margin`、`risk_points`、`approval_status` | `frontend/src/mock/products.js` | mock |
| 商品主数据列表 | `/products/master` | `/api/internal/products/spus/`、`/api/internal/products/skus/` | GET | `spu_code`、`sku_code`、`lifecycle_status`、`sales_status` | `spu_code`、`product_name`、`category`、`lifecycle_status`、`sales_status`、`is_code_frozen`、`sku_code` | `frontend/src/mock/products.js` | mock |
| 商品主数据详情 | `/products/master/:id` | `/api/internal/products/spus/{id}/`、`/api/internal/products/skus/` | GET | `id` | `spu_code`、`product_name`、`category`、`lifecycle_status`、`sales_status`、`is_code_frozen`、`sku_code`、`size`、`material`、`selling_points`、`package_weight`、`package_volume` | `frontend/src/mock/products.js` | mock |
| 商品编码冻结 | `/products/master/:id` | `/api/internal/products/spus/{id}/freeze-code/` | POST | `id` | `spu_code`、`is_code_frozen` | `frontend/src/mock/products.js` | mock |
| 商品状态列表 | `/products/status` | `/api/internal/products/spus/` | GET | `lifecycle_status`、`sales_status` | `spu_code`、`product_name`、`lifecycle_status`、`sales_status`、`is_code_frozen` | `frontend/src/mock/products.js` | mock |
| 商品状态看板 | `/products/status-dashboard` | `/api/internal/products/status-recommendations/` | GET | `date_range`、`source_type` | `status_name`、`count` | `frontend/src/mock/productStatus.js` | pending |
| 商品状态建议列表 | `/products/status-recommendations` | `/api/internal/products/status-recommendations/` | GET | `current_status`、`suggested_status`、`source_type` | `spu_code`、`sku_code`、`current_status`、`suggested_status`、`reason_code`、`confidence`、`source_type` | `frontend/src/mock/productStatus.js` | pending |
| 商品状态建议详情 | `/products/status-recommendations/:id` | `/api/internal/products/status-recommendations/{id}/` | GET | `id` | `reason_detail`、`evidence`、`confirmed_by`、`confirmed_at` | `frontend/src/mock/productStatus.js` | pending |
| 商品状态流转历史 | `/products/status-transitions` | `/api/internal/products/status-transitions/` | GET | `spu_code`、`sku_code`、`source_type` | `from_status`、`to_status`、`source_type`、`reason_code`、`changed_at` | `frontend/src/mock/productStatus.js` | pending |
| 采购订单列表 | `/purchasing/orders` | `/api/internal/purchasing/orders/` | GET | `po_no`、`sku_code`、`supplier_id`、`status`、`approval_status` | `po_no`、`sku_code`、`supplier_id`、`quantity`、`unit_price`、`delivery_date`、`payment_terms`、`status`、`approval_status` | `frontend/src/mock/purchasing.js` | mock |
| 采购订单详情 | `/purchasing/orders/:id` | `/api/internal/purchasing/orders/{id}/` | GET | `id` | `po_no`、`sku_code`、`supplier_id`、`quantity`、`unit_price`、`delivery_date`、`payment_terms`、`status`、`approval_status` | `frontend/src/mock/purchasing.js` | mock |
| 供应商任务列表 | `/suppliers/tasks` | `/api/external/supplier/tasks/` | GET | `task_no`、`status`、`is_overdue` | `task_no`、`supplier_id`、`sku_code`、`production_quantity`、`completed_quantity`、`expected_ship_date`、`status`、`is_overdue` | `frontend/src/mock/suppliers.js` | mock |
| 供应商任务详情 | `/suppliers/tasks/:id` | `/api/external/supplier/tasks/{id}/` | GET | `id` | `task_no`、`supplier_id`、`sku_code`、`production_quantity`、`completed_quantity`、`expected_ship_date`、`status`、`feedback_note`、`exception_note` | `frontend/src/mock/suppliers.js` | mock |
| 供应商任务回填 | `/suppliers/tasks/:id` | `/api/external/supplier/tasks/{id}/feedback/` | POST | `completed_quantity`、`status`、`feedback_note`、`exception_note` | `task_no`、`completed_quantity`、`status` | `frontend/src/mock/suppliers.js` | mock |
| 供应商出货列表 | `/suppliers/shipments` | `/api/external/supplier/shipments/` | GET | `shipment_no`、`status` | `shipment_no`、`supplier_id`、`sku_code`、`ship_quantity`、`carton_count`、`weight`、`volume`、`status` | `frontend/src/mock/suppliers.js` | mock |
| 供应商出货详情 | `/suppliers/shipments/:id` | `/api/external/supplier/shipments/{id}/` | GET | `id` | `shipment_no`、`supplier_id`、`sku_code`、`ship_quantity`、`carton_count`、`weight`、`volume`、`shipping_mark`、`tracking_no`、`attachment_placeholder`、`status` | `frontend/src/mock/suppliers.js` | mock |
| 多国家刊登资料列表 | `/listings/sites` | `/api/internal/listings/sites/` | GET | `sku`、`platform`、`country`、`listing_status` | `items`、`status` | `frontend/src/mock/listings.js` | pending |
| 刊登模板列表 | `/listings/templates` | `/api/internal/listings/templates/` | GET | `platform`、`country`、`category` | `items`、`status` | `frontend/src/mock/listings.js` | pending |
| 价格列表 | `/pricing/prices` | `/api/internal/pricing/prices/` | GET | `sku`、`approval_status` | `items`、`status` | `frontend/src/mock/pricing.js` | pending |
| RPA任务列表 | `/rpa/tasks` | `/api/internal/rpa/tasks/` | GET | `task_id`、`task_type`、`status`、`agent` | `task_id`、`task_type`、`business_type`、`business_id`、`status`、`agent`、`retry_count` | `frontend/src/mock/rpa.js` | pending |
| RPA任务详情 | `/rpa/tasks/:id` | `/api/internal/rpa/tasks/{id}/` | GET | `id` | `task_id`、`payload`、`result`、`logs`、`screenshots`、`error_message`、`manual_required` | `frontend/src/mock/rpa.js` | pending |
| API同步任务列表 | `/integrations/api-sync` | `/api/internal/integrations/sync-tasks/` | GET | `task_no`、`platform`、`sync_type`、`status` | `items`、`status` | `frontend/src/mock/integrations.js` | pending |
| API同步日志列表 | `/integrations/api-sync/logs` | `/api/internal/integrations/sync-logs/` | GET | `log_no`、`platform`、`sync_type`、`status` | `items`、`quality_check_result` | `frontend/src/mock/integrations.js` | pending |
| 平台接入配置列表 | `/integrations/configs` | `/api/internal/integrations/configs/` | GET | `platform`、`status`、`environment` | `platform`、`account_alias`、`environment`、`status`、`credential_fingerprint`、`credential_key_version` | `frontend/src/mock/integrations.js` | pending |
| 平台接入配置详情 | `/integrations/configs/:id` | `/api/internal/integrations/configs/{id}/` | GET | `id` | `platform`、`account_alias`、`environment`、`status`、`credential_fingerprint`、`credential_key_version` | `frontend/src/mock/integrations.js` | pending |
| 同步任务列表 | `/integrations/sync-jobs` | `/api/internal/integrations/sync-jobs/` | GET | `resource_type`、`status`、`schedule_type` | `resource_type`、`schedule_type`、`status`、`is_enabled`、`last_run_at`、`next_run_at` | `frontend/src/mock/integrations.js` | pending |
| 同步执行记录列表 | `/integrations/sync-runs` | `/api/internal/integrations/sync-runs/` | GET | `platform`、`resource_type`、`status` | `run_id`、`status`、`fetched_count`、`failed_count`、`retry_count`、`masked_error_message` | `frontend/src/mock/integrations.js` | pending |
| 同步执行记录详情 | `/integrations/sync-runs/:id` | `/api/internal/integrations/sync-runs/{id}/` | GET | `id` | `run_id`、`status`、`masked_error_message`、`quality_check_result` | `frontend/src/mock/integrations.js` | pending |
| 操作日志列表 | `/audit/operations` | `/api/internal/audit/operation-logs/` | GET | `operator`、`module`、`action`、`object_id` | `items`、`status` | `frontend/src/mock/audit.js` | pending |
| 财务导入入口 | `/finance/imports` | `/api/finance/imports/` | GET | `import_no`、`status` | `items`、`authorization` | `frontend/src/mock/finance.js` | pending |
| 平台账单列表 | `/finance/statements` | `/api/finance/statements/` | GET | `platform`、`currency`、`status` | `platform`、`statement_no`、`currency`、`gross_amount`、`fee_amount`、`net_amount`、`status` | `frontend/src/mock/financeReconciliation.js` | pending |
| 取款记录列表 | `/finance/withdrawals` | `/api/finance/withdrawals/` | GET | `platform`、`status` | `withdrawal_no`、`requested_amount`、`expected_amount`、`completed_at`、`status` | `frontend/src/mock/financeReconciliation.js` | pending |
| 银行到账列表 | `/finance/bank-receipts` | `/api/finance/bank-receipts/` | GET | `currency`、`status` | `masked_account`、`receipt_amount`、`receipt_date`、`reference_no`、`status` | `frontend/src/mock/financeReconciliation.js` | pending |
| 对账匹配列表 | `/finance/reconciliation/matches` | `/api/finance/reconciliation/matches/` | GET | `status`、`match_type` | `match_type`、`matched_amount`、`difference_amount`、`confidence`、`status` | `frontend/src/mock/financeReconciliation.js` | pending |
| 对账异常列表 | `/finance/reconciliation/exceptions` | `/api/finance/reconciliation/exceptions/` | GET | `exception_type`、`status` | `exception_type`、`difference_amount`、`status`、`assigned_to`、`resolution_note` | `frontend/src/mock/financeReconciliation.js` | pending |
| 基础报表首页 | `/reports/basic` | `/api/report/basic/` | GET | `report_name`、`date_range` | `items`、`metrics` | `frontend/src/mock/reports.js` | pending |

## RPA Agent执行接口边界

RPA Agent 执行接口只能由 Agent 访问，前端管理后台页面不得直接调用：

- `/api/rpa/tasks/claim/`
- `/api/rpa/tasks/{id}/heartbeat/`
- `/api/rpa/tasks/{id}/logs/`
- `/api/rpa/tasks/{id}/screenshots/`
- `/api/rpa/tasks/{id}/complete/`
- `/api/rpa/tasks/{id}/fail/`

RPA Agent 不访问 `/api/finance/*`，不访问 `/admin/`，不直连数据库。
