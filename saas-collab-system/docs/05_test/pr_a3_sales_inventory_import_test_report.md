# PR-A3 销售与库存离线导入测试报告

日期：2026-08-10

```text
PR: #45
Branch: feature/module-a-sales-inventory-import
Base SHA: 75995f74ec74a3315065ecfcec317edda8b1df73
Previous Code Review SHA: 013da2c9efb7e8ace24a3582036702b3c786cbdd
Previous Evidence HEAD: ace63284395ce5a0a6ef3bbd3366b9b4f0d05558
Code Review SHA: 69a623f52fe6e2e66c0ec83aebeceee767406819
Evidence HEAD: current evidence-only commit; exact SHA is recorded in the final R4 handoff
Remote CI SHA: 69a623f52fe6e2e66c0ec83aebeceee767406819
Database Version: MySQL 8.4.11
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
| MySQL focused pytest | PASS，56 passed / 0 skipped |
| MySQL backend full | PASS，602 passed / 0 skipped |
| SQLite focused pytest | PASS，55 passed / 1 MySQL-only skipped |
| SQLite backend full baseline | PASS，598 passed / 4 MySQL-only skipped |
| frontend full | PASS，13 files / 163 tests |
| frontend production build | PASS，1957 modules |
| CI guard / credential scan | PASS，0 findings |
| forbidden artifact scan | PASS，0 findings |
| API boundary scan | PASS，无 network/task/webhook/live-provider import |
| Code Review SHA remote CI | PASS，15/15 checks |

## 2. MySQL 8.4 环境证据

- Docker Desktop client/server：29.5.3。
- Linux engine：2 CPU、约 4 GB memory。
- MySQL：8.4.11 Community Server。
- 验证容器：独立 Docker network 与 tmpfs 数据目录，不绑定宿主端口。
- 凭据仅为本轮临时容器占位值，输出不包含密码。
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
| attempt audit 普通 save/create/get_or_create/update_or_create 保护 | PASS |
| attempt audit bulk_create/update/bulk_update/delete 保护 | PASS |
| attempt audit tenant/store/actor/version/状态组合校验 | PASS |
| attempt audit 写入失败时业务记录与 cursor 回滚 | PASS |
| 同一 failed batch 双 worker 最多一次提交 | PASS，MySQL 实测 |

R3 首次全量 MySQL 运行的唯一失败来自测试顺序，已在上一轮关闭。本轮 R4 使用全新 MySQL 8.4.11 tmpfs 数据库重新执行 fresh/upgrade、聚焦和全量测试；聚焦 `56 passed`、全量 `602 passed`，均为 `0 skipped`。

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
R4 Intake Open P1: 1
R4 Intake P2-003: REOPENED / escalated to P1
R4 Intake Attempt Audit Bulk Protection: FAIL
R4 Intake Independent Review: FAIL / REQUEST CHANGES

Developer R4 Remediation Evidence: PASS
Open Developer P1 after remediation: 0
Independent R4 Review: PENDING
PR #45: KEEP DRAFT / UNMERGED
Shopee: pending/mock
TikTok Shop: pending/mock
Production Synchronization: OFF
Real Platform API: NOT CALLED
```

前端 `npm ci` 观察到锁定依赖的 3 个 high 漏洞；本任务未授权依赖升级，测试和构建均通过，该项保留为供应链观察项。本报告只证明 normalized synthetic/offline 整改达到开发侧 R4 提交条件，不证明真实 Shopee/TikTok API adapter 可用，不批准 Production，也不替代独立复审签字。
