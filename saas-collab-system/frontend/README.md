# frontend

阶段0前端工程占位，使用 Vue3 + Vite + vue-router + pinia + axios + Element Plus。

## 阶段0边界

- 只提供页面占位、路由、菜单、API封装和 Mock 数据。
- 未完成接口状态必须标记为 `mock` 或 `pending`。
- 前端不承载真实权限判断，真实权限以后端 `/api/internal/auth/me/` 返回的 `roles`、`permissions`、`data_scope` 为准。
- 不连接真实 BigSeller、TK、Shopee 或其他外部平台。
- 不提交真实账号、密码、Token、API Key。

## 本地启动

```bash
npm install
npm run dev
```

默认启用 Mock：

```text
VITE_USE_MOCK=true
VITE_API_BASE_URL=http://localhost:8000
```

## 阶段1 Mock/API 切换

- `VITE_USE_MOCK=true` 时，前端只使用 `frontend/src/mock/` 示例数据。
- `VITE_USE_MOCK=false` 时，前端通过 `frontend/src/api/request.js` 调用 `VITE_API_BASE_URL` 指向的阶段1后端 API。
- `request.js` 统一处理 `{ success, code, message, data }` 响应结构；非标准响应会被包成统一结构。
- API 请求失败时返回带 `message`、`data.api_status=fallback`、`data.api_error` 的 Mock fallback，页面必须展示错误或 fallback 提示。
- 不硬编码真实后端公网地址，不硬编码真实 Token，不写真实账号密码。
- 未实现或未真实联调接口保持 `mock` 或 `pending`，不得标记为 `connected`。

## 阶段1页面联调边界

- 商品页面使用 `/api/internal/products/research/`、`/api/internal/products/spus/`、`/api/internal/products/skus/`、`/api/internal/products/spus/{id}/freeze-code/`。
- 采购页面使用 `/api/internal/purchasing/orders/`。
- 供应商页面使用 `/api/external/supplier/tasks/`、`/api/external/supplier/tasks/{id}/feedback/`、`/api/external/supplier/shipments/`。
- 供应商页面必须以后端 `tenant_id + supplier_id` 过滤为准，前端不做真实权限过滤。
- RPA管理页面是 internal 管理后台页面；若 `/api/internal/rpa/tasks/` 尚未实现，则保持 pending/mock。
- RPA管理页面不调用 `/api/rpa/tasks/claim/`、`heartbeat`、`logs`、`screenshots`、`complete`、`fail` 等 Agent 执行接口，不模拟 RPA Agent token。
- 前端页面不访问 `/admin/`；供应商页面不访问 `/api/internal/*`；RPA页面不访问 `/api/finance/*`。
- 不上传真实附件，不保存真实商品、供应商、订单、物流、财务或平台数据。

## 阶段1构建观察

- 阶段1构建若出现 Vite chunk size warning，暂不阻断交付。
- 后续由架构复审决定是否引入路由懒加载、Element Plus 按需加载或 `manualChunks` 拆包。

## 阶段2 API同步状态页

- 新增 `/integrations/configs`、`/integrations/sync-jobs`、`/integrations/sync-runs` 等页面。
- 页面只展示 Mock/Sandbox 或后端返回的脱敏状态，不展示明文 API Key、API Secret、Token、Cookie 或 Session。
- 生产环境配置默认显示需专项安全评审，不提供真实平台连接测试或生产启用按钮。

## 阶段2商品状态看板

- 新增 `/products/status-dashboard`、`/products/status-recommendations`、`/products/status-transitions`。
- API、RPA 回读和人工来源只生成状态建议，前端不自动确认商品状态。
- 清仓、停售、归档等高风险状态必须显示人工确认和后端授权边界。

## 阶段2财务对账页面

- 新增 `/finance/statements`、`/finance/withdrawals`、`/finance/bank-receipts`、`/finance/reconciliation/matches`、`/finance/reconciliation/exceptions`。
- 所有财务页面只使用 `/api/finance/*`。
- 银行账号仅掩码展示，不接真实银行、支付或真实平台账单，不提供付款、转账或提现按钮。
