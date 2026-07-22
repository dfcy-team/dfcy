# 模块化开发 API 与权限合同

## 1. 通用合同

成功响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "success",
  "data": {}
}
```

列表响应的 `data` 必须包含 `count`、`next`、`previous` 和 `results`。错误响应必须保持 `success=false`、稳定业务 `code`、可展示 `message` 和 `data=null`。

| HTTP | 含义 |
|---|---|
| 400 | 请求结构、未知查询参数或分页参数错误 |
| 401 | 未认证或会话失效 |
| 403 | 角色、权限、tenant 或 `data_scope` 不足 |
| 404 | 资源不存在或详情越权隐藏 |
| 409 | 重复操作、幂等或状态冲突 |
| 422 | 字段或业务规则校验失败 |

所有写操作必须声明 action permission、幂等策略、合法状态迁移和审计字段。通用 `PATCH` 不得修改状态、tenant、owner、财务范围或其他授权归属字段。

## 2. 开发A合同

开发A复用以下已实现路径，不新增同义资源：

| 能力 | 路径 | 权限 | 状态 |
|---|---|---|---|
| 经营总览 | `GET /api/internal/analytics/overview/` | `analytics.view` | 已实现，需模块联调确认 |
| 销售分析 | `GET /api/internal/analytics/sales/` | `analytics.view` | 已实现，需模块联调确认 |
| 库存分析 | `GET /api/internal/analytics/inventory/` | `analytics.view` | 已实现，需模块联调确认 |
| 指标目录/聚合 | `GET /api/internal/analytics/metrics/*`、`aggregates/*` | `analytics.view` | 已实现 |
| 合成聚合 | `POST /api/internal/analytics/aggregate-mock/` | `analytics.calculate` | mock |
| 库存预警 | `/api/internal/alerts/inventory/*` | `alerts.view/evaluate/manage` | 已实现 |
| 补货建议 | `/api/internal/replenishment/recommendations/*`、`evaluate-mock/` | `replenishment.view/evaluate/review` | 已实现；仅建议 |
| 财务分析 | `GET /api/finance/analytics/{overview,reconciliation,exceptions}/` | `finance.view` | 已实现，需独立财务联调 |
| 财务数据 | `/api/finance/{statements,withdrawals,bank-receipts}/*` | `finance.view`、`finance.import` | 仅 demo/synthetic 导入 |
| 对账建议 | `/api/finance/reconciliation/*` | `finance.view`、`finance.reconcile`、`finance.exception.handle` | 不执行资金操作 |
| 报表 | `/api/report/{catalog,exports}/*` | `reports.view`、`reports.export`、`reports.download` | 脱敏并审计 |

`analytics.view/calculate` 的 CUSTOM scope 使用 `analytics_dimensions`，只允许 `platform`、`store_id`、`country`、`product_id`、`sku_id`、`warehouse_id`。`finance.view` 使用 `platforms` 和大写 ISO 4217 `currencies`，每个 action permission 独立求值，不能继承 view scope。

本期如需新增库存流水或销售明细端点，必须先更新本合同和总接口映射，初始状态为 `pending`；不得为了页面方便在前端跨 tenant 或跨权限拼接数据。

## 3. 开发B合同

达人模块统一使用 `/api/internal/creators/*`，正式资源冻结如下。当前后端尚未实现，状态均为 `pending`；Local Sandbox `/mock/creator-management/*` 保持 `mock`。

| 能力 | 方法与路径 | 权限 | 状态 |
|---|---|---|---|
| 达人档案列表/创建 | `GET/POST /api/internal/creators/profiles/` | `creator.view/manage` | pending |
| 达人档案详情/非状态字段修改 | `GET/PATCH /api/internal/creators/profiles/{id}/` | `creator.view/manage` | pending |
| 档案状态动作 | `POST .../profiles/{id}/{activate,pause,archive}/` | `creator.manage` | pending |
| 合作列表/创建 | `GET/POST /api/internal/creators/collaborations/` | `creator.collaboration.view/manage` | pending |
| 合作详情 | `GET/PATCH /api/internal/creators/collaborations/{id}/` | `creator.collaboration.view/manage` | pending |
| 合作审核动作 | `POST .../collaborations/{id}/{submit,approve,reject,cancel,complete}/` | `creator.collaboration.manage/review` | pending |
| 合作任务 | `GET/POST /api/internal/creators/tasks/`、`GET/PATCH .../{id}/` | `creator.task.view/manage` | pending |
| 效果聚合 | `GET /api/internal/creators/performance/` | `creator.performance.view` | pending |

需新增并迁移的权限码为：

- `creator.view`
- `creator.manage`
- `creator.collaboration.view`
- `creator.collaboration.manage`
- `creator.collaboration.review`
- `creator.task.view`
- `creator.task.manage`
- `creator.performance.view`

CUSTOM scope 统一使用 `creator_dimensions` 对象数组。对象允许 key 仅为 `platform`、`country`、`creator_id`、`collaboration_id` 和 `campaign_code`；对象内 AND、对象间 OR。未知 key、非法类型、空越权值或超授权值返回 `403 DATA_SCOPE_INVALID` 或 `DATA_SCOPE_FORBIDDEN`。缺失 scope 不等于 ALL；只有显式 ALL scope 可访问 tenant 内全部授权资源。

档案状态合法迁移：`candidate -> active -> paused -> active -> archived`；`archived` 为终态。合作状态合法迁移：`draft -> submitted -> approved|rejected`，`approved -> active -> completed`，非终态可按合同进入 `cancelled`。提交人不得审批自己的合作；状态只能经 action 端点变化，模型直接写入、通用 PATCH 和 bulk 更新不得绕过。

达人联系方式、账号标识和备注按敏感字段处理：默认掩码，不进入列表、日志、异常或导出。本期不包含达人结算、付款、真实消息触达、爬取、登录、平台 API 或真实账号同步。

## 4. Mock 与 connected 规则

- `/mock/sales-inventory-finance-reconciliation/*` 和 `/mock/creator-management/*` 只使用合成数据。
- 达人 Mock 只允许 GET；写请求返回 405，未知路径返回 404。
- `VITE_USE_MOCK=true` 使用对应 Mock；`false` 才允许请求本合同中的本地后端路径。
- 非统一 HTTP 200 响应不得包装为成功。
- 只有 JWT 会话、200/401/403/404/409/422、tenant、`data_scope` 和 action permission 联调均有测试证据后，映射状态才能改为 `connected`。

## 5. 禁止合同

- 供应商页面不得调用 `/api/internal/*`；RPA Agent 只能访问 `/api/rpa/*`。
- 达人模块不得访问 `/api/finance/*`、`/admin/` 或 RPA Agent 执行端点。
- 财务页面只使用 `/api/finance/*` 或经授权的 `/api/report/*`。
- 不存在真实平台 adapter、真实银行/支付接口或高风险自动化放行。
