# Shopee / TikTok Shop 授权基础测试报告

## 1. 测试范围

覆盖 tenant/store/platform 隔离、全局门店唯一、状态机与 bulk 绕过、引用原子轮换、raw credential 拒绝、审计不可变、六个 exact action permission、CUSTOM scope、401/403/404/409/422、分页/空数据、旧字段迁移和既有 integrations/sync 回归。

所有测试数据均为 `demo`、`synthetic`、`mock` 或 `placeholder`，未使用真实平台数据或凭据。

## 2. 自动化结果

| 命令/范围 | 结果 |
|---|---|
| 授权基础 + secure config + integrations model + UI-P2 回归 | 60 passed |
| 授权基础 + secure config + sync framework | 53 passed |
| 后端全量 pytest | 433 passed in 53.45s（最终 HEAD） |
| 前端 Vitest | 12 files、160 tests passed |
| Vite build | 成功，1955 modules；无 chunk size warning |

## 3. 数据库与权限

- 全新临时 SQLite 数据库从零应用全部迁移成功。
- `integrations.0007` 反向到 `0006` 后再次前向到 `0007` 成功。
- `makemigrations --check --dry-run` 无遗漏。
- `sync_permissions --check` 通过。
- 数据迁移专项测试确认：synthetic/mock 可转换；未知内容中止；异常和标准输出不包含待迁移值。
- MySQL 可移植性专项测试确认迁移不含 backend-specific `RunSQL`，但 Docker engine 未运行，未获得 MySQL 8.4 容器执行成功证据。

## 4. 安全与制品

- `backend/scripts/ci_guard.py`：PASS。
- API 扫描未发现新增 finance、RPA Agent、admin 或真实平台调用。
- `frontend/dist`、`frontend/node_modules`、`.npm-cache`、数据库、日志、截图和 `.env` 均未被 Git 跟踪。
- `npm audit`：完整依赖树 2 high（`brace-expansion`、`postcss`）；production 树 1 high（`postcss`）。本任务禁止修改 frontend，记录为非本 PR 修复项。

## 5. Sandbox

- `sandbox.ps1 contract integration`：PASS。
- `sandbox.ps1 verify integration`：未完成，Docker Desktop Linux engine 未运行，启动镜像前即失败。
- 未连接真实 Sandbox 店铺、真实平台、银行、支付或 VM。

## 6. 结论

本地代码、SQLite 迁移、权限、后端全量、前端回归和合同检查通过。MySQL 容器运行与远端 CI 仍需补证，因此能力继续标记为 `pending/mock`，不得标记 `connected`。
