# 阶段3前端 API 契约

## 状态规则

- `connected`：后端路径存在，且已完成响应、权限和页面联调验证。
- `pending`：规划中但后端尚未提供或尚未完成权限验证。
- `mock`：页面当前通过 `VITE_USE_MOCK=true` 使用示例数据。

阶段3开发A接口尚未合并，因此本文件中的阶段3新增前端路径均为 `mock`，对应真实接口为 `pending`，没有 `connected` 项。

## 路径清单

| 模块 | 方法与路径 | 页面状态 | 真实接口状态 | 边界 |
|---|---|---|---|---|
| 经营总览 | `GET /api/internal/analytics/overview/` | mock | pending | 只读聚合 |
| 销售分析 | `GET /api/internal/analytics/sales/` | mock | pending | tenant + data_scope |
| 库存分析 | `GET /api/internal/analytics/inventory/` | mock | pending | 只读钻取 |
| 库存预警 | `GET /api/internal/replenishment/alerts/` | mock | pending | 不自动补货 |
| 补货建议 | `GET /api/internal/replenishment/suggestions/` | mock | pending | 不创建采购单 |
| 生命周期复盘 | `GET /api/internal/lifecycle/reviews/` | mock | pending | 不改变商品状态 |
| 生命周期历史 | `GET /api/internal/lifecycle/history/` | mock | pending | 只读审计 |
| 经营预警 | `GET /api/internal/alerts/` | mock | pending | 不触发真实 RPA/付款 |
| 配置项 | `GET /api/internal/config/items/` | mock | pending | 不返回敏感值 |
| 配置版本 | `GET /api/internal/config/versions/` | mock | pending | 版本/审批/回滚只读展示 |
| 财务分析 | `GET /api/finance/analytics/overview/` | mock | pending | 聚合脱敏，只读 |
| 报表导出 | `GET /api/report/exports/` | mock | pending | 导出权限与审计提示 |

## 不变边界

- 所有响应使用 `{ success, code, message, data }`。
- 前端不承担真实权限、tenant 或 data_scope 判断。
- 建议、预警和配置页面不提供真实高风险执行能力。
- 财务分析只使用 `/api/finance/analytics/*`。
- 报表导出只使用 `/api/report/*`，申请按钮在后端接口提供前保持占位。
- 不连接真实平台、银行或支付服务，不提交真实凭据或业务数据。
