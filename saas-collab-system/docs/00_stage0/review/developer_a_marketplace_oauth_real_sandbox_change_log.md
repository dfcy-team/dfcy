# A-PR2-REAL-SANDBOX-OAUTH 变更日志（真实平台 OAuth Sandbox 接入准备）

- 任务编号：A-PR2-REAL-SANDBOX-OAUTH（2026-08-06 交接文件覆盖版任务书）。
- 分支 / PR：`feature/module-a-platform-oauth-callback` → PR #40（保持 Draft，合并自决）。
- 变更前远程与本地基线 HEAD：`8470ed6d91373559a74cf8d084419774aca00966`（已记录，可回退）。
- 变更日期：2026-08-06。
- 合同版本：`a2-synthetic-v1`（仍为当前实现）+ `a2-sandbox-v1`（结构已冻结、值待登记）。

## 1. 治理背景

`developer_a_shopee_tiktok_handover.md`（2026-08-06）生效后，原 A2-00「缺一项即阻断」的流程门禁被覆盖：证据收集转为技术准备事项，由开发A自行推进与确认，安全检查留痕即可。流程门禁解除不改变技术事实约束：在无控制台证据前，真实合同值不推测、不登记，真实 adapter 保持 fail closed，当前运行状态继续为 synthetic/mock。交接覆盖已登记于 `developer_a_marketplace_oauth_callback_dispatch.md` §9。

## 2. 变更清单（按必改项）

### 2.1 evidence registry（必改项 1）

- 新增 `MarketplaceOAuthEvidence` append-only 模型（`backend/apps/integrations/models.py`）：
  写入门控 `oauth_evidence_write()`（ContextVar），仅允许 registry 服务执行 supersede；
  `masked_value` 递归拒绝凭据形状键名（token/secret/password/partner_key/cookie/session/auth_code 等）；
  save 禁止编辑既有行、delete 一律拒绝。
- 新增服务 `backend/apps/integrations/evidence_registry.py`：`register_oauth_evidence()`（注册并 supersede 旧 current 行）、`current_oauth_evidence()`、`real_sandbox_evidence_ready()`、`evidence_readiness_summary()`。
- 迁移 `0014_marketplace_oauth_evidence`（结构）+ `0015_register_a2_sandbox_evidence_baseline`（数据，登记 9 条基线）。
- 只存掩码、来源、确认人、确认时间、合同版本；不提交原值。

### 2.2 技术准备项现状登记（必改项 1，9 条基线）

| evidence_key | platform | readiness | 说明 |
|---|---|---|---|
| a2_00_app_identity | shopee | pending | 缺获批应用标识/组织/环境/负责人（掩码） |
| a2_00_app_identity | tiktok | pending | 同上 |
| a2_00_endpoint_contract | shopee | pending | 缺控制台确认的授权入口/token/refresh 端点、区域域名、API 版本、最小只读 scope |
| a2_00_endpoint_contract | tiktok | pending | 同上 |
| a2_00_callback_url | shopee | pending | 缺已登记且与环境一致的 HTTPS callback URL |
| a2_00_callback_url | tiktok | pending | 同上 |
| a2_00_custody_contract | shared | pending | 托管语义已固定（输入 code、输出引用/掩码），提供方接口未登记 |
| a2_00_network_egress | shared | pending | 门禁设计已固定，allowlist 依赖端点登记派生 |
| a2_00_security_confirmation | shared | ready | source=交接文件 §1/§2，Sandbox 按 E1–E3 口径、三条技术底线 |

### 2.3 合同升版 a2-sandbox-v1（必改项 2）

`docs/03_api/shopee_tiktok_oauth_callback_contract.md` §1/§1.1/§6：冻结每平台字段清单（authorization_entry、token_exchange/refresh/revoke、regional_host、api_version、minimum_read_scopes、token_ttl、callback_url、app_reference 掩码）、托管字段、回调白名单、网络门禁、TikTok shops 查询与状态规则。全部值保持 pending，以控制台与官方文档原文为准，不填推测值；登记位置为 evidence registry 与 `MARKETPLACE_OAUTH_REAL_CONTRACT`。

### 2.4 真实 adapter 与托管 gateway（必改项 3/4/5/7）

`backend/apps/integrations/oauth_adapters.py` 追加（独立 fail-closed 组件，未接入既有 oauth_services 流程）：

- `RealMarketplaceAdapter` 基类 + `ShopeeAdapter` / `TikTokShopAdapter`：
  - 授权 URL 只使用合同登记的获批入口；任一合同字段缺失抛 `OAUTH_CONTRACT_PENDING`（默认 `MARKETPLACE_OAUTH_REAL_CONTRACT={}`，全部真实路径 fail closed）。
  - callback 校验改为字段白名单（Shopee `state/code/shop_id`；TikTok `state/code`）+ state 一次性消费 + 交换响应门店身份比对 `verify_exchange_identity()`（不一致抛 `OAUTH_IDENTITY_MISMATCH`）。真实回调无签名字段，不沿用 synthetic HMAC callback 签名。
- `RealCustodyGateway`：业务层输入 code、输出引用与掩码；HMAC-SHA256 请求签名只发生在托管侧；`fetch_shop_info()` 承载 TikTok `/authorization/{api_version}/shops` 的 shop_id/shop_cipher/region 查询语义；refresh 轮换引用版本、revoke 托管作废语义，外部成功本地失败进入 reconcile_required 的合同口径已冻结。
- HTTP 传输层有意未接线：requirements 无 requests/httpx，门禁通过后抛 `OAUTH_NETWORK_CLIENT_PENDING`，待托管提供方合同登记 + HTTP 依赖单独立项。

### 2.5 网络门禁双重启用（必改项 6）

- `MARKETPLACE_OAUTH_NETWORK_ENABLED` + `MARKETPLACE_OAUTH_NETWORK_ALLOWLIST`（`backend/config/settings/base.py`，allowlist 由环境变量注入，默认空）。
- `assert_network_egress()`：开关关闭拒绝、host 白名单精确匹配、DNS 解析全部记录必须为全局可路由地址（`ipaddress.is_global`，私网/回环/文档地址段一律拒绝）。
- Production settings 无条件拒绝真实网络；429/5xx 上限退避与认证错误不无限重试写入合同约束。

### 2.6 前端状态映射（必改项 8）

- 新增 `frontend/src/utils/oauthCapability.js`：capability 映射 `mock → sandbox_verified → connected`，fail-closed 晋升（仅后端给出的精确值可晋升；未知/降级值一律回落 mock；`connected` 不得由前端自行晋升）。
- `frontend/src/api/integrations.js`：`asMockStatus` 改为 `asCapabilityStatus`，保留后端已验证的 `api_status`，不再无条件盖章 mock，也绝不在本地盖章 sandbox_verified/connected。
- `frontend/src/views/integrations/MarketplaceOAuth.vue`：页头新增 capability 标签与动态说明文案；loadReferenceData/loadAttempt/startAuthorization/runAction 均从响应 `api_status` 归一化 capability。
- Mock 数据保持 `api_status: 'mock'`：当前无真实联调，按状态规则不标记 sandbox_verified。

### 2.7 其他

- `backend/.gitignore`：`db.sqlite3` → `db.sqlite3*`，防止 DB 备份文件进入 Git。
- dispatch 文档 §9：交接文件覆盖登记。

## 3. 三条技术底线合规

1. 真实密码/Token/Secret/私钥不进 Git/日志：本轮未引入任何真实凭据；evidence registry 仅存掩码并拒绝凭据形状键；凭据扫描（`partner_key/app_secret/access_token/refresh_token` 赋值形态、`sk_live/AKIA/ghp_/私钥块` 等模式）在待提交文件中 0 命中（命中项均为扫描器模式定义与文档命令）。
2. tenant/store 数据不互串：真实 adapter 为独立组件，未触碰既有 scope/fencing 路径；callback 身份比对强制门店一致性。
3. 数据库变更前保留可恢复备份：迁移执行前已备份 `backend/db.sqlite3.pre-a2-sandbox-v1.bak`（本地文件，已被 gitignore 排除）。

## 4. 技术不变量

OAuth attempt/action/operation/resource lease 的 fencing 锁顺序与一次性 state 语义零改动（R1–R6 已验证）；真实 adapter 未接入既有流程，待联调立项时再评估接入方式并留痕。

## 5. 验证结果（2026-08-06）

| 检查 | 结果 |
|---|---|
| `python manage.py check` | PASS；0 issues |
| `makemigrations --check --dry-run` | PASS；no changes detected |
| Local sqlite 后端全量 pytest | PASS；484 passed, 5 skipped（基线 473 + 11 新增 gate 测试） |
| MySQL 8.4 后端全量 pytest（127.0.0.1:3307 容器） | PASS；489 passed（含 5 个 MySQL 双 worker fencing 边界测试，基线 478 + 11 新增） |
| 定向门禁测试 `test_marketplace_real_sandbox_gate.py` | PASS；含 evidence append-only/supersede、合同 fail-closed、回调白名单、身份比对、网络门禁四态、gateway 合同/传输两级 pending |
| 前端 Vitest | PASS；15 files，174 tests passed（基线 168 + 6 新增 capability 测试） |
| 前端 production build | PASS；1959 modules transformed，ExitCode=0 |
| `sandbox.ps1 verify integration` | PASS；`LOCAL_SANDBOX_VERIFY=PASS profile=integration`，ExitCode=0 |
| 凭据扫描 | PASS；待提交变更中无真实 Token/Secret |

未执行项：真实 Sandbox 测试店铺全流程（授权/callback/刷新/过期/撤销）——技术准备项 1–6 中 8/9 为 pending，无获批应用与控制台端点，真实联调在技术上不可行；该项在证据登记完成后执行。

## 6. 状态判定

- 当前状态保持 **synthetic/mock**：技术准备项未就绪（技术事实约束）。
- 前端 capability 映射已支持 `sandbox_verified`，但仅在 Sandbox 联调通过且后端给出该值后展示；`connected` 须经真实请求、权限负向态、字段验证全部通过后由开发A判定。
- 默认动作级别 L1 只读；写平台能力（L3）未启用。

## 7. 后续步骤

1. 控制台确认获批应用与端点 → `register_oauth_evidence()` 登记（仅掩码）→ 登记 `MARKETPLACE_OAUTH_REAL_CONTRACT`。
2. 托管提供方接口合同登记 + HTTP 客户端依赖单独立项（解除 `OAUTH_NETWORK_CLIENT_PENDING`）。
3. Sandbox 测试店铺全流程联调 → 通过后将前端/后端状态标记 `sandbox_verified`。
4. 与 A-MKT-SYNC-01（A-06~A-13）的衔接：先合并 #37/#39/#40 后从 main 开新分支，或在当前分支之上堆叠，届时自决并留痕。
