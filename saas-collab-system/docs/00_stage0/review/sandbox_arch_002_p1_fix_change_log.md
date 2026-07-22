# SANDBOX-ARCH-002 P1 整改变更日志

## 1. 整改对象

- 实现 PR：#34
- R1 审核结论：`CONDITIONAL_PASS`
- 整改问题：
  - `SANDBOX-ARCH-002-R1-P1-001`：公开 `--test-mode` 可通过伪造环境变量绕过数据库目标保护。
  - `SANDBOX-ARCH-002-R1-P1-002`：远程 CI 未覆盖 Local Sandbox 合同和一键验证。

## 2. P1-001 整改

- 删除 `seed_local_sandbox` 的公开 `--test-mode` 参数。
- 数据库名称必须始终以 `saas_collab_local_` 开头。
- 数据库主机必须始终为 `mysql`、`localhost` 或 `127.0.0.1`。
- `PYTEST_CURRENT_TEST` 或其他调用方可控环境变量不再影响保护逻辑。
- 测试代码仅在测试进程内替换连接元数据，不向运行时命令暴露绕过开关。
- 增加公开参数不存在、伪造 pytest 环境仍拒绝、本地库名配合远程主机仍拒绝的回归测试。

## 3. P1-002 整改

- 新增 `.github/workflows/local-sandbox-contract.yml`。
- CI 显式执行 Local Sandbox 种子保护回归测试。
- CI 检查 Shell 和 PowerShell 一键入口语法。
- Shell 和 PowerShell 均新增 `contract` 动作，实际验证五个 profile 的 Compose 配置。
- 新增 `validate_contract.py`，验证全部合成 fixture、Mock 和高风险开关安全默认值，以及 RC manifest 正向和负向合同。
- CI 明确检查 RC Compose 不含 `build:`，不依赖真实平台密钥。

## 4. 实际验证

| 检查项 | 结果 |
|---|---|
| `validate_contract.py` | PASS，全部 fixture、RC 正反合同和安全默认值通过 |
| PowerShell `contract` | PASS，五个 profile 通过 |
| Shell `contract` | PASS，五个 profile 通过 |
| Docker 种子命令专项 pytest | PASS，`6 passed in 8.91s` |
| Django check / migration 一致性 | PASS，0 issues / no changes |
| Docker 后端全量 pytest | PASS，`405 passed in 24.15s` |
| 宿主机 pytest | 未执行，宿主机 Python 未安装 pytest；已在项目 Docker 后端环境实际执行 |
| 远程 Local Sandbox CI | 待本整改提交推送后核验 |

## 5. 安全确认

- 未添加真实 `.env`。
- 未添加真实密钥、Token、Cookie、Session 或平台凭据。
- 未连接真实 BigSeller、Shopee、TikTok/TK、银行或支付平台。
- 未开启真实高风险自动化。
- `.env.local` 仍由 Git 忽略。

## 6. 待复审

- 固定 PR #34 整改后 HEAD。
- 等待新增 Local Sandbox CI 门禁成功。
- 执行独立 `SANDBOX-ARCH-002-R2`，确认两项 P1 正式关闭。
