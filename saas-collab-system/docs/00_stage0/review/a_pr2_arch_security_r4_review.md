# A-PR2-ARCH-SEC-R4 独立整改复审报告

## 1. 复审对象

- PR：#40，当前为 `OPEN / Draft`。
- 分支：`feature/module-a-platform-oauth-callback`。
- R3 整改基线：`8629bd83d3008c32bd2b041d38253325b29f21e1`。
- 本轮固定 HEAD：`3c1577d321c46449aa91bf1bcf9565888e08746d`。
- 复审输入：`developer_a_marketplace_oauth_callback_r3_fix_change_log.md`。
- 复审日期：2026-08-05。
- 性质：独立只审核；除本报告外不修改业务代码，不提交、不推送、不合并。

本地与远程 PR HEAD 一致，GitHub 当前可见 checks 全部通过。CI 绿色不替代并发 fencing、副作用原子性和恢复终态的负向复审。

## 2. 复审结论

**不通过（BLOCKED）。**

R3 已有效关闭 callback 归属校验零副作用、全局幂等键约束、模型绑定、exact-permission/retry-only 前后端链路和 service production gate。但本轮独立负向验证确认 2 项 P1 未关闭：

1. fencing 只保护 operation/action 状态写，没有保护授权创建、引用旋转和授权状态转换等真正的本地副作用边界。旧 worker 被新 fence 接管后仍能先写业务数据，再在后续 phase 更新时报 stale。
2. action 成功时只释放 operation owner/lease，不把 operation 设为成功终态。initiate 及 retry 外层 operation 因此永久停留 `pending`，且现有 recovery 无法接管已 `succeeded` 的 action。

无 P0。PR #40 必须继续保持 Draft，不允许合并。

## 3. 阻断问题

| 编号 | 问题 | 证据与影响 | 关闭标准 |
|---|---|---|---|
| A-PR2-R4-P1-001 | 资源 fencing 没有覆盖本地业务副作用 | `_complete_exchange()` 在 `oauth_services.py:647-706` 读 operation 后没有先校验 claim，即可调用 `create_store_authorization()`；第一次强制 stale 检查是后续 `_update_operation()`（`707-713`）。独立负向 probe 将数据库 operation 从 old owner/fence=1 切到 new owner/fence=2，再使用旧 claim 执行 `_complete_exchange()`：调用最终报 `StateConflict`，但本地 `MarketplaceStoreAuthorization` 已被创建，负向断言失败。refresh/revoke 也只在服务起点检查 claim，后续 `rotate_store_authorization_references()`（`842`）及 `transition_store_authorization()`（`873`/`917`）与 fence 检查不在同一原子写边界。现有 fencing 测试（`test_shopee_tiktok_auth_foundation.py:1328-1360`）只断言旧 owner 不能 `complete_oauth_action()`，没有断言旧 worker 不能产生业务副作用。 | 在每个本地授权创建、引用旋转、状态转换、attempt/audit 终态写边界与 operation/resource claim 做同事务行锁校验，或采用带 fence 条件的 compare-and-set；任何旧 owner/token 在接管后必须零业务写入。增加 MySQL 双 worker 暂停/过期/接管测试，分别覆盖 exchange create/rotate/activate、refresh rotate、revoke transition 边界。 |
| A-PR2-R4-P1-002 | action 与 operation 终态不一致，initiate/retry operation 不可恢复 | `complete_oauth_action()` 在 `oauth_services.py:354-360` 只清空 operation `execution_owner/lease_expires_at`，没有写 `status=SUCCEEDED` 和终态 phase。`initiate_oauth()` 在 attempt 创建后直接完成 action（`496`），不存在其他 operation 终态写。独立负向 probe 通过真实 API 成功发起 OAuth，实测 action=`succeeded`、operation=`pending`，“operation 应为 succeeded”断言失败。`recover_oauth_operation()` 对该 pending operation 会调用 `claim_oauth_action(...allow_recovery=True)`，但 `claim_oauth_action()` 对已成功 action 直接返回 `claimed=False`（`195-196`），随后 recovery 在 `973-974` 报“already being recovered”。结果是持久台账无法达到唯一终态。 | 把 action 终态与它绑定的 operation 终态在同一事务、同一 claim/fence 校验下提交；明确 initiate/retry 的 terminal phase/status。recovery 必须对 action 成功但 operation 未终态、operation 成功但 action 未终态两种崩溃窗口都可幂等收敛。增加 initiate 、retry 正常路径与两个崩溃窗口的 MySQL 负向/恢复测试。 |

## 4. R3 六项整改关闭矩阵

| R3 整改项 | R4 结论 | 说明 |
|---|---|---|
| R3-P1-001 callback ownership side effects | 已关闭 | state/platform/session/status/expiry 在 handoff 事务内先校验；无效归属矩阵断言 attempt/operation/audit 零变化。 |
| R3-P1-002 idempotency race and lease fencing | **未关闭** | 全局 key 唯一约束与资源串行化已实现；但 fence 未保护真正业务副作用，见 R4-P1-001。 |
| R3-P1-003 incomplete bindings | 已关闭 | action/operation 的 tenant、actor、attempt、authorization、object/store/config/platform 绑定及 QuerySet 绕过负例已补齐。 |
| R3-P1-004 executable recovery | **未关闭** | exchange/refresh/revoke 的部分 phase resume/compensation 已实现；但旧 worker 副作用可穿透 fence，且 initiate/retry operation 不能收敛终态，见 R4-P1-001/002。 |
| R3-P1-005 exact permission flow | 已关闭 | internal-user 边界、action exact permission/scope、retry-only attempt 读取与前端安全跳转/轮询已有后端和挂载测试。 |
| R3-P1-006 service production gate | 已关闭 | 直接 mutation service 在 synthetic disabled 下 fail closed，零 action/operation/attempt/audit/reference 变化。 |

## 5. 已确认的有效整改

- callback handoff 将归属校验、operation 创建和 state 消费放入同一事务，错误 session/platform/state 不再破坏合法 attempt。
- action 幂等唯一范围改为 tenant/user/action/key，MySQL 并发跨资源同 key 不再生成两条 action。
- action/operation 完整绑定与受保护 QuerySet update 已补齐。
- exchange/refresh/revoke 已持久化安全 custody reference 和 recovery phase，已成功 operation 可补齐未完成 action。
- OAuth target/attempt 内部用户与精确权限边界、retry-only 链路和前端四操作挂载测试已补齐。
- synthetic/mock production gate 已下沉到 action/operation/recovery 服务边界。
- 未发现真实 Shopee/TikTok Shop 网络请求、真实凭据、RPA、财务、订单、付款或库存副作用；能力仍为 synthetic/mock，不得标记 `connected`。

## 6. 独立验证

| 检查 | 结果 | 说明 |
|---|---|---|
| 固定 HEAD / PR 状态 | PASS | 本地与远程均为 `3c1577d`；PR #40 `OPEN / Draft`，mergeable |
| GitHub checks | PASS | 当前可见 repository guard、Django/pytest、Docker Compose、frontend build、RPA/docs 检查全部成功 |
| `git diff --check 8629bd8..3c1577d` | PASS | R3 整改提交无 whitespace error |
| MySQL 8.4 A2 定向 pytest | PASS | 57 passed |
| MySQL 8.4 后端全量 pytest | PASS | 467 passed |
| Django check / migrations / permission catalog | PASS | 无 system check 问题；无未生成迁移；权限目录完整 |
| 前端 Vitest | PASS | 14 files，168 tests passed |
| 前端 production build | PASS | 1958 modules transformed；仅有既有 `@vueuse/core` PURE annotation warning |
| `sandbox.ps1 verify integration` | PASS | `LOCAL_SANDBOX_VERIFY=PASS profile=integration` |
| R4 负向 probe：成功 action 必须关闭 operation | **FAIL** | 真实 initiate API 返回 201；action=`succeeded`，operation=`pending` |
| R4 负向 probe：旧 exchange claim 接管后零副作用 | **FAIL** | 旧 claim 最终被 stale check 拒绝，但本地 authorization 已创建 |
| `npm audit --audit-level=high` | NOT CLEAN | 2 个既有 high：`brace-expansion` 与 `postcss`；本轮未自动升级依赖 |

负向 probe 为复审期间的临时测试，执行后已删除，未留在工作树。现有 467/57/168 项用例通过证明无已知基线回归，但不能覆盖上述新增负例。

## 7. P2 / 观察项

1. `MarketplaceOAuthResourceLease` 没有像 action/operation 一样使用受保护 manager、service-write gate 和 delete guard。任意内部 ORM 代码可删除记录或重置 `fence_token`，会破坏“持久单调”假设。建议在 P1 fencing 修复时一并保护。
2. callback 仍是携带 state/code/signature 的 GET query。仓库内未见 Sandbox/Pilot/Production 反向代理与 access log 的 query redaction 证据，需在环境发布门禁中确认原始 query 不入日志。
3. `brace-expansion` 和 `postcss` 的两个 high 依赖问题不是本轮 OAuth 整改新增，仍需单独升级和回归审查。

## 8. R5 前置条件

1. 仅定向整改 R4-P1-001/002 及直接测试、迁移和文档；不接入真实平台，不扩大业务范围。
2. 为 exchange/refresh/revoke 的每个本地写边界增加真正的 claim+resource fence 原子校验，用 MySQL 双 worker 崩溃注入证明旧 worker 零副作用。
3. 定义 action/operation 统一终态提交规则，补 initiate/retry 正常终态及两向崩溃恢复测试。
4. 提交第四轮定向整改日志，固定新 HEAD 执行 `A-PR2-ARCH-SEC-R5`，复跑 MySQL targeted/full、前端 full/build、CI guard 和 Local Sandbox integration。
5. R5 P0/P1 清零且远程 CI 全绿前，PR #40 继续保持 Draft，不合并。

## 9. 合并结论

**不允许合并。**

允许的下一步仅为 `A-PR2-P1-FIX-R4` 定向整改。即使后续复审通过，也只代表 synthetic/mock 合同通过，不代表真实 Shopee/TikTok Shop Sandbox、Production、真实凭据或 `connected` 获准。
