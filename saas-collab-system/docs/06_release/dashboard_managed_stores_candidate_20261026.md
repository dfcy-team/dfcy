# 工作台本月每日销售增长率：按可管理店铺切换

2026-10-26 开发候选，尚未部署阿里云。

## 行为

先按 `sales_management.view` 的实际销售资源数据范围过滤，再匹配店铺档案的负责运营、BD、组长与当前用户 ID。普通用户即使拥有“全部销售数据”，也只能在本图表查看其管理的店铺；超级管理员保留租户内全店查看能力。没有人员匹配时不退回全量数据。

默认显示“全部可管理店铺”汇总，可切换单店。无销售的店铺也可选择。币种独立展示，保持原来的非取消订单、月初与上月最后一天比较以及店铺时区口径。

接口 `/api/internal/commerce/dashboard/monthly-sales/` 增加可选 `store_id`。返回增加 `stores`（id、code、name、platform_store_name）及 `selected_store_id`。无权访问的店铺返回 403；非法或重复 ID 返回 400。仅影响工作台图表，销售列表及报表沿用原有授权。

## 显示效率

店铺选项直接查询档案表，不依赖订单存在性，不扫描历史订单。请求内复用权限解析结果；同一请求返回店铺选项和图表数据，避免逐店预加载。统计通过租户、店铺、本月与月初前一天的 UTC 时间范围收窄，可利用既有 `idx_sales_order_store_time` 索引。币种切换仅在前端计算；店铺切换重新查询，旧响应不会覆盖新选择。不设置跨请求权限缓存。

## 验证

- 后端：`python -m pytest tests/test_dashboard_monthly_sales_20261016.py tests/test_sales_filter_catalog.py tests/test_report_resource_scope.py -q --disable-warnings --nomigrations`，31 项通过。使用本地 SQLite 创建测试模型表，未执行历史迁移。
- 前端：`npx vitest run tests/dashboard-monthly-growth.spec.js`，7 项通过。
- `npm run build`：菜单权限快照检查与生产构建通过。
- Playwright 本地测试数据：1440px 桌面、390px 窄屏、切换无销售店铺后切回、页面无水平溢出；浏览器无错误与警告。
- 性能结构检查：请求内权限解析完成后，店铺选项仅一次主数据查询，SQL 不包含销售订单表。

本次没有修改线上权限、业务数据或发布版本；尚未测量阿里云真实数据量下的响应耗时。
