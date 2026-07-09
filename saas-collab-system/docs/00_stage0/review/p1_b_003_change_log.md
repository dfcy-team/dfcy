# P1-B-003 Change Log

## Task

采购订单与供应商任务页面阶段1接口联调。

## Preconditions

- 当前分支：`feature/phase1-b-frontend-api-integration`
- 当前 HEAD 未在 `feature/ar0-001-stage0-file-scope` 分支上开发。
- 本次变更未修改 `backend/`、`rpa-agent/`、`docs/04_rpa/`。
- 未连接真实微信服务号、小程序或真实平台。
- 未写入真实供应商数据、真实物流单据、真实财务数据、真实账号密码。

## Input Documents

- 已读取：`docs/00_stage0/frontend_api_mapping.md`
- 缺失：`docs/03_api/phase1_api_priority.md`

## Changes

- `frontend/src/api/purchasing.js`
  - 采购订单列表和详情保留 Mock fallback。
  - 采购订单使用 `/api/internal/purchasing/orders/` 和 `/api/internal/purchasing/orders/{id}/`。

- `frontend/src/api/suppliers.js`
  - 供应商任务和出货列表、详情保留 Mock fallback。
  - 供应商页面使用 `/api/external/supplier/tasks/`、`/api/external/supplier/tasks/{id}/`、`/api/external/supplier/shipments/`、`/api/external/supplier/shipments/{id}/`。

- `frontend/src/mock/purchasing.js`
  - Mock 字段对齐后端 MVP：`po_no`、`sku_code`、`supplier_id`、`quantity`、`unit_price`、`delivery_date`、`payment_terms`、`status`、`approval_status`。

- `frontend/src/mock/suppliers.js`
  - Mock 字段对齐后端 MVP：供应商任务、出货、箱规和 `attachment_placeholder`。
  - 附件仅为 demo/placeholder 字段，不上传真实文件。

- `frontend/src/views/purchasing/`
  - `PurchaseOrderList.vue`：展示采购订单列表、搜索条件占位、loading、error、empty、fallback提示。
  - `PurchaseOrderDetail.vue`：展示采购基础信息、商品明细、供应商信息、付款方式、审批状态占位和生产任务按钮占位。

- `frontend/src/views/suppliers/`
  - `SupplierTaskList.vue`：展示供应商任务列表、生产进度、loading、error、empty、fallback提示。
  - `SupplierTaskDetail.vue`：展示生产任务信息、供应商回填记录、异常说明和采购确认按钮占位。
  - `SupplierShipmentList.vue`：展示供应商出货列表、箱数、重量、体积等字段。
  - `SupplierShipmentDetail.vue`：展示出货基础信息、箱规信息、图片/箱唛/物流单附件占位和采购确认按钮占位。

## Boundary Notes

- 采购订单页面使用 `/api/internal/purchasing/*`。
- 供应商页面使用 `/api/external/supplier/*`。
- 供应商页面未访问 `/api/internal/*`。
- 供应商页面未访问 `/api/finance/*`。
- 供应商页面未调用 `/admin/`。
- 未实现真实微信服务号。
- 未实现真实小程序。
- 未上传真实附件。
- 供应商页面显示“仅展示当前供应商自己的任务/出货记录”，但不在前端实现真实 supplier_id 过滤，真实过滤以后端为准。

## Validation

- `rg "/api/external|/api/finance|/admin/|/admin" frontend/src/api/purchasing.js frontend/src/views/purchasing`：无结果。
- `rg "/api/internal|/api/finance|/admin/|/admin" frontend/src/api/suppliers.js frontend/src/views/suppliers`：无结果。
- `rg "WECHAT|MINI_PROGRAM|APPID|TOKEN|API_KEY|PASSWORD|SECRET|BANK|FINANCE|BIGSELLER|SHOPEE|TIKTOK" frontend/src/api/purchasing.js frontend/src/api/suppliers.js frontend/src/mock/purchasing.js frontend/src/mock/suppliers.js frontend/src/views/purchasing frontend/src/views/suppliers`：无结果。
- `git diff --name-only -- backend rpa-agent docs/04_rpa`：无结果。
- 已执行：`cd frontend && npm run build`
- 结果：构建通过。
- 观察项：
  - Rollup 移除了 `@vueuse/core` 中位置不合规的 `/* #__PURE__ */` 注释。
  - 仍存在 Vite chunk size warning：`dist/assets/index-DhUBJACn.js` 约 `1,139.92 kB`，gzip 后约 `370.83 kB`。
  - 阶段1不强制拆包，继续作为性能优化观察项跟踪。
