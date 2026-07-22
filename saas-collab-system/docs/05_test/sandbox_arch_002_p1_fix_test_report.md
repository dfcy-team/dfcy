# SANDBOX-ARCH-002 P1 整改测试记录

## 测试结论

本机已完成可执行的定向测试，结果为 `PASS`。远程 CI 结果需在整改提交推送后独立核验。

## 执行记录

| 范围 | 执行方式 | 结果 |
|---|---|---|
| 公开绕过参数扫描 | 搜索非文档源码中的 `test-mode` / `test_mode` | PASS，运行时引用为 0 |
| 伪造 pytest 环境 | `test_forged_pytest_environment_cannot_bypass_database_target_guard` | PASS，拒绝非本地库名 |
| 远程主机绕过 | `test_local_database_name_does_not_allow_unapproved_remote_host` | PASS，拒绝未批准主机 |
| 种子命令专项测试 | Docker 后端环境执行 `tests/test_local_sandbox_seed.py` | PASS，`6 passed in 8.91s` |
| Django 系统和迁移检查 | `manage.py check` / `makemigrations --check --dry-run` | PASS，0 issues / no changes |
| 后端全量回归 | Docker 后端环境执行全量 pytest | PASS，`405 passed in 24.15s` |
| 合成 fixture | `python deploy/dev-sandbox/validate_contract.py` | PASS，全部 fixture |
| RC manifest | 合同验证器正向、占位 SHA 负向、镜像不匹配负向 | PASS |
| PowerShell 一键合同 | `sandbox.ps1 -Action contract` | PASS，五个 profile |
| Shell 一键合同 | `sandbox.sh contract integration` | PASS，五个 profile |
| PowerShell 语法 | PowerShell Parser | PASS |

## 未执行项

- 宿主机 Python 缺少 pytest，未直接在宿主机执行 pytest。
- 该项已在包含项目依赖的 Docker 后端环境实际执行，不使用伪造结果。
- GitHub Actions 专用门禁待推送后执行。
