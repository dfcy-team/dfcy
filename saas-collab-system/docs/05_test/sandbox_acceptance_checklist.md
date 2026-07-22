# SANDBOX-ARCH-001 沙箱验收清单

> 状态说明：本清单仅适用于独立基础设施 Sandbox 严格模式。当前模块化 Local Sandbox 使用 `sandbox_arch_002_lean_acceptance_checklist.md`；Production 发布仍必须遵守 SANDBOX-ARCH-002 的不可变制品、备份、回滚和安全底线。

## 1. 基线与部署

- [ ] 部署来源为受保护 `main` 或审批后的 release candidate。
- [ ] 记录 Git SHA、PR、后端镜像 ID/摘要、前端镜像 ID/摘要和迁移版本。
- [ ] 制品由最新 `main` 的 `Sandbox immutable artifacts` 工作流生成，后端全量测试成功。
- [ ] 后端/前端使用 GHCR `@sha256`，OCI revision 与 Git SHA 一致；Redis/MySQL 使用审批的官方摘要。
- [ ] CI 制品清单、SBOM 和 provenance 已归档，Sandbox 主机未重新构建镜像。
- [ ] 受控制品清单权限为 `0400`/`0600`，环境、Git SHA、前后端摘要和迁移摘要与运行实例逐项一致。
- [ ] `SANDBOX_ENVIRONMENT_CODE=sandbox`。
- [ ] 应用、数据库、Redis、网络、卷、端口、DNS 和 TLS 均与 Pilot/Production 独立。
- [ ] `.env.sandbox` 权限为 `0600`，且不在 Git 中。
- [ ] `docker compose config --quiet` 通过。
- [ ] `install-db.sh` 与 `install-app.sh` 成功。
- [ ] `verify-sandbox.sh` 输出 `SANDBOX_VERIFY=PASS`。
- [ ] 制品清单包含环境、时间、Git SHA、后端/前端/Redis 摘要和 migration SHA256。

## 2. 安全开关

- [ ] `DJANGO_DEBUG=false`。
- [ ] `INTEGRATION_ENCRYPTION_PROVIDER=unconfigured-production`。
- [ ] `SANDBOX_ALLOW_REAL_PLATFORM=false`。
- [ ] `SANDBOX_ALLOW_HIGH_RISK_AUTOMATION=false`。
- [ ] 未配置真实 BigSeller、Shopee、TikTok/TK、银行或支付凭据。
- [ ] 未发现真实 Token、Cookie、Session、API Key、API Secret、密码、证书私钥进入仓库或日志。
- [ ] MySQL、Redis 和后端内部端口未暴露公网。
- [ ] HTTP 只重定向 HTTPS，浏览器信任证书链，HSTS 生效。
- [ ] `/admin/` 不作为业务入口。
- [ ] Django 运行时确认 prod、MySQL、Secure Session/CSRF、SSL redirect 和可信代理头。
- [ ] 应用 `DOCKER-USER` 策略只允许内部网络、批准客户端 CIDR 和指定数据库，其他容器出站拒绝。
- [ ] 数据库 `DOCKER-USER` 策略只允许指定应用主机，规则已持久化且重启复验通过。
- [ ] 应用容器网络探针生成 `app-runtime-network-evidence.json`，确认数据库可达且公共 `1.1.1.1:443` 出站被拒绝。
- [ ] 第三台未批准主机生成 `unapproved-db-source-evidence.json`，源地址不同于批准应用地址且访问 MySQL 失败；数据库主机同时生成 `db-unapproved-source-reject-evidence.json` 并证明对应 REJECT 计数器增长。
- [ ] 应用和数据库主机均已重启，`app-post-reboot-evidence.json` 与 `db-post-reboot-evidence.json` 证明 boot ID 已变化且策略/链哈希未漂移。

## 3. 后端与数据库

- [ ] `python manage.py check --deploy` 通过。
- [ ] `python manage.py makemigrations --check --dry-run` 无差异。
- [ ] 全量 migration 在空 Sandbox 数据库执行成功。
- [ ] Django 全量 pytest 通过并记录数量。
- [ ] 阶段专项 pytest 通过并记录数量。
- [ ] MySQL 字符集、时区、约束和索引符合合同。
- [ ] 应用数据库账号无建库、用户管理或跨库权限。
- [ ] 数据库备份、校验和恢复演练通过。
- [ ] 回滚到上一应用制品后数据库仍保持可恢复状态。
- [ ] 数据库中唯一 `sandbox` 环境资源为 `Sandbox/controlled`，异常同名资源不会被静默覆盖。

## 4. 前端与浏览器

- [ ] `npm ci`、`npm test` 和 `npm run build` 通过。
- [ ] Sandbox 构建使用 `VITE_USE_MOCK=false`。
- [ ] 未实现能力标记为 `pending` 或 `mock`，不得误标 `connected`。
- [ ] 登录、刷新、退出、过期会话和多标签会话通过。
- [ ] 菜单、路由、按钮、字段和数据范围按角色正确显示。
- [ ] loading、empty、offline、401、403、404、409、422 页面状态通过。
- [ ] 桌面和目标最小分辨率无重叠、截断或不可见操作。
- [ ] 浏览器 E2E 记录登录、核心流程、权限拒绝和退出证据。
- [ ] 短期 JWT 用户为非超级 internal，权限集合精确为 `pilot.readiness.view`，仅有 sandbox custom scope；已登记的越 scope 环境严格返回 403，测试账号和密码文件已删除。

## 5. API 合同

- [ ] 所有成功响应符合 `success/code/message/data`。
- [ ] 列表响应包含 `count/next/previous/results`。
- [ ] 400、401、403、404、409、422 状态与错误码符合冻结合同。
- [ ] 非统一 HTTP 200 不被前端包装为成功。
- [ ] 幂等键、版本冲突、状态冲突和字段校验通过。
- [ ] API 映射中的 connected 状态具有本次实测时间和证据。
- [ ] 不存在前端调用未实现路径或同义重复接口。

## 6. tenant、data_scope 与角色

- [ ] 核心模型和查询按 tenant 隔离。
- [ ] 缺失、未知、非法、空、重复或越限 data_scope 被拒绝。
- [ ] 跨 tenant 列表不可见、详情返回 404、非法引用被拒绝。
- [ ] internal 用户不能访问 external supplier 身份流程。
- [ ] 供应商只能访问自己的任务、出货和绩效。
- [ ] RPA Agent 只能访问 `/api/rpa/*`，不能访问 internal、finance 或 admin。
- [ ] 普通 internal 用户不能访问财务敏感接口。
- [ ] action permission 与 view permission 分离，不能用查看权限执行审批、导出或状态迁移。

## 7. 业务流程与状态机

- [ ] 商品、采购、供应商、审批、异常和报表核心流程通过。
- [ ] 通用 PATCH、模型 `save()`、bulk 操作不能绕过状态机。
- [ ] 审批职责分离、过期、取消、重复提交和并发冲突通过。
- [ ] 补货和生命周期仅产生建议，不生成正式采购或改变商品状态。
- [ ] 预警不触发真实 RPA 或平台动作。
- [ ] 财务分析只读，不执行付款、转账、提现或自动确认。
- [ ] 审计记录不可被普通流程更新或删除。

## 8. RPA 与外部系统

- [ ] RPA 仅使用 Mock/dry-run，`production_disabled` 拒绝执行。
- [ ] claim、heartbeat、logs、screenshots、complete、fail 权限边界通过。
- [ ] 最大重试、心跳超时、同账号串行、页面变化和人工接管通过。
- [ ] 前端管理页面不模拟 Agent Token，不调用 Agent 执行接口。
- [ ] 没有真实浏览器自动化、真实选择器或真实平台 URL。
- [ ] 所有第三方网络调用被禁用或由允许列表明确阻断。

## 9. 性能、容量与韧性

- [ ] 核心列表、详情、写入和聚合接口达到批准的响应阈值。
- [ ] 并发登录、幂等写入、任务锁和数据库连接池验证通过。
- [ ] Celery 重试、积压、worker 重启和 beat 恢复通过。
- [ ] Redis 重启、应用重启和数据库短时不可用恢复通过。
- [ ] 磁盘、CPU、内存、数据库容量和证书到期告警通过。
- [ ] 性能测试只使用合成数据，不形成真实平台流量。

## 10. CI、安全与证据

- [ ] 远端必需 CI 全部成功，审核 HEAD 未变化。
- [ ] Docker Compose、RPA JSON、API 路径和禁止文件检查通过。
- [ ] 依赖漏洞、密钥、真实平台连接和敏感数据扫描通过。
- [ ] `dist`、`node_modules`、缓存、日志、截图和数据库文件未提交。
- [ ] 测试证据包含执行时间、操作者、环境编码、Git SHA、制品摘要和结果。
- [ ] `sandbox-verification-evidence.json` 为 PASS，且其 Git SHA、前后端摘要、迁移摘要和制品清单哈希与 Pilot 晋级输入完全一致。
- [ ] Pilot Compose 不含 `build:`，安装器不接受可变标签，实际拉取的 OCI revision 与 Sandbox 验证 SHA 一致。
- [ ] 所有失败项具有问题编号、责任人、修复提交和复验结果。

## 11. 放行结论

- [ ] P0：无。
- [ ] P1：无。
- [ ] P2 已登记责任人和处理期限，且明确不阻断原因。
- [ ] 架构审核人批准。
- [ ] 安全审核人批准。
- [ ] 业务验收人批准。
- [ ] 发布负责人批准。

只有以上阻断项全部通过，才可申请进入 `controlled-pilot`。本清单通过不允许直接进入 Production，也不允许真实平台接入或高风险自动化。
