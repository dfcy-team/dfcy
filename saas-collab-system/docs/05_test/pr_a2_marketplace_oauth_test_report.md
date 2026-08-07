# PR-A2 Shopee / TikTok Shop OAuth 与映射测试报告

- 任务编号：`A-PR2-MARKETPLACE-OAUTH`；分支 `feature/module-a-marketplace-oauth`（stacked 于 A-PR1 `05308bd`）。
- 合同：`docs/03_api/pr_a2_marketplace_oauth_contract.md`；测试计划：`docs/05_test/pr_a2_marketplace_oauth_test_plan.md`。
- 所有测试数据均为 `synthetic`、`demo` 或占位值；未接入真实 Shopee/TikTok Shop，未使用任何真实 Token。

## 1. 测试文件与结果

| 测试文件 | 用例数 | 覆盖内容 |
|---|---|---|
| `tests/test_pr_a2_oauth_shopee.py` | 7 | start 权限/raw/不安全输入拒绝、synthetic 授权 URL、state 只存哈希、callback 成功绑定 active 引用、签名篡改与平台混用拒绝、raw 查询参数拒绝、未知/缺失 state、跨 tenant 绑定冲突 |
| `tests/test_pr_a2_oauth_tiktok.py` | 5 | TikTok callback 成功、auth_code/shop_id/shop_cipher 缺失拒绝、raw 参数拒绝与 state failed、主体冲突 |
| `tests/test_pr_a2_oauth_refresh_revoke.py` | 6 | refresh 双权限门（authorize+rotate）、版本递增 v2、raw 载荷拒绝、revoke 终态与幂等、revoked 后 refresh 冲突、跨 tenant 隐藏 |
| `tests/test_pr_a2_store_mapping.py` | 8 | 写保护（save/update/bulk/delete 全拒绝）、身份只从授权派生、禁止字段/raw 拒绝、跨 tenant 404、停用与受控审计、查询白名单 |
| `tests/test_pr_a2_product_mapping.py` | 10 | 写保护、create 校验（inactive 门店映射/重复变体/跨 tenant actor）、suggest tenant SKU 与 confidence 校验、冲突保留旧值、confirm 必须人工确认且同店 SKU 唯一、deactivate 受控码与 SKU 批量失效、API 分发与跨 tenant 隐藏 |
| `tests/test_pr_a2_oauth_security.py` | 7 | 全端点未认证 401、external/RPA 403、无 data scope 403、空/非法 CUSTOM scope 受控码、九个 raw 凭据字段全量拒绝、callback 会话无关、映射操作不产生业务写入 |

A2 专项合计 43 个用例，全部通过。

## 2. 自动化结果

| 命令/范围 | 结果 |
|---|---|
| 后端全量 pytest | 499 passed / 2 skipped（MySQL-only 并发专项，SQLite 环境跳过） |
| `python manage.py check` | 0 issues |
| `python manage.py makemigrations --check --dry-run` | No changes detected（无漂移） |
| `python scripts/ci_guard.py` | PASS（曾发现 3 处负向测试字面量缺少占位标记，已整改为 `*-test-*` 形式） |
| A-PR1 专项回归（`test_shopee_tiktok_auth_foundation.py`） | 全部通过（含在全量中） |

## 3. 关键安全断言

- state 明文只出现在发起响应中；DB 只存哈希，重放/过期/平台错配/会话错配全部返回受控码。
- callback 不接受任何前端 Token；九个 raw 凭据字段（access_token、refresh_token、secret、api_key、api_secret、credentials、credential_ciphertext、cookie、session）在 start、callback、refresh、revoke、门店映射、商品映射写端点全部拒绝。
- 响应/审计只含 `credential_id`/`token_id` 引用与 `synthetic-*` 掩码，序列化输出不含明文凭据字段。
- 映射身份（platform_store_id/identity_key/region/主体）一律从授权记录派生，前端提交身份字段返回 400。
- `mapped` 只能由 `manually_confirmed=true` 产生；冲突保留旧值进入 `conflict`，不静默覆盖。
- 新模型（OAuthStateSession、MarketplaceStoreMapping、MarketplaceProductMapping）直接 `save()`/`update()`/`bulk_*`/Admin 写入全部被服务层写保护拒绝，物理删除永久禁止。
- 映射全流程（create/suggest/confirm/deactivate）执行后 finance 业务表行数不变。

## 4. 迁移

- `integrations.0010`（oauth_state_session）、`0011`（marketplace_store_mapping）、`0012`（marketplace_product_mapping）均为纯新增表，不改动既有表结构与数据。
- 全局门店唯一与变体唯一约束以 DB 约束 + 服务层预检双保险实现（MySQL 8.4 条件唯一索引限制的等价方案）。

## 5. 未覆盖/另行安排项

- 测试计划第 7 节 Local Sandbox 场景清单与第 8 节 MySQL 8.4 专项，按既有流程在 sandbox/CI 环节另行执行；本 PR 本地验证仅覆盖 SQLite 全量。
- 真实平台沙箱接入为独立审批项，未获批前全部使用 synthetic provider。

## 6. 结论

PR-A2 全部提交（A2-01 至 A2-10）在本地通过全量回归、系统检查、迁移漂移检查与 CI guard。能力状态保持 `pending/mock`，不得解释为真实平台已连接。
