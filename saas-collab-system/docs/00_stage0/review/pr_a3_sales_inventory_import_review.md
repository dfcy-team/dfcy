# PR-A3 销售与库存离线导入 R4 整改证据

任务编号：`A-PR3-P1-FIX-R4-AUDIT-CREATION-GUARD`

证据日期：2026-08-11

## 1. 冻结对象

```text
Repository: dfcy-team/dfcy
Branch: feature/module-a-sales-inventory-import
PR Number: 45
PR URL: https://github.com/dfcy-team/dfcy/pull/45
PR State: OPEN / Draft / Unmerged
Base Branch: feature/module-a-real-platform-connection
Base SHA: 75995f74ec74a3315065ecfcec317edda8b1df73
Original Previous Code Review SHA: 013da2c9efb7e8ace24a3582036702b3c786cbdd
Previous Code Review SHA: 69a623f52fe6e2e66c0ec83aebeceee767406819
Previous Evidence HEAD: d52f11f8994ed7291baa67d5469c2b390787532c
Code Review SHA: 4c75eda5458fafc9d1d9fb0833392c94ce106f2a
Evidence HEAD: current evidence-only commit; exact SHA is recorded in the final R4 handoff
Evidence Head CI: PENDING until the evidence-only commit is pushed
Remote CI SHA: 4c75eda5458fafc9d1d9fb0833392c94ce106f2a
Code Commit Count relative to Base: 8
Changed Files at Code Review SHA: 23
Additions / Deletions at Code Review SHA: +3258 / -0
Deployment Environment: 未部署；本地 synthetic/offline + MySQL 8.4 验证
Database Version: MySQL 8.4.11
Migration Head: marketplace_imports.0003_alter_marketplaceimportbatchattempt_options
```

本文件及同步更新的测试报告、变更日志属于 evidence-only 文档提交，不改变上述代码复审对象。最终 Evidence HEAD 以 PR #45 远端 Head 为准，必须与 evidence-only 提交的远程 CI SHA 对齐。

## 2. R1 问题关闭状态

| 编号 | 等级 | 关闭证据 | 状态 |
|---|---|---|---|
| PR-A3-R1-P1-001 failed batch 并发重试可破坏最终状态 | P1 | 锁内认领与状态重检；active attempt owner 提交保护；stale owner 负向测试；MySQL 双 worker 最多一次提交测试 PASS | CLOSED |
| PR-A3-R1-P1-002 MySQL 8.4 必需验证缺失 | P1 | Docker/WSL 修复；MySQL 8.4.10 fresh/upgrade、focused 43、backend full 589 全部 PASS | CLOSED |
| PR-A3-R1-P2-001 原始证据未冻结 SHA | P2 | 测试报告、变更日志和本证据拆分 Code Review SHA 与 Evidence HEAD | CLOSED |
| PR-A3-R1-P2-002 合同示例不可执行 | P2 | 已提供可通过 serializer 的完整 synthetic order 示例 | CLOSED |
| PR-A3-R1-P2-003 retry actor/attempt 不可审计 | P2 -> P1 | R3 只保护修改/删除，普通 create/get_or_create/update_or_create/bulk_create 仍可伪造；R4 入场时重新打开并升级 | REOPENED / ESCALATED TO P1 |

## 3. R3 Docker / WSL 阻断修复历史

原始错误稳定发生在 Docker Desktop 使用 WSL 创建 VM 并挂载 `docker_data.vhdx` 时：

```text
Wsl/Service/AttachDisk/CreateVm/HCS/0x800705aa
Wsl/Service/CreateInstance/CreateVm/HCS/0x800705aa
```

诊断结果：

- 主机内存 15.3 GB，故障时空闲物理内存约 2.5 GB。
- 自动分页文件正常，约 16 GB；空闲虚拟内存约 7.3 GB。
- WSL、VirtualMachinePlatform、Hyper-V 均已启用。
- 无其他运行中的 Hyper-V VM。
- Docker 数据盘 `docker_data.vhdx` 保留，未删除、重置或重建。

修复动作：

1. 清理失去响应的 Docker Desktop/backend 进程。
2. 重启 `WSLService`、`vmcompute` 和 Docker 服务。
3. 新建用户级 `.wslconfig`：`memory=4GB`、`processors=2`、`swap=4GB`、`localhostForwarding=true`。
4. 重新启动 Docker Desktop。
5. 使用隔离的空 `DOCKER_CONFIG` 运行验证命令，避免读取或修改现有 registry 认证配置。

修复后证据：

- WSL VM 成功创建，`vmmem` 正常运行。
- Docker engine：client/server `29.5.3`。
- Docker Desktop Linux engine：2 CPU、约 4 GB memory。
- Docker 日志出现 `Docker engine is ready`、`dockerAPI: running`。
- 修复后日志未再出现 `0x800705aa`。
- MySQL 容器健康，版本 `8.4.10`。

## 4. R3 MySQL 8.4 验证历史

使用独立临时容器、独立 volume、仅绑定 `127.0.0.1:3308` 的数据库执行；没有使用历史 Local Sandbox volume 作为证据，也没有打印数据库密码。

| 验证 | 结果 |
|---|---|
| MySQL version | PASS，8.4.10 |
| Django check | PASS，0 issues |
| MySQL fresh migration | PASS，全部 migration 到 head |
| MySQL upgrade `marketplace_imports.0001 -> 0002` | PASS |
| migration drift | PASS，No changes detected |
| MySQL focused pytest | PASS，43 passed / 0 skipped |
| MySQL failed-retry double worker | PASS，最多一次提交 |
| MySQL backend full | PASS，589 passed / 0 skipped |

首次 MySQL 全量运行得到 `588 passed / 1 failed`：失败原因是 transaction 测试依赖 migration seed 的执行顺序，未显式准备 `integrations.store.sync/retry` 权限；并发状态机未失败。测试已改为显式、幂等创建所需权限，并兼容受控 409 响应的 `data=null`。整改后重新执行聚焦和全量测试，分别为 `43 passed`、`589 passed`。

## 5. R3 其他验证历史

| 验证 | 结果 |
|---|---|
| `git diff --check` | PASS |
| SQLite focused pytest | PASS，42 passed / 1 MySQL-only skipped |
| SQLite backend full baseline | PASS，585 passed / 4 MySQL-only skipped |
| frontend full | PASS，13 files / 163 tests |
| frontend production build | PASS，1957 modules |
| CI guard / credential / forbidden artifact / API boundary | PASS |
| Code Review SHA remote CI | PASS，15/15 checks |
| Phase 2 runs | PASS，`31372728072`、`31372731324` |
| Phase 3 run | PASS，`31372731260` |

## 6. 安全与范围复核

- `PR_A3_SYNTHETIC_IMPORT_ENABLED` 默认关闭。
- `source_mode` 仅允许 `synthetic_contract`；真实 adapter 保持 fail closed。
- 未调用 Shopee/TikTok Shop 真实 API。
- 未新增 scheduler、正式 webhook、历史回补或平台写接口。
- 未新增 finance、purchasing、RPA 或 Production 同步能力。
- Shopee 与 TikTok Shop 均保持 `pending/mock`。
- Production synchronization 保持 OFF。
- 未将 `.wslconfig`、`.env.local`、数据库 volume、密码或临时验证配置加入 Git。

## 7. R4 入场状态更正与开发整改结论

上一轮“Open P1: 0”“attempt audit bulk protection PASS”和独立复审待签字的表述不准确。R4 入场冻结状态为：

```text
Open P1: 1
P2-003: REOPENED / escalated to P1
Attempt audit bulk protection: FAIL
Independent Review: FAIL / REQUEST CHANGES
```

完成本轮代码、测试、MySQL、前端、扫描和 Code Review SHA 远端 CI 后，开发侧状态为：

```text
P0: 0
Open P1: 0
Open P2: 0

Developer R4 Remediation Evidence: PASS
MySQL 8.4 Engineering Gate: PASS
Independent R4 Review: PENDING

PR #45: KEEP OPEN / DRAFT / UNMERGED
A-REAL-PLATFORM-CONNECTION: FAIL / REQUEST CHANGES
Shopee: pending/mock
TikTok Shop: pending/mock
Production Synchronization: OFF
Real Platform API: NOT CALLED
Merge: FORBIDDEN pending independent review
```

本证据只关闭开发侧 R4 P1/P2，不替代架构、安全、测试、数据与发布负责人的独立签字；也不批准真实平台连接或 Production 同步。

独立复审随后在 Evidence HEAD `d52f11f8994ed7291baa67d5469c2b390787532c` 再次给出 `FAIL / REQUEST CHANGES`：`_base_manager.bulk_create()` 仍可伪造审计（Open P1: 1），PR 正文和测试报告仍引用旧 SHA/结果（Open P2: 1）。本次追加整改已在开发侧封住 base manager 并更新证据，但独立复审状态重新置为 `PENDING`，不得沿用上一轮结论。

## 8. R4 实现和验证证据

- attempt audit 创建 ContextVar 与 context manager 为私有能力，只有 `_audit_attempt()` 使用；默认 manager、Django `_base_manager`、queryset 和实例创建/更新/bulk/delete 入口均受保护。
- `MarketplaceImportBatchAttempt.Meta.base_manager_name = "objects"`，`_base_manager.bulk_create()` 负向测试证明拒绝且 0 写入；`marketplace_imports.0003` 仅记录该 manager 元数据。
- 合法状态组合、tenant/store/actor、attempt version、active owner 和 started 前置记录在模型层校验。
- 业务执行使用内层保存点，attempt 生命周期使用外层事务；success audit 故障测试证明 records/cursor 回滚并形成受控 failed 状态。
- MySQL 8.4.11 fresh、`0001 -> 0002 -> 0003` upgrade、focused `57 passed / 0 skipped`、backend full `603 passed / 0 skipped`；双 worker retry started/success 各最多 1 条。
- SQLite focused `56 passed / 1 skipped`、backend full `599 passed / 4 skipped`；SQLite skipped 仅为 MySQL-only 并发测试，不记为 MySQL PASS。
- 前端 13 files / 163 tests、1957 modules build PASS；CI guard、credential、forbidden artifact、API boundary、生成物 tracking 和 `git diff --check` 全部 PASS。
- Code Review SHA `4c75eda5458fafc9d1d9fb0833392c94ce106f2a` 远端 CI 15/15 PASS。

## 9. 独立 R4 复审表

```text
PR-A3 SALES / INVENTORY OFFLINE IMPORT R4 REVIEW

Repository: dfcy-team/dfcy
PR: #45
Branch: feature/module-a-sales-inventory-import
Base SHA: 75995f74ec74a3315065ecfcec317edda8b1df73
Code Review SHA: 4c75eda5458fafc9d1d9fb0833392c94ce106f2a

Draft / Unmerged: PASS
Scope Boundary: PENDING REVIEW
Synthetic Switch Default OFF: PENDING REVIEW
Tenant / Store / Platform Isolation: PENDING REVIEW
Exact Permissions: PENDING REVIEW
Failed Retry Ownership: PENDING REVIEW
Failed Retry MySQL Concurrency: PENDING REVIEW
Service-only Attempt Audit Creation: PENDING REVIEW
Immutable Retry Audit: PENDING REVIEW
SQLite Migration: DEVELOPER EVIDENCE PASS
MySQL 8.4 Fresh / Upgrade: DEVELOPER EVIDENCE PASS
MySQL Focused Tests: DEVELOPER EVIDENCE PASS, 57 passed / 0 skipped
MySQL Backend Full: DEVELOPER EVIDENCE PASS, 603 passed / 0 skipped
Frontend Tests / Build: DEVELOPER EVIDENCE PASS
Remote CI: DEVELOPER EVIDENCE PASS on Code Review SHA
Real Platform Network: NOT CALLED
Production Synchronization: OFF

P0: 0
OPEN P1: 0 after developer remediation
OPEN P2: 0

DEVELOPER R4 REMEDIATION: PASS
INDEPENDENT R4 REVIEW RESULT: PENDING
MERGE: FORBIDDEN UNTIL INDEPENDENT PASS

Architecture Reviewer:
Security Reviewer:
Test Reviewer:
Data Reviewer:
Release Reviewer:
Date:
```
