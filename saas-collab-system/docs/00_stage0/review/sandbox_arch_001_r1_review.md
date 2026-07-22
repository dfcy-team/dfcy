# SANDBOX-ARCH-001-R1 独立前审报告

## 1. 审核对象

- 审核日期：2026-07-22
- 审核分支：`codex/sandbox-arch-001`
- 对比基线：`origin/main@c2a0f082e369dc5623e16b68f3913a9fa01316d6`
- 审核快照：当前暂存区；尚未形成独立审核 commit、PR 或远端 CI HEAD
- 审核性质：只审核，不修复

审核范围：

- `deploy/sandbox/`
- `docs/01_architecture/sandbox_environment_contract.md`
- `docs/05_test/sandbox_acceptance_checklist.md`
- `docs/06_release/sandbox_go_live_gate.md`
- `docs/00_stage0/review/sandbox_arch_001_change_log.md`

## 2. 审核结论

**CONDITIONAL_PASS**

未发现 P0。部署目录、环境合同、验收清单和发布门禁已建立，Sandbox 与 Pilot 的端口、网络、数据卷、数据库名称、TLS 路径和环境示例已分离；Shell 与 Docker Compose 静态检查通过，真实平台和高风险自动化在示例及安装脚本中保持关闭。

但当前存在 4 项 P1：部署仍在目标主机本地构建可变镜像；生产设置与 MySQL 边界没有被安装脚本完整强制；环境编码只存在于环境文件而未登记和复验数据库环境资源；外部网络与数据库来源限制仍主要依赖文档和未被应用消费的开关。关闭上述问题并完成 R2 前，不允许把本交付标记为 Sandbox 可部署 PASS。

## 3. 分支与修改范围

- 分支基于最新 `origin/main`。
- 15 个前审输入文件全部位于允许的 `deploy/sandbox/` 和文档目录。
- 未修改 `backend/`、`frontend/`、`rpa-agent/`、`docs/04_rpa/` 或既有 Pilot 部署包。
- 原有未跟踪 DOCX、`docs/00_stage0/architecture/` 和 `docs/04_rpa/协同开发下发/` 未进入暂存范围。
- `.env.sandbox` 在应用和数据库目录均被根 `.gitignore` 的 `.env.*` 规则忽略。

## 4. 部署包审核

已具备：

- 应用与数据库独立 Compose 文件。
- Redis、Django、Celery worker/beat、前端 Nginx 与 MySQL 8.4 基线。
- 独立网络 `saas-sandbox-network`、Redis 卷 `saas-sandbox-redis-data` 和 MySQL 卷 `saas-sandbox-mysql-data`。
- 后端仅绑定 `127.0.0.1:8100`；数据库示例使用独立 `3307` 端口并要求私网绑定。
- HTTP 到 HTTPS 重定向、TLS 证书链/域名/密钥配对检查、HSTS 和基础安全响应头。
- `/admin/` 在 Sandbox Nginx 入口返回 404。
- Shell 文件以 LF 和可执行位提交。

缺口：应用安装脚本执行 `docker compose build backend frontend`，Compose 使用 `saas-collab-backend:sandbox`、`saas-collab-frontend:sandbox` 等可变标签；这与环境合同要求的“CI 固定 SHA 构建、按同一不可变摘要晋级”不一致。

## 5. 环境与数据隔离审核

- 示例数据库固定为 `saas_collab_sandbox`，安装脚本要求数据库名称包含 `sandbox`。
- 数据库绑定地址仅接受回环或 RFC1918 私网地址。
- 环境合同禁止生产数据复制，并要求测试 tenant、来源标记、清理批次和脱敏。
- 应用示例固定 `SANDBOX_ENVIRONMENT_CODE=sandbox`。

但 `SANDBOX_ENVIRONMENT_CODE` 只被 Shell 比较，后端未消费该变量。部署包没有创建或验证 `PilotEnvironment(code="sandbox", status="controlled")`，也没有通过真实 API/JWT 验证环境 ID 与 data_scope。若数据库不存在该资源，Pilot/Readiness/UI-P8 相关接口无法按合同工作；若存在错误环境资源，当前验证脚本也不能识别。

## 6. 配置与权限边界审核

通过项：

- 示例设置 `DJANGO_SETTINGS_MODULE=config.settings.prod`、`DJANGO_DEBUG=false`、MySQL backend 和禁用的 production provider。
- 安装脚本拒绝 placeholder、Debug、启用真实平台和启用高风险自动化。
- 前端构建先在 Mock 下运行测试，再以 `VITE_USE_MOCK=false` 生成联调制品。
- 合同明确 tenant、permission-specific data_scope、internal/external/RPA/finance 和导出审计边界。

缺口：安装脚本没有强制 `DJANGO_SETTINGS_MODULE=config.settings.prod`、`DB_ENGINE=django.db.backends.mysql`、Secure Cookie/CSRF 及受信任代理配置。仅检查 `DJANGO_DEBUG=false` 不能阻止误用 dev 设置或 SQLite。`SANDBOX_ALLOW_REAL_PLATFORM` 与 `SANDBOX_ALLOW_HIGH_RISK_AUTOMATION` 当前不是应用运行时安全控制，只是部署脚本自检值。

## 7. 网络与真实平台边界审核

文档明确禁止 BigSeller、Shopee、TikTok/TK、银行、支付、真实 RPA、自动采购、自动上架/改价/清仓和资金操作。仓库未发现真实平台 URL、真实凭据或真实业务数据。

但部署包没有出站网络拒绝/允许列表或主机防火墙基线，也未验证数据库主机只接受指定 Sandbox 应用主机。只要容器或依赖代码发起请求，当前 Docker 网络仍可能访问外部网络。该缺口使“默认阻断真实外部系统”尚未成为可验证技术控制。

## 8. 测试与上线门禁审核

- 验收清单覆盖后端、迁移、前端、浏览器、API、tenant、data_scope、角色、状态机、RPA、性能、恢复、安全和审批。
- 发布门禁定义 `G0` 至 `G5`，明确 P0/P1 阻断、固定制品摘要、同摘要晋级、停止条件和职责分离。
- 明确 Sandbox/Pilot PASS 不自动允许 Production、真实平台或高风险自动化。

当前验证脚本只执行服务状态、Django deploy check、迁移一致性和 HTTPS health，并输出本地镜像 ID；没有生成包含 Git SHA、镜像摘要、迁移版本、执行时间和校验和的不可变证据清单，也没有核验后端环境资源、JWT、tenant/data_scope 或角色权限。这些完整测试可在实际 Sandbox 部署后执行，但制品和环境身份门禁必须先补齐。

## 9. 实际执行结果

| 检查项 | 结果 | 说明 |
|---|---|---|
| 分支与基线 | PASS | 本地分支基于 `origin/main@c2a0f082` |
| 文件范围 | PASS | 仅 Sandbox 部署包与允许文档 |
| Shell `sh -n` | PASS | 3 个脚本 |
| 应用 Compose config | PASS | 使用示例环境展开，不启动服务 |
| 数据库 Compose config | PASS | 使用示例环境及回环测试绑定展开 |
| `git diff --cached --check` | PASS | 无空白错误 |
| `.env.sandbox` ignore | PASS | 应用和数据库目录均命中 `.env.*` |
| 真实密钥特征扫描 | PASS | 未发现常见真实密钥或私钥块 |
| 实际 Sandbox 部署 | 未执行 | 尚无独立 Sandbox 主机和真实环境文件 |
| Django/pytest/npm/E2E | 未执行 | 本次为部署包前审，不伪造运行结果 |
| 恢复/回滚/性能 | 未执行 | 需在独立 Sandbox 执行 |
| 远端 CI | 未执行 | 尚未提交和创建 PR |

## 10. P0

无。

## 11. P1

| 编号 | 问题 | 证据 | R2 验收标准 |
|---|---|---|---|
| SANDBOX-ARCH-R1-P1-001 | 制品来源和不可变晋级未闭合 | Compose 使用可变 `:sandbox` 标签；`install-app.sh` 在目标主机执行 build；验证只输出本地 image ID | CI/受控制品仓库提供固定 Git SHA 和 `@sha256` 镜像；Sandbox 安装默认只拉取固定摘要且不重建；生成可核验制品清单；本地构建模式明确不得晋级 |
| SANDBOX-ARCH-R1-P1-002 | 生产设置与 MySQL 运行边界未被安装脚本完整强制 | 只校验 Debug/provider/业务开关，未强制 prod settings、MySQL、Secure Cookie/CSRF 与代理安全配置 | 安装和验证脚本拒绝非 prod、非 MySQL、SQLite、非安全 Cookie/CSRF 或错误代理配置；提供正反向脚本测试 |
| SANDBOX-ARCH-R1-P1-003 | Sandbox 环境身份没有进入可信数据层和 API 验证 | 环境编码只存在 `.env.sandbox`；无环境资源创建/验证；health 不返回环境身份 | 受控创建或核验唯一 `sandbox` 环境资源；校验状态和 tenant/环境 scope；通过 JWT/API 验证返回环境编码且错误编码被拒绝；记录清理规则 |
| SANDBOX-ARCH-R1-P1-004 | 真实平台和数据库网络隔离仍停留在文档/无消费开关 | 无容器出站控制、主机防火墙规则或数据库来源允许列表验证；两个安全开关未被应用消费 | 提供可审计的 Sandbox 主机防火墙/出站允许列表方案；数据库仅允许指定应用主机；验证真实平台域名/IP不可达；安全开关由运行时或网络控制实际执行并有回归测试 |

## 12. P2

1. 安装脚本尚未校验 Secret/数据库密码最小长度、相互不同和轮换元数据，可在 R2 同步增强。
2. SBOM、依赖漏洞报告和镜像签名目前仅在门禁文档中要求，尚无自动生成脚本或 CI 证据。
3. 浏览器 E2E、性能、恢复、回滚和完整业务验收需待独立 Sandbox 主机部署后执行，不在本次静态前审中伪造。
4. 当前审核对象尚未形成固定 commit/PR HEAD；提交后必须重新核验文件范围并取得远端 CI。

## 13. 整改建议

1. 将部署模式拆分为 `local-build` 与 `immutable-artifact`；只有后者可用于正式 Sandbox 验收和晋级。
2. 增加环境前置校验脚本，强制 prod/MySQL、安全 Cookie/代理配置及唯一 Sandbox 环境资源。
3. 增加 `sandbox-artifact-manifest`，记录 Git SHA、镜像 digest、迁移、配置摘要和测试证据哈希。
4. 提供应用/数据库主机网络策略和验证命令，默认拒绝非批准出站与非应用主机数据库访问。
5. 整改后执行 `SANDBOX-ARCH-001-R2`，再决定是否允许提交 Ready PR 和实际部署。

## 14. 准入建议

- 是否允许继续整改：**允许**。
- 是否允许将当前结果标记为 Sandbox 部署 PASS：**不允许**。
- 是否建议直接创建 Ready PR：**不建议；应先关闭 P1 并完成 R2**。
- 是否允许实际 Sandbox 部署：**当前不允许**。
- 是否允许进入 controlled-pilot 或 Production：**不允许**。
- 是否允许真实平台或高风险自动化：**不允许，必须另行专项安全评审**。
