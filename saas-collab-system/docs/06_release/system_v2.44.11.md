# SaaS 协同系统 V2.44.11 生产构建修复登记

- 登记日期：2026-08-13
- 父版本：V2.44.10
- 菜单基线：V2.44.7 / `76ba2c151efa59c4a3a8f153e2d9ca04fd0f8a0e`
- 发布状态：已登记并部署

## 修复范围

V2.44.10 的生产站点曾使用 Mock 构建参数，导致运行时按 Mock 用户权限过滤菜单。V2.44.11 仅修正前端生产构建参数：

```text
VITE_USE_MOCK=false
VITE_API_BASE_URL=
```

本次登记不修改菜单、路由、权限业务逻辑或后端。生产 bundle 走真实认证请求（`/api/internal/auth/login/`、`/api/internal/auth/me/`），不走 Mock 登录分支；既有 V2.44.10 菜单基线及基础档案授权的两项子菜单保持不变。

## 验证证据

- Vite production build：PASS（2014 modules transformed）
- 前端全量测试：12 files / 164 tests PASS
- bundle 入口：`frontend/dist/assets/index-DMpkarLV.js`
- bundle 入口 SHA-256：`92a79ca08fe1cc8af02e26a69e1bbb4dde6b4bf3b9e9231f613ade6c6b7ed41c`
- bundle 中未包含 `mockLogin`、`useMock` 或 `pendingResponse` 分支；认证端点保留真实 `/api/internal/auth/*` 请求
- 已部署前端镜像：`saas-collab-frontend:v2.44.11@sha256:51697ae417666daefbdd4925b260639f2645de0ff001a2b90539c5a5998f930e`
