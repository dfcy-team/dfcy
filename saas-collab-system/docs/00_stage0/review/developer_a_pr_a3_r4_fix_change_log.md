# 开发A PR-A3 R4 attempt audit 创建边界整改日志

任务编号：`A-PR3-P1-FIX-R4-AUDIT-CREATION-GUARD`

日期：2026-08-10

## 1. 冻结对象

```text
Repository: dfcy-team/dfcy
PR: #45
PR URL: https://github.com/dfcy-team/dfcy/pull/45
Branch: feature/module-a-sales-inventory-import
Base Branch: feature/module-a-real-platform-connection
Base SHA: 75995f74ec74a3315065ecfcec317edda8b1df73
Previous Code Review SHA: 013da2c9efb7e8ace24a3582036702b3c786cbdd
Previous Evidence HEAD: ace63284395ce5a0a6ef3bbd3366b9b4f0d05558
New Code Review SHA: 69a623f52fe6e2e66c0ec83aebeceee767406819
Evidence HEAD: current evidence-only commit; exact SHA is recorded in the final R4 handoff
Remote CI SHA: 69a623f52fe6e2e66c0ec83aebeceee767406819
Remote CI: PASS, 15/15 checks
Migration Head: marketplace_imports.0002_marketplaceimportbatch_active_attempt_id_and_more
Database Version: MySQL 8.4.11 Community Server
PR State: OPEN / Draft / Unmerged
```

Git 提交中的文件内容无法包含该提交自身的 SHA，因此 `Evidence HEAD` 以本 evidence-only commit 的 PR Head 为准；精确 SHA 和该 SHA 的 CI 结果在推送后写入最终 R4 移交信息，不伪造预知值。

## 2. R4 入场状态更正

```text
Open P1: 1
P2-003: REOPENED / escalated to P1
Attempt audit bulk protection: FAIL
Independent Review: FAIL / REQUEST CHANGES
```

根因是原 `MarketplaceImportBatchAttempt` 只阻止既有记录修改和删除，普通 `save/create/get_or_create/update_or_create` 创建分支仍可追加，`bulk_create` 还能绕过 `save()` 与 `full_clean()`。因此原“append-only / service-only creation / bulk protection PASS”声明不成立。

## 3. 代码整改

- 新增 attempt 专用私有 `ContextVar` 与 context manager，使用 token 和 `finally` 恢复；只有 `services._audit_attempt()` 打开该受控创建上下文。
- 首次实例 `save()`、普通 manager/queryset `create()` 和 `get_or_create()` 创建分支在上下文外拒绝；`update_or_create()` 创建和更新一律拒绝；`bulk_create()` 一律拒绝。
- 既有实例 `save()`、QuerySet `update()`、`bulk_update()`、实例 `delete()` 与 QuerySet `delete()` 继续拒绝。
- 模型层冻结 import started、retry started、success、failed 四类合法组合，并校验 tenant/store/actor、attempt version、batch 当前状态、active owner、started 前置记录与 controlled error code。
- `_audit_attempt()` 从 batch 派生 tenant、store 和 attempt version，不接受调用方替换这些主体字段。
- `import_normalized_batch()` 使用 attempt 生命周期外层事务；业务、cursor、水位和成功审计位于内层保存点。成功审计失败时业务与 cursor 回滚并写受控 failed；若 failed 审计也无法创建，则认领和 started 一并回滚。
- failed retry 的 `select_for_update()`、锁内 payload/status 重检、active attempt owner、completed duplicate、processing 409、stale attempt、幂等、records/cursor/watermark 原子性保持有效。

没有修改公共权限、统一异常、data scope、settings 或路由。没有 migration 变更。

## 4. 必需负向与并发场景

| # | 场景 | 结果 |
|---|---|---|
| 1 | attempt 实例首次 save 拒绝 | PASS |
| 2 | objects.create 拒绝 | PASS |
| 3 | get_or_create 创建分支拒绝 | PASS |
| 4 | update_or_create 创建/更新拒绝 | PASS |
| 5 | bulk_create 拒绝 | PASS |
| 6 | 已有 attempt 实例 save 拒绝 | PASS |
| 7 | QuerySet update 拒绝 | PASS |
| 8 | bulk_update 拒绝 | PASS |
| 9 | 实例 delete 拒绝 | PASS |
| 10 | QuerySet delete 拒绝 | PASS |
| 11 | 跨 tenant actor 拒绝且 guard 恢复 | PASS |
| 12 | batch/tenant 不一致校验拒绝 | PASS |
| 13 | batch/store_mapping 不一致校验拒绝 | PASS |
| 14 | 非法 attempt status/result 组合拒绝 | PASS |
| 15 | 唯一受控 `_audit_attempt()` 正常创建 | PASS |
| 16 | success audit 写入失败时 records/cursor 回滚 | PASS |
| 17 | stale attempt 不能伪造 failed 审计 | PASS |
| 18 | MySQL 双 worker 最多一个 retry started | PASS |
| 19 | MySQL 双 worker 最多一个 retry success | PASS |
| 20 | completed duplicate 不新增 attempt | PASS |

## 5. 验证结果

| 验证 | 结果 |
|---|---|
| Django check | PASS，0 issues |
| migration drift | PASS，No changes detected |
| SQLite focused | PASS，55 passed / 1 MySQL-only skipped |
| SQLite backend full | PASS，598 passed / 4 MySQL-only skipped |
| MySQL version | PASS，8.4.11 Community Server |
| MySQL fresh migration | PASS，迁移至 head |
| MySQL upgrade | PASS，`marketplace_imports.0001 -> 0002` |
| MySQL migration drift | PASS，No changes detected |
| MySQL focused | PASS，56 passed / 0 skipped |
| MySQL double worker concurrency | PASS，started/success 各最多 1 条 |
| MySQL backend full | PASS，602 passed / 0 skipped |
| Frontend tests | PASS，13 files / 163 tests |
| Frontend build | PASS，1957 modules |
| CI guard / credential scan | PASS，0 findings |
| forbidden artifact scan | PASS，0 findings |
| API boundary scan | PASS，0 network/task/webhook/platform-write findings |
| `git diff --check` | PASS |
| dist/node_modules/cache tracking | PASS，0 tracked paths |
| Code Review SHA remote CI | PASS，15/15 checks |
| Worktree before evidence edit | CLEAN |

前端 `npm ci` 安装 249 packages，并观察到锁定依赖的 3 个 high 漏洞。本任务未授权依赖升级，未修改 lockfile；测试和 production build 均通过，该项保留为供应链观察项。

## 6. 修改文件

Code Review SHA：

- `backend/apps/marketplace_imports/models.py`
- `backend/apps/marketplace_imports/services.py`
- `backend/tests/test_pr_a3_marketplace_imports.py`
- `docs/03_api/pr_a3_sales_inventory_import_contract.md`

Evidence-only：

- `docs/00_stage0/review/developer_a_pr_a3_r4_fix_change_log.md`
- `docs/00_stage0/review/developer_a_pr_a3_sales_inventory_import_change_log.md`
- `docs/00_stage0/review/pr_a3_sales_inventory_import_review.md`
- `docs/05_test/pr_a3_sales_inventory_import_test_report.md`

R4 共修改 8 个明确文件；Evidence HEAD 相对 Base 的 PR 统计为 22 个文件，最终统计在移交时确认。

## 7. 开发侧结论

```text
Developer R4 Remediation Evidence: PASS
Independent R4 Review: PENDING
P0: 0
Open P1 after developer remediation: 0
Open P2: 0

A-REAL-PLATFORM-CONNECTION: FAIL / REQUEST CHANGES
Shopee: pending/mock
TikTok Shop: pending/mock
Production Synchronization: OFF
Real Platform API: NOT CALLED
PR #45: OPEN / Draft / Unmerged
Merge: FORBIDDEN pending independent review
```

开发A未签署 Architecture、Security、Test、Data 或 Release Reviewer PASS。未取得独立 R4 PASS 前不得合并，也不得进入真实平台 adapter 开发。
