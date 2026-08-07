# PR-A2 Shopee / TikTok Shop OAuth 与映射测试计划（准备稿）

- 任务编号：`A-PR2-MARKETPLACE-OAUTH`；合同见 `docs/03_api/pr_a2_marketplace_oauth_contract.md`。
- 本文是门禁期准备的测试用例清单；分支已 stacked 于 `feature/module-a-platform-auth-foundation` @ `05308bd`（2026-08-07 获批决策），PR #37/#39 合并后须同步最新基线并重跑全量用例。
- 所有用例只允许 synthetic/mock 引用与 synthetic 门店/商品；任何用例不得要求真实平台、真实 Token 或 `connected` 状态。
- 建议测试文件（与现有命名对齐）：
  - `backend/tests/test_pr_a2_oauth_state.py`
  - `backend/tests/test_pr_a2_marketplace_oauth_shopee.py`
  - `backend/tests/test_pr_a2_marketplace_oauth_tiktok.py`
  - `backend/tests/test_pr_a2_store_product_mapping.py`
  - `backend/tests/test_pr_a2_oauth_security.py`

## 1. OAuth state（A2-02）

- [ ] state 正常创建：返回授权 URL、一次性明文 state、过期时间；DB 只存哈希。
- [ ] state 正常消费：callback 成功后 `status=consumed`、`consumed_at` 落库。
- [ ] state 过期：`expires_at` 后消费返回 `OAUTH_STATE_EXPIRED`。
- [ ] state 重复消费：成功 callback 后重放返回 `OAUTH_STATE_CONSUMED`，不创建第二条授权。
- [ ] 失败后重放：callback 失败置 `failed` 后再次提交同一 state 被拒绝。
- [ ] 平台不匹配：shopee state 提交到 tiktok callback 返回 `OAUTH_PLATFORM_MISMATCH`。
- [ ] tenant 隔离：state 恢复的 tenant 与请求体/查询参数中伪造的 tenant 无关，伪造值被忽略。
- [ ] 用户/会话不匹配：`session_binding` 不一致返回 `OAUTH_SESSION_MISMATCH`。
- [ ] state 被篡改：哈希不存在返回 `OAUTH_STATE_INVALID`。
- [ ] callback 缺少 state：返回 `OAUTH_STATE_INVALID`。
- [ ] redirect_uri 与发起时不一致：返回 `OAUTH_SESSION_MISMATCH`。
- [ ] 并发 callback：两个并发请求消费同一 state，仅一个成功（条件更新原子性）。
- [ ] `OAuthStateService.expire_before` 只修改过期记录状态，不影响 pending/consumed。

## 2. Shopee OAuth（A2-04）

- [ ] 授权 URL 包含 `partner_id`、`redirect`、`state`，redirect_uri 与发起时冻结值一致。
- [ ] callback 签名正确：创建授权记录（pending → active），引用为 `synthetic-shopee-*`。
- [ ] 签名错误：拒绝，state 置 failed，错误码 `OAUTH_CALLBACK_REJECTED`，不落授权。
- [ ] `shop_id` 缺失：拒绝。
- [ ] `merchant_id` 与既有绑定主体冲突：拒绝 `OAUTH_STORE_BOUND_CONFLICT`。
- [ ] 平台门店已被其他 tenant 绑定：返回冲突，DB 唯一约束兜底。
- [ ] Token 引用托管：响应/审计只有 `credential_id`/`token_id`/掩码，无原始值。
- [ ] raw Token 不进入响应、日志、异常文本（断言日志捕获中不出现 token 字符串）。
- [ ] 多门店返回：逐条创建授权，单条失败不阻断其余，失败条目有受控审计。
- [ ] 刷新成功：版本递增、`refreshed_at`/`expires_at` 更新。
- [ ] 刷新版本冲突：并发刷新仅一个成功，另一个 `STATE_CONFLICT`，无覆盖。
- [ ] 撤销成功 + 重复撤销幂等。
- [ ] `revoked` 后刷新/再次 callback 均被拒绝。
- [ ] provider 429、5xx、认证失败 → `normalize_error` 输出受控码，无原始报文泄露。

## 3. TikTok Shop OAuth（A2-05）

- [ ] 授权 URL 包含 `app_key`、`state`、`redirect_uri`。
- [ ] callback 签名正确时成功；签名错误拒绝。
- [ ] `auth_code` 缺失拒绝。
- [ ] `shop_id` 缺失拒绝。
- [ ] `shop_cipher` 缺失或格式非法拒绝（符合 A-PR1 `clean()` 合同）。
- [ ] 平台主体冲突拒绝。
- [ ] 跨 tenant 重复门店绑定返回冲突。
- [ ] Token 引用托管成功，raw Token 不进入响应或日志。
- [ ] 多市场返回：region 缺失条目进入受控隔离，不写半身份记录。
- [ ] 列表响应不含 `shop_cipher`/`merchant_subject_id` 明文主体（仅详情权限内可见）。
- [ ] 刷新、版本冲突、撤销、重复撤销幂等（同 Shopee 对应项）。
- [ ] provider 错误标准化：平台错误脱敏后转内部受控码。

## 4. 门店与 SKU 映射（A2-07/A2-08）

- [ ] 内部门店 tenant 校验：跨 tenant 门店 ID 建映射返回 404/422。
- [ ] `PlatformMaster.platform_type` 与映射平台不一致拒绝。
- [ ] 平台门店唯一约束：同 tenant/platform/platform_store_id 重复映射冲突。
- [ ] 跨 tenant 门店映射详情返回 404。
- [ ] 授权非 `active` 时不能建立 `active` 映射。
- [ ] 停用优先：映射停用置 `inactive`，禁止物理删除。
- [ ] 映射修改审计包含旧值/新值（脱敏），审计不可更新/删除。
- [ ] 同一平台变体在同一门店不能映射多个 active 内部 SKU。
- [ ] 相同 SKU 字符串不跨 tenant 自动匹配（建议结果仅含当前 tenant 候选）。
- [ ] 自动建议仅产生 `suggested`；`mapped` 必须 `manually_confirmed=true`。
- [ ] 冲突记录保留旧值进入 `conflict`，不静默覆盖。
- [ ] `inactive` 映射不参与后续同步选择查询。
- [ ] 内部 SKU 受控失效 → 关联映射 `inactive` + 受控码。
- [ ] 映射操作不触发订单/库存/财务任何写入（断言相关模型无新增行）。

## 5. 权限与安全

- [ ] 未认证用户：所有 A2 接口 401。
- [ ] external 用户、RPA 用户：403。
- [ ] internal 用户缺 exact permission：403（authorize/revoke/rotate/view 逐项）。
- [ ] permission 存在但 data scope 缺失：`DATA_SCOPE_MISSING`。
- [ ] 空、未知、非法 `store_ids` scope：`DATA_SCOPE_INVALID`。
- [ ] 跨 tenant/store 请求返回 404（不泄露存在性）。
- [ ] 请求体提交 `access_token`/`refresh_token`/`secret`/`api_key`/`api_secret`/`credentials`/`credential_ciphertext`/`cookie`/`session` 任一字段：`FORBIDDEN_FIELD`。
- [ ] 请求体携带 `tenant`/操作者字段：拒绝或忽略且审计记录发起主体。
- [ ] 日志、异常、审计、serializer 输出文本断言不含 synthetic 之外的凭据样串。
- [ ] QuerySet `update`/`bulk_update`/Admin/直接 `save()` 不能修改新模型的归属与状态字段（服务层保护测试）。
- [ ] callback 不依赖登录会话：未登录 + 有效 state 可完成；无 state 已登录也拒绝。

## 6. 回归与工程门禁

- [ ] A-PR1 专项测试（`test_shopee_tiktok_auth_foundation.py` 等）全部通过。
- [ ] integrations 既有同步/mock 路由回归通过。
- [ ] 权限目录同步检查通过（无未登记权限、无多余权限）。
- [ ] 后端全量 pytest 通过；`python manage.py check`、`makemigrations --check --dry-run` 无漂移。
- [ ] 前端既有测试与生产构建通过（如 A2 有前端按钮联动）。
- [ ] CI guard 通过；Git 密钥与禁止制品扫描通过。

## 7. Local Sandbox 场景清单

在 `deploy/dev-sandbox` 既有框架内扩展（fixture 仅 synthetic），覆盖：

1. 两个 tenant（沿用现有 sandbox tenant）。
2. 两个平台：shopee、tiktok。
3. 每 tenant 至少两个门店（StoreMaster + PlatformMaster 已有 fixture 扩展）。
4. 正常授权闭环：start → synthetic callback → active → 映射建立。
5. 过期 state 场景。
6. 重复 callback 场景（第二次返回受控冲突）。
7. 跨 tenant 门店冲突场景。
8. Token 刷新并发场景（两请求竞争，仅一个成功）。
9. 撤销与重复撤销幂等场景。
10. 商品映射冲突场景（同变体双 SKU 建议）。
11. 权限与 store scope 正向/负向各至少一条。
12. 迁移演练：全新库 migrate、回滚（drop 新表）、重跑。

synthetic fixtures 建议命名：`synthetic-shopee-store-001/002`、`synthetic-tiktok-store-001/002`、`synthetic-shopee-credential-001`、`synthetic-tiktok-token-001`；商品 `synthetic-product-001`/`synthetic-sku-001`。

平台官方沙箱接入（应用配置、回调域名、出口网络、凭据托管、安全测试审批）为独立审批项，未获批前 Sandbox 场景全部使用 synthetic provider。

## 8. MySQL 8.4 专项

- [ ] 三张新表在 MySQL 8.4 的 migrate 与约束验证（条件唯一约束的等价实现验证）。
- [ ] state 条件更新并发消费在 MySQL 下仅一行成功。
- [ ] `select_for_update` 刷新互斥在 MySQL 下有效。
- [ ] 记录迁移耗时与锁影响（写入 PR 描述 Migration 节）。
