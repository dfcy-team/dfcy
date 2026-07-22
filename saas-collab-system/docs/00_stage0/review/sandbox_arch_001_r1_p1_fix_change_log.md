# SANDBOX-ARCH-001-R1 P1 整改日志

## 1. 整改对象

整改依据：`sandbox_arch_001_r1_review.md`。本次只修改 Sandbox 部署、CI 和治理文档，不修改业务代码，不连接真实平台。

## 2. P1 关闭情况

| 编号 | 原问题 | 整改内容 | 证据 | 状态 |
|---|---|---|---|---|
| SANDBOX-ARCH-R1-P1-001 | 可变镜像与目标主机构建 | 新增 main-only 制品工作流；后端全量测试后推送 GHCR；生成 SBOM、provenance 和清单；Compose 只接受固定摘要；安装逐项核对只读审批清单、OCI revision/Git SHA，运行后比对迁移摘要并记录清单哈希 | `.github/workflows/sandbox-artifacts.yml`、Compose、`install-app.sh`、`write-artifact-manifest.sh` | 待 R2 确认 |
| SANDBOX-ARCH-R1-P1-002 | prod/MySQL/安全设置未完整强制 | 安装前强制 prod、MySQL、Debug false、provider disabled、精确 Host/CORS、密码边界；运行时核验 Secure Session/CSRF、SSL redirect 和代理头；负向门禁测试覆盖错误配置 | `install-app.sh`、`verify-sandbox.sh`、`tests/test-install-guards.sh` | 待 R2 确认 |
| SANDBOX-ARCH-R1-P1-003 | 环境身份未进入可信层和 API | 注册/核验唯一 `sandbox`、`Sandbox/controlled` 资源；运行时 ORM 校验；短期内部账号 JWT E2E 验证 login/me/readiness 和错误环境拒绝 | `register-sandbox-environment.sh`、`verify-sandbox.sh`、`verify-sandbox-e2e.sh` | 待 R2 确认 |
| SANDBOX-ARCH-R1-P1-004 | 外部网络与数据库来源限制不闭合 | 新增应用/数据库 `DOCKER-USER` 专用链、默认拒绝容器出站、客户端 CIDR 和数据库应用主机允许规则；使用 netfilter-persistent；安装前强制应用策略；运行时探测数据库可达和公共出站被阻断 | `network/`、应用/数据库安装与验证脚本、验收清单 | 待 R2 确认 |

## 3. 安全确认

- 未修改 `backend/`、`frontend/`、`rpa-agent/` 或 `docs/04_rpa/`。
- 未提交真实 `.env`、密码、Token、Cookie、Session、API Key、API Secret、TLS/SSH 私钥。
- 未加入真实 BigSeller、Shopee、TikTok/TK、银行或支付配置。
- 未启用真实 RPA、自动采购、上架、改价、清仓、生命周期变化或资金操作。
- 网络策略必须显式设置 `SANDBOX_NETWORK_APPLY=YES`，否则安装停止。

## 4. 本地执行结果

- Shell 语法：通过，覆盖 10 个安装、登记、验证、网络和测试脚本。
- 安装负向门禁：通过，输出 `SANDBOX_INSTALL_GUARDS=PASS`。
- 应用 Compose：通过，确认后端和前端不存在目标主机 `build` 配置。
- 数据库 Compose：使用临时私网占位值通过。
- workflow YAML：解析通过。
- 仓库安全门禁：通过，未发现禁止文件或高置信凭据模式。
- Django check：通过，无系统检查问题。
- migration 一致性：通过，`No changes detected`。
- auth 与 pilot/readiness 定向 pytest：`62 passed`。
- `git diff --check`：通过。

## 5. 待 R2 与运行环境验证

1. 实际 GHCR 工作流、摘要拉取、OCI revision、SBOM/provenance 和审批清单需在提交后由远端工作流验证。
2. 防火墙规则、数据库正向连通、公共出站阻断、未批准数据库来源拒绝和主机重启持久化需在独立 Sandbox 主机执行。
3. 环境资源登记、Django 运行设置、JWT login/me/readiness 和错误环境拒绝需在独立 Sandbox 主机执行。
4. 完成独立 `SANDBOX-ARCH-001-R2` 后再决定是否允许 Ready PR 和实际部署。
