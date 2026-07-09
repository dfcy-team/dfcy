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

## 阶段1 API切换策略

- `VITE_USE_MOCK=true`：前端只使用 `frontend/src/mock/` 数据，不请求后端。
- `VITE_USE_MOCK=false`：前端通过 `frontend/src/api/request.js` 请求 `VITE_API_BASE_URL` 指向的阶段1后端接口；请求失败时回退到 Mock，并在返回 `data.api_status` 中标记 `fallback`。
- `request.js` 统一返回 `{ success, code, message, data }`，后端返回非标准结构时会包成统一格式。
- 未实现接口保持 `pending` 或 Mock fallback，不标记为 `connected`。
- 内部管理页面使用 `/api/internal/*`，供应商协同页面使用 `/api/external/*`，财务页面使用 `/api/finance/*`，报表页面使用 `/api/report/*`。
- RPA管理页面使用 `/api/internal/rpa/*` 占位联调，不调用 RPA Agent 执行接口 `/api/rpa/*`，也不在前端模拟 Agent token。
- 前端不硬编码真实公网后端地址、真实账号、真实密码、真实 Token 或 API Key。

## 阶段1商品页面联调

- 新品市调页面调用 `/api/internal/products/research/` 与 `/api/internal/products/research/{id}/`。
- 商品主数据页面调用 `/api/internal/products/spus/`、`/api/internal/products/spus/{id}/`、`/api/internal/products/skus/`。
- 编码冻结按钮只调用 `/api/internal/products/spus/{id}/freeze-code/`。
- 商品页面继续保留 Mock fallback，并展示 loading、error、empty 和 fallback 提示。
- 商品页面不访问 `/api/external/*`、`/api/finance/*` 或 `/admin/`，不承载真实权限判断，不上传真实附件。

## 阶段1 RPA页面联调

- RPA管理页面使用 `/api/internal/rpa/tasks/` 与 `/api/internal/rpa/tasks/{id}/` 作为管理端查询占位。
- RPA Agent 执行接口 `/api/rpa/*` 只允许 Agent 使用，前端管理页面不调用、不模拟 Agent token。
- RPA页面继续保留 Mock fallback，并展示 loading、error、empty、status 标签、payload/result JSON、日志和截图占位。
- 截图字段只展示 demo URL 或占位引用，不提交真实截图、真实页面快照、真实 Cookie 或 Session。
- 重试按钮、人工接管按钮当前仅为占位，不执行真实自动化，不连接真实 BigSeller。

## 阶段1性能优化观察项

阶段1执行 `npm run build` 时，Vite 构建可通过，但仍存在 chunk size warning。

当前处理策略：

- 阶段1不强制拆包。
- 暂不提交 `frontend/dist/` 构建产物。
- 后续如主包持续增大，再评估路由懒加载、Element Plus 按需加载或 `manualChunks` 分包。
