# A-PR2-ARCH-SEC-R6 独立整改复审报告

## 1. 复审对象

- PR：#40，当前为 `OPEN / Draft`。
- 分支：`feature/module-a-platform-oauth-callback`。
- R5 固定基线：`5111c00041a897377dc31153188bebdaeee227c7`。
- 本轮本地固定 HEAD：`bc09028be138308481c1994337cddf811d8b6d30`。
- 复审输入：`developer_a_marketplace_oauth_callback_r5_fix_change_log.md`。
- 复审日期：2026-08-05。
- 性质：独立只审核；除本报告外不修改业务代码，不提交、不推送、不合并。

复审时本地 HEAD 为 `bc09028`，但 `origin/feature/module-a-platform-oauth-callback` 与 PR #40 仍为 `5111c00`。因此本报告可给出本地固定 HEAD 的代码/架构结论，但远程 CI 门禁必须在推送 `bc09028` 后重新确认。当前远程绿色 checks 只对应旧 HEAD，不能作为新整改提交的通过证据。

## 2. 复审结论

**本地固定 HEAD 代码/架构复审通过（PASS）；远程合并门禁待完成（REMOTE HEAD / CI PENDING）。**

- P0：0。
- P1：0。
- R5-P1-001：已关闭。
- 合并结论：当前仍不允许合并；PR #40 继续保持 Draft，直到远程 HEAD 与 `bc09028` 一致且该 HEAD 的 CI 全部通过。

## 3. R5-P1-001 关闭证据

| 检查项 | R6 结论 | 证据 |
|---|---|---|
| 共享 resource lease 是否进入业务写事务 | 已关闭 | `assert_operation_fence()` 对 action-bound claim 先从 tenant/object type/object ID 解析共享租约标识，对 `MarketplaceOAuthResourceLease` 执行 `select_for_update()`，再校验 owner/fence/expiry，之后才锁 operation。create/rotate/transition/reconcile 本身处于事务中，租约行锁持有到授权/引用/审计写提交或回滚。 |
| 新 action 是否可在旧 fenced 写开放时颁发新 fence | 已关闭 | 统一锁顺序为 action（仅 action-management）→ resource lease → operation → authorization。新 action 必须等待旧写事务释放同一 resource lease 行，不再出现“新 fence 已颁发、旧 worker 后提交”。 |
| 阻塞后是否使用过时时钟判断 | 已关闭 | `claim_oauth_action()` 在取得 action 行锁和 resource lease 行锁后重新计算 `timezone.now()`；`claim_oauth_operation()` 也在取得 operation 行锁后重新计算，不使用等待前的 stale clock。 |
| MySQL 并发测试暂停点 | 已关闭 | 测试 helper 改为先执行原始 resource+operation fence，再暂停旧 worker；接管在独立线程中执行并断言租约行锁持有期间仍被阻塞。exchange、refresh、revoke 三个双 worker 测试通过。 |
| R6 独立 MySQL 时序 probe | PASS | 旧 refresh worker 完成真实 resource+operation fence 后暂停；墙钟租约过期后启动新 action，新 action 在旧事务结束前一直阻塞且未颁发新 fence；旧写事务提交后才颁发更高 fence，时序断言通过。 |

## 4. 独立验证

| 检查 | 结果 | 说明 |
|---|---|---|
| 本地固定 HEAD | PASS | `bc09028be138308481c1994337cddf811d8b6d30` |
| 远程 PR HEAD | PENDING | PR #40 仍为 `5111c00041a897377dc31153188bebdaeee227c7`，尚未包含 R5 整改 |
| `git diff --check 5111c00..bc09028` | PASS | 无 whitespace error |
| MySQL 8.4 A2 定向 pytest | PASS | 68 passed |
| MySQL 8.4 后端全量 pytest | PASS | 478 passed |
| Django check / migrations / permission catalog | PASS | 无 system check 问题；无未生成迁移；权限目录完整 |
| 前端 Vitest | PASS | 14 files，168 tests passed |
| 前端 production build | PASS | 1958 modules transformed；仅有既有 `@vueuse/core` PURE annotation warning |
| `sandbox.ps1 verify integration` | PASS | `LOCAL_SANDBOX_VERIFY=PASS profile=integration` |
| R6 独立 MySQL 后校验接管时序 probe | PASS | 1 passed；新 fence 颁发时间不早于旧 fenced 写事务结束 |
| 远程 CI | PENDING | 当前绿色 checks 属于旧 HEAD `5111c00`；需在推送 `bc09028` 后重跑 |
| `npm audit --audit-level=high` | NOT CLEAN | 2 个既有 high：`brace-expansion` 与 `postcss`；本轮未自动升级依赖 |

R6 独立 probe 为复审期间的临时 MySQL 测试，执行后已删除，未留在工作树。

## 5. 安全边界

- 仍为 synthetic/mock 能力，没有启用真实 Shopee/TikTok Shop 网络请求或真实凭据。
- 未发现新增 RPA、财务、订单、付款、库存或其他真实业务副作用。
- production network 与 synthetic OAuth gate 仍 fail closed。
- 本轮不授权标记 `connected`。

## 6. P2 / 观察项

1. callback 仍是携带 state/code/signature 的 GET query。仓库内未见 Sandbox/Pilot/Production 反向代理与 access log 的 query redaction 证据，需在环境发布门禁中确认原始 query 不入日志。
2. `brace-expansion` 和 `postcss` 的两个 high 依赖问题不是本轮 OAuth 整改新增，仍需单独升级和回归审查。

## 7. 远程门禁与合并结论

**本地 R6 P0/P1 已清零，但当前仍不允许合并。**

后续必须依次完成：

1. 将已审核的 `bc09028` 推送到 `origin/feature/module-a-platform-oauth-callback`，使 PR #40 HEAD 与本报告固定 HEAD 一致。
2. 等待该新 HEAD 的远程 CI 全部完成并通过；不得沿用 `5111c00` 的绿色结果。
3. 确认 PR 继续为 Draft，不合并，按用户既定要求等待整个任务完成后再统一处理合并。

只有远程 HEAD 同步且对应 CI 全绿后，A-PR2 才可记录为“技术复审通过、等待总任务合并”。此结论仅覆盖 synthetic/mock 合同，不代表真实平台 Sandbox、Production、真实凭据或 `connected` 获准。
