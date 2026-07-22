# 阶段1前后端接口对接清单

## UI-P7 治理与受控试点合同（2026-07-17）

本节为 UI-P7 现行口径，详细合同见 `docs/03_api/ui_p7_governance_pilot_contract.md`。合同冻结时能力均为 `pending`；完成 handler、页面和自动化证据后，固定检查更新为 `mock`，其余受控记录能力更新为 `sandbox`。真实认证浏览器 E2E 通过前不得标记 `connected`。

| 页面名称 | 页面路径 | API | 权限 | 状态 |
|---|---|---|---|---|
| API治理目录 | `/governance/api-contracts` | `GET /api/internal/governance/api-contracts/` | `governance.api.view` | sandbox |
| API合同详情 | `/governance/api-contracts/:id` | `GET /api/internal/governance/api-contracts/{id}/` | `governance.api.view` | sandbox |
| API合同Mock检查 | `/governance/api-contracts` | `POST /api/internal/governance/api-contracts/check-mock/` | `governance.api.check` | mock |
| 智能体治理占位 | `/governance/assistants` | `GET /api/internal/governance/assistants/` | `governance.assistants.view` | sandbox |
| 智能体占位详情 | `/governance/assistants/:id` | `GET /api/internal/governance/assistants/{id}/` | `governance.assistants.view` | sandbox |
| 智能体Mock评估 | `/governance/assistants/:id` | `POST /api/internal/governance/assistants/{id}/evaluate-mock/` | `governance.assistants.evaluate` | mock |
| 试点就绪 | `/pilot/readiness` | `GET /api/internal/pilot/readiness/` | `pilot.readiness.view` | sandbox |
| 双主机拓扑 | `/pilot/topology` | `GET /api/internal/pilot/topology/` | `pilot.topology.view` | sandbox |
| 拓扑Mock检查 | `/pilot/topology` | `POST /api/internal/pilot/topology/verify-mock/` | `pilot.topology.verify` | mock |
| 备份恢复计划 | `/pilot/recovery` | `GET/POST /api/internal/pilot/recovery-plans/`、`GET {id}/` | `pilot.recovery.view/plan` | sandbox |
| 恢复审批与排期 | `/pilot/recovery` | `POST recovery-plans/{id}/submit-review/`、`approve/`、`reject/`、`schedule/`、`cancel/` | `pilot.recovery.plan/review` | sandbox |
| 恢复演练记录 | `/pilot/recovery` | `POST recovery-plans/{id}/start/`、`resume/`；`GET recovery-drills/`、`POST recovery-drills/{id}/record-result/` | `pilot.recovery.view/record` | sandbox |
| 灰度发布计划 | `/pilot/releases` | `GET/POST /api/internal/pilot/release-plans/`、`GET {id}/` | `pilot.release.view/plan` | sandbox |
| 发布审批与排期 | `/pilot/releases` | `POST release-plans/{id}/submit-review/`、`approve/`、`reject/`、`schedule/`、`cancel/` | `pilot.release.plan/review` | sandbox |
| 发布结果记录 | `/pilot/releases` | `POST release-plans/{id}/start/`、`resume/`、`record-result/` | `pilot.release.record` | sandbox |
| 回滚批准与记录 | `/pilot/releases` | `POST release-plans/{id}/approve-rollback/`、`resume-rollback/`、`record-rollback/` | `pilot.release.rollback` | sandbox |
| 容量摘要 | `/pilot/capacity` | `GET /api/internal/pilot/capacity/summary/` | `pilot.capacity.view` | sandbox |
| 容量观测 | `/pilot/capacity` | `GET /api/internal/pilot/capacity/observations/` | `pilot.capacity.view` | sandbox |

UI-P7 页面只登记计划、审批、结果和脱敏证据，不直接执行 shell、Docker、SQL、备份、恢复、部署或回滚。智能体占位不接入真实模型，不使用网络工具，不写业务数据。真实平台和高风险自动化继续禁止。

## UI-P6 API接入与分析复盘合同（2026-07-17）

本节为 UI-P6 现行冻结口径；详细合同见 `docs/03_api/ui_p6_api_analysis_contract.md`。后端路径存在不等于 UI 联调已经完成，本阶段实施和验收前统一标记 `pending`；仅 Mock 动作标记 `mock`。

| 页面名称 | 页面路径 | API | 权限 | 后端现状 | UI-P6状态 |
|---|---|---|---|---|---|
| 经营总览 | `/analytics/overview` | `GET /api/internal/analytics/overview/` | `analytics.view` | 已实现 | pending |
| 销售归因复盘 | `/analytics/sales` | `GET /api/internal/analytics/sales/`、`metrics/`、`aggregates/` | `analytics.view` | 已实现 | pending |
| 库存分析 | `/analytics/inventory` | `GET /api/internal/analytics/inventory/` | `analytics.view` | 已实现 | pending |
| 财务只读复盘 | `/finance/analytics` | `GET /api/finance/analytics/overview/`、`reconciliation/`、`exceptions/` | `finance.view` | 已实现 | pending |
| 生命周期复盘 | `/lifecycle/reviews` | `GET /api/internal/lifecycle/reviews/`、`POST reviews/{id}/confirm|reject/` | `products.lifecycle.view/confirm/high_risk_confirm` | 已实现 | pending |
| 生命周期历史 | `/lifecycle/history` | `GET /api/internal/lifecycle/decisions/` | `products.lifecycle.view` | 已实现 | pending |
| 清仓申请 | `/lifecycle/clearance-requests` | `GET /api/internal/workflow/approvals/?approval_type=clearance`、`POST approvals/mock/` | `workflow.approvals.view/submit` + `approval_types=clearance` | 查询已实现，创建仅Mock | mock |
| API接入配置 | `/integrations/configs` | `GET /api/internal/integrations/configs/`及详情 | `integrations.view` | 已实现 | pending |
| API同步任务 | `/integrations/sync-jobs` | `GET sync-jobs/`、`POST {id}/run-mock|disable/` | `integrations.view/run/manage` | 已实现；仅run-mock可执行 | mock |
| API同步运行 | `/integrations/sync-runs` | `GET sync-runs/`及详情 | `integrations.view` | 已实现 | pending |
| 平台准入 | `/settings/platform-readiness` | 安全评审与接入状态占位 | `integrations.view` | 无真实连接合同 | pending |
| 报表导出 | `/reports/exports` | `GET/POST /api/report/exports/`、详情、download | `reports.view/export/download` | 已实现审计占位 | pending |

UI-P6 禁止把配置 `active`、HTTP 200、凭据指纹或一次 Mock 成功解释为真实平台已连接。指标、生命周期建议和清仓申请不得直接触发采购、改价、刊登、库存修改、真实 RPA 或资金动作。

## UI-P5 业务主链路状态覆盖（2026-07-17）

本节为 UI-P5 的现行口径；如与阶段0旧表冲突，以本节和 `docs/03_api/ui_p5_business_mainflow_contract.md` 为准。

| 页面 | 路径 | API | 方法 | 权限/身份 | 状态 |
|---|---|---|---|---|---|
| 新品市调 | `/products/research` | `/api/internal/products/research/` | GET | `products.research.view` + data_scope | connected |
| 商品主数据 | `/products/master` | `/api/internal/products/spus/`、`/api/internal/products/skus/` | GET | `products.master.view` + data_scope | connected |
| 商品编码冻结 | `/products/master/:id` | `/api/internal/products/spus/{id}/freeze-code/` | POST | `products.master.freeze` + data_scope | connected |
| 采购订单 | `/purchasing/orders` | `/api/internal/purchasing/orders/` | GET | `purchasing.orders.view` + data_scope | connected |
| 供应商任务 | `/suppliers/tasks` | `/api/external/supplier/tasks/` | GET | external + 当前 tenant/supplier | connected |
| 供应商任务回填 | `/suppliers/tasks/:id` | `/api/external/supplier/tasks/{id}/feedback/` | PATCH | external + 当前 tenant/supplier | connected |
| 供应商出货 | `/suppliers/shipments` | `/api/external/supplier/shipments/` | GET/POST | external + 当前 tenant/supplier | connected |
| 多国家刊登 | `/listings/*` | 尚未冻结后端路径 | - | internal 展示占位 | pending/mock |
| 价格中心 | `/pricing/*` | 尚未冻结后端路径 | - | internal 展示占位 | pending/mock |
| 销售订单 | 尚无页面 | 尚无后端路径 | - | 待阶段任务拆分 | pending |

所有 connected 列表统一解析 `data.count/next/previous/results`；Mock 使用 `data.items`。刊登与价格在 `VITE_USE_MOCK=false` 时返回受控 pending 数据，不发送不存在的后端请求。

## UI-P4 审批、报告、异常与协同

| 页面 | 页面路径 | API | 方法 | Mock位置 | 当前状态 |
|---|---|---|---|---|---|
| 审批中心 | `/workflow/approvals` | `/api/internal/workflow/approvals/` | GET | `frontend/src/mock/workflow.js` | connected/mock切换 |
| 审批详情 | `/workflow/approvals/{id}` | `/api/internal/workflow/approvals/{id}/` | GET | `frontend/src/mock/workflow.js` | connected/mock切换 |
| 审批动作 | 同审批详情 | `approve/`、`reject/`、`withdraw/` | POST | 不执行Mock写入 | connected |
| 异常中心 | `/workflow/exceptions` | `/api/internal/workflow/exceptions/` | GET | `frontend/src/mock/workflow.js` | connected/mock切换 |
| 异常详情 | `/workflow/exceptions/{id}` | `/api/internal/workflow/exceptions/{id}/` | GET | `frontend/src/mock/workflow.js` | connected/mock切换 |
| 异常动作 | 同异常详情 | `assign/`、`resolve/`、`close/` | POST | 不执行Mock写入 | connected |
| 协同回填 | `/workflow/collaboration-events` | `/api/internal/workflow/collaboration-events/` | GET | `frontend/src/mock/workflow.js` | connected/mock切换 |
| 协同确认 | 同协同回填 | `confirm/`、`reject/` | POST | 不执行Mock写入 | connected |
| 报表下载审计 | `/reports/exports` | `/api/report/exports/{id}/download/` | POST | 不生成文件 | connected |

UI-P4全部真实写动作必须由后端permission-specific data_scope与状态机校验。飞书/微信回调仅为Mock合同，不标记真实平台connected。

本清单用于阶段1前端页面、Mock fallback 和后端接口边界对齐。未真实联调的接口不得标记为 `connected`。

## UI-P1认证与工作台映射

| 页面/能力 | 页面路径 | API | 方法 | 返回/用途 | 当前状态 |
|---|---|---|---|---|---|
| 内部登录 | `/login` | `/api/internal/auth/login/` | POST | `access`、`refresh`；仅内部用户 | pending（代码完成，待Pilot复验） |
| Token刷新 | 全局请求层 | `/api/internal/auth/refresh/` | POST | 新`access`；并发请求共享一次刷新 | pending（代码完成，待Pilot复验） |
| 当前用户 | 全局会话 | `/api/internal/auth/me/` | GET | 用户、tenant、superuser、roles、permissions、data_scope | pending（代码完成，待Pilot复验） |
| 角色工作台 | `/` | 后续聚合合同 | GET | 当前只展示可信会话上下文和授权入口，不显示虚构业务数量 | pending |

生产模式不得在认证API网络失败时回退为Mock身份；菜单只消费`/auth/me/`的可信授权上下文，直接访问仍由后端权限拒绝。

## 阶段3旧映射（已废止）

本节原阶段3 Mock 路径已由阶段3最终合同和本文件顶部 UI-P6 现行合同取代。旧的补货 suggestions、生命周期 history、未区分 inventory/business 的 alerts、配置 items/versions 等别名全部退役，不再作为本文件中的可调用 API。

现行阶段3资源路径以 `docs/03_api/phase3_api_contract_final.md` 为基线；UI-P6 页面、状态和动作以 `docs/03_api/ui_p6_api_analysis_contract.md` 为唯一实施合同。历史 Mock 文件可以保留作为离线测试数据，但不得据此将接口标记为 `connected`。

## 接口路径边界

- 内部后台页面使用 `/api/internal/*`。
- 供应商外部页面使用 `/api/external/*`。
- 财务页面使用 `/api/finance/*`。
- 报表页面使用 `/api/report/*`。
- RPA前端管理后台页面不直接使用 RPA Agent 执行接口。
- UI-P3 已实现 `/api/internal/rpa/*` 管理查询；关闭 Mock 后实际成功才标记 `connected`，网络回退标记 `degraded`。
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
| RPA任务列表 | `/rpa/tasks` | `/api/internal/rpa/tasks/` | GET | `page`、`page_size`、`status`、`task_type` | `count`、`results[].task_id/task_type/status/agent/retry_count` | `frontend/src/mock/rpa.js` | connected |
| RPA任务详情 | `/rpa/tasks/:id` | `/api/internal/rpa/tasks/{id}/` | GET | `id` | `task_id`、`payload`、`result`、`logs`、`screenshots`、`error_message` | `frontend/src/mock/rpa.js` | connected |
| RPA运行列表 | `/rpa/runs` | `/api/internal/rpa/runs/` | GET | `page`、`page_size`、`status` | `task_code`、`attempt_no`、`agent`、`heartbeat_at`、`status`、`masked_error` | `frontend/src/mock/rpaStability.js` | connected |
| RPA设备列表 | `/rpa/devices` | `/api/internal/rpa/devices/` | GET | `page`、`page_size` | `name`、`execution_mode`、`availability`、`fingerprint_masked` | `frontend/src/mock/rpaStability.js` | connected |
| RPA设备dry-run | `/rpa/devices` | `/api/internal/rpa/devices/{id}/dry-run/` | POST | `id` | `status=dry_run`、`checks` | `frontend/src/mock/rpaStability.js` | connected |
| RPA稳定性看板 | `/rpa/stability` | `/api/internal/rpa/stability/` | GET | 无 | `task_states`、`run_states`、`manual_required` | `frontend/src/mock/rpaStability.js` | connected |
| RPA人工接管队列 | `/rpa/manual-queue` | `/api/internal/rpa/manual-queue/` | GET | `page`、`page_size` | `task_id`、`manual_assignee`、`manual_reason`、`status` | `frontend/src/mock/rpaStability.js` | connected |
| RPA账号锁 | `/rpa/account-locks` | `/api/internal/rpa/account-locks/` | GET | `page`、`page_size` | `platform`、`account_alias`、`lock_status`、`expires_at` | `frontend/src/mock/rpaStability.js` | connected |
| RPA页面签名异常 | `/rpa/page-signatures` | `/api/internal/rpa/page-signatures/` | GET | `page`、`page_size` | `platform`、`page_type`、`signature_hash_masked`、`detected_status` | `frontend/src/mock/rpaStability.js` | connected |
| API同步任务列表 | `/integrations/api-sync` | `/api/internal/integrations/sync-jobs/` | GET | `resource_type`、`status`、`schedule_type` | `count/next/previous/results` | `frontend/src/mock/integrations.js` | pending |
| API同步日志列表 | `/integrations/api-sync/logs` | `/api/internal/integrations/sync-runs/` | GET | `platform`、`resource_type`、`status` | `count/next/previous/results`、`quality_check_result` | `frontend/src/mock/integrations.js` | pending |
| 平台接入配置列表 | `/integrations/configs` | `/api/internal/integrations/configs/` | GET | `platform`、`status`、`environment` | `platform`、`account_alias`、`environment`、`status`、`credential_fingerprint`、`credential_key_version` | `frontend/src/mock/integrations.js` | pending |
| 平台接入配置详情 | `/integrations/configs/:id` | `/api/internal/integrations/configs/{id}/` | GET | `id` | `platform`、`account_alias`、`environment`、`status`、`credential_fingerprint`、`credential_key_version` | `frontend/src/mock/integrations.js` | pending |
| 平台接入配置修改 | `/integrations/configs/:id` | `/api/internal/integrations/configs/{id}/` | PATCH | `id`及允许修改字段 | 统一响应；不得返回明文凭据 | 无真实配置Mock | pending |
| 平台接入配置动作 | `/integrations/configs/:id` | `/api/internal/integrations/configs/{id}/disable/`、`verify/`、`rotate/` | POST | `id`及动作字段 | 脱敏结果与审计摘要 | 无真实配置Mock | pending |
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
- Path fixes made after backend merge: obsolete Phase 2 sync task/log aliases were retired in favor of `sync-jobs` and `sync-runs`.
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

## UI-P7 治理与受控试点实施映射

UI-P7 已完成代码、Mock/dry-run、自动化测试和受控 JWT 浏览器 E2E，并通过独立 R3。固定检查端点标记为 `mock`；查询、计划、审批及外部执行结果记录端点保持 `sandbox`。该 E2E 未连接真实平台或执行生产动作，因此仍不得标记为 `connected`。

| 页面 | 页面路径 | API | 权限 | Mock位置 | 当前状态 |
|---|---|---|---|---|---|
| API合同目录/详情 | `/governance/api-contracts` | `GET /api/internal/governance/api-contracts/`、`GET /api/internal/governance/api-contracts/{id}/` | `governance.api.view` | `frontend/src/mock/governance.js` | sandbox |
| API合同固定检查 | `/governance/api-contracts` | `POST /api/internal/governance/api-contracts/check-mock/` | `governance.api.check` | `frontend/src/mock/governance.js` | mock |
| 助手治理目录/详情 | `/governance/assistants` | `GET /api/internal/governance/assistants/`、`GET /api/internal/governance/assistants/{id}/` | `governance.assistants.view` | `frontend/src/mock/governance.js` | sandbox |
| 助手固定评估 | `/governance/assistants` | `POST /api/internal/governance/assistants/{id}/evaluate-mock/` | `governance.assistants.evaluate` | `frontend/src/mock/governance.js` | mock |
| 试点准入 | `/pilot/readiness` | `GET /api/internal/pilot/readiness/` | `pilot.readiness.view` | `frontend/src/mock/pilot.js` | sandbox |
| 部署拓扑 | `/pilot/topology` | `GET /api/internal/pilot/topology/` | `pilot.topology.view` | `frontend/src/mock/pilot.js` | sandbox |
| 拓扑固定校验 | `/pilot/topology` | `POST /api/internal/pilot/topology/verify-mock/` | `pilot.topology.verify` | `frontend/src/mock/pilot.js` | mock |
| 容量观察 | `/pilot/capacity` | `GET /api/internal/pilot/capacity/summary/`、`GET /api/internal/pilot/capacity/observations/` | `pilot.capacity.view` | `frontend/src/mock/pilot.js` | sandbox |
| 恢复计划与演练 | `/pilot/recovery` | `/api/internal/pilot/recovery-plans/*`、`/api/internal/pilot/recovery-drills/*` | `pilot.recovery.view/plan/review/record` | `frontend/src/mock/pilot.js` | sandbox |
| 发布与回滚记录 | `/pilot/releases` | `/api/internal/pilot/release-plans/*` | `pilot.release.view/plan/review/record/rollback` | `frontend/src/mock/pilot.js` | sandbox |

受控边界：恢复、发布、回滚的 `start`、`resume` 和 `record-result` 只记录外部人工执行事实，不执行 Shell、Docker、SQL、网络、备份恢复或部署命令；页面不调用 `/api/rpa/*`、`/api/finance/*` 或 `/admin/`。

## UI-P8 生产试点运维与专项安全准入映射

UI-P8 合同与本地实现已完成，并已在 `VITE_USE_MOCK=false` 下完成真实 JWT 浏览器 login/me、GET、POST 和 PATCH 联调；远端 CI 放行前仍统一标记为 `pending`。Mock 数据标记为 `mock`，任何 HTTP 200 均不得绕过统一响应校验而自动标记为 `connected`。

| 页面 | 页面路径 | API | 权限 | Mock位置 | 当前状态 |
|---|---|---|---|---|---|
| 生产试点控制台 | `/pilot/control-room` | `GET /api/internal/pilot/control-room/` | `pilot.control.view` | `frontend/src/mock/pilot.js` | pending |
| 专项安全评审 | `/pilot/security-reviews` | `GET/POST /api/internal/pilot/security-reviews/`、`GET/PATCH /api/internal/pilot/security-reviews/{id}/`、`POST .../{submit|approve|reject}/` | `pilot.security_review.view/plan/review`；`finance_boundary` 叠加 `finance.view` | `frontend/src/mock/pilot.js` | pending |
| 受控验证记录 | `/pilot/verification-runs` | `GET/POST /api/internal/pilot/verification-runs/`、`GET/PATCH /api/internal/pilot/verification-runs/{id}/`、`POST .../{submit|approve|record-result|cancel}/` | `pilot.verification.view/plan/review/record/cancel` | `frontend/src/mock/pilot.js` | pending |
| 性能容量验证 | `/pilot/performance-runs` | `GET/POST /api/internal/pilot/performance-runs/`、`GET/PATCH /api/internal/pilot/performance-runs/{id}/`、`POST .../{submit|approve|record-result|cancel}/` | `pilot.performance.view/plan/review/record/cancel` | `frontend/src/mock/pilot.js` | pending |
| 试点准入决策 | `/pilot/entry-decisions` | `GET/POST /api/internal/pilot/entry-decisions/`、`GET/PATCH /api/internal/pilot/entry-decisions/{id}/`、`POST .../{submit|approve|reject}/` | `pilot.entry.view/plan/review`，引用资源叠加各资源 `view` | `frontend/src/mock/pilot.js` | pending |

UI-P8 复用 `/pilot/readiness`、`/pilot/topology`、`/pilot/capacity`、`/pilot/recovery`、`/pilot/releases`、`/system/security-operations` 和 `/audit/operations`，不得创建同义页面。准入 `go` 只表示人工评审结论，不表示已部署、已连接真实平台或已开启生产流量。

UI-P8 创建类 POST 按 exact plan permission 的 `pilot_environments` scope 授权；详情和 action 按各 exact permission 的资源 ID scope 授权。准入决策引用安全评审、验证、性能、恢复和发布资源时逐类重新校验对应 view permission 和 scope；`finance_boundary` 同时要求 `finance.view`。submit、approve、reject、record-result 和 cancel 的请求、响应及合法状态以 `docs/03_api/ui_p8_production_pilot_security_contract.md` 为唯一合同，不得由通配路径自行推断。

UI-P8 列表统一支持 `page`、`page_size`、`environment`、`status` 及合同声明的资源筛选字段；草稿 PATCH 必须携带 `version`。验证目标别名与证据引用必须先登记到当前 tenant 和环境的受控注册表。准入批准会重新读取证据并与提交时不可变快照比较；证据状态、版本、摘要或有效期变化均返回 `409`。`403/409/422` 失败尝试写入脱敏、不可变审计事件。

## 模块化开发节点映射

本节与 `docs/03_api/module_development_api_contract.md` 一致。开发A复用现有阶段3资源；开发B达人正式接口在实现、JWT联调和CI完成前统一为 `pending`，现有 Local Sandbox 达人路由保持 `mock`。

| 模块/页面 | 页面路径 | API | 权限 | Mock位置 | 当前状态 |
|---|---|---|---|---|---|
| 销售与库存总览 | `/analytics/overview`、`/analytics/sales`、`/analytics/inventory` | `GET /api/internal/analytics/{overview,sales,inventory}/` | `analytics.view` | `deploy/dev-sandbox/fixtures/sales-inventory-finance-reconciliation.json` | pending（待模块JWT复验） |
| 库存预警 | `/alerts/inventory` | `/api/internal/alerts/inventory/*` | `alerts.view/evaluate/manage` | 同上 | pending（待模块JWT复验） |
| 补货建议 | `/replenishment/recommendations` | `/api/internal/replenishment/recommendations/*`、`evaluate-mock/` | `replenishment.view/evaluate/review` | 同上 | pending；evaluate为mock |
| 财务对账 | `/finance/reconciliation/*`、`/finance/analytics` | `/api/finance/analytics/*`、`/api/finance/reconciliation/*` | `finance.view/reconcile/exception.handle` | 同上 | pending（待独立财务权限复验） |
| 达人档案 | `/creators/profiles`、`/creators/profiles/{id}` | `GET/POST /api/internal/creators/profiles/`、`GET/PATCH .../{id}/`、状态action | `creator.view/manage` | `deploy/dev-sandbox/fixtures/creator-management.json` | pending；fallback为mock |
| 达人合作 | `/creators/collaborations`、`/creators/collaborations/{id}` | `/api/internal/creators/collaborations/*`、审核action | `creator.collaboration.view/manage/review` | 同上 | pending；fallback为mock |
| 达人任务 | `/creators/tasks` | `/api/internal/creators/tasks/*` | `creator.task.view/manage` | 同上 | pending |
| 达人效果复盘 | `/creators/performance` | `GET /api/internal/creators/performance/` | `creator.performance.view` | 同上 | pending |

达人模块不得访问 `/api/finance/*`、`/admin/` 或 `/api/rpa/*` Agent执行端点。销售库存权限不能替代财务权限；补货建议不得自动创建采购订单。只有统一响应、分页、401/403/404/409/422、tenant、permission-specific `data_scope` 和action permission均有实际联调证据后，相关条目才可改为 `connected`。
