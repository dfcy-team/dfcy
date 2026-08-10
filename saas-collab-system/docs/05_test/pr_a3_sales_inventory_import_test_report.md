# PR-A3 销售与库存离线导入测试报告

日期：2026-08-10

```text
PR: #45
Branch: feature/module-a-sales-inventory-import
Base SHA: 75995f74ec74a3315065ecfcec317edda8b1df73
Code Review SHA: 013da2c9efb7e8ace24a3582036702b3c786cbdd
Remote CI SHA: 013da2c9efb7e8ace24a3582036702b3c786cbdd
Database Version: MySQL 8.4.10
Migration Head: marketplace_imports.0002_marketplaceimportbatch_active_attempt_id_and_more
```

能力边界：normalized synthetic/offline only；Shopee/TikTok Shop `pending/mock`；Production synchronization OFF；未调用真实平台 API。

## 1. 自动化结果

| 验证 | 结果 |
|---|---|
| `git diff --check` | PASS |
| Django check on MySQL | PASS，0 issues |
| migration drift | PASS，No changes detected |
| MySQL 8.4 fresh migration | PASS，包含 `marketplace_imports.0002` |
| MySQL 8.4 upgrade `0001 -> 0002` | PASS |
| MySQL focused pytest | PASS，43 passed / 0 skipped |
| MySQL backend full | PASS，589 passed / 0 skipped |
| SQLite focused pytest | PASS，42 passed / 1 MySQL-only skipped |
| SQLite backend full baseline | PASS，585 passed / 4 MySQL-only skipped |
| frontend full | PASS，13 files / 163 tests |
| frontend production build | PASS，1957 modules |
| CI guard / credential scan | PASS，0 findings |
| forbidden artifact scan | PASS，0 findings |
| API boundary scan | PASS，无 network/task/webhook/live-provider import |
| Code Review SHA remote CI | PASS，15/15 checks |

## 2. MySQL 8.4 环境证据

- Docker Desktop client/server：29.5.3。
- Linux engine：2 CPU、约 4 GB memory。
- MySQL：8.4.10 Community Server。
- 验证容器：独立临时 volume，仅绑定 `127.0.0.1:3308`。
- 凭据从 ACL 保护且 Git ignored 的 `.env.local` 注入，输出不包含密码。
- 历史 Local Sandbox volume 因凭据版本不同未用作证据，也未被删除。
- `docker_data.vhdx` 未删除或重建。

## 3. 并发与审计回归

| 场景 | 结果 |
|---|---|
| failed -> processing 锁内认领 | PASS |
| completed retry 返回 duplicate | PASS |
| processing retry 返回受控冲突 | PASS |
| stale attempt 不得覆盖 completed 状态 | PASS |
| stale attempt 不得覆盖 cursor/records | PASS |
| attempt version 单调递增 | PASS |
| retry actor 与 started/success/failed 历史完整 | PASS |
| attempt audit save/update/delete/bulk 保护 | PASS |
| 同一 failed batch 双 worker 最多一次提交 | PASS，MySQL 实测 |

首次全量 MySQL 运行的唯一失败来自测试顺序：transaction 测试在权限 seed 被 flush 后未准备所需 permission，且测试未兼容受控 409 的 `data=null`。完成测试隔离整改后，聚焦测试 `43 passed`，全量测试 `589 passed`，均无 skipped。

## 4. 功能与负向场景

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

## 5. 受控结论

```text
Developer Test Evidence: PASS
Open Developer P1: 0
Independent R3 Review: PENDING SIGN-OFF
PR #45: KEEP DRAFT / UNMERGED
Shopee: pending/mock
TikTok Shop: pending/mock
Production Synchronization: OFF
Real Platform API: NOT CALLED
```

本报告关闭开发侧 MySQL 8.4 阻断，但不证明真实 Shopee/TikTok API adapter 可用，不批准 Production，也不替代独立复审签字。
