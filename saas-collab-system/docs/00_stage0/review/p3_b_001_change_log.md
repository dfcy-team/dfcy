# P3-B-001 经营总览看板变更日志

## 变更范围

- 新增阶段3经营分析通用页面组件，统一筛选、加载、错误、空态、指标、趋势和明细展示。
- 首页替换为经营总览看板，展示销售额、订单量、可售库存、缺货风险和数据质量状态。
- 新增 `/api/internal/analytics/overview/` 前端封装与 Mock fallback。

## API 状态

- `/api/internal/analytics/overview/`：`mock`。
- 开发A阶段3接口尚未合并，未标记为 `connected`。
- 页面仅展示聚合指标，不执行采购、商品状态、RPA 或资金动作。

## 验证记录

- `npm install`：成功，依赖已是最新，`0 vulnerabilities`。
- `npm run build`：成功，Vite 构建耗时约 7.62 秒。
- 构建观察：Element Plus vendor chunk 约 `923.28 kB`，存在非阻断 chunk size warning。
- API路径扫描：经营总览 API 与页面未发现 `/api/external/*`、`/api/finance/*`、`/api/rpa/*` 或 `/admin/`。
- `frontend/dist`、`frontend/node_modules` 和 `frontend/.npm-cache` 均未被 Git 跟踪。
