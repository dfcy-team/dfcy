# SANDBOX-ARCH-002-R1 模块化 Local Sandbox 独立复审报告

## 1. 复审对象

- 复审日期：2026-07-22
- 审核 PR：[#34](https://github.com/dfcy-team/dfcy/pull/34)
- base：`main`
- head：`codex/local-sandbox-profiles`
- 固定审核 HEAD：`c2c85c7116a02441a0ea774c842a6ae8d79a9658`
- 对比基线：`origin/main@5e06191cc79ea341e00c0a51631178e94507ae60`
- 审核性质：只审核，不修改 PR #34 的实现代码

审核依据：

- `sandbox_arch_002_decision_record.md`
- `sandbox_arch_002_local_profiles_change_log.md`
- `sandbox_arch_002_local_profiles_test_report.md`
- PR #34 的提交、文件差异和远端 CI
- `deploy/dev-sandbox/`、`seed_local_sandbox.py` 及对应测试

## 2. 复审结论

**CONDITIONAL_PASS**

未发现 P0。模块化 Compose Profiles、合成数据、只读 Creator Mock、Windows/Linux 一键脚本、MySQL 测试库最小授权和不可变摘要格式门禁均已落地，实际 Docker integration 验证和远端应用 CI 均通过。

仍有两项 P1：种子命令的测试模式可以被调用方伪造环境变量而绕过数据库名称和主机保护；仓库 CI 没有执行新增 Local Sandbox 合同，因此当前全部绿色 CI 不能证明 profiles、fixtures、RC 摘要校验和一键脚本不会回归。PR #34 应继续保持 Draft，完成定向整改后执行 R2。

## 3. 分支、范围与远端状态

- PR #34 状态：OPEN / Draft。
- mergeable：MERGEABLE。
- PR 仅包含 21 个预期文件：`deploy/dev-sandbox/`、种子命令及测试、审计文档和 `.gitignore` 精确规则。
- 未修改 `frontend/`、`rpa-agent/`、`docs/04_rpa/` 或生产部署代码。
- 全部 10 项现有远端检查为 SUCCESS。
- 未发现真实 `.env`、运行产物、证书、私钥或真实业务数据进入 PR。

## 4. Profiles 与生命周期审核

已实现并可解析：

- `core`
- `sales-inventory-finance-reconciliation`
- `creator-management`
- `procurement`
- `integration`
- `release-candidate`

五个开发 profile 均通过 `docker compose config --quiet`。服务端口默认绑定 `127.0.0.1`；`stop integration` 能移除容器和网络而保留数据卷；`reset` 缺少显式确认时拒绝执行。

## 5. 合成数据与权限审核

已确认：

- 种子数据使用两个 tenant，并生成 internal、finance、creator、external、RPA 和第二 tenant 查看账号。
- 普通 internal 角色不包含 `finance.*`，财务权限由独立角色授予。
- Creator Mock 角色没有业务写权限，Mock Server 的写方法返回 405。
- 数据标识使用 `LOCAL-*`、`demo`、`synthetic`、`placeholder` 和 `example.com`。
- integration 种子幂等，测试覆盖两 tenant、非超级用户和财务权限分离。

但 `--test-mode` 的可信边界不成立，见 P1-001。

## 6. Mock 与真实平台边界

- Creator Mock 仅提供本地只读路由；GET 为 200，未知路由为 404，写操作为 405。
- fixture 校验器拒绝凭据字段、私钥形态、真实公网接口和凭据形态字符串。
- `SANDBOX_ALLOW_REAL_PLATFORM=false` 和 `SANDBOX_ALLOW_HIGH_RISK_AUTOMATION=false` 在 Compose 和种子命令中均为强制条件。
- 未发现 BigSeller、Shopee、TikTok/TK、银行或支付平台真实连接。
- 未发现自动采购、改价、清仓、停售、归档或资金操作。

## 7. Release Candidate 合同审核

已确认：

- RC Compose 不包含 `build:`。
- Git SHA 必须为非占位 40 位值。
- backend、frontend、MySQL 和 Redis 必须使用 `@sha256`。
- 环境值必须与批准清单逐项一致。
- 占位 SHA/digest 被拒绝，匹配的示例合同可通过。

观察项：RC 本地运行仍使用 `config.settings.dev`、`DEBUG=true` 和 `test-only` provider，因此它验证的是制品身份及本地可启动性，不是 production settings/TLS 的等价验证。文档已明确 RC PASS 不代表允许生产发布，本项列为 P2。

## 8. 实际验证证据

| 检查项 | 结果 |
|---|---|
| 五个开发 profile Compose 配置 | PASS |
| RC Compose 配置及无本地 build | PASS |
| Python 编译 | PASS |
| PowerShell 语法 | PASS |
| Alpine `sh -n` | PASS |
| fixture integration 校验 | PASS，4 files |
| Docker core 后端 | PASS，20 passed |
| Docker integration 后端 | PASS，402 passed |
| Phase 3 数据质量 | PASS |
| 前端测试 | PASS，153 passed |
| 前端构建 | PASS |
| 仓库 CI Guard | PASS |
| PR #34 远端 CI | PASS，10/10 |
| `--test-mode` 伪造负向验证 | **FAIL，已复现保护绕过** |
| Local Sandbox 专项 CI 检索 | **FAIL，无 workflow 引用新增合同** |

## 9. 安全扫描

- 未发现真实账号、密码、Token、Cookie、Session、API Key 或 API Secret。
- 未发现真实平台、供应商、订单、财务或银行数据。
- `.env.local`、`frontend/dist`、`node_modules`、缓存和 Celery Beat 状态文件均未进入提交。
- PR #34 的仓库安全与禁止文件检查均成功。

## 10. P0

无。

## 11. P1

### SANDBOX-ARCH-002-R1-P1-001：种子命令测试模式可绕过数据库目标保护

证据：`seed_local_sandbox.py:83-86` 仅凭调用参数 `--test-mode` 和可由调用方设置的 `PYTEST_CURRENT_TEST` 判定测试模式；进入该模式后跳过数据库名称前缀和主机白名单。

独立负向验证将数据库名称设为 `production_like_db`、主机设为 `remote.example`，同时伪造 `PYTEST_CURRENT_TEST`，`_validate_environment()` 未拒绝并输出 `TEST_MODE_GUARD_BYPASS=REPRODUCED`。

整改要求：

1. 删除可从管理命令公开触发的保护绕过，或要求测试数据库本身满足严格的 SQLite 内存库/`test_saas_collab_local_*` 和本地主机约束。
2. 不得把可伪造环境变量当作数据库安全边界。
3. 增加负向测试：即使提供 `--test-mode` 和伪造环境变量，非本地数据库名称或远端主机仍必须被拒绝。

### SANDBOX-ARCH-002-R1-P1-002：远端 CI 未覆盖新增 Local Sandbox 合同

证据：`.github/workflows/` 中没有 `dev-sandbox`、`validate_fixtures.py`、`validate_rc_manifest.py`、`sandbox.ps1` 或 `sandbox.sh` 引用。现有 CI 虽为全绿，但只执行既有应用测试、根 Compose 和通用安全门禁。

整改要求：

1. 新增轻量 CI job，至少检查五个开发 profile 和 RC Compose 配置。
2. 执行 fixture integration 校验、RC 占位拒绝/匹配合同测试、Python 编译、PowerShell parser 与 `sh -n`。
3. 执行种子保护专项 pytest，包括 P1-001 的负向用例。
4. CI 不需要启动完整 Docker integration，但必须覆盖新增合同和保护逻辑；完整 402/153 测试可继续复用现有 job。

## 12. P2

1. RC 本地运行使用 dev settings 和 test-only provider，只能作为制品身份/启动观察，不能替代 production settings、TLS、迁移预检和回滚验证。
2. Local Sandbox 开发 Dockerfile 的 Python、Node、MySQL 和 Redis 基础镜像仍使用 tag；本地开发不阻断，但后续可固定 digest 增强可复现性。
3. Linux/macOS 入口已通过 `sh -n`，但完整一键流程尚未在原生 POSIX 主机执行。
4. 前端构建存在第三方 `PURE` 注释警告，不阻断当前整改。

## 13. 整改与 R2 建议

1. 关闭 `--test-mode` 的可伪造绕过，并补充远端数据库负向测试。
2. 增加 Local Sandbox 专项 CI 轻量门禁。
3. 固定整改 commit 和 PR #34 新 HEAD，等待全部 CI 成功。
4. 执行 `SANDBOX-ARCH-002-R2`，重点复核两项 P1，不重复修改业务功能。

## 14. 准入建议

- 是否允许继续整改：**允许**。
- 是否建议将 PR #34 转为 Ready：**不建议**。
- 是否建议合并 PR #34：**不建议**。
- 是否允许团队把 Local Sandbox 标记为标准化完成：**暂不允许**。
- 是否允许真实平台或高风险自动化：**不允许，必须另行专项安全评审**。
