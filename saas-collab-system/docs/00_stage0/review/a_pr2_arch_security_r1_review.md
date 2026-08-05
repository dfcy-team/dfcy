# A-PR2-ARCH-SEC-R1 架构与安全复审报告

## 1. 复审对象

- 对应 PR：[#40](https://github.com/dfcy-team/dfcy/pull/40)。
- 实现分支：`feature/module-a-platform-oauth-callback`。
- 审核 HEAD：`e903cf67c20b788883b65f9b8fb78f184a532939`。
- stacked base：`feature/module-a-platform-auth-foundation` / `05308bd`。
- 审核范围：PR-A2 的 frozen contract、OAuth attempt/state、public callback、synthetic custody、authorize/status/refresh/revoke/retry、权限与 data scope、前端、迁移、测试和发布边界。
- 审核性质：独立只审核；除本报告外不修改业务实现。

PR #40 当前为 `OPEN / Draft`，merge state 为 `CLEAN`，远端可见检查全部成功；基线 PR 仍按既定 stacked Draft 流程保留，整个任务完成前不合并。本次复审固定在上述 HEAD，不以开发变更日志中的自测结论替代代码和故障路径复核。

## 2. 复审结论

**不通过（BLOCKED）。**

未发现 P0，也未发现真实 Shopee/TikTok Shop 网络请求、真实凭据、Production 连接或高风险业务自动化；但发现 5 项未关闭 P1。当前只允许执行 `A-PR2-P1-FIX` 定向整改并随后进行固定新 HEAD 的 R2 复审。PR #40 必须继续保持 Draft，不允许合并，不允许启用真实 Sandbox/Pilot/Production，也不允许标记 `connected`。

## 3. 已通过项

- OAuth 路径只枚举 `shopee|tiktok`，真实网络开关默认关闭，Production settings 强制将真实网络开关设为 `False`。
- initiate body、callback query 和 synthetic adapter 均拒绝未知字段；callback 同名参数重复、错误签名、错误门店和开放重定向已有后端校验。
- state 使用 32 字节 CSPRNG，数据库模型只保存 state/session/idempotency hash，attempt 写入受服务上下文保护，QuerySet update/delete/bulk 绕过受阻。
- internal API 使用分离的 exact permission 和 permission-specific `platforms/store_ids` scope；跨 tenant 资源访问由后端边界拒绝。
- callback 响应只跳转到服务端相对路径 allowlist，未回显 state、code、签名或平台原始 query。
- code 只在当前请求中传给 synthetic custody gateway；数据库、API serializer 和审计未发现 code、Token、Secret、Cookie 或 Session 原值。
- Shopee synthetic 正向闭环、state 重放、callback 负向路径、refresh/revoke 基础路径和现有幂等样例测试均通过。
- 前端不自行拼接 callback/state，不写 localStorage/sessionStorage；页面和 API 状态仍标记为 `mock/pending`。
- Django check、迁移一致性、后端全量、前端全量、生产构建、CI guard 和远端 CI 均通过。

## 4. P1 问题

| 编号 | 问题 | 证据与影响 | 关闭标准 |
|---|---|---|---|
| A-PR2-R1-P1-001 | OAuth 幂等重放跨越 user 绑定，并在普通 cache 中持久化 raw state | `oauth_services.py:126-138` 的幂等 hash 只包含 tenant 与用户提供的 key，查询也不校验 `internal_user/session/action`；`oauth_services.py:68-69,170` 将包含 raw state 的完整 authorization URL 缓存 5 分钟。独立测试复现：同 tenant、同 scope 的第二个用户使用相同 key 和 payload，得到第一个用户的 attempt ID 与完全相同的 authorization URL；cache 值可直接命中 raw state。这与 attempt 绑定 tenant/user/session 以及“state 只存 hash”的声明冲突，并泄漏可消费的 OAuth state。并发首次请求发生唯一键竞争时，`oauth_services.py:160-164` 直接返回 409，也不满足同 key 同请求返回原 attempt。 | 冻结并实现 tenant + internal user + action + key 的幂等作用域；命中时校验 user/session、action 和 request fingerprint；并发唯一键竞争后读取并返回同一结果。不得在普通业务 cache、数据库、日志或审计中保存 raw state/完整授权 URL；若必须重发授权结果，应先冻结专用秘密托管或改为不重发旧 state 的安全合同，并补跨 user/session、cache 扫描和并发测试。 |
| A-PR2-R1-P1-002 | 过期 callback 的 `expired/consumed` 状态在事务异常中被回滚 | `consume_callback()` 被 `transaction.atomic` 包裹；`oauth_services.py:183-192` 先保存 `callback_received`、再保存 `expired`，随后抛出 `OAUTH_STATE_EXPIRED`，整个事务因此回滚。`views.py:358-363` 又明确不调用 `fail_attempt()`。独立测试复现：callback 返回 `OAUTH_STATE_EXPIRED`，但数据库 attempt 仍为 `initiated` 且 `consumed_at=NULL`，可无限重复进入过期路径；状态查询与一次性消费合同不可信。 | 在同一行锁边界内持久化最终 `expired` 和明确的一次性消费语义，不通过抛出事务异常回滚最终状态；补过期后状态查询、再次 callback、并发过期 callback 和审计断言。 |
| A-PR2-R1-P1-003 | exchange/refresh/revoke 外部副作用没有 saga、补偿或崩溃恢复，撤销顺序与冻结合同相反 | `oauth_services.py:209-249` 在 custody exchange 后分段创建/激活授权和更新 attempt，任一步失败都会留下已生成引用、pending/active 授权或未完成 attempt，且无 operation ledger/补偿；`oauth_services.py:252-263` refresh 先生成新引用，再执行本地轮换，本地冲突时没有撤销新引用；`oauth_services.py:266-276` 先执行外部 revoke、后更新本地状态，正好与 dispatch 要求“先阻止新业务使用旧引用，再撤销外部引用”相反。授权状态枚举没有 `revoking/reconcile_required`，仓库中也没有恢复 worker/ledger。独立故障注入复现：外部 revoke 成功、本地 transition 失败后记录仍显示 `active`，无 reconcile 标记或可恢复操作记录。 | 引入持久化、脱敏且不可变的 operation/saga ledger 与稳定 operation ID；gateway 必须按 operation ID 幂等。撤销先原子阻止新业务使用旧引用，再执行外部撤销，外部成功/本地失败进入 `reconcile_required` 并可安全重试；exchange/refresh 对新引用提供补偿或恢复。补每一步崩溃、重复投递、超时、429/5xx、补偿失败和恢复完成的故障注入测试。 |
| A-PR2-R1-P1-004 | refresh/revoke/retry 的幂等、行锁、版本和失败审计合同只由 5 分钟非原子 cache 模拟 | `views.py:280-290,384-419` 先读 cache、执行外部动作、最后写 cache，key 不含 tenant/user，请求之间没有锁或数据库唯一约束；两个同 key 并发请求都可越过 cache miss 并重复外部副作用。cache 5 分钟过期后，同 key refresh 会再次轮换，同 key revoke 会再次调用外部撤销；这不是持久幂等。view 只捕获 `OAuthAdapterError`，本地 `StateConflict`、版本冲突或意外异常没有动作失败审计。retry 直接复用 initiate 的 tenant 级幂等空间，也没有独立 action operation。 | 为 initiate/refresh/revoke/retry 建立持久的 action-scoped 幂等记录、请求 fingerprint、资源行锁/版本和唯一约束；同 key 并发及过期后重放返回原结果，不重复 gateway 副作用；同 key 不同请求稳定 409。所有 custody 与本地失败路径均追加脱敏、不可变的失败审计，并覆盖 MySQL 并发测试。 |
| A-PR2-R1-P1-005 | 前端未落实 exact action permission 与冻结状态矩阵，且没有 PR-A2 前端专项测试 | 路由和菜单只以 `integrations.store.authorize` 放行页面（`frontend/src/router/menu.js:61,169`），因此仅有 rotate/revoke/retry 权限的用户无法进入；进入页面后 `MarketplaceOAuth.vue:65-68` 又对所有用户同时显示 refresh/revoke/retry 按钮，没有按 `integrations.credential.rotate`、`integrations.store.revoke`、`integrations.store.retry` 分别控制。页面未实现合同要求的状态轮询和 403/409/422/503/offline 等稳定语义，callback 的 `error_code` 也未消费。`frontend/tests/` 没有 OAuth 页面/API/组件专项测试；160 个现有测试全部通过不能证明 A2 前端验收。 | 页面入口按任一相关 exact permission 可达，每个动作分别按 exact permission 显示/禁用并由后端继续兜底；实现 attempt 轮询、到期/重放/禁止/离线/稳定错误码语义，避免让用户手填任意授权 ID 作为主流程。增加真实组件挂载与 API 测试，覆盖 loading/pending/success/expired/failed/replayed/401/403/404/409/422/429/502/503/offline、键盘焦点和移动布局。 |

## 5. P2 与非阻断观察

1. `MARKETPLACE_OAUTH_SYNTHETIC_SIGNING_KEY` 在 base settings 中有公开固定默认值，Production 只关闭真实网络而未显式关闭 synthetic endpoint。当前 synthetic 不产生真实平台副作用，暂不升级为 P1；进入任何非测试部署前应要求显式非默认签名配置，或在 Production 完全禁用 synthetic initiate/callback。
2. attempt status API 只按 tenant 与资源 scope 过滤，没有限制为发起用户。是否允许同 scope 运维人员查看他人 attempt 需要合同明确；无论最终选择如何，都不得返回他人的 raw state 或 authorization URL。
3. `npm audit --omit=dev` 报告现有 `postcss <=8.5.22` 1 项 high advisory。该依赖并非 PR-A2 新增，且不改变上述 OAuth 结论，但应单独安排依赖修复与回归。
4. 前端页面要求用户手工输入 Store authorization ID，后端 scope 可阻止越权，但该交互容易产生 404/403 和误操作；建议改为从已授权的服务端列表选择。

## 6. 独立验证结果

2026-08-04 在固定审核 HEAD 执行：

| 检查 | 结果 | 说明 |
|---|---|---|
| `manage.py check` | PASS | 0 issues |
| `makemigrations --check --dry-run` | PASS | No changes detected |
| PR-A2/A1 定向后端测试 | PASS | 34 passed，1 MySQL-only skipped |
| 后端全量 pytest | PASS | 444 passed，1 skipped |
| 前端全量测试 | PASS | 12 files / 160 tests |
| 前端生产构建 | PASS_WITH_OBSERVATION | 1957 modules；仅第三方 `@vueuse/core` PURE 注释提示 |
| CI guard | PASS | 无 forbidden files 或 high-confidence credential patterns |
| GitHub PR #40 checks | PASS | 固定远端 HEAD 与本地一致，当前可见 checks 全部 SUCCESS |
| 独立安全/一致性故障复现 | FAIL | 3/3 复现：过期状态回滚、跨 user 幂等泄漏 raw state、外部撤销成功/本地失败无恢复状态；临时测试文件已删除 |
| `npm audit --omit=dev` | FAIL_WITH_KNOWN_OBSERVATION | `postcss` 1 项 high；非 PR-A2 新增 |
| Local Sandbox integration | BLOCKED | Docker Desktop Linux engine pipe 不存在，integration profile 无法启动 |
| MySQL 8.4 新迁移/并发/崩溃恢复 | NOT_RUN | 同上；不得视为 MySQL PASS |

现有自动化全部成功，只能证明现有断言通过；它们没有覆盖 P1 中的幂等作用域、raw state cache、过期事务回滚、外部副作用崩溃窗口、持久幂等和前端 exact action permission。

## 7. R2 复审前置条件

1. 只整改上述 5 项 P1 及其直接需要的模型、迁移、服务、测试和文档，不扩展到真实平台 adapter、订单、库存、退款、支付、RPA 或 webhook。
2. 提交 `A-PR2-P1-FIX` 变更日志，逐项映射 P1、代码、迁移、测试、故障注入和回滚方案。
3. 在固定新 HEAD 重跑 Django check、迁移一致性、A2 定向、后端全量、前端专项/全量/build、CI guard、依赖审计和远端 CI。
4. Docker Desktop Linux engine 恢复后，在 MySQL 8.4 验证全新迁移、A1 升级、同 key/同 state/同 store 并发、gateway 每一步崩溃、补偿、reconcile 和失败重跑；执行 `sandbox.ps1 verify integration`。
5. R2 必须独立复核，而不是引用整改日志自证；P0/P1 清零前 PR #40 继续 Draft 且不合并。

## 8. 是否允许继续后续开发

**不允许进入依赖 PR-A2 的下一业务开发阶段。**

允许的下一步仅为 `A-PR2-P1-FIX` 定向整改。整改完成并经 `A-PR2-ARCH-SEC-R2` 固定 HEAD 复审 PASS 后，才可规划下一 stacked PR；即使 R2 PASS，也仍不代表允许真实 Sandbox、Production、真实凭据或 `connected` 状态。
