# UI-P6 API接入与分析复盘实施变更日志

## 1. 实施对象

- 分支：`feature/ui-p6-api-analytics-review`
- 基线：`8c05228c77c262a9041e0f4c78d467819ba6efb2`
- 唯一合同：`docs/03_api/ui_p6_api_analysis_contract.md`
- 验收清单：`docs/05_test/ui_p6_api_analysis_acceptance.md`
- 实施日期：2026-07-17

## 2. 后端实施

1. 新增 permission-specific data_scope 解析器，按 exact permission 分别执行 analytics、lifecycle、workflow、integrations、finance 和 reports 范围。
2. 固化 ALL/CUSTOM/OWN/DEPARTMENT 语义：ALL 仅当前 tenant；CUSTOM 同记录 key 为 AND、记录间为 OR；未冻结归属模型的 OWN/DEPARTMENT 返回 `DATA_SCOPE_UNSUPPORTED`。
3. 增加 `DATA_SCOPE_MISSING`、`DATA_SCOPE_INVALID`、`DATA_SCOPE_UNSUPPORTED`、`DATA_SCOPE_FORBIDDEN` 和 `RESOURCE_NOT_FOUND` 错误码。
4. analytics overview/sales/inventory、metrics、aggregates 与 aggregate-mock 使用统一响应、严格查询参数和最大 100 条分页。
5. finance analytics 三个端点返回逐端点只读 DTO，账号只返回掩码，并固定 `read_only=true`、`fund_action_available=false`。
6. lifecycle、workflow、integrations 和 report export/detail/download 执行 tenant、exact permission、data_scope 与越权 403/404 语义。
7. reports view/export/download 分别计算 `report_types`，并与来源模块权限和范围取交集；拒绝下载也保留审计记录。

主要文件：

- `backend/apps/permissions/ui_p6_scopes.py`
- `backend/apps/common/error_codes.py`
- `backend/apps/common/exceptions.py`
- `backend/apps/reports/`
- `backend/apps/finance/`
- `backend/apps/integrations/views.py`
- `backend/apps/products/lifecycle_views.py`
- `backend/apps/products/lifecycle_services.py`
- `backend/apps/workflows/views.py`
- 对应 `backend/tests/` 回归测试

## 3. 前端实施

1. 新增 `/analytics/overview` 与 `/lifecycle/clearance-requests` 页面和路由合同。
2. analytics/finance 请求适配冻结参数，统一解析 `success/code/message/data`、分页、质量字段和旧 Mock 字段。
3. 网络降级状态统一为 `degraded`，不把 fallback 或一次 Mock 成功标为 connected。
4. 经营总览、销售、库存和财务页面展示 loading/error/empty/数据质量/分页状态；财务页面不提供资金动作。
5. 清仓申请只允许创建 Mock 审批，不改变商品、价格、刊登、采购或 RPA 状态。
6. integrations 配置 PATCH 唯一使用详情路径；详情动作仅有 Sandbox 验证和禁用，不提供真实连接或生产启用。
7. Mock 用户仅增加 UI-P6 查看和 Mock-safe 权限，未增加高风险生命周期确认或财务资金权限。

主要文件：

- `frontend/src/api/uiP6Adapters.js`
- `frontend/src/api/analytics.js`
- `frontend/src/api/financeAnalytics.js`
- `frontend/src/api/integrations.js`
- `frontend/src/api/request.js`
- `frontend/src/components/Phase3AnalyticsPage.vue`
- `frontend/src/views/analytics/BusinessOverview.vue`
- `frontend/src/views/analytics/SalesAnalysis.vue`
- `frontend/src/views/analytics/InventoryAnalysis.vue`
- `frontend/src/views/finance/FinanceAnalyticsOverview.vue`
- `frontend/src/views/lifecycle/ClearanceRequestList.vue`
- `frontend/src/views/integrations/IntegrationConfigDetail.vue`
- `frontend/src/router/`
- `frontend/src/mock/auth.js`
- `frontend/src/mock/financeAnalytics.js`
- `frontend/tests/ui-p6-api-analysis.spec.js`

## 4. 接口映射状态

`docs/00_stage0/frontend_api_mapping.md` 已按唯一冻结路径更新。当前浏览器验收使用 Mock 会话，未完成受控 Pilot 的真实 JWT 联调，因此 analytics、finance、integrations 和 reports 仍保持 `pending`，清仓申请和 Mock 聚合保持 `mock`，没有误标 connected。

## 5. 高风险边界

- 补货和生命周期能力只产生建议。
- 不自动创建采购订单。
- 不自动清仓、停售、归档、改价或下架。
- 预警和页面动作不触发真实 RPA。
- 财务分析不付款、转账或提现。
- production adapter 和真实平台连接保持禁用。

## 6. 安全确认

- 未提交真实 `.env`、账号、密码、Token、Cookie、Session、API Key 或 API Secret。
- 未提交真实平台、供应商、订单、财务、银行或支付数据。
- 未修改 `rpa-agent/` 或 `docs/04_rpa/`。
- 未连接 BigSeller、Shopee、TikTok/TK、银行或支付平台。
- 未处理、未修改、未纳入本阶段范围的 DOCX 文件继续保留在工作区外侧。

## 7. 待独立复审

本日志不构成架构 PASS。应按 `ui_p6_arch_recheck_prompt.md` 执行 UI-P6-ARCH-R1 独立复审。
