# P1-B-FIX-005 接口映射文档整改记录

## 整改内容

- 更新 `docs/00_stage0/frontend_api_mapping.md`。
- 商品模块改为阶段1后端路径：
  - `/api/internal/products/research/`
  - `/api/internal/products/spus/`
  - `/api/internal/products/skus/`
  - `/api/internal/products/spus/{id}/freeze-code/`
- 采购模块改为 `/api/internal/purchasing/orders/`。
- 供应商模块改为：
  - `/api/external/supplier/tasks/`
  - `/api/external/supplier/tasks/{id}/feedback/`
  - `/api/external/supplier/shipments/`
- RPA模块明确前端管理后台不直接使用 Agent 执行接口。
- `/api/internal/rpa/tasks/` 管理查询接口标记为 `pending`。

## 状态规则

- `connected`：已真实调用后端且路径存在。
- `mock`：未真实联调但有 Mock fallback。
- `pending`：后端暂未提供接口或管理查询接口。
- 未将 pending 误标 connected。
