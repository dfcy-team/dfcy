# 开发A PR-A3 销售与库存离线导入变更日志

任务：`A-PR3-P1-FIX-R4-AUDIT-CREATION-GUARD`

日期：2026-08-11

```text
Repository: dfcy-team/dfcy
PR: #45
PR URL: https://github.com/dfcy-team/dfcy/pull/45
Branch: feature/module-a-sales-inventory-import
Base Branch: feature/module-a-real-platform-connection
Base SHA: 75995f74ec74a3315065ecfcec317edda8b1df73
Original Previous Code Review SHA: 013da2c9efb7e8ace24a3582036702b3c786cbdd
Previous Code Review SHA: 69a623f52fe6e2e66c0ec83aebeceee767406819
Previous Evidence HEAD: d52f11f8994ed7291baa67d5469c2b390787532c
Code Review SHA: 4c75eda5458fafc9d1d9fb0833392c94ce106f2a
Evidence HEAD: current evidence-only commit; exact SHA is recorded in the final R4 handoff
Evidence Head CI: PENDING until the evidence-only commit is pushed
Remote CI SHA: 4c75eda5458fafc9d1d9fb0833392c94ce106f2a
Migration Head: marketplace_imports.0003_alter_marketplaceimportbatchattempt_options
PR State: OPEN / Draft / Unmerged
```

Evidence HEAD 为包含本日志、测试报告和 R4 证据的后续 evidence-only 提交；它不改变 `Code Review SHA` 的运行时代码。

## 1. 实现与 R2 整改历史

- 新建独立 `marketplace_imports` app、normalized synthetic/offline 合同和内部 API。
- failed retry 在事务和行锁内认领并重检状态；只有 active attempt owner 能提交成功或失败。
- stale owner 不得覆盖 completed batch、cursor 或 records。
- append-only attempt audit 保存 actor、版本、状态转换、结果和受控错误码，不保存 raw payload 或凭据。
- API 合同包含可执行的完整 synthetic order 示例。
- 未加入真实平台网络、scheduler、正式 webhook、历史回补、平台写接口、finance、purchasing 或 RPA。

## 2. R3 Docker / WSL 修复历史

- 确认原始失败为 `Wsl/Service/AttachDisk/CreateVm/HCS/0x800705aa`。
- 保留 `docker_data.vhdx` 和历史 Docker volume，未执行 factory reset 或数据删除。
- 清理卡死的 Docker 后台进程并重启 `WSLService`、`vmcompute`、Docker 服务。
- 新建本机用户级 `.wslconfig`：4 GB memory、2 CPU、4 GB swap。
- Docker engine 恢复：client/server 29.5.3，Linux engine 2 CPU / 约 4 GB。
- MySQL 8.4.10 独立验证容器健康。
- 本机 `.wslconfig`、`.env.local` 和临时验证资源均未进入 Git。

## 3. R3 MySQL 测试隔离修复历史

- 并发测试现在显式、幂等准备 `integrations.store.sync` 和 `integrations.store.retry`，不再依赖 migration seed 或全量测试顺序。
- 受控 409 错误响应允许 `data=null`；测试不再把它误当作对象调用 `.get()`。
- 产品状态机、锁和 attempt owner 逻辑未因该测试修复改变。

## 4. R3 验证历史

- Docker engine：PASS，29.5.3。
- MySQL version：PASS，8.4.10。
- Django check：PASS。
- MySQL fresh migration：PASS。
- MySQL `marketplace_imports.0001 -> 0002` upgrade：PASS。
- migration drift：PASS，No changes detected。
- MySQL focused：43 passed / 0 skipped。
- MySQL backend full：589 passed / 0 skipped。
- SQLite focused：42 passed / 1 MySQL-only skipped。
- SQLite backend full baseline：585 passed / 4 MySQL-only skipped。
- frontend：13 files / 163 tests PASS；production build PASS（1957 modules）。
- CI guard、credential scan、forbidden artifact scan、API boundary scan、`git diff --check`：PASS。
- Code Review SHA 远程 CI：15/15 checks PASS。

## 5. R3 状态与移交历史

- R1 P1/P2 开发整改：全部关闭。
- Open developer P1：0。
- 独立 R3 复审签字：PENDING。
- `A-REAL-PLATFORM-CONNECTION = FAIL / REQUEST CHANGES`。
- `Shopee = pending/mock`。
- `TikTok Shop = pending/mock`。
- `Production synchronization = OFF`。
- `Real platform API = NOT CALLED`。
- PR #45 保持 Draft、不合并，等待独立复审。

## 6. R4 audit creation guard 整改

R4 入场状态已更正为：`Open P1: 1`；`P2-003: REOPENED / escalated to P1`；`Attempt audit bulk protection: FAIL`；`Independent Review: FAIL / REQUEST CHANGES`。

- 为 `MarketplaceImportBatchAttempt` 增加独立私有 `ContextVar` 创建门，只有 `services._audit_attempt()` 在受控 context manager 中创建；上下文使用 `try/finally` 恢复。
- 普通首次/既有实例 `save()`、`objects.create()`、`get_or_create()` 创建分支、`update_or_create()` 创建/更新、`bulk_create()`、`update()`、`bulk_update()`、实例和 QuerySet `delete()` 全部拒绝。
- 模型层冻结 import/retry started、success、failed 合法组合，并校验 batch/tenant/store/actor、attempt version、batch 当前状态、active owner、终态 started 前置记录和 controlled error code。
- 将认领、started、业务保存点和 success/failed 审计纳入同一外层事务；审计失败不留下半完成业务记录、cursor/watermark 或 processing 认领。
- 保持 failed retry `select_for_update()`、锁内重检、active attempt owner、completed duplicate、processing 409、stale attempt、cursor/watermark 和幂等规则不变。

## 7. 上一版 R4 验证与移交历史

- Django check：PASS，0 issues；migration drift：PASS，No changes detected；无新 migration。
- SQLite focused：55 passed / 1 MySQL-only skipped；SQLite backend full：598 passed / 4 MySQL-only skipped。
- MySQL 8.4.11 fresh/`0001 -> 0002` upgrade：PASS；focused：56 passed / 0 skipped；backend full：602 passed / 0 skipped。
- MySQL 双 worker：retry started 最多 1 条、success 最多 1 条，PASS。
- 前端：13 files / 163 tests PASS；production build 1957 modules PASS。`npm ci` 的 3 个 high 漏洞保留为未扩范围的供应链观察项。
- CI guard、credential、forbidden artifact、API boundary、`git diff --check`、dist/node_modules/cache tracking：PASS，0 findings。
- Code Review SHA remote CI：15/15 checks PASS。
- 上一版 R4 代码提交只修改 models、services、focused tests 与 PR-A3 API contract；未修改公共权限、统一异常、data scope、settings 或路由。

## 8. R4 独立复审追加整改

独立复审在 Evidence HEAD `d52f11f8994ed7291baa67d5469c2b390787532c` 结论为 `FAIL / REQUEST CHANGES`，追加 `Open P1: 1` 和 `Open P2: 1`：Django `_base_manager.bulk_create()` 可绕过默认 manager；PR 正文与测试报告仍引用 R3/上一版 R4 结果。

- `MarketplaceImportBatchAttempt.Meta.base_manager_name = "objects"`，使 Django base manager 使用既有 append-only/service-only QuerySet；普通调用方不能通过 `_base_manager.bulk_create()` 追加伪造审计。
- 新增 `_base_manager.bulk_create()` 负向测试；整改前稳定复现，整改后抛出 `ValidationError` 且 0 写入。
- 新增仅含 `AlterModelOptions` 的 `marketplace_imports.0003`；MySQL 8.4.11 fresh 和 `0001 -> 0002 -> 0003` upgrade 均 PASS。
- SQLite focused `56 passed / 1 skipped`，backend full `599 passed / 4 skipped`；MySQL focused `57 passed / 0 skipped`，backend full `603 passed / 0 skipped`。
- failed retry 双 worker started/success 各最多 1 条；前端 13 files / 163 tests 与 1957 modules build PASS；credential、forbidden artifact、API boundary 和远端 Code Review SHA CI 15/15 PASS。
- PR 正文将在 Evidence HEAD 固定后更新为本轮 SHA 和验证结果；不回复或关闭独立审查线程，由复审负责人重新判定。

```text
Developer R4 Remediation Evidence: PASS
Independent R4 Review: PENDING
Open Developer P1: 0
Open Developer P2: 0
PR #45: OPEN / Draft / Unmerged
Shopee: pending/mock
TikTok Shop: pending/mock
Production synchronization: OFF
Real platform API: NOT CALLED
Merge: FORBIDDEN pending independent review
```
