# Shopee / TikTok Shop 授权基础测试报告

## 1. 测试范围

覆盖 tenant/store/platform 隔离、全局门店唯一、状态机与 bulk 绕过、引用原子轮换、raw credential 拒绝、审计不可变、六个 exact action permission、CUSTOM scope、401/403/404/409/422、分页/空数据、旧字段迁移和既有 integrations/sync 回归。

所有测试数据均为 `demo`、`synthetic`、`mock` 或 `placeholder`，未使用真实平台数据或凭据。

## 2. 自动化结果

| 命令/范围 | 结果 |
|---|---|
| A1 定向回归 | 78 passed；MySQL 并发用例在 SQLite 跳过 |
| MySQL 并发引用轮换 | 1 passed |
| 后端全量 pytest | 本地 SQLite 439 passed / 1 MySQL-only skipped；MySQL 并发专项另行通过 |
| 前端 Vitest | 12 files、160 tests passed |
| Vite build | 成功，1955 modules；无 chunk size warning |

## 3. 数据库与权限

- 迁移拆分为 `0007` 新增结构、`0008` 全量预检与转换、`0009` 条件删除旧列。
- `makemigrations --check --dry-run` 无遗漏。
- `sync_permissions --check` 通过。
- 数据迁移专项确认：仅显式批准 Mock provenance 可转换；`live-example-credential` 不会因关键字误命中；混合安全/未知批次在首个业务写入前中止。
- MySQL 8.4.10：全新全量迁移成功；安全 Mock 各转换 1 条；未知混合批次 `platform_reference_writes=0`、`api_reference_writes=0`、`0008` 登记数为 0；修正 provenance 后重跑成功；旧列余数为 0；待处理 metadata lock 为 0。
- 已执行旧版 `0007` 且旧列已删除的 Local Sandbox 数据卷可继续应用 `0008/0009`，无需 reset 数据卷。

## 4. 安全与制品

- `backend/scripts/ci_guard.py`：PASS。
- API 扫描未发现新增 finance、RPA Agent、admin 或真实平台调用。
- `frontend/dist`、`frontend/node_modules`、`.npm-cache`、数据库、日志、截图和 `.env` 均未被 Git 跟踪。
- `npm audit`：完整依赖树 2 high（`brace-expansion`、`postcss`）；production 树 1 high（`postcss`）。本任务禁止修改 frontend，记录为非本 PR 修复项。

## 5. Sandbox

- `sandbox.ps1 contract integration`：PASS。
- `sandbox.ps1 verify integration`：PASS；最终代码容器内 MySQL 后端 440 passed、前端 160 passed、Vite build 成功。
- 未连接真实 Sandbox 店铺、真实平台、银行、支付或 VM。

## 6. 结论

本地代码、MySQL 8.4 迁移与并发、权限、后端全量、前端回归、生产构建和 Local Sandbox integration 均通过。真实 Shopee/TikTok Shop 未接入，能力继续标记为 `pending/mock`，不得标记 `connected`；远端 CI 仍需在整改提交推送后复核。
