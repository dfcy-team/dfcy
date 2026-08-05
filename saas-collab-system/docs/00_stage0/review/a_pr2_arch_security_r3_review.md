# A-PR2-ARCH-SEC-R3 独立整改复审报告

## 1. 复审对象

- 对应 PR：#40。
- 分支：`feature/module-a-platform-oauth-callback`。
- R2 基线：`724e51458e7f373f4a8764716627ade47c062f95`。
- 本轮固定 HEAD：`8629bd83d3008c32bd2b041d38253325b29f21e1`。
- 整改说明：`developer_a_marketplace_oauth_callback_r2_fix_change_log.md`。
- 复审日期：2026-08-05。
- 性质：独立只审核；除本报告外不修改业务实现，不提交、不推送、不合并。

PR #40 当前为 `OPEN / Draft`，远端 HEAD 与本轮固定 HEAD 一致，merge state 为 `CLEAN`，当前 GitHub checks 全部通过。按既定流程，CI 绿色不替代架构、安全、并发和恢复语义复审。

## 2. 复审结论

**不通过（BLOCKED）。**

本轮确认进程级 raw-state vault 已移除、过期状态命令已增加、回调 durable operation 的创建顺序有改善、顺序执行的跨资源 key 冲突测试已增加、前端 action-only 页面入口已有真实挂载测试、公开 OAuth 动作端点的 production synthetic gate 已补齐。

但固定 HEAD 仍有 6 项 P1 未关闭：错误会话 callback 可破坏合法 attempt；数据库约束无法阻止同 key 跨资源并发竞态且 lease 无 fencing；模型绑定只校验同 tenant；exchange recovery 只改状态而不恢复或补偿；retry-only 前端/后端链路不完整且 target 查询未强制 internal；action service helper 可绕过 production synthetic gate 创建 action/operation。无 P0。

## 3. 阻断问题

| 编号 | 问题 | 证据与影响 | 关闭标准 |
|---|---|---|---|
| A-PR2-R3-P1-001 | 错误会话 callback 会把合法 attempt 永久标为失败 | `views.py:434` 在 `consume_callback()` 验证 session 前创建 exchange operation；session 不一致时服务抛出 `OAUTH_STATE_INVALID`，但 `views.py:457-458` 仅排除 expired/consumed，随后对合法 attempt 调用 `fail_attempt()`。因此持有泄漏 state、但没有原 session 的请求可将受害者 attempt 从 `initiated` 改为 `failed`；合法用户之后会因状态不再是 initiated 而进入 consumed 冲突。现有跨 tenant/session 测试只断言未创建授权，没有断言 attempt 保持 initiated，也没有断言零 operation/零失败审计。 | 在同一事务中先锁定并验证 state、platform、session，再创建 durable handoff 并消费；session/state 归属失败不得改变 attempt、不得创建 operation/audit。补错误 session、错误 platform、未知 state、重复 callback 的零副作用矩阵。 |
| A-PR2-R3-P1-002 | 同 key 跨资源并发仍可创建两套 action；lease 没有 fencing | `models.py:559` / migration `0012:37` 把 `object_type/object_id` 加进唯一约束，数据库因此允许同 tenant/user/action/key 在资源 A、B 各插一行。`begin_oauth_action()` 的宽条件查询只能拒绝顺序请求；两个 worker 同时查询空集时可分别提交，新增测试 `test_oauth_action_key_cannot_cross_resources` 只覆盖顺序调用。`claim_oauth_action()` 生成 owner，但后续 gateway、complete/fail/update 均不携带或校验 owner；lease 过期接管后，旧 worker 仍可提交结果。不同 key 的同资源 refresh 也各有独立 lease，不能形成资源级串行。 | 用数据库唯一 key registry 或不含资源 ID 的唯一约束保证同作用域 key 只能有一行，同时在命中后校验完整 fingerprint/resource；为执行增加可比较 fencing token，所有副作用和完成写入必须校验 owner/token；增加 MySQL 双进程跨资源同 key、同资源同 key、lease 过期接管和旧 owner 提交拒绝测试。 |
| A-PR2-R3-P1-003 | action/operation 模型绑定一致性仍不完整 | `MarketplaceOAuthAction.clean()`（`models.py:574-582`）只检查 user、attempt、authorization 是否属于同一 tenant，不检查 `action.internal_user == attempt.internal_user`，也不检查 `object_type/object_id` 与 attempt/authorization 主键一致。`MarketplaceOAuthOperation.clean()`（`models.py:657-663`）同样只比较 tenant，不校验同时存在的 attempt 与 authorization 是否属于同一 store/config/platform。服务上下文中的 QuerySet update 仍可绕过 `full_clean()`。因此同 tenant 内可构造“用户 A action 绑定用户 B attempt”或“object_id B 绑定 authorization A”的持久记录。 | 在模型和每个服务入口验证 tenant、actor、attempt owner、authorization、object target、store、config、platform 的完整绑定；受保护 QuerySet 更新不得绕过这些字段；增加同 tenant 跨用户、跨 attempt、跨 authorization、object ID 不一致、operation 双目标不一致的负向测试。 |
| A-PR2-R3-P1-004 | recovery 入口不是按 phase 可执行、幂等的恢复/补偿 | `recover_oauth_operation()` 在 exchange 分支（`oauth_services.py:625-641`）仅把 attempt 标为 failed、operation 标为 `reconcile_required`，没有重放 exchange、撤销已生成引用、创建替代授权流程或完成 reconciliation。若进程在 `custody_exchanged` 后崩溃，孤立引用没有补偿入口。refresh/revoke recovery 没有 operation claim/lease/fencing；refresh synthetic result（`oauth_adapters.py:104-109`）只按 authorization ID 和当前版本生成，忽略 operation ID，局部成功后重跑可能再次推进版本而非返回同一结果。没有新增 recovery/崩溃注入测试。 | 为每个 durable phase 定义可执行且幂等的 resume/compensate/reconcile；持久化恢复所需的安全引用或可重建材料；recovery 本身必须 claim/fence；补 operation 创建前后、callback consume 后、custody 后、本地写前后、审计前后崩溃及重复恢复测试，并证明最终只有一个授权结果和一个终态。 |
| A-PR2-R3-P1-005 | exact-permission 前端链路仍不闭环 | `oauth_target_collection` 使用 `IsAuthenticated`（`views.py:297`），没有动作端点具备的 internal-user 边界；具有相应 role/permission/scope 的 external 用户可进入目标元数据查询。retry-only 用户可调用 retry 并收到 attempt/authorization URL，但 attempt detail 固定要求 `IsMarketplaceStoreAuthorizer`（`views.py:390`）；前端 `runAction()`（`MarketplaceOAuth.vue:223-240`）不会像 initiate 分支那样跳转 `authorization_url`，而是立即调用 `loadAttempt()`，retry-only 用户得到 403。新增挂载测试只覆盖 authorize-only 与 rotate-only，未覆盖 revoke/retry 实际点击、URL 跳转和轮询。 | target endpoint 强制 internal 并按 action 使用 exact permission class；retry 创建的 attempt 必须允许 retry 权限在相同 data scope 下读取，或提供专用状态端点；前端 retry 成功后安全跳转服务端 URL并能轮询。补 external、authorize-only、rotate-only、revoke-only、retry-only 的后端与真实组件交互矩阵。 |
| A-PR2-R3-P1-006 | production synthetic gate 在 action service 边界仍可绕过 | 公开 initiate/callback/refresh/revoke/retry 与 exchange/refresh/revoke/recovery service 已调用 `_require_synthetic()`；但 `begin_oauth_action()`（`oauth_services.py:119`）自身无 gate，并直接创建 operation 与 action。任何管理命令、后台任务或后续服务直接调用该公开 helper，在 `MARKETPLACE_OAUTH_SYNTHETIC_ENABLED=False` 时仍可写入。现有 production test 只覆盖 HTTP 端点，未直接覆盖 begin/claim/complete/fail 等 mutation service。当前未发现外部路由直接利用此缺口，但整改日志“所有 service-layer boundary fail closed”的结论不成立。 | 在所有可直接调用的 synthetic mutation service 统一执行环境 gate，或把未加 gate 的 helper 私有化并只暴露一个受控入口；增加 production settings 导入后的 service 级零副作用测试，逐项断言 action、operation、attempt、authorization、reference、audit 均不变化。 |

## 4. R2 整改项关闭矩阵

| R2 整改项 | R3 结论 | 说明 |
|---|---|---|
| raw state lifecycle | 部分关闭 | 进程 vault 已删除，业务记录不保存 raw state；过期命令存在。仍缺实际调度证据和 callback query/access-log 脱敏证明。 |
| tenant and binding consistency | 未关闭 | 仅同 tenant 校验，不是完整 owner/object/store/config/platform 绑定。 |
| durable callback handoff and recovery | 未关闭 | handoff 顺序改善；错误 session 有副作用，recovery 只转人工状态。 |
| action idempotency and ownership | 未关闭 | 顺序跨资源测试通过，但数据库竞态与 lease fencing 未解决。 |
| exact frontend action permissions | 未关闭 | action-only 入口改善；target internal 边界和 retry-only 完整流程仍失败。 |
| production synthetic gate | 未关闭 | HTTP 与主要业务 service 已补 gate；action mutation helper 仍可直接写入。 |

## 5. 已确认的有效整改

- `_STATE_VAULT` 已从实现中移除，action response 不保存 authorization URL。
- callback 前已创建 durable exchange operation，并记录 callback-received phase。
- expired callback 的持久化行为未回退；新增主动过期服务与管理命令。
- action fingerprint 已包含 method、path、action、object type、object ID 和 body。
- action 增加 running/owner/lease 字段，顺序重复请求可读取 durable 终态。
- synthetic custody 不再依赖进程内结果缓存。
- reconcile-required 授权 retry 后可替换引用并恢复 active，顺序测试已加入。
- OAuth 菜单/路由使用四个 action 权限的 OR 语义；新增 Vue Test Utils 挂载测试。
- HTTP 公开 mutation 端点在 synthetic disabled 时返回 503，现有测试断言不创建 action。
- 未发现真实平台网络、真实凭据、RPA、财务、订单、付款或库存副作用。

## 6. 独立验证

| 检查 | 结果 | 说明 |
|---|---|---|
| 固定 HEAD / PR 状态 | PASS | 本地与远端均为 `8629bd8`；PR #40 OPEN/Draft，merge state CLEAN |
| GitHub checks | PASS | 当前可见 Django/pytest、Docker Compose、frontend build、RPA/docs、repository guard 全部通过 |
| `git diff --check 724e514..8629bd8` | PASS | 整改提交无 whitespace error |
| Python 3.12 `py_compile` | PASS | 本轮变更的 integrations、migration、commands 和测试文件语法通过 |
| Node `--check` | PASS | integrations API/mock、menu 和新增 Vitest 文件通过 |
| CI guard | PASS | 无 forbidden files 或 high-confidence credential patterns |
| OAuth boundary/artifact scan | PASS | 未发现 finance/RPA/admin 路径、前端持久化敏感值或提交 dist/node_modules/cache/.env |
| 本机 Django/pytest/MySQL 8.4 | BLOCKED | 当前托管沙箱拒绝 Docker API、Docker config 与 `.env.local`；本轮未把整改日志中的 450 passed 视为独立复跑证据 |
| 本机 Vitest/build | BLOCKED | node_modules 存在，但 esbuild 因托管沙箱拒绝读取上级根目录而无法解析 `vite.config.js`；GitHub 对固定 HEAD 的对应 checks 为 PASS |
| npm audit | KNOWN OBSERVATION | 整改日志记录既有 postcss high；本轮未执行自动依赖升级 |

## 7. P2 / 观察项

1. `expire_marketplace_oauth_attempts` 已实现，但提交中没有 Celery Beat、计划任务或运维接入；只有其他 callback 到来时才触发 bounded cleanup。需要补实际调度与积压监控证据。
2. 整改日志声称 raw state 不进入日志，但 callback 使用 GET query，仓库没有 `django.server`/反向代理 query redaction 配置。至少应证明本地 Sandbox、Pilot 和 Production access log 不记录 state/code/signature。
3. authorize target 返回 config 与 store 两个独立列表，没有返回允许的 config-store 配对；前端 config 下拉也未按 platform 过滤，用户可组合出后端拒绝的目标。region 仍可与 store country 不一致。建议作为 UX/合同 P2 修复。
4. synthetic refresh reference ID 只含 authorization ID，不含 operation/version；即使不发生崩溃，不同独立 refresh 的引用标识也相同。应保证不同版本可区分且旧/新引用不指向同一标识。
5. 现有 `@vueuse/core` build notice 与 postcss high advisory 不是本轮 OAuth 代码新增，但仍需独立依赖治理。

## 8. R4 前置条件

1. 仅整改本报告 6 项 P1 及直接测试、迁移和文档，不接入真实平台，不扩大业务范围。
2. 提交第三轮定向整改日志，逐项映射错误 session 零副作用、数据库 key registry/fencing、完整绑定、phase recovery、retry-only 流程和 service production gate。
3. 在 MySQL 8.4 增加双进程并发与崩溃注入测试；顺序 SQLite 测试不能替代。
4. 使用固定新 HEAD 执行独立 `A-PR2-ARCH-SEC-R4`，复跑 targeted/full pytest、frontend mount/full/build、CI guard、凭据扫描和 `sandbox.ps1 verify integration`。
5. R4 P0/P1 清零且远端 CI 全绿前，PR #40 保持 Draft，不合并，不进入依赖 PR-A2 的下一 stacked PR。

## 9. 合并结论

**不允许合并。**

允许的下一步仅为第三轮 `A-PR2-P1-FIX` 定向整改。即使后续复审通过，也只代表 synthetic/mock 合同通过，不代表真实 Shopee/TikTok Shop Sandbox、Production、真实凭据或 `connected` 获准。
