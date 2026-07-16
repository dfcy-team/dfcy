# 阶段1前后端接口对接清单

本清单用于阶段1前端页面、Mock fallback 和后端接口边界对齐。未真实联调的接口不得标记为 `connected`。

## UI-P1认证与工作台映射

| 页面/能力 | 页面路径 | API | 方法 | 返回/用途 | 当前状态 |
|---|---|---|---|---|---|
| 内部登录 | `/login` | `/api/internal/auth/login/` | POST | `access`、`refresh`；仅内部用户 | pending（代码完成，待Pilot复验） |
| Token刷新 | 全局请求层 | `/api/internal/auth/refresh/` | POST | 新`access`；并发请求共享一次刷新 | pending（代码完成，待Pilot复验） |
| 当前用户 | 全局会话 | `/api/internal/auth/me/` | GET | 用户、tenant、superuser、roles、permissions、data_scope | pending（代码完成，待Pilot复验） |
| 角色工作台 | `/` | 后续聚合合同 | GET | 当前只展示可信会话上下文和授权入口，不显示虚构业务数量 | pending |

生产模式不得在认证API网络失败时回退为Mock身份；菜单只消费`/auth/me/`的可信授权上下文，直接访问仍由后端权限拒绝。

## 阶段3前端页面映射

阶段3开发A接口尚未合并，以下新增页面均使用 Mock fallback，路径状态不得标记为 `connected`。

| 页面名称 | 页面路径 | 需要的API | 请求方式 | Mock文件位置 | 当前状态 |
|---|---|---|---|---|---|
| 经营总览 | `/` | `/api/internal/analytics/overview/` | GET | `frontend/src/mock/analytics.js` | mock |
| 销售分析 | `/analytics/sales` | `/api/internal/analytics/sales/` | GET | `frontend/src/mock/analytics.js` | mock |
| 库存分析 | `/analytics/inventory` | `/api/internal/analytics/inventory/` | GET | `frontend/src/mock/analytics.js` | mock |
| 库存预警 | `/inventory/alerts` | `/api/internal/replenishment/alerts/` | GET | `frontend/src/mock/replenishment.js` | mock |
| 补货建议 | `/inventory/replenishment` | `/api/internal/replenishment/suggestions/` | GET | `frontend/src/mock/replenishment.js` | mock |
| 生命周期复盘 | `/lifecycle/reviews` | `/api/internal/lifecycle/reviews/` | GET | `frontend/src/mock/lifecycle.js` | mock |
| 生命周期历史 | `/lifecycle/history` | `/api/internal/lifecycle/history/` | GET | `frontend/src/mock/lifecycle.js` | mock |
| 经营预警 | `/alerts/business` | `/api/internal/alerts/` | GET | `frontend/src/mock/alerts.js` | mock |
| 配置中心 | `/settings/config-center` | `/api/internal/config/items/` | GET | `frontend/src/mock/configCenter.js` | mock |
| 配置版本 | `/settings/config-versions` | `/api/internal/config/versions/` | GET | `frontend/src/mock/configCenter.js` | mock |
| 财务经营分析 | `/finance/analytics` | `/api/finance/analytics/overview/` | GET | `frontend/src/mock/financeAnalytics.js` | mock |
| 报表导出 | `/reports/exports` | `/api/report/exports/` | GET | `frontend/src/mock/reportExports.js` | mock |

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
| 登录页 | `/login` | `/api/internal/auth/login/`、`/api/internal/auth/me/` | POST、GET | `username`、`password` | `access`、`refresh`、用户、tenant、roles、permissions、data_scope | `frontend/src/mock/auth.js` | pending（待Pilot复验） |
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
| 内部供应商绩效看板 | `/suppliers/performance` | `/api/internal/suppliers/performance/` | GET | `period`、`supplier_id` | `total_tasks`、`on_time_rate`、`overdue_rate`、`exception_rate`、`total_score` | `frontend/src/mock/supplierPerformance.js` | pending |
| 内部供应商绩效详情 | `/suppliers/performance/:supplierId` | `/api/internal/suppliers/performance/{supplier_id}/` | GET | `supplier_id` | `total_tasks`、`total_shipments`、`shipment_accuracy_rate`、`feedback_timeliness_rate`、`total_score` | `frontend/src/mock/supplierPerformance.js` | pending |
| 我的供应商绩效 | `/suppliers/my-performance` | `/api/external/supplier/performance/` | GET | 后端身份范围 | `total_tasks`、`on_time_rate`、`overdue_rate`、`exception_rate`、`total_score` | `frontend/src/mock/supplierPerformance.js` | pending |
| 我的供应商绩效历史 | `/suppliers/my-performance/history` | `/api/external/supplier/performance/history/` | GET | 后端身份范围、`period` | `period`、`total_tasks`、`on_time_rate`、`total_score` | `frontend/src/mock/supplierPerformance.js` | pending |
| 多国家刊登资料列表 | `/listings/sites` | `/api/internal/listings/sites/` | GET | `sku`、`platform`、`country`、`listing_status` | `items`、`status` | `frontend/src/mock/listings.js` | pending |
| 刊登模板列表 | `/listings/templates` | `/api/internal/listings/templates/` | GET | `platform`、`country`、`category` | `items`、`status` | `frontend/src/mock/listings.js` | pending |
| 价格列表 | `/pricing/prices` | `/api/internal/pricing/prices/` | GET | `sku`、`approval_status` | `items`、`status` | `frontend/src/mock/pricing.js` | pending |
| RPA任务列表 | `/rpa/tasks` | `/api/internal/rpa/tasks/` | GET | `task_id`、`task_type`、`status`、`agent` | `task_id`、`task_type`、`business_type`、`business_id`、`status`、`agent`、`retry_count` | `frontend/src/mock/rpa.js` | pending |
| RPA任务详情 | `/rpa/tasks/:id` | `/api/internal/rpa/tasks/{id}/` | GET | `id` | `task_id`、`payload`、`result`、`logs`、`screenshots`、`error_message`、`manual_required` | `frontend/src/mock/rpa.js` | pending |
| RPA稳定性看板 | `/rpa/stability` | `/api/internal/rpa/tasks/` | GET | `status` | `status`、`count` | `frontend/src/mock/rpaStability.js` | pending |
| RPA尝试列表 | `/rpa/attempts` | `/api/internal/rpa/attempts/` | GET | `status`、`agent` | `task`、`attempt_no`、`agent`、`heartbeat_at`、`status`、`masked_error` | `frontend/src/mock/rpaStability.js` | pending |
| RPA人工接管队列 | `/rpa/manual-queue` | `/api/internal/rpa/manual-queue/` | GET | `status=manual_required` | `task`、`failed_step`、`last_success_step`、`masked_error`、`manual_required` | `frontend/src/mock/rpaStability.js` | pending |
| RPA账号锁 | `/rpa/account-locks` | `/api/internal/rpa/account-locks/` | GET | `platform`、`account_alias` | `platform`、`account_alias`、`lock_status`、`expires_at` | `frontend/src/mock/rpaStability.js` | pending |
| RPA页面签名异常 | `/rpa/page-signatures` | `/api/internal/rpa/page-signatures/` | GET | `platform`、`page_type` | `platform`、`page_type`、`signature_hash`、`detected_status` | `frontend/src/mock/rpaStability.js` | pending |
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

## UI-P1 路由与动作权限合同

### 路由合同

- 所有非公开前端路由必须在 `frontend/src/router/menu.js` 的 `routeCapabilities` 中登记。
- 未登记路由默认拒绝并进入统一403页面，不得因不在菜单中而默认放行。
- 详情路由继承最长匹配的资源路径合同。
- `internal`、`external` 和后端 action permission 同时参与判定；前端判定仅改善体验，后端仍是最终安全边界。
- 财务导入使用 `finance.import`，财务查询使用 `finance.view`，对账写操作使用 `finance.reconcile`，不得以 `finance.view` 代替动作权限。
- 供应商任务和出货页面仅允许 `external`；内部商品、采购、治理、RPA管理页面仅允许 `internal`。

### 动作合同

| 页面动作 | 后端权限码 | 无权时行为 |
|---|---|---|
| 补货建议接受/拒绝 | `replenishment.review` | 隐藏且点击处理器二次拒绝 |
| 生命周期建议确认/拒绝 | `products.lifecycle.confirm` | 隐藏且点击处理器二次拒绝；高风险权限仍由后端追加校验 |
| 经营预警处理/关闭 | `alerts.manage` | 隐藏且不发送请求 |
| 配置提交审批 | `config.manage` | 隐藏且不发送请求 |
| 配置回滚 | `config.rollback` | 隐藏且不发送请求 |
| 报表申请导出 | `reports.export` | 隐藏且不发送请求 |
| 财务Mock对账、确认、拒绝 | `finance.reconcile` | 隐藏且不发送请求 |
| 商品状态确认/拒绝 | `products.status.confirm` | 隐藏且点击处理器二次拒绝 |
| API同步run-mock | `integrations.run` | 隐藏且不发送请求 |
| API同步disable | `integrations.manage` | 隐藏且不发送请求 |

通用动作组件通过认证store的 `hasPermission()` 消费后端返回权限码。动作可显式配置为“无权时禁用并展示原因”，默认采用隐藏策略；无论展示策略如何，点击处理器都会再次校验权限。

## P2-B-R1 API Integration Summary

- Latest `origin/main`: `51535c246b430064b782c4078591253506b16c17`.
- Development A backend merge is present in `main`: PR #5 `feature/phase2-a-api-status-finance`.
- Detailed Phase 2 frontend contract: `docs/03_api/phase2_frontend_api_contract.md`.
- Path fixes made after backend merge:
  - `/api/internal/integrations/sync-tasks/` -> `/api/internal/integrations/sync-jobs/`.
  - `/api/internal/integrations/sync-logs/` -> `/api/internal/integrations/sync-runs/`.
  - `GET /api/finance/reconciliation/matches/{id}/` is not provided by backend Phase 2; the detail page now uses `GET /api/finance/reconciliation/matches/` collection data.
- Connected contract paths:
  - `/api/internal/integrations/configs/`
  - `/api/internal/integrations/configs/{id}/`
  - `/api/internal/integrations/sync-jobs/`
  - `/api/internal/integrations/sync-jobs/{id}/run-mock/`
  - `/api/internal/integrations/sync-jobs/{id}/disable/`
  - `/api/internal/integrations/sync-runs/`
  - `/api/internal/integrations/sync-runs/{id}/`
  - `/api/internal/products/status-recommendations/`
  - `/api/internal/products/status-recommendations/{id}/`
  - `/api/internal/products/status-recommendations/{id}/confirm/`
  - `/api/internal/products/status-recommendations/{id}/reject/`
  - `/api/internal/products/status-transitions/`
  - `/api/internal/products/status/evaluate-mock/`
  - `/api/finance/statements/`
  - `/api/finance/withdrawals/`
  - `/api/finance/bank-receipts/`
  - `/api/finance/reconciliation/matches/`
  - `/api/finance/reconciliation/run-mock/`
  - `/api/finance/reconciliation/matches/{id}/confirm/`
  - `/api/finance/reconciliation/matches/{id}/reject/`
  - `/api/finance/reconciliation/exceptions/`
  - `/api/internal/suppliers/performance/`
  - `/api/internal/suppliers/performance/{supplier_id}/`
  - `/api/internal/suppliers/performance/calculate-mock/`
  - `/api/external/supplier/performance/`
  - `/api/external/supplier/performance/history/`
- RPA internal management query APIs are still not provided in latest `main`; frontend keeps pending/mock fallback and must not call `/api/rpa/*` Agent execution endpoints.

## UI-P2 系统治理与基础档案

UI-P2 接口代码已完成，当前保留 Mock/API 切换；只有在受控 Pilot 环境使用真实认证会话完成联调后，才可由 `pending（代码完成）` 更新为 `connected`。

| 页面名称 | 页面路径 | 需要的API | 请求方式 | 权限 | Mock文件位置 | 当前状态 |
|---|---|---|---|---|---|---|
| 组织架构 | `/system/departments` | `/api/internal/system/departments/` | GET、POST | `system.organization.view/manage` | `frontend/src/mock/systemAdmin.js` | pending（代码完成） |
| 用户目录 | `/system/users` | `/api/internal/system/users/`、`/api/internal/system/user-role-options/`、`/api/internal/system/users/{id}/status/`、`/api/internal/system/users/{id}/roles/` | GET、POST、PUT | `system.users.view/manage` | `frontend/src/mock/systemAdmin.js` | pending（代码完成，待Pilot复验） |
| 角色权限 | `/system/roles` | `/api/internal/system/roles/`、`/api/internal/system/roles/{id}/permissions/`、`/api/internal/system/permissions/` | GET、POST、PUT | `system.roles.view/manage` | `frontend/src/mock/systemAdmin.js` | pending（代码完成） |
| 安全运维 | `/system/security-operations` | `/api/internal/system/security-operations/` | GET | `security.operations.view` | `frontend/src/mock/systemAdmin.js` | pending（代码完成） |
| 平台档案 | `/master-data/platforms` | `/api/internal/master-data/platforms/`、`/api/internal/master-data/platforms/{id}/status/` | GET、POST | `masterdata.view/manage` | `frontend/src/mock/masterData.js` | pending（代码完成） |
| 店铺档案 | `/master-data/stores` | `/api/internal/master-data/stores/`、`/api/internal/master-data/stores/{id}/status/` | GET、POST | `masterdata.view/manage` | `frontend/src/mock/masterData.js` | pending（代码完成） |
| 仓库档案 | `/master-data/warehouses` | `/api/internal/master-data/warehouses/`、`/api/internal/master-data/warehouses/{id}/status/` | GET、POST | `masterdata.view/manage` | `frontend/src/mock/masterData.js` | pending（代码完成） |
| 供应商档案 | `/master-data/suppliers` | `/api/internal/master-data/suppliers/`、`/api/internal/master-data/suppliers/{id}/status/` | GET、POST | `masterdata.view/manage` | `frontend/src/mock/masterData.js` | pending（代码完成） |

UI-P2 所有页面仅允许 `internal` 用户；联系方式必须脱敏，安全运维只显示凭据别名、指纹、版本和引用状态。前端动作权限不替代后端 tenant、data scope 与 Permission 校验。
