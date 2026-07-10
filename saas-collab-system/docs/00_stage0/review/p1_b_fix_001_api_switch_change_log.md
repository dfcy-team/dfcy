# P1-B-FIX-001-A Mock/API切换整改记录

## 整改内容

- 更新 `frontend/src/api/request.js`：
  - 保留 `VITE_USE_MOCK`。
  - 保留 `VITE_API_BASE_URL`。
  - `VITE_USE_MOCK=true` 时使用 Mock。
  - `VITE_USE_MOCK=false` 时调用阶段1后端 API。
  - 统一响应结构为 `{ success, code, message, data }`。
  - API失败时返回带 `message`、`data.api_status=fallback`、`data.api_error` 的 Mock fallback。
- 更新 `frontend/src/api/*.js`，接入 `requestWithMockFallback`。
- 更新 `frontend/src/mock/index.js`，默认未实现接口状态为 `pending`，不误标 `connected`。
- 更新 `frontend/README.md`，补充阶段1 Mock/API 切换说明。

## 路径边界

- 商品：`/api/internal/products/research/`、`/api/internal/products/spus/`、`/api/internal/products/skus/`、`/api/internal/products/spus/{id}/freeze-code/`
- 采购：`/api/internal/purchasing/orders/`
- 供应商：`/api/external/supplier/tasks/`、`/api/external/supplier/tasks/{id}/feedback/`、`/api/external/supplier/shipments/`
- RPA管理：`/api/internal/rpa/tasks/` pending/mock，不调用 Agent 执行接口。

## 安全确认

- 未硬编码真实后端公网地址。
- 未硬编码真实 Token。
- 未写真实账号密码。
- 未将 pending 接口标记为 connected。
