# A-PR2-REAL-SANDBOX-OAUTH R8 自查复审报告

## 1. 复审对象

- 任务：A-PR2-REAL-SANDBOX-OAUTH（2026-08-06 交接文件覆盖版任务书）。
- PR：#40，`OPEN / Draft`（是否合并由开发A自决，本轮保持 Draft）。
- 分支：`feature/module-a-platform-oauth-callback`。
- 变更前基线 HEAD：`8470ed6d91373559a74cf8d084419774aca00966`（已记录，可回退）。
- 本轮固定 HEAD：`c03463ab7f5ebd10023dac16e80112a5fc3d7988`。
- 复审输入：`developer_a_marketplace_oauth_real_sandbox_change_log.md` 与固定 HEAD 代码。
- 复审日期：2026-08-06。
- 性质：开发A自查复审（交接文件生效后不再等待其他角色复审；R1–R7 编号已占用，本轮起用 R8）。

## 2. 复审结论

**固定 HEAD 自查复审通过（PASS）。当前状态保持 synthetic/mock；不标记 sandbox_verified，不标记 connected。**

- P0：0。
- P1：0。
- P2 / 观察项：2（见 §6）。

## 3. 必改项逐条检查

| 必改项 | 结论 | 检查要点 |
|---|---|---|
| 1. 技术准备项登记入 evidence registry | PASS | append-only + 写入门控 + 凭据形状键拒绝均有测试覆盖；9 条基线中 8 条 pending、安全确认 ready；masked_value 只含结构占位与缺失说明，无原值 |
| 2. a2-sandbox-v1 合同冻结 | PASS | 结构冻结于合同 §1.1；所有值为 pending，未见推测值；登记路径固定为 registry + `MARKETPLACE_OAUTH_REAL_CONTRACT` |
| 3. ShopeeAdapter / TikTokShopAdapter | PASS | 授权 URL 仅用合同入口，字段缺失即 `OAUTH_CONTRACT_PENDING`；callback 白名单（无签名字段）、state 一次性、`verify_exchange_identity` 门店比对均有正负例测试 |
| 4. 托管 gateway 真实合同 | PASS | 业务侧只传 code、拿引用/掩码；签名语义锁定在托管侧；传输层有意未接线（`OAUTH_NETWORK_CLIENT_PENDING`），避免在托管合同登记前引入 HTTP 依赖 |
| 5. TikTok shops 查询 | PASS | `fetch_shop_info()` 冻结 `/authorization/{api_version}/shops` 语义与字段（shop_id/shop_cipher/region），值待合同登记 |
| 6. 网络门禁双重启用 | PASS | 开关 + allowlist + DNS 全局地址校验四态测试通过；Production 无条件拒绝；默认 allowlist 为空即全拒绝 |
| 7. refresh/revoke 真实语义 | PASS | 轮换引用版本、托管作废 + 本地 saga、外部成功本地失败进 reconcile_required 均已写入口径；实现路径与传输层同步 pending，无半成品接线 |
| 8. 前端状态映射 | PASS | capability 映射 fail-closed：仅后端精确值可晋升，未知值回落 mock；Mock 数据保持 `mock`；前端无本地晋升 connected 的路径 |

## 4. 技术底线与不变量

| 检查 | 结论 |
|---|---|
| 凭据不进 Git/日志 | PASS；本轮零真实凭据；registry 拒绝凭据形状键；凭据扫描 0 命中；`.gitignore` 扩为 `db.sqlite3*` 防止 DB 备份入库 |
| tenant/store 不互串 | PASS；真实 adapter 独立于既有 scope/fencing 路径；callback 身份比对强制门店一致 |
| DB 变更前备份 | PASS；`backend/db.sqlite3.pre-a2-sandbox-v1.bak`（本地，gitignore 排除） |
| fencing 锁序与一次性 state 不变量 | PASS；既有 oauth_services 零改动；MySQL 双 worker 边界测试 5 项全过（sqlite 下按设计 skip） |

## 5. 独立验证复述

| 检查 | 结果 |
|---|---|
| Django check / `makemigrations --check` | PASS |
| sqlite 全量 pytest | PASS；484 passed, 5 skipped |
| MySQL 8.4 全量 pytest | PASS；489 passed（含 5 个双 worker fencing 测试） |
| 前端 Vitest | PASS；15 files，174 tests |
| 前端 production build | PASS；1959 modules，ExitCode=0 |
| `sandbox.ps1 verify integration` | PASS；`LOCAL_SANDBOX_VERIFY=PASS profile=integration` |
| 凭据扫描 | PASS |

## 6. P2 / 观察项

1. HTTP 传输层与托管提供方合同为两级 pending（`OAUTH_CONTRACT_PENDING` → `OAUTH_NETWORK_CLIENT_PENDING`）。接线时必须单独立项评估 requests/httpx 依赖、超时与退避实现，并复跑本门禁测试套件。
2. 前端 capability 展示依赖后端在联调通过后于响应中给出 `api_status: 'sandbox_verified'`；后端该字段的发放逻辑属于联调阶段工作，本轮未实现（当前后端仍为 synthetic 响应），登记为联调前检查项。

## 7. 状态与后续

- 本轮不启用真实网络请求，不做真实联调，不发放 sandbox_verified/connected。
- 技术准备项 1–6 就绪（registry 9/9 ready）后，按变更日志 §7 顺序执行登记 → 联调 → 状态升级。
- PR #40 保持 Draft；与 A-MKT-SYNC-01 的衔接方式在下一任务立项时留痕决定。
