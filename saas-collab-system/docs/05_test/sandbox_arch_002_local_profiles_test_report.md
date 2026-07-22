# SANDBOX-ARCH-002 Local Sandbox 测试报告

## 1. 测试对象

- 分支：`codex/local-sandbox-profiles`
- 基线：`5e06191cc79ea341e00c0a51631178e94507ae60`
- 环境：Windows、Docker Desktop、Docker Compose v2、Python 3.12、Node 22、MySQL 8.4、Redis 7。
- 数据：仅 Local Sandbox 合成数据。

## 2. 静态检查

| 检查项 | 结果 | 证据 |
|---|---|---|
| Python 编译检查 | PASS | 新增 Python 文件可成功编译 |
| PowerShell 语法解析 | PASS | `sandbox.ps1` 无解析错误 |
| Shell 语法解析 | PASS | Alpine 容器内执行 `sh -n sandbox.sh` |
| Compose 配置 | PASS | 五个开发 profile 均通过 `docker compose config --quiet` |
| RC Compose 配置 | PASS | 配置可解析且不存在 `build:` |
| Git diff 格式 | PASS | `git diff --check` 无错误 |

## 3. 合成数据与种子测试

| 检查项 | 结果 |
|---|---|
| 四组 JSON fixture 格式和统一响应结构 | PASS |
| integration fixture 汇总校验 | PASS，`files=4` |
| 显式 `--confirm-local` 保护 | PASS |
| 非本地环境及真实平台/高风险开关拒绝 | PASS |
| 幂等种子执行 | PASS |
| 两 tenant 隔离数据 | PASS |
| 财务权限独立 | PASS |
| 不创建超级用户 | PASS |
| 种子命令专项测试 | PASS，`3 passed` |

## 4. 后端验证

| 命令/范围 | 结果 |
|---|---|
| `python manage.py check` | PASS，0 issues |
| `makemigrations --check --dry-run` | PASS，No changes detected |
| `sync_permissions --check` | PASS |
| 本机聚焦测试 | PASS，`94 passed` |
| 本机全量测试 | PASS，`402 passed` |
| Docker `core` profile | PASS，`20 passed` |
| Docker `integration` profile | PASS，`402 passed in 73.79s` |
| Phase 3 数据质量检查 | PASS |

Docker 测试实际连接 MySQL 8.4。脚本先以容器内 root 准备 `test_saas_collab_local_*`，只向 Sandbox 应用用户授予该测试库权限，不授予全局数据库权限。

## 5. 前端验证

| 检查项 | 结果 |
|---|---|
| `npm ci` | PASS，0 vulnerabilities |
| `npm test` | PASS，11 files / `153 passed` |
| `npm run build` | PASS |
| 容器内页面探测 | PASS |

观察项：`@vueuse/core` 存在第三方 `PURE` 注释位置警告；构建成功，不阻断本次 Local Sandbox 落地。

## 6. Mock 与网络边界

| 检查项 | 结果 |
|---|---|
| Creator Mock GET | PASS，HTTP 200 |
| Creator Mock 写操作 | PASS，HTTP 405 |
| 未知 Mock 路径 | PASS，HTTP 404 |
| 对外监听 | PASS，仅 `127.0.0.1` |
| 真实平台连接扫描 | PASS，未发现真实连接实现 |
| 仓库 CI Guard | PASS，无禁止文件或高置信凭据模式 |

## 7. Release Candidate 门禁

| 检查项 | 结果 |
|---|---|
| 占位 Git SHA/digest | PASS，校验器拒绝 |
| 匹配的示例 SHA/digest/manifest | PASS |
| 清单与四类镜像摘要一致性 | PASS |
| 本地构建禁用 | PASS，RC Compose 无 `build:` |

## 8. 防误操作

- `.env.local` 被 Git 忽略，脚本不打印生成的密码。
- `reset` 未提供显式确认时拒绝执行，验证通过。
- `stop integration` 可停止并移除全部 profile 容器和网络，且不删除数据卷。
- `frontend/dist`、`node_modules`、缓存和 Celery Beat 状态文件未进入提交范围。

## 9. 结论

结论：**PASS_WITH_NON_BLOCKING_OBSERVATIONS**。

模块化 Local Sandbox Profiles、合成测试数据和 Windows 一键验证已通过真实 Docker/MySQL 集成验证。进入合并前仍需独立架构复审；POSIX Shell 已通过语法检查，完整一键流程建议在 Linux/macOS 或 CI 环境复跑。
