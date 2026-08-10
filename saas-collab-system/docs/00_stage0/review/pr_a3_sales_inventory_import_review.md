# PR-A3 销售与库存离线导入 R2 整改复审报告

任务编号：`A-PR3-P1-OFFLINE-SALES-INVENTORY-IMPORT-REVIEW`

复审日期：2026-08-10

## 1. 冻结对象

```text
Repository: dfcy-team/dfcy
Branch: feature/module-a-sales-inventory-import
PR Number: 45
PR URL: https://github.com/dfcy-team/dfcy/pull/45
PR State: OPEN / Draft / Unmerged
Base Branch: feature/module-a-real-platform-connection
Base SHA: 75995f74ec74a3315065ecfcec317edda8b1df73
Code Review SHA: c33f2a6b5341eb57e59df2f3e798b95fab64028e
Remote CI SHA: c33f2a6b5341eb57e59df2f3e798b95fab64028e
Commit Count: 2
Changed Files: 20
Additions / Deletions: +2391 / -0
Deployment Environment: 未部署；本地 synthetic/offline 验证
Database: SQLite 验证完成；MySQL 8.4 BLOCKED
Migration Head: marketplace_imports.0002_marketplaceimportbatch_active_attempt_id_and_more
```

本文件及同步更新的测试报告、变更日志属于 evidence-only 文档提交，不改变上述代码复审对象。最终 Evidence HEAD 以 PR #45 远端 Head 为准，必须与该 evidence-only 提交的远程 CI SHA 对齐；代码行为与自动化结论固定到 `Code Review SHA`。

## 2. R1 问题整改状态

| 编号 | 等级 | 整改结果 | 状态 |
|---|---|---|---|
| PR-A3-R1-P1-001 failed batch 并发重试可破坏最终状态 | P1 | 重试认领移入 `transaction.atomic()` + `select_for_update()`；锁内重检状态；completed 返回 duplicate；仅 active attempt owner 可写 failed；增加双 worker MySQL 并发测试和 stale owner 负向测试 | 代码整改完成；MySQL 实测待补 |
| PR-A3-R1-P1-002 MySQL 8.4 必需验证缺失 | P1 | 已尝试启动 Docker Service 和 Docker Desktop；WSL 创建 VM 因 `HCS/0x800705aa` 资源不足失败 | OPEN / BLOCKED |
| PR-A3-R1-P2-001 原始证据未冻结 SHA | P2 | 测试报告、变更日志和本报告补充 PR、Base、Code Review、Remote CI 与 evidence-only 说明 | CLOSED |
| PR-A3-R1-P2-002 合同示例不可执行 | P2 | 将空 `orders` 示例替换为可通过 serializer 的完整 synthetic order，并标明约束 | CLOSED |
| PR-A3-R1-P2-003 retry actor/attempt 不可审计 | P2 | 新增 append-only `MarketplaceImportBatchAttempt`，记录 batch、tenant、store、actor、action、attempt、前后状态、结果、受控错误码和时间 | CLOSED |

## 3. 并发与审计整改

重试执行现在遵循以下状态机：

```text
failed
  -> 锁内认领 processing + 新 attempt_id/version + started audit
  -> 仅 active attempt owner 可提交 completed 或 failed

completed
  -> duplicate（不重新执行、不回写 failed）

processing
  -> 受控并发冲突
```

新增保护证明：

- stale attempt 不能覆盖已完成批次、cursor 或导入记录。
- attempt version 单调递增，每次重试记录当前 actor。
- started/success/failed 审计为 append-only，普通 save/update/delete/bulk 路径不能修改或删除。
- 审计不保存原始平台响应、订单 payload 或凭据。
- MySQL 双 worker 测试断言同一 failed batch 最多一次提交，最终 batch/cursor/records/audit 一致；该测试已编写，但目标数据库尚未运行。

## 4. 验证结果

| 验证 | 结果 |
|---|---|
| `git diff --check` | PASS |
| Django check | PASS |
| `makemigrations --check --dry-run` | PASS，No changes detected |
| SQLite fresh migration | PASS，包含 `marketplace_imports.0002` |
| SQLite upgrade `0001 -> 0002` | PASS |
| focused pytest | PASS，42 passed / 1 MySQL-only skipped |
| backend full | PASS，585 passed / 4 MySQL-only skipped / 5 warnings |
| frontend full | PASS，13 files / 163 tests |
| frontend production build | PASS，1957 modules |
| CI guard / credential / forbidden artifact / API boundary | PASS |
| Phase 2 CI Quality Gates | PASS，run `31366790607`，5/5 jobs success |
| Phase 3 CI and Data Quality Gates | PASS，run `31366790595`，5/5 jobs success |
| Remote CI SHA | PASS，与 Code Review SHA 一致 |
| MySQL 8.4 fresh migration | NOT RUN / BLOCKED |
| MySQL 8.4 upgrade migration | NOT RUN / BLOCKED |
| MySQL 8.4 focused/full pytest | NOT RUN / BLOCKED |
| MySQL 8.4 failed-retry concurrency | NOT RUN / BLOCKED |

## 5. MySQL 8.4 阻断证据

本轮已实际执行以下恢复动作：

1. 启动 Windows `com.docker.service`，服务进入 Running。
2. 启动 Docker Desktop。
3. Docker Desktop 在创建 WSL 虚拟机时失败，错误为 `Wsl/Service/CreateInstance/CreateVm/HCS/0x800705aa`，即系统资源不足。
4. Docker daemon 因此不可用，本机也没有可替代的 MySQL 8.4 CLI/服务。

SQLite 和远程 CI 不能替代 MySQL 对 `select_for_update()`、事务隔离、唯一键竞争和双 worker 重试的实测。本报告不把 4 个 MySQL-only skip 记为 PASS。

## 6. 安全与范围复核

- `PR_A3_SYNTHETIC_IMPORT_ENABLED` 默认关闭。
- `source_mode` 仅允许 `synthetic_contract`；真实 adapter 保持 fail closed。
- 未调用 Shopee/TikTok Shop 真实 API。
- 未新增 scheduler、正式 webhook、历史回补或平台写接口。
- 未新增 finance、purchasing、RPA 或 Production 同步能力。
- Shopee 与 TikTok Shop 均保持 `pending/mock`。
- Production synchronization 保持 OFF。
- 未发现 raw credential 或 forbidden artifact 进入提交。

## 7. 当前复审结论

```text
P0: 0
Open P1: 1（MySQL 8.4 必需验证）
Open P2: 0

R1 Code Remediation: PASS
R2 Engineering Gates: PARTIAL PASS
MySQL 8.4: BLOCKED / FAIL

PR-A3 Offline Foundation: FAIL / REQUEST CHANGES
PR #45: KEEP OPEN / DRAFT / UNMERGED
Shopee: pending/mock
TikTok Shop: pending/mock
Production Synchronization: OFF
Real Platform API: NOT CALLED
Merge: FORBIDDEN
```

代码级并发缺陷与三项 P2 已整改，但 P1-002 未关闭。PR #45 必须继续保持 Draft，不得合并，不得开始真实平台或 Production 同步。

## 8. R3 关闭条件

释放足够 WSL/Docker 资源或提供经批准的 MySQL 8.4 环境后，必须固定新证据 SHA 并完整执行：

1. MySQL 8.4 全新数据库 migration。
2. MySQL 8.4 `0001 -> 0002` 升级 migration。
3. MySQL 聚焦测试，failed retry、idempotency key、cursor 竞争和 inventory observation 并发测试不得 skipped。
4. MySQL 后端全量 pytest。
5. Django check、migration drift、SQLite fresh/upgrade 回归。
6. 前端全量测试与 production build。
7. CI guard、credential scan、forbidden artifact scan、API boundary scan。
8. 最终 Evidence HEAD 的远程 CI 全部通过并与记录 SHA 对齐。

## 9. 最终复审表

```text
PR-A3 SALES / INVENTORY OFFLINE IMPORT R2 REVIEW

Repository: dfcy-team/dfcy
PR: #45
Branch: feature/module-a-sales-inventory-import
Base SHA: 75995f74ec74a3315065ecfcec317edda8b1df73
Code Review SHA: c33f2a6b5341eb57e59df2f3e798b95fab64028e
Remote CI SHA: c33f2a6b5341eb57e59df2f3e798b95fab64028e

Draft / Unmerged: PASS
Scope Boundary: PASS
Synthetic Switch Default OFF: PASS
Tenant / Store / Platform Isolation: PASS
Exact Permissions: PASS
Failed Retry Ownership: PASS (code/SQLite)
Failed Retry MySQL Concurrency: BLOCKED
Immutable Retry Audit: PASS
SQLite Migration: PASS
MySQL 8.4: BLOCKED / FAIL
Focused Tests: PASS, 42 passed / 1 skipped
Backend Full: PASS, 585 passed / 4 skipped
Frontend Tests / Build: PASS
Remote CI: PASS on Code Review SHA
Real Platform Network: NOT CALLED
Production Synchronization: OFF

P0: 0
OPEN P1: 1
OPEN P2: 0

REVIEW RESULT: FAIL / REQUEST CHANGES
MERGE: FORBIDDEN

Architecture Reviewer:
Security Reviewer:
Test Reviewer:
Data Reviewer:
Release Reviewer:
Date: 2026-08-10
```
