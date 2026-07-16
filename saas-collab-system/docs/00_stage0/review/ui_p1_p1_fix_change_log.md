# UI-P1 R1 P1定向整改变更日志

## 1. 整改目标

本次定向关闭 `UI-P1-ARCH-R1` 的两项P1：

1. `UI-P1-R1-P1-001` 非公开路由合同不完整且未登记路径默认放行。
2. `UI-P1-R1-P1-002` 按钮和动作权限未按后端 action permission 收敛。

## 2. 路由权限整改

- 新增完整 `routeCapabilities` 合同，覆盖 `router/index.js` 中全部非公开路由。
- 路由合同显式声明 `userTypes`、permissions和详情页继承规则。
- `canAccessPath()` 改为未登记路径默认拒绝。
- `/finance/imports` 独立要求 `finance.import`，不再被 `finance.view` 放行。
- finance、integrations、reports、config、analytics、alerts、replenishment和商品状态页面使用对应后端权限码。
- 供应商任务和出货页面限制为external；内部业务、治理和RPA管理页面限制为internal。
- 财务菜单增加导入、提现、到账和异常入口，并按 `finance.import`/`finance.view` 分别过滤。

## 3. 动作权限整改

- 新增 `frontend/src/utils/actionAccess.js`，统一解析动作权限、显示策略、禁用状态和拒绝原因。
- `Phase2DataPage` 与 `Phase3DecisionPage` 通过认证store的 `hasPermission()` 过滤动作。
- 未授权动作默认隐藏；可选配置为禁用并显示缺失权限原因。
- 点击处理器执行前再次检查权限，未授权时不调用API。
- 已为补货复核、生命周期确认、预警管理、配置管理/回滚、报表导出、财务对账、商品状态确认和API同步动作绑定后端权限码。
- 敏感字段仍只消费后端脱敏结果，未新增仅靠CSS隐藏的保护逻辑。

## 4. 修改文件

- `frontend/src/router/menu.js`
- `frontend/src/utils/actionAccess.js`
- `frontend/src/components/Phase2DataPage.vue`
- `frontend/src/components/Phase3DecisionPage.vue`
- `frontend/src/views/alerts/BusinessAlertList.vue`
- `frontend/src/views/finance/ReconciliationMatchDetail.vue`
- `frontend/src/views/finance/ReconciliationMatchList.vue`
- `frontend/src/views/integrations/SyncJobList.vue`
- `frontend/src/views/inventory/ReplenishmentSuggestionList.vue`
- `frontend/src/views/lifecycle/LifecycleReviewList.vue`
- `frontend/src/views/products/ProductStatusRecommendationDetail.vue`
- `frontend/src/views/reports/ReportExportCenter.vue`
- `frontend/src/views/settings/ConfigCenterList.vue`
- `frontend/src/views/settings/ConfigVersionHistory.vue`
- `frontend/tests/ui-p1-foundation.spec.js`
- `docs/00_stage0/frontend_api_mapping.md`
- `docs/05_test/ui_p1_foundation_test_report.md`

## 5. P1关闭证据

| 原P1 | 整改状态 | 证据 |
|---|---|---|
| UI-P1-R1-P1-001 | 待R2确认关闭 | `routeCapabilities` 全路由登记、未知路径默认拒绝、finance import和internal/external直接URL测试 |
| UI-P1-R1-P1-002 | 待R2确认关闭 | 通用action access、页面动作权限码、view-only动作拒绝测试、点击前二次校验 |

## 6. 测试结果

- UI-P1专项：28 passed。
- 前端全量Vitest：3 files，61 passed。
- 前端生产构建：PASS，1873 modules transformed。
- Vite第三方PURE注释提示继续作为P2观察项，不阻断本次P1整改。

## 7. 安全确认

- 未修改后端权限实现，后端tenant、data_scope和action permission仍为最终安全边界。
- 未提交真实账号、密码、Token、Cookie、Session、API Key或API Secret。
- 未接入真实平台、真实银行或支付系统。
- 未启用自动采购、自动清仓、自动改价、真实RPA或资金操作。

## 8. 待复审事项

由架构员执行 `UI-P1-ARCH-R2`，独立确认两项原P1是否关闭。R2通过前，不将UI-P1标记为正式收尾。
