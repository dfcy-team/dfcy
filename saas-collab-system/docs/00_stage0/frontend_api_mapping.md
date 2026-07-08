# 阶段0前后端接口对接清单

本清单用于阶段0前端页面、Mock 数据和后续后端接口边界对齐。当前未完成接口统一标记为 `mock` 或 `pending`，不得将未完成接口标记为 `connected`，不得编造后端已完成。

## 接口路径边界

- 内部后台页面使用 `/api/internal/*`。
- 供应商外部页面后续使用 `/api/external/*`。
- RPA任务页面后续使用 `/api/rpa/*` 或 `/api/internal/rpa/*`，但 RPA Agent 执行接口必须是 `/api/rpa/*`。
- 财务页面使用 `/api/finance/*`。
- 报表页面使用 `/api/report/*`。
- 不允许把 `/admin/` 当业务接口。
- 不允许供应商页面访问 `/api/internal/*`。
- 不允许 RPA 访问 `/api/finance/*`。

## 对接清单

| 页面名称 | 页面路径 | 需要的API | 请求方式 | 请求参数 | 返回字段 | Mock文件位置 | 后续后端负责人 | 当前状态 |
|---|---|---|---|---|---|---|---|---|
| 登录页 | `/login` | `/api/internal/auth/login/` | POST | `username`、`password` 占位 | `success`、`code`、`message`、`data.user` | `frontend/src/mock/auth.js` | 开发A | mock |
| 首页 | `/` | `/api/internal/dashboard/summary/` | GET | `tenant_id`、`date_range` | `success`、`code`、`message`、`data.summary` | `frontend/src/mock/reports.js` | 开发A | pending |
| 新品市调列表 | `/products/research` | `/api/internal/products/research/` | GET | `research_no`、`product_name`、`platform`、`approval_status` | `items`、`total`、`status` | `frontend/src/mock/products.js` | 开发A | mock |
| 新品市调详情 | `/products/research/:id` | `/api/internal/products/research/{id}/` | GET | `id` | `research_no`、`product_name`、`risk_points`、`attachments` | `frontend/src/mock/products.js` | 开发A | pending |
| 商品主数据列表 | `/products/master` | `/api/internal/products/master/` | GET | `product_code`、`spu`、`sku`、`status` | `items`、`total`、`status` | `frontend/src/mock/products.js` | 开发A | mock |
| 商品主数据详情 | `/products/master/:id` | `/api/internal/products/master/{id}/` | GET | `id` | `product_code`、`spu`、`sku`、`attributes` | `frontend/src/mock/products.js` | 开发A | pending |
| 商品状态列表 | `/products/status` | `/api/internal/products/status/` | GET | `product_code`、`lifecycle_status`、`sales_status` | `items`、`total`、`status` | `frontend/src/mock/products.js` | 开发A | pending |
| 采购订单列表 | `/purchasing/orders` | `/api/internal/purchasing/orders/` | GET | `purchase_order_no`、`supplier_id`、`status`、`approval_status` | `items`、`total`、`status` | `frontend/src/mock/purchasing.js` | 开发A | mock |
| 采购订单详情 | `/purchasing/orders/:id` | `/api/internal/purchasing/orders/{id}/` | GET | `id` | `purchase_order_no`、`items`、`supplier`、`approval_status` | `frontend/src/mock/purchasing.js` | 开发A | pending |
| 供应商任务列表 | `/suppliers/tasks` | `/api/external/supplier/tasks/` | GET | `task_no`、`supplier_id`、`status`、`is_overdue` | `items`、`total`、`status` | `frontend/src/mock/suppliers.js` | 开发A | mock |
| 供应商任务详情 | `/suppliers/tasks/:id` | `/api/external/supplier/tasks/{id}/` | GET | `id` | `task_no`、`supplier`、`progress`、`feedback_records` | `frontend/src/mock/suppliers.js` | 开发A | pending |
| 供应商出货列表 | `/suppliers/shipments` | `/api/external/supplier/shipments/` | GET | `shipment_no`、`supplier_id`、`status` | `items`、`total`、`status` | `frontend/src/mock/suppliers.js` | 开发A | mock |
| 供应商出货详情 | `/suppliers/shipments/:id` | `/api/external/supplier/shipments/{id}/` | GET | `id` | `shipment_no`、`carton_count`、`logistics_no`、`attachments` | `frontend/src/mock/suppliers.js` | 开发A | pending |
| 多国家刊登资料列表 | `/listings/sites` | `/api/internal/listings/sites/` | GET | `sku`、`platform`、`country`、`listing_status` | `items`、`total`、`status` | `frontend/src/mock/listings.js` | 开发A | mock |
| 多国家刊登资料详情 | `/listings/sites/:id` | `/api/internal/listings/sites/{id}/` | GET | `id` | `sku`、`platform`、`country`、`site_attributes` | `frontend/src/mock/listings.js` | 开发A | pending |
| 刊登模板列表 | `/listings/templates` | `/api/internal/listings/templates/` | GET | `platform`、`country`、`category` | `items`、`total`、`status` | `frontend/src/mock/listings.js` | 开发A | mock |
| 价格列表 | `/pricing/prices` | `/api/internal/pricing/prices/` | GET | `sku`、`approval_status` | `items`、`total`、`status` | `frontend/src/mock/pricing.js` | 开发A | mock |
| 价格详情 | `/pricing/prices/:id` | `/api/internal/pricing/prices/{id}/` | GET | `id` | `sku`、`costs`、`suggested_price`、`approved_price` | `frontend/src/mock/pricing.js` | 开发A | pending |
| RPA任务列表 | `/rpa/tasks` | `/api/internal/rpa/tasks/` | GET | `task_id`、`task_type`、`status`、`agent` | `items`、`total`、`status` | `frontend/src/mock/rpa.js` | 开发A | mock |
| RPA任务详情 | `/rpa/tasks/:id` | `/api/internal/rpa/tasks/{id}/` | GET | `id` | `task_id`、`payload`、`result`、`logs`、`screenshots` | `frontend/src/mock/rpa.js` | 开发A | pending |
| API同步任务列表 | `/integrations/api-sync` | `/api/internal/integrations/sync-tasks/` | GET | `task_no`、`platform`、`sync_type`、`status` | `items`、`total`、`status` | `frontend/src/mock/integrations.js` | 开发A | mock |
| API同步日志列表 | `/integrations/api-sync/logs` | `/api/internal/integrations/sync-logs/` | GET | `log_no`、`platform`、`sync_type`、`status` | `items`、`total`、`quality_check_result` | `frontend/src/mock/integrations.js` | 开发A | mock |
| 操作日志列表 | `/audit/operations` | `/api/internal/audit/operation-logs/` | GET | `operator`、`module`、`action`、`object_id` | `items`、`total`、`status` | `frontend/src/mock/audit.js` | 开发A | mock |
| 财务导入入口 | `/finance/imports` | `/api/finance/imports/` | GET | `import_no`、`status`、`authorization_status` | `items`、`total`、`authorization` | `frontend/src/mock/finance.js` | 开发A | mock |
| 基础报表首页 | `/reports/basic` | `/api/report/basic/` | GET | `report_name`、`date_range` | `items`、`metrics`、`updated_at` | `frontend/src/mock/reports.js` | 开发A | mock |

## RPA Agent接口边界

RPA Agent 后续只能访问 `/api/rpa/*`，例如：

- `/api/rpa/tasks/claim/`
- `/api/rpa/tasks/{id}/logs/`
- `/api/rpa/tasks/{id}/screenshots/`
- `/api/rpa/tasks/{id}/result/`

RPA Agent 不访问 `/api/finance/*`，不直连数据库。
