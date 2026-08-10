# PR-A3 准入审核材料

任务：`PR-A3-ENTRY-REVIEW`

生成日期：2026-08-10

材料状态：**DRAFT / NOT APPROVED**
当前结论：**不满足 PR-A3 准入条件**

本材料用于判断是否允许开始 Shopee / TikTok Shop 销售与库存数据导入设计和开发。它不批准 Production，不批准任何同步任务，也不把代码实现或本机路由可用解释为真实平台已连接。

## 1. 准入结论

```text
A-REAL-PLATFORM-CONNECTION review = FAIL / REQUEST CHANGES
Shopee capability = pending/mock
TikTok Shop capability = pending/mock
PR-A3 admission = NOT APPROVED
Production synchronization = OFF
```

阻断原因：两平台真实 OAuth、authorized shop、最小只读 API、refresh、revoke、reauthorization 尚未形成完整脱敏证据；真实流程后的数据库、日志和浏览器凭据扫描尚未完成；独立架构、安全、测试、数据和发布复审尚未签字；公网 callback 路由和日志脱敏尚未形成可接受证据；当前 stacked PR 均为 Draft 且未合并。

## 2. 冻结证据身份

| 字段 | 值 |
|---|---|
| Repository | `dfcy-team/dfcy` |
| PR-A2 | Draft [#41](https://github.com/dfcy-team/dfcy/pull/41) |
| PR-A2 branch / SHA | `feature/module-a-marketplace-oauth` / `5c3d285e2bf89baa13f669c71e6ef6cbfb9263e0` |
| 正式平台连接 PR | Draft [#42](https://github.com/dfcy-team/dfcy/pull/42) |
| PR #42 base / head | `feature/module-a-marketplace-oauth` / `a276fa647081ccdec1484473450d2b0828479480` |
| 配置 UI stacked PR | Draft [#43](https://github.com/dfcy-team/dfcy/pull/43) |
| PR #43 base / Code Review SHA | `feature/module-a-real-platform-connection` / `d36be683668f819f9471c9af3195ab37f443a9f3` |
| Code Review SHA | `d36be683668f819f9471c9af3195ab37f443a9f3` |
| Artifact source SHA | `d36be683668f819f9471c9af3195ab37f443a9f3` |
| Previous fully passed evidence baseline SHA | `d183f1870339af6517e29b2382e33a188f443757` |
| Evidence HEAD SHA | 复审签字时从 PR #43 `headRefOid` 冻结；提交不能自包含其自身 SHA |
| CI SHA | 必须等于复审签字时冻结的 Evidence HEAD SHA |
| Evidence-only diff | 从 Code Review SHA 到 Evidence HEAD 仅允许修改本文档；用 `git diff --name-only` 复核 |
| PR #42 commit count / changed files | 8 / 39 |
| PR #43 stacked commit count / changed files | 7 / 51 |
| Deployment environment | 本机受控 Pilot；Production 同步关闭 |
| Deployment artifact | `a-real-platform-d36be68.zip` |
| Artifact SHA-256 | `35B344C87F0FD9F43EC9250B5339E86BDD464F80030D25D9E28C46362C093C63` |
| Artifact size | 1,614,807 bytes |
| Container image digest | `NOT AVAILABLE` |
| Database | MySQL 8.4.10（已记录；须在最终 Code Review SHA 上复核） |
| Integrations migration head | `0015_file_credential_custody_metadata` |
| Permissions migration head | `0016_seed_api_platform_config_permissions` |
| Review date | 2026-08-10 |

冻结说明：PR #41、#42、#43 均为 `OPEN / Draft`。当前制品来自固定 Code Review SHA；Evidence HEAD/CI 允许晚于 Code Review SHA，但差异必须仅为本文档，且 CI SHA 必须与签字时的 Evidence HEAD SHA 一致。禁止再笼统声称“CI SHA 与 Review SHA 一致”。不存在容器镜像 digest，因此不能把本机制品等同于正式部署镜像证据。

## 3. 已取得的工程证据

| 检查 | 结果 | 限制 |
|---|---|---|
| `git diff --check` | PASS | 仅证明差异格式 |
| Django `check` | PASS，0 issues | 本机环境 |
| `makemigrations --check --dry-run` | PASS，No changes | 本机环境 |
| 后端 focused 配置安全测试 | PASS，21 tests | fake transport / synthetic evidence |
| 后端全量 pytest | PASS，550 passed / 3 skipped | 未替代真实平台测试 |
| 前端全量测试 | PASS，166 passed | 未替代浏览器真实流程扫描 |
| 前端 production build | PASS，1963 modules | 本机制品 |
| PR #43 远程 CI | PASS at previous evidence baseline `d183f18` | 后续整改提交必须重新全绿；CI SHA 绑定 Evidence HEAD，不等于 Code Review SHA |
| 本机后端 health | PASS，HTTP 200 | 仅本机运行状态 |
| 本机 Shopee callback 路由 | PASS，缺少参数时返回受控 HTTP 400 | 仅证明路由存在，不证明 OAuth 成功 |
| Pilot loopback callback 限制 | PASS | 仅允许 `127.0.0.1:8000` 固定平台路径；Production 仍强制 HTTPS |
| Production 同步边界 | PASS by code/test | 订单、库存、财务、webhook、定时任务、RPA 和平台写能力未因本任务开启 |

由于真实 OAuth、callback、authorized shop、refresh、revoke 和最小只读 API 均未完成，上述结果只支持 `pending/mock`，不支持 `pending/live-validation` 或 `connected`。

## 4. 前置复审状态

| 门禁 | 状态 | 说明 |
|---|---|---|
| PR-A1 架构/安全 R2 | PASS | 固定范围结论；不证明真实平台连接 |
| PR-A2 OAuth/state/permission 基线 | PASS in developer regression | 最终准入仍须由独立复审人员重新确认 |
| A-REAL-PLATFORM-CONNECTION 独立复审 | FAIL | 真实平台矩阵和真实流程后扫描未完成 |
| MySQL 8.4 migration | PARTIAL | 已记录 8.4.10 和 migration head；须对最终 Code Review SHA 重跑并冻结输出 |
| MySQL 同授权双 worker refresh | NOT RUN on final live authorization | synthetic/MySQL 工程测试不能替代真实授权引用验证 |
| Local Sandbox integration | PASS previously | 不能替代固定真实 Pilot 制品证据 |
| 固定部署制品 | PARTIAL | zip SHA 已固定，无镜像 digest |
| 工作区干净 | PASS at evidence freeze | 最终签字前必须再次复核 |

## 5. 真实平台准入矩阵

| 必须证据 | Shopee | TikTok Shop |
|---|---|---|
| 获批应用和当前官方合同 | PARTIAL | PARTIAL |
| Callback 与平台后台完全一致 | NOT PROVEN | NOT PROVEN |
| 真实 OAuth initiate | NOT RUN | NOT RUN |
| 真实 callback / state 一次性消费 | NOT RUN | NOT RUN |
| authorization code 交换 | NOT RUN | NOT RUN |
| 凭据直接进入 custody | NOT RUN | NOT RUN |
| authorized shop discovery | NOT RUN | NOT RUN |
| shop identity / `shop_cipher` | NOT RUN | NOT RUN |
| 主体与内部 tenant/store 绑定 | NOT RUN | NOT RUN |
| 跨 tenant 重复绑定冲突 | NOT RUN with real subject | NOT RUN with real subject |
| 最小只读 metadata | NOT RUN | NOT RUN |
| refresh | NOT RUN | NOT RUN |
| refresh version monotonicity | NOT RUN with live reference | NOT RUN with live reference |
| 双 worker refresh concurrency | NOT RUN with live reference | NOT RUN with live reference |
| revoke | NOT RUN | NOT RUN |
| repeated revoke idempotency | NOT RUN | NOT RUN |
| reauthorization / new reference | NOT RUN | NOT RUN |
| 429 / 5xx / timeout | PASS in controlled simulation only | PASS in controlled simulation only |
| custody failure | PASS in controlled simulation only | PASS in controlled simulation only |
| database failure | PARTIAL in automated tests | PARTIAL in automated tests |

一个平台通过不得提升另一个平台；一个店铺通过不得提升整个 tenant。

## 6. 安全扫描与日志门禁

| 扫描 | 状态 | 准入要求 |
|---|---|---|
| Git credential scan | PASS for current tracked tree | 最终 Code Review SHA 再跑，0 raw findings |
| Forbidden artifact scan | PASS for current tracked tree | 最终 Code Review SHA 再跑 |
| 业务数据库 raw credential scan | NOT RUN after live OAuth | 必须为 0 |
| Django/runtime log scan | NOT RUN after live OAuth | 必须为 0 |
| Nginx callback query scan | BLOCKED | 公网 callback 曾在进入 Django 前返回 404；须确认相关日志不含原始 query，并部署脱敏路由 |
| Docker/Celery/CI/error-report scan | NOT RUN after live OAuth | 必须为 0 |
| 浏览器 storage/cookie/network/console scan | NOT RUN after live OAuth | 必须为 0 |
| API response boundary scan | PASS in automated tests / NOT RUN live | 真实流程后复核 |
| Audit immutability | PASS in regression / NOT RUN live | 真实 revoke/reauthorize 后复核 |

不得把真实 Token、Secret、Cookie、Session、完整 authorization code 或 callback query 复制到本材料、PR、Issue、聊天或截图中。真实验证只记录 mask、内部 reference、reference version、状态、时间和受控错误码。

## 7. P0 / P1 / P2

### P0

未在当前代码和脱敏证据中确认 P0。若后续扫描发现真实凭据泄漏、跨 tenant 访问或 OAuth state 可绕过，立即停止真实连接、禁用 live network 并进入安全事件流程。

### P1（当前未关闭）

1. Shopee 真实 OAuth、authorized shop、最小只读 API、refresh、revoke、reauthorization 未完成。
2. TikTok Shop 真实 OAuth、authorized shop/`shop_cipher`、最小只读 API、refresh、revoke、reauthorization 未完成。
3. 两平台真实授权引用的 MySQL 双 worker refresh 并发证据缺失。
4. 真实流程后的数据库、Nginx、Django、Docker/Celery/CI 和浏览器扫描缺失。
5. 公网 callback 路由与 query 日志脱敏未形成可接受证据。
6. 容器镜像 digest 不可用；正式运行环境与 Code Review SHA 的构建链未完成。
7. 架构、安全、测试、数据和发布独立复审未签字。
8. PR #41、#42、#43 仍为 Draft，正式平台连接基线未合并或形成独立批准的固定基线。

### P2

- 本机开发制品使用工作区已验证依赖运行时；正式部署应使用固定镜像和 digest。
- MySQL 对 finance 条件唯一约束的既有 warning 与本准入任务无直接关系，但应由数据负责人记录。

## 8. PR-A3 第 43 节准入检查

- [ ] A-REAL-PLATFORM-CONNECTION 复审 PASS。
- [ ] 无未关闭 P0/P1。
- [ ] 当前基线已合并或由审批人书面固定。
- [ ] 从最新 `main` 创建或同步 PR-A3 分支。
- [ ] Shopee capability 与真实平台证据一致。
- [ ] TikTok Shop capability 与真实平台证据一致。
- [x] Production 同步保持 OFF。
- [x] 订单/库存数据口径未因 OAuth 工程完成而默认批准。
- [x] 全量初始化、增量游标、幂等、退款取消、库存口径和限流保留给 PR-A3 独立设计复审。

准入判定：**3/9 边界项满足，6/9 核心准入项未满足；NOT APPROVED。**

## 9. 关闭阻断项所需的最小证据包

1. 从同一远程 Code Review SHA 构建固定镜像，记录 artifact SHA 和 image digest。
2. 在已部署脱敏 callback 路由的受控环境中，为 Shopee 和 TikTok Shop 分别创建新的 OAuth state。
3. 完成两平台 OAuth、主体绑定、authorized shop、最小只读 metadata、refresh、并发 refresh、revoke 和 reauthorization。
4. 每个平台、每个试点店铺独立记录 mask/reference/version/status/error code，不记录真实凭据。
5. 真实流程后执行 Git、数据库、日志、浏览器和 API boundary 扫描，全部为 0 raw findings。
6. 复核 Production 同步、订单、库存、webhook、定时任务、历史回补、财务、RPA 和平台写能力全部关闭。
7. 架构、安全、测试、数据和发布负责人对同一 Code Review SHA、Evidence HEAD/CI SHA 和制品签字。
8. 重跑 focused/full backend、frontend test/build、MySQL 8.4、Sandbox、CI 和相关真实平台场景。

整改后不得只验证修改点，必须重新执行完整 A-REAL-PLATFORM-CONNECTION 复审。

## 10. 正式签字表

```text
PR-A3 ENTRY REVIEW

Code Review SHA: d36be683668f819f9471c9af3195ab37f443a9f3
Artifact Source SHA: d36be683668f819f9471c9af3195ab37f443a9f3
Previous Fully Passed Evidence Baseline SHA: d183f1870339af6517e29b2382e33a188f443757
Evidence HEAD SHA: <freeze from PR #43 headRefOid at signing>
CI SHA: <must equal Evidence HEAD SHA>
Evidence-only Diff: docs/00_stage0/review/pr_a3_entry_admission_review_materials.md only
Artifact SHA-256: 35B344C87F0FD9F43EC9250B5339E86BDD464F80030D25D9E28C46362C093C63
Image Digest: NOT AVAILABLE

A-REAL-PLATFORM-CONNECTION Review: FAIL / REQUEST CHANGES
Shopee: pending/mock
TikTok Shop: pending/mock
Production Synchronization: OFF
PR-A3 Admission: NOT APPROVED

Architecture Reviewer:
Security Reviewer:
Test Reviewer:
Data Reviewer:
Release Reviewer:
Date:
```

任何签字前对代码 Review SHA、制品、数据库版本、migration head 或真实验证环境的变更都会使本表失效，必须重新冻结证据。

## 11. 参考材料

- `docs/00_stage0/review/a_pr1_arch_security_r2_review.md`
- `docs/03_api/pr_a2_marketplace_oauth_contract.md`
- `docs/05_test/pr_a2_marketplace_oauth_test_report.md`
- `docs/05_test/real_platform_connection_review.md`
- `docs/05_test/shopee_tiktok_live_connection_test_report.md`
- `docs/05_test/api_platform_configuration_ui_test_report.md`
- `docs/00_stage0/review/a_real_platform_connection_review.md`
- `docs/00_stage0/review/developer_a_real_platform_connection_change_log.md`
- `docs/00_stage0/review/developer_a_api_platform_configuration_ui_change_log.md`
- `docs/06_release/a_real_platform_connection_release_notes.md`
- `docs/06_release/a_real_platform_connection_rollback_guide.md`
