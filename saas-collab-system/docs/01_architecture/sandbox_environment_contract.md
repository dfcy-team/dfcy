# SANDBOX-ARCH-001 沙箱环境合同

## 1. 目标

Sandbox 是开发验证与受控 Pilot 之间的独立环境，用于完成真实前后端联调、权限和 tenant 隔离、浏览器 E2E、故障注入、备份恢复及发布回滚验证。Sandbox 不承载生产业务，不连接真实平台，不执行高风险自动化。

## 2. 环境链路

```text
local/dev -> CI -> sandbox -> controlled-pilot -> production
```

- `local/dev`：单元测试、Mock 和组件开发。
- `CI`：构建、静态检查、测试、安全扫描和制品生成。
- `sandbox`：独立基础设施上的集成与回归验证。
- `controlled-pilot`：审批后的内网小范围业务试点。
- `production`：必须经过独立生产发布评审；当前不在授权范围内。

禁止跳过 Sandbox 直接从开发分支部署 Pilot/Production。Sandbox PASS 只允许申请下一门禁，不自动允许真实平台或生产发布。

## 3. 标识与隔离

| 项目 | Sandbox 合同 |
|---|---|
| 环境编码 | 固定为 `sandbox` |
| Git 基线 | 最新受保护 `main` 或审批后的 release candidate |
| 应用主机 | 与 Pilot/Production 独立 |
| 数据库 | 独立 MySQL 8.4 数据库和最小权限账号 |
| Redis | 独立实例和数据卷 |
| Docker 网络 | `saas-sandbox-network` |
| TLS | 独立证书、私钥和受信任 CA；不得复用生产私钥 |
| DNS | 独立 Sandbox 域名 |
| 端口 | 不与 Pilot/Production 共用 |
| 日志与备份 | 独立保留和访问控制 |

MySQL、Redis 和后端内部端口不得暴露公网。应用容器运行时只允许访问同一 Sandbox 网络和指定数据库地址；客户端只允许从批准 CIDR 访问 Nginx；数据库只允许指定 Sandbox 应用主机访问。规则写入 Docker `DOCKER-USER` 专用链并通过 `netfilter-persistent` 持久化。Nginx 是唯一用户入口，HTTP 仅重定向 HTTPS，`/admin/` 不作为业务入口并在 Sandbox 代理层拒绝。

## 4. 数据合同

1. 仅允许合成、脱敏或审批后的测试数据。
2. 禁止复制未经脱敏的生产数据库、订单、供应商、银行、财务、客户或平台凭据。
3. 每条测试数据必须具有测试 tenant 和来源标记，可按批次清理。
4. tenant、supplier、finance 和 data_scope 场景必须使用不同测试主体，不得以管理员账号代替越权测试。
5. 文件、截图、日志和导出不得包含 Token、Cookie、Session、API Key、API Secret、密码或完整银行账号。
6. 测试结束后按保留周期销毁临时账号、Token、导出文件和测试数据。

## 5. 配置与凭据

- 真实 `.env.sandbox` 只存在于受控主机，权限为 `0600`，不得进入 Git、日志或截图。
- Sandbox 账号、数据库密码、JWT Secret、TLS 私钥必须独立生成并按最小权限托管。
- `INTEGRATION_ENCRYPTION_PROVIDER=unconfigured-production`。
- `SANDBOX_ALLOW_REAL_PLATFORM=false`。
- `SANDBOX_ALLOW_HIGH_RISK_AUTOMATION=false`。
- 前端构建固定 `VITE_USE_MOCK=false`，用于验证真实 Sandbox 后端；Mock 测试在构建阶段单独执行。
- 凭据轮换、吊销和应急访问必须可审计。
- 安装脚本强制 `config.settings.prod`、MySQL、Secure Session/CSRF、受信任 HTTPS 代理和精确 Host/CORS；任一不满足必须停止。

## 6. 外部连接边界

默认阻断 BigSeller、Shopee、TikTok/TK、银行、支付、邮件、短信、飞书、微信及其他真实外部系统。若未来使用第三方官方 Sandbox，必须另行完成专项安全评审，并为其配置独立 Sandbox 凭据、出站允许列表、限流、脱敏日志和停止开关。

未经专项批准：

- 不允许真实商品上架、改价、上下架或清仓。
- 不允许自动创建正式采购订单或通知真实供应商。
- 不允许真实 RPA 浏览器自动化。
- 不允许付款、转账、提现或自动确认财务对账。
- API/RPA/分析/预警只可产生建议、Mock 结果或待人工确认记录。

## 7. 权限与审计

1. 后端是权限可信边界；前端菜单和按钮隐藏不构成授权。
2. 所有核心查询和写入必须校验 tenant、permission-specific data_scope 和 exact action permission。
3. internal、external supplier、RPA Agent、finance 权限域保持隔离。
4. 401、403、404、409、422 及高风险 action 必须可审计，且不得泄露跨 tenant 资源存在性。
5. 财务查询和导出需要独立财务权限、脱敏和导出审计。
6. 审计记录和验收证据不得由普通业务用户更新或删除。

## 8. 制品合同

1. `.github/workflows/sandbox-artifacts.yml` 只允许从 `main` 的固定 Git SHA 构建并推送后端和前端制品。
2. Sandbox 验收记录必须包含 Git SHA、后端镜像 ID/摘要、前端镜像 ID/摘要和数据库迁移版本。
3. 晋级 Pilot/Production 必须使用 Sandbox 已验证的同一镜像摘要，禁止重新构建。
4. 制品必须完成依赖锁定、安全扫描和 SBOM/依赖清单归档。
5. 任何代码、依赖、配置模板或迁移变化都会使原 Sandbox PASS 失效并要求重跑。

Sandbox 应用安装只接受 `ghcr.io/dfcy-team/dfcy/*@sha256:<digest>`，并核对 OCI `org.opencontainers.image.revision` 与审批 Git SHA；目标主机不得重新构建。受控制品清单以 `0600` 保存，安装脚本逐项比对环境、Git SHA 和前后端摘要，运行后比对迁移摘要并记录清单哈希。Redis 和 MySQL 同样使用审批后的官方固定摘要。CI 同时生成 SBOM、provenance 和可下载制品清单。

## 9. 可信环境身份

- 数据库中必须且只能存在一个 `PilotEnvironment(code="sandbox")`，名称为 `Sandbox`、状态为 `controlled`。
- 注册脚本只允许首次创建或核验完全一致的资源；发现同 code 异常名称/状态时停止，不自动覆盖。
- 运行验证必须检查 Django 实际设置、MySQL backend 和环境资源。
- JWT/API E2E 使用短期、非超级 internal 用户，验证 login、`auth/me`、`environment_id=sandbox` readiness，以及已登记但越出 scope 的环境严格返回 403。
- E2E 用户的权限集合必须精确为 `pilot.readiness.view`，data_scope 必须仅有一个 `scope_type=custom` 且 `environment_ids=["sandbox"]`；测试后立即删除账号和密码文件。

## 9.1 网络运行证据合同

1. 应用与数据库网络策略应用时必须记录策略哈希、链哈希、应用时间和应用时 boot ID。
2. 主机重启后的验收必须证明当前 boot ID 与应用时不同，同时策略哈希和链哈希保持一致。
3. 应用容器必须实际证明 Sandbox 数据库可达且公共 `1.1.1.1:443` 出站被拒绝。
4. 数据库来源拒绝必须从独立于批准应用主机的第三台主机发起；探针发现自身源地址等于批准应用地址时必须停止；数据库主机的对应 `REJECT` 计数器必须在探针窗口内增长。
5. 应用、数据库重启后证据和未授权来源拒绝证据均为 `0400` JSON，记录时间、环境、主机角色或探针类型及脱敏目标，不记录凭据。
6. 上述运行证据未在独立 Linux Sandbox 主机生成时，网络隔离项只能记为“实现完成、实测未完成”，不得关闭 P1。

## 10. 可观测性与恢复

- 健康检查覆盖 Nginx、Django、Celery、Redis 和 MySQL。
- 日志使用 request_id、tenant_id 和脱敏 actor 标识关联，不记录认证材料或完整请求体。
- 告警至少覆盖服务不可用、迁移失败、任务积压、登录异常、权限拒绝激增、磁盘和证书到期。
- 上线申请前必须完成数据库备份校验、恢复演练和应用回滚演练。
- 恢复或回滚只由受控运维流程执行，业务 API、前端或 RPA 不得执行 Shell、Docker、SSH、SQL 或恢复命令。

## 11. 准入与退出

进入 Sandbox 前必须满足：代码已合并受保护 `main`、CI 成功、无未关闭 P0/P1、测试数据和账号获批、部署配置完成安全复核。

Sandbox 退出并申请 Pilot 前必须满足 `sandbox_acceptance_checklist.md` 全部阻断项，通过发布负责人、安全审核人和业务验收人签字，形成不可变测试证据。失败项必须整改后重新执行，禁止口头豁免。
