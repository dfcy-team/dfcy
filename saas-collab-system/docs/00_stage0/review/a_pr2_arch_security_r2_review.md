# A-PR2-ARCH-SEC-R2 独立整改复审报告

## 1. 复审对象

- 对应 PR：[#40](https://github.com/dfcy-team/dfcy/pull/40)。
- 分支：`feature/module-a-platform-oauth-callback`。
- R1 实现 HEAD：`e903cf67c20b788883b65f9b8fb78f184a532939`。
- R2 整改 HEAD：`724e51458e7f373f4a8764716627ade47c062f95`。
- stacked base：`feature/module-a-platform-auth-foundation` / `05308bd`。
- 整改说明：`developer_a_marketplace_oauth_callback_p1_fix_change_log.md`。
- 复审范围：R1 五项 P1 的实现、迁移、状态机、幂等、saga/reconcile、Production 门禁、前端 exact permission 和自动化证据。
- 复审性质：独立只审核；除本报告外不修改业务实现。

PR #40 当前仍为 `OPEN / Draft`，远端 HEAD 与本次固定 HEAD 一致，merge state 为 `CLEAN`，当前可见 CI 全部成功。按用户要求，整个任务完成前不合并。

## 2. 复审结论

**不通过（BLOCKED）。**

R1 的 5 项 P1 中，`A-PR2-R1-P1-002` 已关闭；`P1-001/003/004/005` 仍未完全关闭，并新增 1 项 Production synthetic 门禁 P1。当前合计 5 项未关闭 P1，无 P0。

本结论不否认本轮已增加 durable action/operation 模型、过期状态持久化、`revoking/reconcile_required` 状态和前端权限判断；但“记录了失败状态”不等于具备可执行恢复，“已有测试全绿”也不能替代本轮已复现的跨资源幂等、不可恢复 retry、raw state 滞留和 Production fail-closed 缺口。

## 3. R1 P1 关闭矩阵

| 原 P1 | R2 结论 | 独立证据 | 后续要求 |
|---|---|---|---|
| A-PR2-R1-P1-001：幂等跨 user 与 raw state | **未关闭** | tenant + user + action 作用域和 durable action 已加入，跨 user 复用已被阻断，普通 Django cache 中的完整 URL 也已移除。但 `oauth_services.py:39,76-90,334` 将 raw state 放入进程全局 `_STATE_VAULT`；callback 成功/失败/消费后没有 pop，过期条目只有再次 `_vault_get()` 才清理。独立复现确认成功 callback 后 raw state 仍可从进程字典读取。相同请求重放又依赖同一进程内的 vault，多 worker、进程重启或滚动部署会从原结果变成 409。 | callback 消费后立即销毁 raw state；过期条目必须主动清理，不能依赖命中时惰性删除。冻结可在多 worker/重启下成立的 initiate 幂等合同：要么使用经批准的专用短期秘密托管，要么明确不重发旧 state 并修改合同/客户端流程。补内存扫描、消费删除、过期清理、多 worker 和重启测试。 |
| A-PR2-R1-P1-002：过期 callback 状态回滚 | **已关闭** | `oauth_services.py:338-363` 在行锁事务内持久化 `consumed_at/status=expired/last_error_code`，退出事务后才抛稳定错误；新增测试和独立复核均确认过期 attempt 保持 `expired`，再次 callback 进入 consumed 分支。 | R3 只需确认整改未回退，并补 MySQL 并发过期 callback 证据。 |
| A-PR2-R1-P1-003：外部副作用无 saga/恢复 | **未关闭** | operation ledger、补偿 hook、`revoking/reconcile_required` 和先阻止本地使用再 revoke 已加入。但 callback 在 `views.py:348-354` 先消费 state，之后才创建 exchange operation；该窗口崩溃会留下 `callback_received` 且没有 operation。仓库只有写入 reconcile 状态的函数，没有 recovery worker、恢复命令或恢复端点。exchange operation 只保存随机 operation ID 的 hash，授权 code 又按合同丢弃，进程崩溃后无法重放原 exchange。独立复现确认：对 `reconcile_required` 授权调用 retry 虽生成新 attempt，callback 仍因现有授权唯一约束失败，attempt 进入 failed，原授权仍为 `reconcile_required`。 | 在消费 state 前建立可恢复 operation，或在同一原子设计中保证消费与 durable handoff 不可分割；为每个 operation phase 提供实际可执行、幂等的恢复/补偿入口与 worker/命令。retry 必须恢复原 operation 或明确创建可替换现有授权的流程，不能再次走必然冲突的纯 create。补每一步进程崩溃、重启、重复投递、补偿失败和 reconcile 完成测试。 |
| A-PR2-R1-P1-004：生命周期动作幂等/并发/审计 | **未关闭** | durable action、唯一约束和失败审计已有明显改进。但 `begin_oauth_action()` 的 fingerprint 仅计算 body（`oauth_services.py:140-155`），命中时不比较 `object_type/object_id`；模型唯一约束也不含资源 ID。独立复现：同一用户以同 key、同空 body 先 refresh 授权 A，再请求授权 B，第二次返回 200 和 A 的响应，B 未执行。跨进程并发命中 pending action 时仍可同时执行 gateway；`_ACTION_LOCK` 与 synthetic gateway 结果表都是进程内对象，不能形成多 worker 幂等边界。 | fingerprint 必须包含 method、规范化路径/action、object type、resource ID 和 body；命中时显式校验资源。外部 gateway 使用 durable operation key 或远端幂等键，pending action 需有 owner/lease/claim，保证只有一个执行者；其他请求等待或读取最终结果。补同 key 跨资源、同资源双线程/双进程、worker 崩溃接管和 MySQL 8.4 并发测试。 |
| A-PR2-R1-P1-005：前端 exact permission 与状态矩阵 | **未关闭** | 四个按钮已分别检查 exact permission，轮询和 callback error code 也已加入。但页面无条件请求 `fetchIntegrationConfigs()` 和 `fetchMarketplaceStoreAuthorizations()`，对应后端分别要求 `integrations.view` 与 `integrations.store.view`；只有 authorize/rotate/revoke/retry exact permission 的用户会在页面初始化即 403。菜单父项仍要求 `integrations.view`，action-only 用户看不到入口。更关键的是 initiate 的 `storeOptions` 来自“已有授权列表”，零授权门店不会出现，首次授权在 UI 中不可发起。新增的 4 个 Vitest 只读取源码并断言字符串存在，没有挂载组件、模拟角色/API 或验证状态/键盘/移动布局。 | 为 authorize 提供受其 exact permission/data scope 保护的 config/store 目标查询，不能用“已有授权列表”代替可授权门店；生命周期列表按各 action 权限返回可操作资源。父菜单和页面加载不得隐含依赖未冻结的 view 权限。增加真实组件挂载测试，逐角色验证入口、按钮、403/404/409/422/429/502/503/offline、轮询停止、焦点恢复和移动布局。 |

## 4. 新增 P1

| 编号 | 问题 | 证据与影响 | 关闭标准 |
|---|---|---|---|
| A-PR2-R2-P1-001 | Production synthetic 禁用开关只阻断 initiate，未阻断 callback/refresh/revoke/retry | `prod.py` 将 `MARKETPLACE_OAUTH_SYNTHETIC_ENABLED=False`，但 `_require_synthetic()` 仅在 `initiate_oauth()` 调用；callback、refresh 和 revoke 服务没有检查。独立 override-settings 复现：在 `SYNTHETIC_ENABLED=False`、`NETWORK_ENABLED=False` 下，refresh 端点仍返回 200 并轮换业务授权引用。这与整改日志“Production 明确禁用 synthetic OAuth execution”不符，也不满足 fail closed。 | 在所有 synthetic public/internal 入口和服务边界统一执行环境门禁；Production 下 initiate/callback/refresh/revoke/retry 均稳定拒绝且不创建 action/operation/audit 成功记录、不改变 attempt/authorization/reference。补 Production settings 导入测试和所有端点的零副作用负向矩阵。 |

## 5. 已确认的有效整改

- 新增 `MarketplaceOAuthAction` 和 `MarketplaceOAuthOperation`，直接 save/update/delete/bulk 受 OAuth 服务上下文保护。
- initiate 的持久幂等作用域已包含 tenant、user 和 action，跨 user 复用不再共享 attempt。
- 完整 authorization URL 不再写入 Django cache 或 action response data。
- 过期 callback 最终状态已持久化，并追加稳定失败审计。
- revoke 顺序已改为 `active -> revoking -> external revoke -> revoked/reconcile_required`。
- refresh/revoke 的 custody 与本地失败路径会更新 action/operation，并记录失败审计。
- Production settings 已增加 synthetic 开关，尽管当前覆盖范围不足。
- 前端按钮已按四个 exact permission 分离，轮询、callback error code、server-scoped authorization selector 和基本 empty/offline 文案已加入。
- PR 仍保持 Draft，真实平台网络、真实凭据和 `connected` 状态未启用。

## 6. 独立验证结果

2026-08-04 在固定整改 HEAD 执行：

| 检查 | 结果 | 说明 |
|---|---|---|
| `manage.py check` | PASS | 0 issues |
| `makemigrations --check --dry-run` | PASS | No changes detected |
| A2/A1 定向后端测试 | PASS | 36 passed，1 MySQL-only skipped |
| 后端全量 pytest | PASS | 446 passed，1 skipped |
| 前端全量测试 | PASS | 13 files / 164 tests |
| 前端生产构建 | PASS_WITH_OBSERVATION | 1957 modules；仅第三方 `@vueuse/core` PURE 注释提示 |
| CI guard | PASS | 无 forbidden files 或 high-confidence credential patterns |
| GitHub PR #40 checks | PASS | 固定远端 HEAD 与本地一致，当前可见 checks 全部 SUCCESS |
| R2 独立负向复现 | FAIL | 4/4 缺口成立：跨资源幂等串用、reconcile retry 不可恢复、callback 后 raw state 仍在 vault、Production 禁用时 refresh 仍成功；临时测试文件已删除 |
| `npm audit --omit=dev` | FAIL_WITH_KNOWN_OBSERVATION | `postcss <=8.5.22` 仍有 1 项 high；非本次整改新增 |
| Local Sandbox integration | PASS | Docker Desktop Linux engine 恢复后，`sandbox.ps1 verify integration` 通过；MySQL 后端 447 passed、Phase 3 数据质量通过、前端 164 passed、生产构建 1957 modules，并输出 `LOCAL_SANDBOX_VERIFY=PASS profile=integration` |
| MySQL 8.4 迁移/并发 | PASS | 隔离空库全新迁移至 `integrations.0011`；0008 未知旧记录 fail-closed 且批准记录零写入，整改后重跑至 0011；旧凭据列移除；MySQL 行锁并发专项 1 passed、无 skip |

## 7. P2 与流程观察

1. R1 报告当前仍是本地未跟踪文件，PR 整改日志引用了它，但远端 PR diff 中没有该审核依据；后续应在不覆盖用户改动的前提下补齐审核链。
2. action/operation 模型没有模型级 tenant、user、attempt、authorization 归属一致性校验；当前依赖服务正确传参。P1 修复时应补服务入口校验和跨 tenant 负向测试。
3. synthetic refresh 的引用 ID 只按 authorization ID 生成，不含版本或 operation；第二次独立 refresh 会再次得到相同引用 ID，同时轮换逻辑撤销“旧引用”。应让不同版本引用可区分并测试旧/新引用不会指向同一对象。
4. `npm audit` 的既有 high advisory 仍需独立依赖修复，不应混入 OAuth P1 代码整改。

## 8. R3 前置条件

1. 只整改本报告 5 项未关闭 P1 及直接测试/迁移/文档，不接入真实平台或扩展业务范围。
2. 提交第二轮定向整改日志，逐项映射原 P1、R2 新 P1、故障注入和恢复证据。
3. 使用固定新 HEAD 进行独立 `A-PR2-ARCH-SEC-R3`，不得用整改日志替代复查。
4. Local Sandbox integration、MySQL 8.4 全新迁移、旧记录 fail-closed/整改重跑和现有行锁并发专项已通过；仍须补同 key 跨资源、同资源 action 并发、claim/lease、崩溃接管、补偿/reconcile 完成的 MySQL 证据。
5. R3 P0/P1 清零且远端 CI 全绿前，PR #40 保持 Draft，不合并，不进入依赖 PR-A2 的下一 stacked PR。

## 9. 合并与后续开发结论

**不允许合并，不允许进入下一业务开发阶段。**

允许的下一步仅为第二轮 `A-PR2-P1-FIX` 定向整改。即使后续 R3 PASS，也只表示 synthetic/mock 合同通过，不代表允许真实 Sandbox、Production、真实凭据或 `connected`。
