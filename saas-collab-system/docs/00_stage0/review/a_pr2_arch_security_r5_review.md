# A-PR2-ARCH-SEC-R5 独立整改复审报告

## 1. 复审对象

- PR：#40，当前为 `OPEN / Draft`。
- 分支：`feature/module-a-platform-oauth-callback`。
- R4 整改前基线：`3c1577d321c46449aa91bf1bcf9565888e08746d`。
- R4 业务整改提交：`2e27dec`。
- 本轮固定 HEAD：`5111c00041a897377dc31153188bebdaeee227c7`。
- 复审输入：`developer_a_marketplace_oauth_callback_r4_fix_change_log.md`。
- 复审日期：2026-08-05。
- 性质：独立只审核；除本报告外不修改业务代码，不提交、不推送、不合并。

本地与远程 PR HEAD 一致，GitHub 当前可见 checks 全部通过。

## 2. 复审结论

**不通过（BLOCKED）。**

R4-P1-002 已关闭：action 成功/失败现与 operation 终态在同一事务中提交，initiate/retry 不再永久停留 `pending`，历史不一致窗口也可恢复收敛。资源租约模型的写入/删除绕过也已补上 service gate。

但 R4-P1-001 仍未关闭。新增 `assert_operation_fence()` 只锁定“旧 action 自己的 operation 行”，没有在业务写事务内锁定并校验“共享资源租约行”。同一授权的新 action 使用另一条 operation，因此可在旧 worker 已通过 operation fence 但尚未写授权时，等租约到期后取得资源新 fence。旧 worker 恢复后仍会提交授权副作用。

本轮无 P0，有 1 项 P1。PR #40 必须继续保持 Draft，不允许合并。

## 3. 阻断问题

| 编号 | 问题 | 证据与影响 | 关闭标准 |
|---|---|---|---|
| A-PR2-R5-P1-001 | 业务写边界只锁 operation，没有锁共享资源租约；“校验后、提交前”仍可被另一 action 接管 | `assert_operation_fence()`（`store_authorization_service.py:64-84`）只对 `MarketplaceOAuthOperation` 执行 `select_for_update()`。refresh/revoke 的两个 action 有不同 operation 行；`claim_oauth_action()`（`oauth_services.py:210-240`）接管时锁共享 resource lease，但只更新新 action 的 operation，不需要、也不会等待旧 operation 行锁。独立 MySQL 双线程 probe 让旧 refresh worker 先调用原始 `assert_operation_fence()` 并持有旧 operation 行锁，然后暂停；等 2 秒租约到期后，新 refresh action 成功获得更高 resource fence；释放旧 worker 后，其仍将 `credential_reference_version` 从 1 写为 2，之后才在 `_update_operation()` 中报 `StateConflict`。这证明旧 owner 仍能在接管后提交本地授权副作用。现有 `_pause_fence_and_take_over()` 测试在调用原始 fence 前就暂停（`test_shopee_tiktok_auth_foundation.py:1723-1727`），只覆盖“接管后才进入写边界”，没有覆盖本次失败时序。 | 对 refresh/revoke 等 action-bound 业务写，在同一事务中按统一顺序锁定并校验 resource lease owner/fence/expiry，然后再锁 operation 和 authorization，且持有共享 resource lease 行锁直到业务写提交。无 resource lease 的 callback exchange 可继续使用单 operation 锁。增加 MySQL 双 worker 测试：旧 worker 必须在完成 resource+operation fence 校验后暂停，租约到期后启动新 action 接管；新 action 必须等待旧写事务结束，且不得出现“新 fence 已颁发、旧 worker 后提交”。覆盖 refresh rotate 和 revoke transition，断言新 fence 颁发后旧 worker 零授权/引用/审计副作用。 |

## 4. R4 整改关闭矩阵

| R4 整改项 | R5 结论 | 说明 |
|---|---|---|
| R4-P1-001 fencing 未覆盖业务副作用 | **未关闭** | 接管后才进入边界的旧 claim 已能拒绝；但旧 worker 先通过自己 operation fence、共享 resource lease 随后被新 action 接管的窗口仍可提交副作用。 |
| R4-P1-002 action/operation 终态分离 | 已关闭 | complete/fail 已在同一事务中写 action/operation 终态并释放 owner/lease；initiate/retry 终态、成功/失败恢复窗口与幂等重跑测试通过。 |
| R4-P2-001 resource lease 绕过写 | 已关闭 | lease model/QuerySet 已增加 service-write gate 和 delete guard，直接 save/update/bulk/delete 负例通过。 |

## 5. 已确认的有效整改

- `complete_oauth_action()` 和 `fail_oauth_action()` 已同步 action/operation 终态、phase、error code 与 owner/lease 释放。
- initiate 与 retry 内外层 operation 正常路径均达到 `succeeded`。
- recovery 可收敛 action 已终态、operation 非终态的历史/崩溃窗口，重复调用幂等。
- exchange 这类单 operation 接管的 stale-claim create 已能在业务写前拒绝。
- `MarketplaceOAuthResourceLease` 已防止绕过 service layer 的写入、重置和删除。
- 未发现真实 Shopee/TikTok Shop 网络请求、真实凭据、RPA、财务、订单、付款或库存副作用；能力仍为 synthetic/mock，不得标记 `connected`。

## 6. 独立验证

| 检查 | 结果 | 说明 |
|---|---|---|
| 固定 HEAD / PR 状态 | PASS | 本地与远程均为 `5111c00`；PR #40 `OPEN / Draft`，mergeable |
| GitHub checks | PASS | 当前可见 repository guard、Django/pytest、Docker Compose、frontend build、RPA/docs 检查全部成功 |
| `git diff --check 3c1577d..5111c00` | PASS | 无 whitespace error |
| MySQL 8.4 A2 定向 pytest | PASS | 68 passed |
| MySQL 8.4 后端全量 pytest | PASS | 478 passed |
| Django check / migrations / permission catalog | PASS | 无 system check 问题；无未生成迁移；权限目录完整 |
| 前端 Vitest | PASS | 14 files，168 tests passed |
| 前端 production build | PASS | 1958 modules transformed；仅有既有 `@vueuse/core` PURE annotation warning |
| `sandbox.ps1 verify integration` | PASS | `LOCAL_SANDBOX_VERIFY=PASS profile=integration` |
| R5 MySQL 负向 probe：旧 worker 先通过 fence、后发生资源接管 | **FAIL** | 新 action 成功获得更高 resource fence；旧 worker 随后仍将引用版本 1 写为 2，最后才报 `StateConflict` |
| `npm audit --audit-level=high` | NOT CLEAN | 2 个既有 high：`brace-expansion` 与 `postcss`；本轮未自动升级依赖 |

R5 负向 probe 为复审期间的临时 MySQL 测试，执行后已删除，未留在工作树。现有 478/68/168 项用例通过证明无基线回归，但不能覆盖上述失败时序。

## 7. P2 / 观察项

1. callback 仍是携带 state/code/signature 的 GET query。仓库内未见 Sandbox/Pilot/Production 反向代理与 access log 的 query redaction 证据，需在环境发布门禁中确认原始 query 不入日志。
2. `brace-expansion` 和 `postcss` 的两个 high 依赖问题不是本轮 OAuth 整改新增，仍需单独升级和回归审查。

## 8. R6 前置条件

1. 仅定向整改 R5-P1-001 及直接测试和文档；不接入真实平台，不扩大业务范围。
2. 先固定全局锁顺序，再使 action-bound 业务写事务持有共享 resource lease 行锁直到授权/引用/审计写入提交；不得仅锁旧 action 自己的 operation。
3. 修正并发测试的暂停点：必须在原始 resource+operation fence 检查完成后再暂停，验证新 action 接管的阻塞/串行语义，而不是在 fence 校验前暂停。
4. 提交第五轮定向整改日志，固定新 HEAD 执行 `A-PR2-ARCH-SEC-R6`，复跑 MySQL targeted/full、前端 full/build、CI guard 和 Local Sandbox integration。
5. R6 P0/P1 清零且远程 CI 全绿前，PR #40 继续保持 Draft，不合并。

## 9. 合并结论

**不允许合并。**

允许的下一步仅为 `A-PR2-P1-FIX-R5` 定向整改。即使后续复审通过，也只代表 synthetic/mock 合同通过，不代表真实 Shopee/TikTok Shop Sandbox、Production、真实凭据或 `connected` 获准。
