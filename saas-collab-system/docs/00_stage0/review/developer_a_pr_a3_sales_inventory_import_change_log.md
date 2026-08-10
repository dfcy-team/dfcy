# 开发A PR-A3 销售与库存离线导入变更日志

任务：`A-PR3-P1-OFFLINE-SALES-INVENTORY-IMPORT`

日期：2026-08-10

```text
Repository: dfcy-team/dfcy
PR: #45
PR URL: https://github.com/dfcy-team/dfcy/pull/45
Branch: feature/module-a-sales-inventory-import
Base Branch: feature/module-a-real-platform-connection
Base SHA: 75995f74ec74a3315065ecfcec317edda8b1df73
Code Review SHA: c33f2a6b5341eb57e59df2f3e798b95fab64028e
Remote CI SHA: c33f2a6b5341eb57e59df2f3e798b95fab64028e
Migration Head: marketplace_imports.0002_marketplaceimportbatch_active_attempt_id_and_more
PR State: OPEN / Draft / Unmerged
```

Evidence HEAD 为包含本日志、测试报告和复审报告的后续 evidence-only 提交；它不改变 `Code Review SHA` 的运行时代码。

## 1. 范围

- 新建独立 `marketplace_imports` app、normalized synthetic/offline 合同和内部 API。
- 未修改冻结的 OAuth/callback/refresh/revoke/custody/live provider 安全边界。
- 未加入 scheduler、正式 webhook、历史回补、平台写接口、finance、purchasing 或 RPA 能力。
- 未使用 `git add -A`；提交均使用明确文件清单。

## 2. 原始实现

- migration `0001_initial` 创建 import batch、cursor、order、refund、inventory snapshot 模型。
- 实现批次幂等、事件 fingerprint、旧事件跳过、同时间冲突、terminal 状态保护、原子 cursor/watermark/version 推进。
- 复用 `integrations.store.view/sync/retry` 和现有 tenant/store data scope。
- synthetic/offline 开关默认关闭；真实 adapter 固定 fail closed。

## 3. R2 整改

- migration `0002_marketplaceimportbatch_active_attempt_id_and_more` 为批次增加 `attempt_version`、`active_attempt_id`，并创建 append-only `MarketplaceImportBatchAttempt`。
- failed retry 在同一事务内通过 `select_for_update()` 认领；锁内重新检查 completed/processing/failed 状态。
- 每次认领生成新的 attempt ID 和单调递增版本；只有 active attempt owner 能提交 success/failure。
- stale owner 不得把 completed 批次改回 failed，也不得覆盖 cursor 或业务记录。
- 重试审计记录 batch、tenant、store、actor、action、attempt/version、前后状态、结果、受控错误码和时间；不保存 raw payload 或凭据。
- 增加 completed duplicate、stale owner、append-only audit 和 MySQL 双 worker concurrent retry 测试。
- API 合同空数组示例已替换为可执行的完整 synthetic order。

## 4. 验证

- Django check：PASS。
- migration drift：PASS，No changes detected。
- SQLite fresh migration：PASS，包含 `marketplace_imports.0002`。
- SQLite upgrade `0001 -> 0002`：PASS。
- focused：42 passed / 1 MySQL-only skipped。
- backend full：585 passed / 4 MySQL-only skipped / 5 warnings。
- frontend：13 files / 163 tests PASS。
- production build：PASS，1957 modules。
- CI guard、credential scan、forbidden artifact scan、API boundary scan、`git diff --check`：PASS。
- 远程 Phase 2 run `31366790607`：5/5 jobs success。
- 远程 Phase 3 run `31366790595`：5/5 jobs success。
- MySQL 8.4：BLOCKED。Docker Desktop 创建 WSL VM 时返回 `HCS/0x800705aa` 资源不足；fresh/upgrade、聚焦/全量和双 worker 测试均未运行，未伪造 PASS。

## 5. 状态与移交

- R1 P1-001 代码整改完成；其 MySQL 并发实测并入仍开放的 P1-002。
- R1 三项 P2 已关闭。
- Open P1：1（MySQL 8.4 必需验证）。
- `A-REAL-PLATFORM-CONNECTION = FAIL / REQUEST CHANGES`。
- `Shopee = pending/mock`。
- `TikTok Shop = pending/mock`。
- `Production synchronization = OFF`。
- `Real platform API = NOT CALLED`。
- PR #45 保持 Draft、不合并；MySQL 门禁关闭后进行 R3 完整复审。
