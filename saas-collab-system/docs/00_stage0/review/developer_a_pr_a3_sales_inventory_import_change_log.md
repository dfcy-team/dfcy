# 开发A PR-A3 销售与库存离线导入变更日志

任务：`A-PR3-P1-OFFLINE-SALES-INVENTORY-IMPORT`

日期：2026-08-10

Stacked base：`feature/module-a-real-platform-connection`

Base SHA：`75995f74ec74a3315065ecfcec317edda8b1df73`

## 1. 现场与范围

- 开始时确认分支为 `feature/module-a-sales-inventory-import`，HEAD 与固定 Base SHA 一致。
- 初始未跟踪 `backend/apps/marketplace_imports/` scaffold 经逐项审查后确认属于本任务并保留。
- 未修改冻结的 OAuth/callback/refresh/revoke/custody/live provider、finance、purchasing 或 RPA 文件。
- 未使用 `git add -A`；提交将使用明确文件清单。

## 2. 实现

- 新建独立 `marketplace_imports` app 与 migration `0001_initial`。
- 新建 import batch、cursor、order、refund、inventory snapshot 模型；写入只允许 service context，普通 save/update/bulk/delete 被阻断。
- 冻结 `pr-a3-normalized-v1` 严格合同、金额/数量/时间/状态/未知字段校验和 100 条批次/100 行订单上限。
- 实现批次幂等、事件 fingerprint、旧事件跳过、同时间冲突、terminal 状态保护、原子 cursor/watermark/version 推进和 failed batch retry。
- 复用 `integrations.store.view/sync/retry` 与现有 tenant/store data scope；platform/store identity 只从 mapping 恢复。
- 新增内部 API，默认开关关闭；真实 adapter 固定 fail closed，无 HTTP 客户端、webhook、scheduler 或写平台路径。

## 3. 验证

- focused：40 passed。
- backend full：583 passed / 3 MySQL-only skipped。
- frontend：163 passed；production build PASS（1957 modules）。
- Django check、migration drift、SQLite fresh/upgrade、CI guard、credential/forbidden artifact/API boundary scan、`git diff --check`：PASS。
- MySQL 8.4：BLOCKED（Docker daemon 未运行，本机无 mysql CLI），未伪造 PASS。

## 4. 状态与移交

- `A-REAL-PLATFORM-CONNECTION = FAIL / REQUEST CHANGES`
- `Shopee = pending/mock`
- `TikTok Shop = pending/mock`
- `PR-A3 import contract = development / pending-platform-samples`
- `Production synchronization = OFF`
- 真实 API 返回样本待用户后续以脱敏、批准的方式提供；本变更不得用于真实同步。
- PR #41、#42、#43 及本任务新 PR 必须保持 Draft，不合并。
