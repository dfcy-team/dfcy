# 模块化 Local Sandbox

本目录实现 SANDBOX-ARCH-002 的本地模块开发环境、合成数据和一键验证。它只面向开发人员电脑，不是 Production 部署方案。

## 1. 环境要求

- Windows: Docker Desktop + PowerShell 5.1 或 PowerShell 7。
- Linux/macOS: Docker Engine + Docker Compose v2 + POSIX shell + OpenSSL + curl。
- Docker 需能访问 Docker Hub，或已预先导入 `python:3.12-slim`、`python:3.12-alpine`、`node:22-alpine`、`mysql:8.4` 和 `redis:7-alpine`。
- 所有端口默认只绑定 `127.0.0.1`。

## 2. Profiles

| Profile | 用途 | 数据/外部能力 |
|---|---|---|
| `core` | 认证、tenant、权限、审计底座 | 两个合成 tenant 和最小角色 |
| `sales-inventory-finance-reconciliation` | 销售库存财务对账 | 合成商品、库存快照和对账建议 |
| `creator-management` | 达人管理合同开发 | 只读 Mock，不连接任何真实达人平台 |
| `procurement` | 供应链采购 | 合成采购单、供应商任务、出货和绩效 |
| `integration` | 全模块本地联调 | 上述数据的合集，高风险动作仍禁用 |
| `release-candidate` | 不可变制品本地候选验证 | 只接受 CI 批准的 `@sha256` 镜像，不本地构建 |

## 3. Windows 一键命令

```powershell
cd deploy/dev-sandbox

# 首次初始化：生成本地密码，不显示密码值
.\sandbox.ps1 init

# 启动单个模块
.\sandbox.ps1 start sales-inventory-finance-reconciliation

# 一键验证：启动、迁移、合成数据、模块测试、前端测试和构建
.\sandbox.ps1 verify sales-inventory-finance-reconciliation

.\sandbox.ps1 status sales-inventory-finance-reconciliation
.\sandbox.ps1 stop sales-inventory-finance-reconciliation

# 会删除本地 Sandbox volumes，必须显式确认
.\sandbox.ps1 reset integration -ConfirmReset
```

## 4. Linux/macOS 一键命令

```sh
cd deploy/dev-sandbox
chmod +x sandbox.sh

./sandbox.sh init
./sandbox.sh start procurement
./sandbox.sh verify procurement
./sandbox.sh status procurement
./sandbox.sh stop procurement

# 会删除本地 Sandbox volumes
./sandbox.sh reset integration --confirm-reset
```

## 5. 本地地址与账号

- 前端: `http://127.0.0.1:5173`
- 后端: `http://127.0.0.1:8000`
- MySQL: `127.0.0.1:3307`
- 达人管理 Mock: `http://127.0.0.1:8091`（仅相关 profile）

合成账号名以 `local_` 开头，包括 internal、finance、external、RPA 和另一 tenant 的查看者。密码在首次 `init` 时随机生成到被 Git 忽略的 `.env.local`；脚本不打印该值。

## 6. 合成数据边界

- `seed_local_sandbox` 需同时满足 `--confirm-local`、`DEBUG=true`、本地数据库名/主机约束和两个安全开关为 `false`。
- 生成两个 tenant，用于隔离和越权测试。
- 财务权限只赋予专用 finance 账号，普通 internal 账号不获得 `finance.*`。
- 数据只包含 `LOCAL-*`、`demo`、`synthetic` 和 `example.com` 值，不得导入生产数据。
- 达人 Mock 只允许 GET，任何写入返回 405。

## 7. Release Candidate 同摘要校验

1. 从 CI 下载制品清单，以 `sandbox-artifact-manifest.example.json` 为字段参考。
2. 在 `.env.local` 中填写受保护 main 的 Git SHA、四个固定镜像 digest 和制品清单路径。
3. 执行合同校验：

```powershell
.\sandbox.ps1 verify-rc
.\sandbox.ps1 start-rc
```

`docker-compose.rc.yml` 不包含 `build:`，任何 tag-only 镜像、占位 digest、Git SHA 不匹配或清单不匹配都必须失败。

## 8. 安全限制

- Local Sandbox 不能连接真实 BigSeller、Shopee、TikTok/TK、银行或支付平台。
- 不允许自动采购、改价、清仓、停售、归档、付款、转账或提现。
- `release-candidate` 验证通过不代表允许生产发布，仍需独立审核、备份、迁移预检和回滚门禁。
