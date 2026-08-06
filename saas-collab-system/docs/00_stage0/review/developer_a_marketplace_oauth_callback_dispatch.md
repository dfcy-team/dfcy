# 开发A节点分发：PR-A2 Marketplace OAuth / Callback

## 1. 任务信息

- 任务：`A-PR2-MARKETPLACE-OAUTH-CALLBACK`。
- 建议实现分支：`feature/module-a-platform-oauth-callback`。
- 规划基线：`feature/module-a-platform-auth-foundation` / `05308bd`。
- 交付方式：stacked Draft PR；按用户要求，PR #37、PR #39 和 PR-A2 在整个任务完成前均不合并。
- 风险等级：L3，涉及公网 callback、OAuth state、密钥托管、网络出口、授权身份、迁移、权限和审计。
- 当前状态：`技术复审通过、等待总任务合并`。本分发不实现 OAuth、不发真实平台请求、不创建真实凭据。

## 2. 开发目标

在 A1 授权基础上，实现受控的 Shopee / TikTok Shop OAuth 发起、一次性 callback、密钥托管引用交换、授权状态查询、刷新、撤销和失败重试闭环。业务数据库不得保存或输出 Token、Secret、授权 code、Cookie、Session 或可还原密文。

PR-A2 首先必须以 synthetic adapter 完成全合同测试。只有获批应用控制台证据、回调域名、最小只读 scope、精确 endpoint、区域、限流、密钥托管和网络出口专项安全评审全部通过，才允许在同一合同下启用真实 Sandbox adapter。Production 始终禁用。

## 3. 开工阻断项（A2-00）

下列证据缺一项即只允许开发 synthetic/mock，不允许真实 Sandbox 网络请求：

1. Shopee 与 TikTok Shop 获批应用标识、所属组织、环境和负责人；只登记掩码或引用，不提交原值。
2. 控制台显示的精确授权入口、Token 交换/刷新/撤销 endpoint、区域域名、API 版本和最小只读 scope。
3. 已登记且与环境一致的 HTTPS callback URL；禁止通配符、IP 地址、localhost 和用户提交的任意 URL。
4. 密钥托管服务合同：业务层输入授权 code，输出 `credential_id/token_id/mask/version/expires_at`，任何 Token 不返回业务层。
5. 网络出口 allowlist、DNS/TLS 校验、连接/读取超时、代理策略、紧急停止开关和回退方案。
6. 专项安全评审书面批准；批准需区分 synthetic、Sandbox、Pilot 和 Production，不得沿用环境权限。

## 4. 工作包

### A2-01 合同与证据登记

- 冻结 `shopee_tiktok_oauth_callback_contract.md`、平台版本、scope、endpoint、回调域名、错误码与弃用策略。
- 新增只保存掩码、来源、审核人、审核时间和合同版本的 evidence registry；禁止保存控制台截图中的密钥或 Token。
- 未确认项保持 `pending`，不得以示例值代替获批控制台值。

### A2-02 OAuth attempt 与 state

- 新增 `MarketplaceOAuthAttempt` 或等价独立模型，绑定 tenant、internal user、session、platform、integration config、store、region 和允许列表 redirect target code。
- state 使用至少 256-bit CSPRNG；数据库只保存 SHA-256 hash，固定 5 分钟 TTL，一次性原子消费。
- 状态固定为 `initiated/callback_received/exchanged/succeeded/failed/expired`；所有写入经服务层、行锁和不可变审计。
- `Idempotency-Key` 只保存 hash；同 key 同请求返回原 attempt，同 key 不同请求返回 409。

### A2-03 Internal authorize 与状态查询

- 注册 `POST /api/internal/integrations/store-authorizations/oauth/initiate/`。
- 注册 `GET /api/internal/integrations/oauth-attempts/{id}/`。
- 仅 authenticated internal 用户、`integrations.store.authorize` 和对应 `platforms/store_ids` scope 可访问。
- authorize 响应只返回 allowlisted `authorization_url`、attempt ID、过期时间和 request ID，不返回 state 原值以外的任何安全材料；state 仅嵌入服务端生成 URL。

### A2-04 Public callback 与托管交换

- 注册 `GET /api/platform/oauth/{platform}/callback/`，该路径不使用 JWT，但必须通过 state、平台、时间窗、session 绑定、一次性消费和平台合同校验。
- callback 只接受平台合同冻结的字段；拒绝 Token、Secret、Cookie、Session、通用 `credentials` 和未知参数。
- 授权 code 仅在内存中传递给密钥托管边界，禁止持久化、日志、异常、APM、审计或重试队列记录。
- 托管成功后才创建或激活 `MarketplaceStoreAuthorization`；失败保持旧授权不变并记录稳定错误码。
- 浏览器仅 302 到服务端 allowlist 中的 redirect target，查询参数只允许结果码和 attempt 公共 ID。

### A2-05 Refresh、revoke 与 retry

- `POST /api/internal/integrations/store-authorizations/{id}/refresh/` 使用 `integrations.credential.rotate`。
- `POST /api/internal/integrations/store-authorizations/{id}/revoke/` 使用 `integrations.store.revoke`。
- `POST /api/internal/integrations/store-authorizations/{id}/retry/` 使用 `integrations.store.retry`。
- 所有动作要求 `Idempotency-Key`、行锁、版本冲突 409、permission-specific scope 和成功/失败审计。
- revocation 是 saga：先使新业务请求停止使用旧引用，再调用托管/平台撤销；外部成功而本地失败必须可恢复，不得用单个数据库事务假装覆盖外部副作用。

### A2-06 Synthetic、Sandbox 与前端

- synthetic adapter 必须可完全离线运行并覆盖成功、拒绝、过期、重放、签名错误、托管失败、429、5xx 和超时。
- Sandbox adapter 默认关闭；通过独立 settings 开关和环境/域名 allowlist 双重启用，Production settings 强制拒绝。
- 前端仅增加“发起授权、查看状态、撤销、重试”受控交互；不提供 Token/Secret 输入框，不直接拼接 callback URL。
- 未完成真实 Sandbox JWT/权限/字段联调前，映射状态保持 `pending/mock`。

## 5. 明确不包含

- 订单、退款、库存、商品、SKU 映射或销售导入（A-07/A-08 及后续）。
- webhook 业务处理、自动同步任务和真实 RPA。
- 写权限 scope、商品上下架、改价、采购、付款、转账或提现。
- Pilot、Production、生产 DNS/证书变更或生产网络出口。
- 将任何能力标记为 `connected`。

## 6. 必须测试

- 两 tenant、两平台、多 store 的 authorize/callback/status/refresh/revoke/retry 隔离。
- exact permission 与 permission-specific `platforms/store_ids` scope 不可互相替代。
- state 随机性、只存 hash、5 分钟过期、一次性消费、并发 callback、跨 tenant/user/session/platform/store 重放全部拒绝。
- callback 未知字段、缺字段、篡改、错误平台、错误签名、过期 code、重复 code 和 redirect 注入拒绝。
- code/Token/Secret/Cookie/Session 在数据库、API、日志、异常、审计、APM 测试输出中均不存在。
- 密钥托管成功/失败/超时和外部撤销 saga 的补偿、重试、幂等及崩溃恢复。
- 200/302/400/401/403/404/409/422/429/502/503 稳定合同。
- Django check、迁移一致性、模块/全量 pytest、前端 test/build、MySQL 并发、Sandbox integration、CI guard 与凭据扫描。

## 7. 交付与审核

1. 先提交 A2-01 合同与 A2-00 证据状态，执行专项架构/安全 R0；未通过时不写真实 adapter。
2. 完成 A2-02 至 A2-06 后提交 Draft stacked PR，base 为 A1 分支，不合并。
3. P0/P1 清零后执行固定 HEAD R1；整个任务完成时按依赖顺序统一合并并重跑 integration。
4. 任何真实 Sandbox 执行必须在报告中记录应用环境、合同版本、掩码证据和结果，不记录凭据或真实业务载荷。

## 8. R7 状态登记（2026-08-05，架构员核对）

- A-PR2 状态：由“本地复审通过、远程门禁 PENDING”更新为“技术复审通过、等待总任务合并”。
- 依据：PR #40 最终 HEAD `907ad541efa6cc27f481287e4dbeb91b2ea8062e` 的全部 15 项 checks 均 pass（含 Django and pytest、Phase 3 Django, data quality, and pytest）；未沿用旧 HEAD `5111c00` 的绿色结果。
- HEAD 演进：`bc09028`（R5 整改）→ `66c7546`（R6 报告归档，R7-T1）→ `5704ef4`（npm high 清零，R7-T3）→ `907ad54`（redaction 门禁登记，R7-T4）。
- PR #40 保持 Draft；合并须待用户授权后按 #37 → #39 → #40 顺序以 merge commit 执行（R7-T5）。
- 结论仅覆盖 synthetic/mock 合同；不授权标记 `connected`，不启用真实回调域名。callback query redaction 已登记为发布前置条件（`docs/06_release/a_pr2_oauth_callback_query_redaction_gate.md`）。

## 9. 交接文件覆盖登记（2026-08-06，开发A留痕）

- 交接文件 `developer_a_shopee_tiktok_handover.md`（2026-08-06）生效：开发A升级为开发负责人、模块架构负责人、上线负责人；本模块不再设流程阻断项。
- 本文 §3 A2-00 六项证据的流程阻断效力被交接文件覆盖：证据收集转为技术准备事项，由开发A自行推进与确认，安全检查留痕即可；Pilot/Production 阶段仍按完整六项口径。
- 三项技术底线继续强制：真实密码/Token/Secret/私钥不进 Git/日志；tenant/store 数据不互串；数据库变更前保留可恢复备份。
- 技术不变量默认保持：OAuth attempt/action/operation/resource lease 的 fencing 锁顺序与一次性 state 语义（R1–R6 已验证），改动需自评估并留痕。
- PR #40 基线 HEAD `8470ed6d91373559a74cf8d084419774aca00966` 已记录；合并或重写前保留可回退引用。
- 真实联调的技术事实约束不变：获批应用、控制台端点、callback URL、托管接口证据未就绪前，真实 adapter 保持 fail closed，不发起真实网络请求；合同值不填推测值。
