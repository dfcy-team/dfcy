# SANDBOX-ARCH-001-R2 独立复审报告

## 1. 复审对象

- 复审日期：2026-07-22
- 复审分支：`codex/sandbox-arch-001`
- 对比基线：`origin/main@c2a0f082e369dc5623e16b68f3913a9fa01316d6`
- 复审快照：当前暂存区；尚未形成固定 commit、PR 或远端 CI HEAD
- 复审依据：`sandbox_arch_001_r1_review.md`、`sandbox_arch_001_r1_p1_fix_change_log.md`
- 复审性质：只审核，不修复

复审范围包括 `.github/workflows/sandbox-artifacts.yml`、`deploy/sandbox/`、Sandbox 环境合同、验收清单、上线门禁和整改日志。只读核对现有 `deploy/pilot/`，用于确认同摘要晋级是否真正闭合。

## 2. 复审结论

**CONDITIONAL_PASS**

未发现 P0。Sandbox 部署端已取消目标主机构建，具备固定摘要、审批清单、OCI revision、迁移摘要、prod/MySQL/TLS 代理安全设置、可信环境资源和 `DOCKER-USER` 网络策略。Shell、Compose、仓库安全门禁、后端全量测试、前端测试和构建均通过。

但 3 项 P1 尚未完全关闭：现有 Pilot 安装仍使用本地 build 和可变标签，无法技术保证 Sandbox 验证摘要原样晋级；JWT/API 脚本没有断言非超级用户、精确 action permission 和 sandbox-only data_scope；网络策略尚无独立 Sandbox 主机上的未批准数据库来源、真实出站阻断和重启持久化实测证据。因此当前交付尚不能标记为 Sandbox 可部署 PASS。

## 3. 原 P1 关闭情况

| 原问题编号 | 是否关闭 | 复审证据 | 备注 |
|---|---|---|---|
| SANDBOX-ARCH-R1-P1-001 | 否，部分整改 | Sandbox Compose 已删除 build；`install-app.sh` 强制 GHCR `@sha256`、审批清单和 OCI revision；workflow 生成 SBOM/provenance/清单。但 `deploy/pilot/application/install-app.sh:62` 仍执行 build，Pilot Compose 仍使用 `saas-collab-*:pilot` 和 build | Sandbox 不再本机构建已关闭；同摘要晋级未闭合 |
| SANDBOX-ARCH-R1-P1-002 | 是 | `install-app.sh` 强制 prod、MySQL、Debug false、精确 Host/CORS、禁用 provider/真实平台/高风险动作；`verify-sandbox.sh` 核验 Secure Session/CSRF、SSL redirect 和代理头；负向门禁通过 | 实际 TLS 链和运行设置仍需部署验收，但实现缺口已关闭 |
| SANDBOX-ARCH-R1-P1-003 | 否，部分整改 | `register-sandbox-environment.sh` 登记并核验唯一 `sandbox`、`Sandbox/controlled`；运行脚本核验 ORM；E2E 覆盖 login/me/readiness。当前 `auth/me` 断言只验证 internal 和 tenant，未拒绝 superuser，未断言 `pilot.readiness.view` 及仅含 sandbox 的 permission-specific data_scope | 使用超级用户或 ALL scope 仍可能通过该 E2E，不能证明最小权限边界 |
| SANDBOX-ARCH-R1-P1-004 | 否，部分整改 | 应用/数据库专用 `DOCKER-USER` 链、默认 REJECT、持久化检查和公共 IP 出站探针已实现 | 未在独立 Sandbox 主机执行；缺少从未批准来源访问 MySQL 的自动负向证据及重启后复验 |

## 4. 不可变制品与晋级复审

已确认：

- `Sandbox immutable artifacts` 仅允许 `main` ref 执行发布 job。
- 后端和前端构建产物推送 GHCR，并生成 digest、SBOM、provenance 和 90 天制品清单。
- Sandbox Compose 不包含后端或前端 build，只消费环境文件中的固定摘要。
- 安装器校验审批清单权限、schema、环境、Git SHA、前后端摘要、OCI revision 和迁移摘要。
- 运行证据记录审批清单哈希和实际迁移哈希。

未关闭项：Pilot 部署包没有消费该清单或固定摘要，仍在目标主机重新构建后端和前端。当前治理文档虽然要求同摘要晋级，但技术路径可以绕过，原 P1 不能关闭。

## 5. prod、MySQL 与代理安全复审

P1 已关闭。安装和运行验证共同覆盖：

- `config.settings.prod`、`DJANGO_DEBUG=false` 和 `django.db.backends.mysql`。
- 独立 Sandbox 数据库名称、非 root 用户、私网数据库地址及密码长度/分离。
- 唯一 HTTPS CORS Origin、受限 Allowed Hosts、受信任证书链和域名、证书私钥配对。
- `SESSION_COOKIE_SECURE`、`CSRF_COOKIE_SECURE`、`SECURE_SSL_REDIRECT` 和 `SECURE_PROXY_SSL_HEADER`。
- Nginx 固定传递 HTTPS、Host 和端口代理头，`/admin/` 返回 404。
- 真实平台和高风险自动化开关必须保持关闭。

负向脚本确认可变镜像、dev settings、SQLite、真实平台、高风险自动化、Host/CORS 扩大和数据库公网绑定均被拒绝。

## 6. 可信环境身份与 JWT/API 复审

环境资源已进入可信数据库层，且异常名称或状态不会被脚本静默覆盖。readiness API 本身已有 permission-specific data_scope 校验及后端测试。

当前 E2E 证据脚本仍不充分：

1. 没有断言 `.data.is_superuser == false`。
2. 没有断言 `.data.permissions` 只包含或至少明确包含 `pilot.readiness.view`。
3. 没有从 `.data.data_scope` 定位授予该权限的 scope 并确认 `scope_type=custom`、`environment_ids=["sandbox"]`。
4. 错误环境允许 404；超级用户访问不存在环境同样可能得到 404，因此该结果不能单独证明 scope 拒绝。

应使用非超级、短期、最小权限账号，并增加一个已登记但不在 scope 内的受控环境作为 403 负向样本。

## 7. 网络控制复审

实现层已具备：

- 应用容器仅允许同 Sandbox 子网及指定数据库地址，其他容器出站默认 REJECT。
- 仅批准客户端 CIDR 可访问前端容器 80/443。
- 数据库容器仅允许指定应用主机访问 3306，其他来源 REJECT。
- 规则挂接 `DOCKER-USER`，并通过 `netfilter-persistent` 保存。
- 安装后检查链、规则和持久化文件；应用验证探测数据库可达及公共 IP 443 不可达。

当前未在 Linux Sandbox 主机实际执行 iptables、数据库未批准来源访问、真实外部域名/IP阻断及重启后持久化测试。该运行证据属于原 P1 的明确验收标准，不能以 Windows 静态检查替代。

## 8. 实际执行结果

| 检查项 | 结果 | 说明 |
|---|---|---|
| Shell 语法 | PASS | 10 个 Sandbox Shell 脚本 |
| 安装负向门禁 | PASS | `SANDBOX_INSTALL_GUARDS=PASS` |
| 应用 Compose | PASS | 配置展开成功；后端/前端无 build |
| 数据库 Compose | PASS | 使用临时私网占位地址展开成功 |
| workflow YAML | PASS | 本地解析通过 |
| 仓库 CI 安全门禁 | PASS | 无禁止文件或高置信凭据模式 |
| Django check | PASS | 0 issues |
| migration 一致性 | PASS | `No changes detected` |
| 后端全量 pytest | PASS | `399 passed` |
| 前端测试 | PASS | 11 files、`153 passed` |
| 前端生产构建 | PASS | Vite build 成功；仅第三方 PURE 注释警告 |
| 远端制品 workflow | 未执行 | 尚无固定 commit/PR HEAD，不能伪造 GHCR、SBOM/provenance 运行结果 |
| 实际 Sandbox 部署 | 未执行 | 当前没有经本任务确认的独立 Sandbox 主机 |
| TLS、JWT/API E2E | 未执行 | 需要独立 Sandbox 域名、CA 和短期最小权限账号 |
| iptables/来源拒绝/重启持久化 | 未执行 | Windows 本地环境不能替代 Linux 主机验证 |

## 9. 安全扫描结果

- 未发现真实 `.env`、账号、密码、Token、Cookie、Session、API Key、API Secret、TLS/SSH 私钥。
- 未发现真实 BigSeller、Shopee、TikTok/TK、银行或支付配置。
- 未发现真实供应商、订单、财务或银行数据。
- 未修改 `backend/`、`frontend/`、`rpa-agent/` 或 `docs/04_rpa/` 业务代码。
- 无关 DOCX、`docs/00_stage0/architecture/`、RPA 下发目录及既有 Pilot 运维文档未纳入本次审核暂存范围。

## 10. P0

无。

## 11. P1

1. **SANDBOX-ARCH-R2-P1-001：Pilot 同摘要晋级未技术闭合。** Pilot 安装必须消费 Sandbox 审批清单中的同一后端/前端摘要，删除目标主机构建和可变 `:pilot` 标签，并核验 Git SHA、OCI revision、迁移摘要与清单哈希。
2. **SANDBOX-ARCH-R2-P1-002：JWT/API E2E 未证明最小权限 sandbox-only data_scope。** 必须拒绝超级用户测试账号，断言 permission-specific scope，并对已登记但越出 scope 的环境验证 403。
3. **SANDBOX-ARCH-R2-P1-003：网络隔离缺少独立主机运行证据。** 必须实测公共出站阻断、批准数据库连接成功、未批准来源连接失败和主机重启后规则仍有效。

## 12. P2

1. 后端 `python:3.12-slim`、前端 `node:22-alpine` 和 Nginx 基础镜像仍按 tag 构建；最终制品摘要固定可防止晋级漂移，但建议后续同时固定基础镜像摘要以增强可复现性。
2. 镜像已生成 SBOM/provenance，但尚未增加独立签名与签名验证。
3. 前端构建存在第三方依赖 PURE 注释警告，不阻断本次架构整改。
4. 当前审核对象尚无固定 commit、PR 和远端 CI；HEAD 固定后必须重跑范围、安全和 workflow 检查。

## 13. 整改与复验建议

1. 将 Pilot Compose/安装器改为读取 Sandbox 审批清单和相同 GHCR `@sha256`，禁止 build，并增加摘要不一致负向测试。
2. 强化 `verify-sandbox-e2e.sh`：断言非超级用户、精确权限和 custom scope；建立第二个受控测试环境验证越 scope 返回 403。
3. 在独立 Sandbox 应用/数据库虚拟机执行安装和网络测试，保存 `iptables-save`、重启前后规则、连接探针和时间戳证据。
4. 完成定向整改后执行 `SANDBOX-ARCH-001-R3`；通过后再提交 Ready PR 和允许实际 Sandbox 部署。

## 14. 准入建议

- 是否允许继续整改：**允许**。
- 是否建议创建 Ready PR：**不建议**。
- 是否允许将当前交付标记为 Sandbox PASS：**不允许**。
- 是否允许实际 Sandbox 部署：**不允许；先关闭剩余 P1 并复审**。
- 是否允许进入 controlled-pilot/Production：**不允许**。
- 是否允许真实平台或高风险自动化：**不允许，必须另行专项安全评审**。
