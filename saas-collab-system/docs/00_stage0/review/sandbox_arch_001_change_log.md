# SANDBOX-ARCH-001 变更记录

## 1. 目标

补齐独立 Sandbox 部署包、环境合同、测试验收清单和上线准入门禁，使业务功能在进入受控 Pilot 或申请生产发布前具有可复现的隔离调试与验证路径。

## 2. 新增部署文件

- `deploy/sandbox/README.md`
- `deploy/sandbox/application/env.sandbox.example`
- `deploy/sandbox/application/docker-compose.sandbox-app.yml`
- `deploy/sandbox/application/Dockerfile.frontend`
- `deploy/sandbox/application/nginx.conf`
- `deploy/sandbox/application/install-app.sh`
- `deploy/sandbox/application/verify-sandbox.sh`
- `deploy/sandbox/application/register-sandbox-environment.sh`
- `deploy/sandbox/application/verify-sandbox-e2e.sh`
- `deploy/sandbox/application/write-artifact-manifest.sh`
- `deploy/sandbox/database/env.sandbox.example`
- `deploy/sandbox/database/docker-compose.sandbox-db.yml`
- `deploy/sandbox/database/install-db.sh`
- `deploy/sandbox/network/env.network.example`
- `deploy/sandbox/network/apply-app-policy.sh`
- `deploy/sandbox/network/apply-db-policy.sh`
- `deploy/sandbox/network/verify-network-policy.sh`
- `deploy/sandbox/tests/test-install-guards.sh`
- `.github/workflows/sandbox-artifacts.yml`

## 3. 新增治理文件

- `docs/01_architecture/sandbox_environment_contract.md`
- `docs/05_test/sandbox_acceptance_checklist.md`
- `docs/06_release/sandbox_go_live_gate.md`
- `docs/00_stage0/review/sandbox_arch_001_change_log.md`

## 4. 核心控制

1. Sandbox 环境编码固定为 `sandbox`。
2. Sandbox 与 Pilot/Production 的网络、数据库、Redis、端口、TLS、账号和数据独立。
3. 安装脚本拒绝占位值、非固定摘要、非 prod、非 MySQL、调试模式、真实平台开关和高风险自动化开关。
4. 前端构建先执行 Mock 测试，再以 `VITE_USE_MOCK=false` 生成 Sandbox 联调制品。
5. 验证脚本检查 Compose、运行服务、Django deploy check、迁移一致性和受信任 HTTPS 健康响应。
6. CI 生成带 SBOM/provenance 的固定摘要和制品清单；目标主机只拉取摘要，不执行构建。
7. 唯一 Sandbox 环境资源进入数据库可信层，并通过 JWT/API E2E 验证。
8. 应用出站、客户端入口和数据库来源使用持久化 `DOCKER-USER` 策略控制。

## 5. 安全确认

- 未修改 `backend/`、`frontend/` 或 `rpa-agent/` 业务代码。
- 未修改既有 Pilot 部署配置。
- 未提交真实 `.env`、密码、Token、Cookie、Session、API Key、API Secret 或证书私钥。
- 未加入真实平台、银行或支付配置。
- 未启用真实 RPA、自动采购、自动上架、改价、清仓、生命周期变更或资金操作。
- 示例配置只使用 `change-me` 和 `example.internal` 占位值。

## 6. 验证状态

本变更完成部署合同和静态配置交付。2026-07-22 在架构工作区实际执行：

- 三个 Shell 脚本 `sh -n`：PASS。
- 应用 Docker Compose 使用示例环境展开：PASS。
- 数据库 Docker Compose 使用示例环境及回环测试绑定展开：PASS。
- 环境编码、真实平台禁用、高风险自动化禁用、production provider 禁用及前端关闭 Mock 构建规则扫描：PASS。
- Sandbox 新目录中的 `.env`、私钥、证书密钥和 SSH 私钥文件名扫描：PASS。

上述结果只证明部署包语法和静态合同有效，没有启动容器或连接数据库、外部平台。实际 Sandbox 主机部署、浏览器 E2E、性能、恢复和完整业务验收仍为“未执行”，在独立环境完成前不得标记 Sandbox 运行验收 PASS。

## 7. 下一步

1. 提交并审核 `SANDBOX-ARCH-001`。
2. PR 合并 `main` 后，由运维基于本部署包创建独立 Sandbox 主机和数据库。
3. 执行完整验收清单并生成固定 Git SHA/镜像摘要的 Sandbox 验收报告。
4. 仅在无 P0/P1 时申请进入 `controlled-pilot`。
