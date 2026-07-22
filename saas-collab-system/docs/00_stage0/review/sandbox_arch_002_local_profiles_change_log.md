# SANDBOX-ARCH-002 模块化 Local Sandbox 变更日志

## 1. 实施目标

基于最新 `main` 落地“开发人员本地 Sandbox + GitHub CI 不可变制品 + 生产发布门禁”中的本地开发部分，为模块分工提供可重复、可隔离、只使用合成数据的开发和验证环境。

## 2. 分支与基线

- 实施分支：`codex/local-sandbox-profiles`
- 基线提交：`5e06191cc79ea341e00c0a51631178e94507ae60`
- 实施方式：在隔离 worktree 中完成，未修改原工作区的未提交文件。

## 3. Local Sandbox Profiles

- `core`：认证、tenant、权限和审计基础。
- `sales-inventory-finance-reconciliation`：销售库存财务对账。
- `creator-management`：达人管理只读 Mock 合同。
- `procurement`：采购、供应商任务、出货和绩效。
- `integration`：全部模块的本地集成验证。
- `release-candidate`：仅使用 CI 批准的 Git SHA 和 `@sha256` 镜像，不允许本地构建。

## 4. 主要变更

- 新增 Local Sandbox Compose、开发镜像、环境变量示例和 Windows/Linux 一键脚本。
- 新增 `seed_local_sandbox`，幂等生成两个 tenant、六个非超级用户、角色权限和模块合成数据。
- 新增四组合成 JSON fixtures、结构校验器和达人管理只读 Mock Server。
- 新增 Release Candidate 制品清单与镜像摘要校验器。
- 新增 Local Sandbox 种子命令测试和 MySQL 最小权限测试库准备步骤。
- Celery Beat 状态文件固定写入容器 `/tmp`，并忽略历史本地运行缓存。

## 5. 一键命令

Windows：

```powershell
cd deploy/dev-sandbox
.\sandbox.ps1 init
.\sandbox.ps1 verify core
.\sandbox.ps1 verify integration
```

Linux/macOS：

```sh
cd deploy/dev-sandbox
./sandbox.sh init
./sandbox.sh verify core
./sandbox.sh verify integration
```

## 6. 数据与权限边界

- 数据仅使用 `LOCAL-*`、`demo`、`synthetic` 和 `example.com` 值。
- 普通 internal 用户不具备 `finance.*`；财务权限由独立角色授予。
- 提供第二 tenant 用于隔离和越权测试。
- 所有端口默认只绑定 `127.0.0.1`。
- 达人管理 Mock 只允许 GET，写操作返回 405。
- 测试数据库授权仅限 `test_saas_collab_local_*`，应用用户不获得全局数据库权限。

## 7. 安全确认

- 未提交 `.env.local` 或任何真实 `.env`。
- 未提交真实账号、密码、Token、Cookie、Session、API Key 或 API Secret。
- 未连接 BigSeller、Shopee、TikTok/TK、银行或支付平台。
- 未启用自动采购、改价、清仓、停售、归档、付款、转账或提现。
- Release Candidate Compose 不包含 `build:`，占位 SHA、占位 digest 或清单不一致时拒绝运行。

## 8. 待独立审核

- 核验各 profile 的模块边界、tenant 和财务权限隔离。
- 核验合成数据无真实业务信息且种子命令不可用于非本地环境。
- 核验一键脚本的删除保护和 Release Candidate 同摘要晋级门禁。
- Linux/macOS Shell 入口已通过 Alpine 容器内 `sh -n`；完整一键流程仍建议由 Linux/macOS 开发者或 CI 复跑。
