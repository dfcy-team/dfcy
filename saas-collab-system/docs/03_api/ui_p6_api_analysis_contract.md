# UI-P6 API接入与分析复盘合同

## 1. 通用响应

成功响应统一为 `success/code/message/data`。错误响应同样保留四个顶层字段，失败时 `success=false`、`data=null`。错误状态覆盖：

- `400`：请求结构、未知查询参数或分页参数错误。
- `401`：未认证或会话失效。
- `403`：角色、permission、tenant 或 data_scope 不满足。
- `404`：资源不存在、跨 tenant 或详情资源超出 data_scope。
- `409`：重复动作、状态冲突或幂等冲突。
- `422`：字段校验或业务规则失败。

聚合分析与财务列表统一使用：

```json
{
  "success": true,
  "code": "OK",
  "message": "success",
  "data": {
    "count": 0,
    "next": null,
    "previous": null,
    "results": [],
    "api_status": "connected",
    "quality": {
      "status": "unknown",
      "score": null,
      "metric_version": null,
      "refreshed_at": null,
      "missing_fields": [],
      "source_summary": []
    }
  }
}
```

`page` 从 1 开始，`page_size` 默认 20、最大 100；超过上限返回 `400`，不得静默截断。所有业务查询由后端使用认证用户的 tenant、exact permission 和 permission-specific data_scope 过滤。前端筛选只能缩小范围，不能扩大范围。

## 2. 页面与API合同

### 2.1 分析、财务、生命周期、工作流与报表

| 页面 | 方法与路径 | 页面权限 | UI-P6状态 |
|---|---|---|---|
| 经营总览 | `GET /api/internal/analytics/overview/` | `analytics.view` | pending |
| 销售归因复盘 | `GET /api/internal/analytics/sales/` | `analytics.view` | pending |
| 库存分析 | `GET /api/internal/analytics/inventory/` | `analytics.view` | pending |
| 指标目录 | `GET /api/internal/analytics/metrics/`、`GET metrics/{id}/` | `analytics.view` | pending |
| 指标聚合 | `GET /api/internal/analytics/aggregates/`、`GET aggregates/{id}/` | `analytics.view` | pending |
| Mock聚合 | `POST /api/internal/analytics/aggregate-mock/` | `analytics.calculate` | mock |
| 财务总览 | `GET /api/finance/analytics/overview/` | `finance.view` | pending |
| 财务对账复盘 | `GET /api/finance/analytics/reconciliation/` | `finance.view` | pending |
| 财务异常复盘 | `GET /api/finance/analytics/exceptions/` | `finance.view` | pending |
| 生命周期建议 | `GET /api/internal/lifecycle/reviews/`、`GET reviews/{id}/` | `products.lifecycle.view` | pending |
| 生命周期历史 | `GET /api/internal/lifecycle/decisions/` | `products.lifecycle.view` | pending |
| Mock生命周期评估 | `POST /api/internal/lifecycle/evaluate-mock/` | `products.lifecycle.evaluate` | mock |
| 生命周期确认/拒绝 | `POST reviews/{id}/confirm/`、`POST reviews/{id}/reject/` | `products.lifecycle.confirm`；高风险追加 `products.lifecycle.high_risk_confirm` | pending |
| 清仓审批列表/详情 | `GET /api/internal/workflow/approvals/?approval_type=clearance`、`GET approvals/{id}/` | `workflow.approvals.view` + `approval_types=clearance` | pending |
| 清仓Mock申请 | `POST /api/internal/workflow/approvals/mock/` | `workflow.approvals.submit` + `approval_types=clearance` | mock |
| 报表目录/导出 | `GET /api/report/catalog/`、`GET/POST /api/report/exports/`、`GET exports/{id}/` | `reports.view` / `reports.export` | pending |
| 导出下载 | `POST /api/report/exports/{id}/download/` | `reports.download` | pending |

### 2.2 integrations 唯一路径

| 能力 | 方法与唯一路径 | 权限 | 状态 |
|---|---|---|---|
| 配置列表/创建 | `GET/POST /api/internal/integrations/configs/` | `integrations.view` / `integrations.manage` | pending |
| 配置详情/修改 | `GET/PATCH /api/internal/integrations/configs/{id}/` | `integrations.view` / `integrations.manage` | pending |
| 禁用配置 | `POST /api/internal/integrations/configs/{id}/disable/` | `integrations.manage` | pending |
| 验证配置 | `POST /api/internal/integrations/configs/{id}/verify/` | `integrations.manage` | pending；production拒绝 |
| 轮换凭据 | `POST /api/internal/integrations/configs/{id}/rotate/` | `integrations.rotate` | pending |
| 同步任务列表/创建 | `GET/POST /api/internal/integrations/sync-jobs/` | `integrations.view` / `integrations.manage` | pending |
| Mock同步 | `POST /api/internal/integrations/sync-jobs/{id}/run-mock/` | `integrations.run` | mock |
| 禁用同步任务 | `POST /api/internal/integrations/sync-jobs/{id}/disable/` | `integrations.manage` | pending |
| 同步运行列表/详情 | `GET /api/internal/integrations/sync-runs/`、`GET sync-runs/{id}/` | `integrations.view` | pending |

`PATCH` 只允许详情路径 `/configs/{id}/`，不存在集合级 PATCH。`verify` 只验证 Mock/Sandbox 配置；HTTP 200、配置 active、凭据指纹或一次 Mock 成功均不代表真实平台已连接。

`pending` 表示尚未获得 UI-P6 受控环境联调证据。只有完成真实会话、权限、tenant、data_scope、异常和页面状态验收后，单个端点才可改为 `connected`。

## 3. 逐端点请求与响应合同

### 3.1 analytics

通用查询参数为 `page`、`page_size`、`period_start`、`period_end`、`granularity`、`metric_code`。时间使用带时区的 ISO 8601；`period_start` 必须早于 `period_end`。端点未列出的参数返回 `400`。

| 端点 | 追加查询参数 | `data.results[]` 必填字段 | `data` 追加字段 |
|---|---|---|---|
| `overview/` | `platform`、`store_id`、`country` | `metric_code`、`metric_name`、`value`、`unit`、`period_start`、`period_end`、`dimensions`、`updated_at`、`metric_version`、`quality_status`、`is_missing`、`source_summary` | `metrics[]`、`trend[]` |
| `sales/` | `platform`、`store_id`、`country`、`product_id`、`sku_id` | 同 overview | `metrics[]`、`trend[]`、`attribution_scope` |
| `inventory/` | `platform`、`store_id`、`country`、`product_id`、`sku_id`、`warehouse_id` | 同 overview | `metrics[]`、`trend[]`、`inventory_scope` |
| `metrics/` | `is_active` | `id`、`metric_code`、`metric_name`、`unit`、`default_granularity`、`metric_version`、`source_type`、`is_sensitive`、`updated_at` | 无 |
| `aggregates/` | `platform`、`store_id`、`country`、`product_id`、`sku_id`、`warehouse_id` | `id`、`metric_code`、`value`、`unit`、`granularity`、`period_start`、`period_end`、`dimensions`、`quality_status`、`is_missing`、`source_summary`、`updated_at`、`metric_version` | 无 |

`metrics/{id}/` 和 `aggregates/{id}/` 返回对应单对象到 `data`，不使用分页。`aggregate-mock/` 请求至少包含 `metric_code`、`period_start`、`period_end`、`granularity` 和 `dimensions`；响应返回生成的聚合对象，不得触发真实平台、采购、RPA、商品状态或资金动作。

`quality` 为端点级质量摘要；每条结果同时保留 `quality_status/is_missing/source_summary`，二者不得互相矛盾。缺失值使用 `null` 且 `is_missing=true`，不得改写为数值 0。

### 3.2 finance analytics

通用查询参数为 `page`、`page_size`、`period_start`、`period_end`、`platform`、`currency`；`reconciliation/` 和 `exceptions/` 可追加 `status`。端点未列出的参数返回 `400`。三个端点均只读，`data.read_only=true`、`data.fund_action_available=false`。

| 端点 | `data.results[]` 必填字段 | `data` 追加字段 |
|---|---|---|
| `overview/` | `period_start`、`period_end`、`platform`、`currency`、`statement_amount`、`receipt_amount`、`difference_amount`、`exception_count`、`account_mask`、`quality_status` | `metrics[]`、`trend[]` |
| `reconciliation/` | `status`、`match_count`、`matched_amount`、`total_difference`、`currency`、`quality_status` | 无 |
| `exceptions/` | `exception_type`、`status`、`exception_count`、`total_difference`、`currency`、`quality_status` | 无 |

旧的 `currencies/statuses/exceptions/items` 顶层变体不得继续作为 UI-P6 合同。后端 serializer 与前端解析必须统一到上述分页和字段结构，完成实际联调前保持 `pending`。

### 3.3 敏感字段

财务账号、凭据、错误日志和导出内容必须由后端先脱敏。前端仅接受 `account_mask`、`credential_mask`、`credential_fingerprint`、`credential_key_version`、`masked_error_message` 和 `masked_log` 等安全字段；禁止返回或显示明文密钥、Token、Cookie、Session、完整银行账号或真实敏感业务数据。

## 4. permission-specific data_scope合同

后端必须按当前端点所要求的 exact permission 调用 permission-specific scope，不得使用把用户全部角色 scope 合并后的全局 scope 替代。

### 4.1 通用语义

- `ALL`：仅表示当前认证 tenant 内全部授权数据，不得跨 tenant。
- `CUSTOM`：同一条 scope 记录内不同 key 采用 AND；同一 permission 的多条 CUSTOM scope 记录采用 OR。
- `OWN`、`DEPARTMENT`：UI-P6 下列模块未冻结相应归属模型，出现时返回 `403 DATA_SCOPE_UNSUPPORTED`，不得默认放行。
- permission 存在但没有 scope、scope 为空、key 非法或值格式非法：返回 `403 DATA_SCOPE_MISSING` 或 `403 DATA_SCOPE_INVALID`。
- 列表查询中的合法筛选值超出 scope：返回 `200` 和空分页，不暴露资源是否存在。
- 详情或动作对象超出 scope：返回 `404 RESOURCE_NOT_FOUND`。
- 请求体主动提交超出 scope 的维度：返回 `403 DATA_SCOPE_FORBIDDEN`。
- 跨 tenant 对象始终返回 `404 RESOURCE_NOT_FOUND`。

### 4.2 exact permission 与 scope key

| 模块/permission | CUSTOM scope key | 值与组合规则 |
|---|---|---|
| `analytics.view`、`analytics.calculate` | `analytics_dimensions` | 对象数组；允许 key 仅为 `platform`、`store_id`、`country`、`product_id`、`sku_id`、`warehouse_id`。对象内 AND，对象间 OR；每个 permission 独立计算。 |
| `products.lifecycle.view/evaluate/confirm/high_risk_confirm` | `spu_ids`、`sku_ids` | 字符串或整数 ID 数组；view/evaluate/confirm 各自过滤。高风险确认必须同时位于 `confirm` 与 `high_risk_confirm` scope。 |
| `workflow.approvals.view/submit/review` | `approval_types` | 字符串数组；UI-P6 清仓仅允许 `clearance`。三种 permission 分别计算，不得互相继承。 |
| `integrations.view/manage/rotate/run` | `platforms`、`integration_config_ids`、`resource_types` | `platforms/resource_types` 为非空字符串数组，`integration_config_ids` 为正整数数组；同一 scope 记录内 AND，多记录 OR。动作按自己的 permission 重新校验，不继承 view scope。 |
| `finance.view` | `platforms`、`currencies` | 均为非空字符串数组，currency 使用大写 ISO 4217；两者同时存在时 AND。财务 tenant 隔离和独立权限先于 scope。 |
| `reports.view/export/download` | `report_types` 及来源模块 scope | `report_types` 仅允许 `analytics_summary`、`inventory_alerts`、`replenishment`、`lifecycle`、`business_alerts`、`finance_summary`；同时与 analytics、lifecycle、finance 等来源资源 scope 取交集。view/export/download 独立校验。 |

后端负责 exact permission scope 解析、过滤、错误码和定向测试；前端只消费 `/api/internal/auth/me/` 返回的权限与可选展示范围，不得自行扩展 scope，也不得把菜单可见性当作授权。

## 5. 路由权限合同

| 前端路由 | 用户类型 | 必需权限 |
|---|---|---|
| `/analytics/overview`、`/analytics/sales`、`/analytics/inventory` | internal | `analytics.view` |
| `/finance/analytics` | internal | `finance.view` |
| `/lifecycle/reviews`、`/lifecycle/history` | internal | `products.lifecycle.view` |
| `/lifecycle/clearance-requests` | internal | `workflow.approvals.view` |
| `/integrations/configs*`、`/integrations/sync-jobs`、`/integrations/sync-runs*` | internal | `integrations.view` |
| `/settings/platform-readiness` | internal | `integrations.view` |
| `/reports/exports` | internal | `reports.view` |

所有非公开路由必须登记在 `routeCapabilities`，未登记路由默认拒绝。详情路由继承资源路由权限。菜单隐藏不等于授权，后端仍执行最终校验。

## 6. 动作权限合同

| 页面动作 | permission | 无权或scope不满足时 |
|---|---|---|
| 运行Mock指标聚合 | `analytics.calculate` | 隐藏且不发送请求 |
| 生命周期Mock评估 | `products.lifecycle.evaluate` | 隐藏且不发送请求 |
| 生命周期确认/拒绝 | `products.lifecycle.confirm` | 隐藏；处理器二次拒绝 |
| 清仓/停售/归档确认 | 上述权限 + `products.lifecycle.high_risk_confirm` | 隐藏；后端再次拒绝 |
| 创建清仓Mock申请 | `workflow.approvals.submit` + `approval_types=clearance` | 仅Mock环境显示 |
| 审核清仓申请 | `workflow.approvals.review` + `approval_types=clearance` | 仅在审批中心显示 |
| 创建/修改/禁用/验证配置 | `integrations.manage` | 隐藏且不发送请求 |
| 轮换凭据 | `integrations.rotate` | 隐藏；不得回显明文 |
| 运行Mock同步 | `integrations.run` | 隐藏；禁止生产执行 |
| 申请报表导出 | `reports.export` | 隐藏且不发送请求 |
| 下载审计占位 | `reports.download` | 隐藏；失败尝试仍由后端留痕 |

财务只读页面不得出现需要 `finance.import`、`finance.reconcile`、`finance.exception.handle` 或资金操作的按钮。

## 7. 高风险状态合同

- 分析指标、库存风险、补货建议、生命周期建议和清仓申请不得直接改变业务状态。
- 清仓审批通过只形成审批结论；商品状态、价格、刊登或 RPA 动作仍需独立合同和人工确认。
- `run-mock` 只运行 Mock/Sandbox adapter，production adapter 保持禁用。
- API接入状态和数据同步状态是两套状态，不得合并为单一“已连接”。
- 前端不得调用 `/api/rpa/*` Agent执行接口、`/admin/` 或非财务页面的 `/api/finance/*`。

## 8. 实施责任

开发A负责最终 URL、serializer、逐端点字段、分页、错误码、tenant、exact permission data_scope、权限、脱敏、审计和状态机；开发B负责前端 API 路径、请求参数、统一响应与分页解析、错误展示、动作权限、字段映射和 `pending/mock/connected` 证据状态。任何一侧未完成验收时，对应能力保持 `pending` 或 `mock`。
