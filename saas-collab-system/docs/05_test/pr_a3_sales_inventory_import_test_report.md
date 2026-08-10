# PR-A3 销售与库存离线导入测试报告

日期：2026-08-10

```text
PR: #45
Branch: feature/module-a-sales-inventory-import
Base SHA: 75995f74ec74a3315065ecfcec317edda8b1df73
Code Review SHA: c33f2a6b5341eb57e59df2f3e798b95fab64028e
Remote CI SHA: c33f2a6b5341eb57e59df2f3e798b95fab64028e
Migration Head: marketplace_imports.0002_marketplaceimportbatch_active_attempt_id_and_more
```

能力边界：normalized synthetic/offline only；Shopee/TikTok Shop `pending/mock`；Production synchronization OFF；未调用真实平台 API。

## 1. 自动化结果

| 验证 | 结果 |
|---|---|
| `git diff --check` | PASS |
| Django check | PASS |
| migration drift | PASS，No changes detected |
| SQLite fresh migration | PASS，包含 `marketplace_imports.0002` |
| SQLite upgrade `0001 -> 0002` | PASS |
| focused pytest | PASS，42 passed / 1 MySQL-only skipped |
| backend full | PASS，585 passed / 4 MySQL-only skipped / 5 warnings |
| frontend full | PASS，13 files / 163 tests |
| frontend production build | PASS，1957 modules |
| CI guard / credential scan | PASS，0 findings |
| forbidden artifact scan | PASS，0 findings |
| API boundary scan | PASS，无 network/task/webhook/live-provider import |
| Phase 2 CI Quality Gates | PASS，run `31366790607`，5/5 jobs success |
| Phase 3 CI and Data Quality Gates | PASS，run `31366790595`，5/5 jobs success |
| MySQL 8.4 | BLOCKED：Docker Desktop 创建 WSL VM 返回 `HCS/0x800705aa`；本机无可替代 MySQL 8.4 服务 |
| Local Sandbox | 未作为运行制品证据；本阶段仅验证 offline synthetic contract |

前端测试和构建在无源码改动的 ASCII 临时副本中完成；临时副本、临时 `dist` 和验证数据库均已清理。主工作树中的依赖目录未加入 Git。

## 2. 功能与负向场景

| 场景 | 结果 |
|---|---|
| initial / incremental orders | PASS |
| 重复、旧事件、同时间冲突、cancelled/terminal 保护 | PASS |
| 五种退款状态、重复/旧事件/terminal 保护 | PASS |
| inventory initial、重复、同时间冲突、负数拒绝 | PASS |
| cursor mismatch、watermark、失败原子性、重放、key/payload 冲突 | PASS |
| tenant/store/platform 隔离 | PASS |
| 空/未知/非法 scope、view/sync/retry、external/RPA/匿名拒绝 | PASS |
| raw credential、unknown field、live/production source 拒绝 | PASS |
| real adapter 返回 `PLATFORM_RESPONSE_CONTRACT_PENDING` | PASS |
| 无真实网络、scheduler、webhook 或平台写操作 | PASS |

## 3. R2 并发与审计回归

| 场景 | 结果 |
|---|---|
| failed -> processing 锁内认领 | PASS（SQLite/service 测试） |
| completed retry 返回 duplicate | PASS |
| processing retry 返回受控冲突 | PASS |
| stale attempt 不得覆盖 completed 状态 | PASS |
| stale attempt 不得覆盖 cursor/records | PASS |
| attempt version 单调递增 | PASS |
| retry actor 与 started/success/failed 历史完整 | PASS |
| attempt audit save/update/delete/bulk 保护 | PASS |
| 同一 failed batch 双 worker 最多一次提交 | NOT RUN / MySQL-only skipped |

## 4. MySQL 阻断

本轮已启动 `com.docker.service` 并尝试启动 Docker Desktop。Docker Desktop 在 WSL `CreateVm` 阶段返回 `HCS/0x800705aa`（系统资源不足），daemon 未能提供 MySQL 8.4 容器。本机无 mysql CLI 或其他 MySQL 8.4 服务。

因此以下门禁保持 NOT RUN / BLOCKED：

- MySQL 8.4 fresh migration。
- MySQL 8.4 `0001 -> 0002` upgrade migration。
- MySQL focused/full pytest。
- failed retry、idempotency key、cursor 和 inventory observation 并发测试。

SQLite 与远程 CI 结果不替代上述门禁，4 个 MySQL-only skip 不计为 PASS。

## 5. 受控结论

R1 并发所有权缺陷和审计缺口已完成代码整改，三项 P2 已关闭；但 MySQL 8.4 必需验证仍为 P1 阻断。

```text
Test Result: PARTIAL PASS
Open P1: 1
PR-A3 Review: FAIL / REQUEST CHANGES
PR #45: KEEP DRAFT / UNMERGED
Shopee: pending/mock
TikTok Shop: pending/mock
Production Synchronization: OFF
Real Platform API: NOT CALLED
```

本报告不证明真实 Shopee/TikTok API adapter 可用，不批准 Production，也不得用于宣称 MySQL 并发安全已经实测通过。
