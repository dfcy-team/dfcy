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
Code Review SHA: 013da2c9efb7e8ace24a3582036702b3c786cbdd
Remote CI SHA: 013da2c9efb7e8ace24a3582036702b3c786cbdd
Migration Head: marketplace_imports.0002_marketplaceimportbatch_active_attempt_id_and_more
PR State: OPEN / Draft / Unmerged
```

Evidence HEAD 为包含本日志、测试报告和 R3 证据的后续 evidence-only 提交；它不改变 `Code Review SHA` 的运行时代码。

## 1. 实现与 R2 整改

- 新建独立 `marketplace_imports` app、normalized synthetic/offline 合同和内部 API。
- failed retry 在事务和行锁内认领并重检状态；只有 active attempt owner 能提交成功或失败。
- stale owner 不得覆盖 completed batch、cursor 或 records。
- append-only attempt audit 保存 actor、版本、状态转换、结果和受控错误码，不保存 raw payload 或凭据。
- API 合同包含可执行的完整 synthetic order 示例。
- 未加入真实平台网络、scheduler、正式 webhook、历史回补、平台写接口、finance、purchasing 或 RPA。

## 2. Docker / WSL 修复

- 确认原始失败为 `Wsl/Service/AttachDisk/CreateVm/HCS/0x800705aa`。
- 保留 `docker_data.vhdx` 和历史 Docker volume，未执行 factory reset 或数据删除。
- 清理卡死的 Docker 后台进程并重启 `WSLService`、`vmcompute`、Docker 服务。
- 新建本机用户级 `.wslconfig`：4 GB memory、2 CPU、4 GB swap。
- Docker engine 恢复：client/server 29.5.3，Linux engine 2 CPU / 约 4 GB。
- MySQL 8.4.10 独立验证容器健康。
- 本机 `.wslconfig`、`.env.local` 和临时验证资源均未进入 Git。

## 3. MySQL 测试隔离修复

- 并发测试现在显式、幂等准备 `integrations.store.sync` 和 `integrations.store.retry`，不再依赖 migration seed 或全量测试顺序。
- 受控 409 错误响应允许 `data=null`；测试不再把它误当作对象调用 `.get()`。
- 产品状态机、锁和 attempt owner 逻辑未因该测试修复改变。

## 4. 验证

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

## 5. 状态与移交

- R1 P1/P2 开发整改：全部关闭。
- Open developer P1：0。
- 独立 R3 复审签字：PENDING。
- `A-REAL-PLATFORM-CONNECTION = FAIL / REQUEST CHANGES`。
- `Shopee = pending/mock`。
- `TikTok Shop = pending/mock`。
- `Production synchronization = OFF`。
- `Real platform API = NOT CALLED`。
- PR #45 保持 Draft、不合并，等待独立复审。
