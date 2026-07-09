# P1-B-001 Change Log

## Task

前端从 Mock 切换到阶段1 API 联调策略。

## Preconditions

- 当前分支：`feature/phase1-b-frontend-api-integration`
- 当前 HEAD 未在 `feature/ar0-001-stage0-file-scope` 分支上开发。
- 本次变更未修改 `backend/`、`rpa-agent/`、`docs/04_rpa/`、`.env.example`。

## Input Documents

- 已读取：`docs/00_stage0/frontend_api_mapping.md`
- 缺失：`docs/03_api/phase1_api_priority.md`
- 缺失：`docs/01_architecture/phase1_mvp_scope.md`

## Changes

- `frontend/src/api/request.js`
  - 保留 `VITE_USE_MOCK` 和 `VITE_API_BASE_URL`。
  - 增加统一响应规整，返回 `{ success, code, message, data }`。
  - `VITE_USE_MOCK=true` 时直接使用 Mock。
  - `VITE_USE_MOCK=false` 时请求阶段1后端接口，请求失败后 fallback 到 Mock。

- `frontend/src/api/*.js`
  - 登录和内部管理页面使用 `/api/internal/*`。
  - 供应商协同页面使用 `/api/external/supplier/*`。
  - 财务页面使用 `/api/finance/*`。
  - 报表页面使用 `/api/report/*`。
  - RPA管理页面使用 `/api/internal/rpa/*` 占位联调，不调用 RPA Agent 执行接口 `/api/rpa/*`。

- `frontend/src/mock/index.js`
  - 默认 pending response 标记为 `pending`，避免未实现接口被误标为 connected。

- `frontend/README.md`
  - 增加阶段1 API切换策略说明。

## API Status

- 已接入阶段1联调路径并保留 Mock fallback：
  - `auth`
  - `products`
  - `purchasing`
  - `suppliers`
  - `listings`
  - `pricing`
  - `integrations`
  - `finance`
  - `reports`
  - `audit`
  - `rpa`

- 当前状态仍按 `mock` 或 `pending` 处理，未将 pending 接口标记为 connected。

## Boundary Notes

- 未硬编码真实后端公网地址。
- 未硬编码真实 Token。
- 未写入真实账号密码。
- 未连接 BigSeller、Shopee、TikTok 或其他真实平台。
- 前端不承载真实权限判断，真实权限以后端 `/api/internal/auth/me/` 返回为准。
- 前端 RPA管理页面与 RPA Agent 执行接口保持隔离，未模拟 Agent token。

## Validation

- `rg "/api/internal|/api/finance|/admin" frontend/src/api/suppliers.js`：无结果。
- `rg "/api/finance|/admin|RPA_AGENT_TOKEN|Authorization|tasks/claim|heartbeat|complete|fail" frontend/src/api/rpa.js`：无结果。
- `git diff --name-only -- backend docs/04_rpa rpa-agent .env.example docker-compose.yml`：无结果。
- `git ls-files --others --exclude-standard frontend/dist`：无结果。

## Build Result

- 已执行：`cd frontend && npm run build`
- 结果：构建通过。
- 观察项：
  - Rollup 移除了 `@vueuse/core` 中位置不合规的 `/* #__PURE__ */` 注释。
  - 仍存在 Vite chunk size warning：`dist/assets/index-3VcIdeTk.js` 约 `1,101.25 kB`，gzip 后约 `364.95 kB`。
  - 阶段1不强制拆包，继续按 `frontend/README.md` 的性能优化观察项跟踪。
