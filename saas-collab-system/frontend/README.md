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
