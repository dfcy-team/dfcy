# SANDBOX-ARCH-002-R2 Local Sandbox P1 整改复审报告

## 1. 复审对象

- 实现 PR：#34
- 审核对象：`origin/codex/local-sandbox-profiles`
- 固定 HEAD：`b590b9e3bbfe6bb6d221f4882f932b80270edb14`
- 对比基线：`origin/main@5e06191cc79ea341e00c0a51631178e94507ae60`
- 原 R1 报告：`sandbox_arch_002_r1_review.md`
- 整改证据：`sandbox_arch_002_p1_fix_change_log.md`、`sandbox_arch_002_p1_fix_test_report.md`
- 复审日期：2026-07-22
- 复审性质：独立只审核；未在开发分支修改实现代码

## 2. 复审结论

**PASS**

R1 的两项 P1 均已关闭，未发现新增 P0/P1。种子命令不再暴露测试绕过参数，数据库名称和主机保护无条件执行；远程 CI 已新增 Local Sandbox 专用门禁，实际执行 profiles、fixtures、RC 正反合同、种子保护和 Shell/PowerShell 一键入口。

PR #34 当前为 OPEN / Draft，HEAD 与本报告固定提交一致，共 11/11 远程检查为 SUCCESS，mergeable 为 MERGEABLE。

## 3. 原 P1 关闭情况

| 原问题 | 是否关闭 | 证据 | 备注 |
|---|---|---|---|
| SANDBOX-ARCH-002-R1-P1-001 种子命令测试模式可绕过数据库目标保护 | 是 | `seed_local_sandbox.py`、`test_local_sandbox_seed.py`、独立 `6 passed` | 公开 `--test-mode` 已删除，伪造 pytest 环境和远程主机均被拒绝 |
| SANDBOX-ARCH-002-R1-P1-002 远程 CI 未覆盖 Local Sandbox 合同 | 是 | `.github/workflows/local-sandbox-contract.yml`、`validate_contract.py`、GitHub Actions run `29895380818` | 专用门禁实际执行两套一键合同入口并成功 |

## 4. P1-001 数据库目标保护复审

代码复核结果：

1. `seed_local_sandbox` 参数仅保留 `--module` 和必须显式提供的 `--confirm-local`。
2. 非文档源码中无 `--test-mode` 或运行时 `test_mode` 分支。
3. `PYTEST_CURRENT_TEST` 仅出现在伪造环境的负向回归测试中，不再参与运行时安全判断。
4. 数据库名称无条件要求 `saas_collab_local_` 前缀。
5. 数据库主机无条件限定为 `mysql`、`localhost` 或 `127.0.0.1`。
6. 测试代码在测试进程内临时替换连接元数据，未将绕过能力暴露给管理命令调用方。

独立执行：

- Docker 后端环境运行 `tests/test_local_sandbox_seed.py`：`6 passed in 9.12s`。
- 负向用例覆盖“伪造 `PYTEST_CURRENT_TEST` + 非本地库名”和“本地名称 + 未批准远程主机”。

结论：**P1-001 已关闭**。

## 5. P1-002 Local Sandbox CI 合同复审

`.github/workflows/local-sandbox-contract.yml` 已设置 `pull_request`、`main` push 和手动触发，并对 Local Sandbox 相关文件变更执行以下内容：

1. 安装锁定的后端依赖。
2. 执行种子命令专项 pytest，包含 P1-001 负向用例。
3. 执行 PowerShell parser 和 `sh -n`。
4. 通过 Shell `contract` 动作解析 core、销售库存财务对账、达人管理、采购和 integration 五个 profile。
5. 通过 PowerShell `contract` 动作重复验证五个 profile。
6. `validate_contract.py` 校验全部 fixture、Mock/高风险开关安全默认值、RC 匹配合同、占位 SHA 拒绝和镜像摘要不匹配拒绝。
7. RC Compose 必须不含 `build:`，CI 不依赖真实平台密钥。

远程实际证据：

- GitHub Actions run：`29895380818`。
- 种子保护专项：`6 passed in 16.44s`。
- Shell：`LOCAL_SANDBOX_ONE_CLICK_CONTRACT=PASS profiles=all`。
- PowerShell：`LOCAL_SANDBOX_ONE_CLICK_CONTRACT=PASS profiles=all`。
- PR #34 固定 HEAD 共 11/11 检查 SUCCESS。

独立本机执行：

- `python validate_contract.py`：PASS。
- `sandbox.ps1 -Action contract -SandboxProfile integration`：PASS，`profiles=all`。
- `sandbox.sh contract integration`：PASS，`profiles=all`。

结论：**P1-002 已关闭**。

## 6. 安全与边界扫描

- `ci_guard.py --root ..`：PASS，未发现禁止文件或高置信凭据模式。
- 未跟踪 `deploy/dev-sandbox/.env.local`，该文件由 `.gitignore` 覆盖。
- 扫描出的 URL 仅为 `example.test`、`test.invalid`、本地地址、配置占位符或 Nginx 容器内部路由。
- 未发现真实 BigSeller、Shopee、TikTok/TK、银行或支付平台连接。
- 未发现自动采购、清仓、停售、归档、改价、真实 RPA 或资金操作。
- PR #34 仍为 Draft，本次复审未提前合并或修改实现分支。

## 7. 未执行项与说明

- R2 未重复启动完整 Docker integration 应用栈；R1 已实际执行，且 R1 整改要求明确允许专用 CI 采用轻量合同门禁。
- R2 未在原生 Linux/macOS 主机执行完整 `verify` 生命周期；GitHub Ubuntu runner 已执行 Shell 合同入口。
- 宿主机 Python 未安装 pytest，独立 pytest 在包含项目依赖的 Docker 后端环境执行。

## 8. P0

无。

## 9. P1

无。R1 的两项 P1 已关闭。

## 10. P2

1. RC 本地运行仍使用 dev settings 和 test-only provider，只适合制品身份与启动观察，不替代生产设置、TLS、迁移预检和回滚验证。
2. Local Sandbox 开发 Dockerfile 的基础镜像仍使用 tag，后续可固定 digest 提高开发环境可复现性。
3. 原生 POSIX 主机完整一键 `verify` 生命周期尚未执行。
4. 前端构建的第三方 `PURE` 注释警告继续作为非阻断观察项。

## 11. 最终准入建议

- 是否允许将 PR #34 转为 Ready：**允许**。
- 是否建议合并 PR #34：**允许，但必须在合并前再次固定 HEAD 为 `b590b9e3bbfe6bb6d221f4882f932b80270edb14`并确认 11/11 CI 仍为 SUCCESS**。
- 是否允许将模块化 Local Sandbox Profiles 标记为标准化完成：**允许，待 PR #34 合并 main 后生效**。
- 是否允许真实平台或高风险自动化：**不允许，必须另行专项安全评审**。
