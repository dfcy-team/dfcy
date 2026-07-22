# frontend

## 销售库存财务对账模块

- 销售总览、销售分析和库存分析复用 `/api/internal/analytics/*`；库存预警与补货建议分别使用 `/api/internal/alerts/inventory/*` 和 `/api/internal/replenishment/recommendations/*`。
- 财务页面只调用 `/api/finance/*`，集合统一解析 `count/next/previous/results`，并展示 loading、empty、error、forbidden 和 degraded 状态。
- 对账 `run-mock` 携带非敏感 `Idempotency-Key`；确认/拒绝使用 `finance.reconcile`，异常处理使用独立 `finance.exception.handle`。前端权限仅改善交互，最终授权和 `data_scope` 以后端为准。
- 银行账号只展示掩码。页面不连接真实平台、银行或支付系统，不执行付款、转账、提现，也不会从补货建议自动创建采购订单。
- `VITE_USE_MOCK=true` 使用合成 Mock；`false` 才请求 `VITE_API_BASE_URL`。Local Sandbox JWT 复验完成前，总接口映射保持 `pending`。

## Phase 3 analytics and decision pages

- Added business overview, sales and inventory analytics, inventory alerts, replenishment suggestions, lifecycle reviews, business alerts, configuration governance, read-only finance analytics, and report export audit guidance.
- All new Phase 3 APIs remain `mock`/`pending` until Development A routes are merged and runtime permission contracts are verified.
- Replenishment never creates purchase orders; lifecycle pages never change product status; alerts never trigger real RPA; finance analytics has no payment, transfer, or withdrawal actions.
- Configuration pages do not expose real credential inputs. Report export requests are placeholders and require backend permission, data-scope, masking, and audit validation.

## Phase 3 build and test

```bash
npm install
npm test
npm run build
```

- Vitest covers the unified response envelope, Phase 3 Mock contracts, route registration, API partitions, high-risk endpoint exclusions, and shared loading/accessibility markers.
- Element Plus components are resolved on demand by Vite instead of registering the full plugin in `main.js`.
- The largest JavaScript chunk is about `108.98 kB`; the previous `923.28 kB` Element Plus chunk and `500 kB` warning are removed.
- Desktop browser smoke checks pass. The application includes a `900px` mobile navigation breakpoint; a real narrow viewport retest remains a release observation because the in-app viewport override did not apply during verification.

## Phase 2 frontend build observation

- Route pages are lazy loaded in `frontend/src/router/index.js`.
- Vite `manualChunks` splits `vue`, `element-plus`, and `axios` vendor bundles.
- `npm run build` succeeds after the split. The original main app chunk dropped from about `1,164.29 kB` to about `12.71 kB`.
- A remaining non-blocking chunk warning is caused by the full `element-plus` vendor chunk, about `923.26 kB`. Future optimization can evaluate Element Plus on-demand imports or deeper manual chunks.

## Phase 2 platform access risk placeholders

- Added read-only routes:
  - `/settings/platform-risk`
  - `/settings/platform-readiness`
  - `/settings/security-review`
- These pages only use Mock placeholder data from `frontend/src/mock/platformRisk.js`.
- They do not provide real Token, Cookie, Session, API Key, API Secret, account, password, bank, or payment configuration inputs.
- They do not provide production connect buttons, real OAuth redirects, or real platform SDK calls.
- Production access is shown as disabled until a dedicated security review is completed.

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

## 阶段2供应商绩效页面

- 内部绩效页面使用 `/api/internal/suppliers/performance/*`。
- 供应商自己的绩效页面使用 `/api/external/supplier/performance/*`，不得传入其他 `supplier_id`。
- 供应商身份与 `tenant_id + supplier_id` 过滤以后端为准，前端不承载可信权限过滤。

## 阶段2 RPA失败转人工页面

- 新增 `/rpa/stability`、`/rpa/attempts`、`/rpa/manual-queue`、`/rpa/account-locks`、`/rpa/page-signatures`。
- 页面是 internal 管理页面，只使用 `/api/internal/rpa/*` pending/mock 管理接口。
- 不模拟 RPA Agent token，不调用 `/api/rpa/tasks/claim/`、heartbeat、logs、screenshots、complete、fail 等 Agent 执行动作。
- evidence/screenshot 仅使用 demo 或 placeholder，不连接真实 BigSeller。
