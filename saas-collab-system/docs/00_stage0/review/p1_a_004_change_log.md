# P1-A-004 本地/CI可复现测试说明变更记录

## 基本信息

- 任务编号：P1-A-004
- 任务名称：补齐后端与 Docker 可复现测试说明
- 执行分支：feature/phase1-a-backend-mvp-api
- 执行目录：saas-collab-system/

## 准入检查

- 当前分支已确认是 feature/phase1-a-backend-mvp-api。
- 当前分支已确认不是 feature/ar0-001-stage0-file-scope。
- 本次未修改 backend 业务代码。
- 本次未修改 frontend/、rpa-agent/、docs/04_rpa/。
- 本次未修改 docker-compose.yml。

## 关闭的 AR0-010 P2

本次针对 AR0-010-P2-004：

> 当前审核环境缺少 Python 与 Docker CLI，启动构建测试无法完全本机复现。

处理方式：

- 新增本地测试指南：docs/05_test/phase1_local_test_guide.md
- 新增 CI 检查清单：docs/06_release/phase1_ci_checklist.md
- 更新根 README 增加 Phase 1 可复现检查入口。
- 更新 backend/README.md 增加 Phase 1 测试复现说明入口。

## 文档覆盖内容

- Python 版本建议。
- pip 依赖安装。
- Django check 命令。
- pytest 命令。
- Docker compose config 命令。
- MySQL/Redis 最小启动命令。
- 前端 build 命令引用。
- RPA JSON 校验命令。
- 安全扫描命令。
- Windows PowerShell 与 bash 两套命令。
- 不使用真实 .env。
- 不接真实平台。

## 安全边界

- 文档明确禁止使用真实 `.env`。
- 文档明确禁止连接真实 BigSeller、Shopee、TikTok、微信服务号、小程序、银行或支付平台。
- 文档明确安全扫描可能命中占位示例，需确认不是真实凭据。
- 未修改依赖版本。
- 未修改 Docker Compose 运行行为。

## 验证记录

本任务为文档任务，未修改业务代码。

已执行：

```powershell
git diff --check
```

执行结果：

- git diff --check：通过。
