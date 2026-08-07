# PR-A2 Shopee / TikTok Shop OAuth 与门店映射合同（准备稿）

## 0. 文档状态与门禁

- 任务编号：`A-PR2-MARKETPLACE-OAUTH`，覆盖节点 A-04、A-05、A-06。
- 本文是门禁期内允许的合同冻结与设计稿（任务书第 2 节第 1～4 项），**不是正式编码产出**。
- 截至 2026-08-07：PR #37 与 PR #39 暂不合并，获批采用 stacked PR 方式：分支 `feature/module-a-marketplace-oauth` 已创建，基线为 `feature/module-a-platform-auth-foundation` @ `05308bd64436ab2ddb1ff67936d1ed328253dfde`。PR #39/`main` 更新后必须重新同步基线并重验本合同。
- 本文不得作为接入真实平台、真实账号或真实 Token 的依据；能力状态保持 `pending/mock`。

## 1. A-PR1 兼容性红线（不得修改）

以下来自 `apps/integrations` A-PR1 基线的约束在 PR-A2 中只允许扩展、不允许削弱：

1. 不恢复 `APIIntegrationConfig` 的任何明文凭据列；它保持 legacy 兼容模型。
2. `PlatformIntegrationConfig` 仍是唯一连接配置主模型；`MarketplaceStoreAuthorization` 仍是门店授权主模型。
3. 凭据只允许引用式字段：`credential_id`、`token_id`、`credential_mask`、`credential_reference_version`；写入只允许经轮换服务（`authorization_service_write` 上下文）。
4. `MarketplaceStoreAuthorization` 的状态、归属、引用字段只能经服务层修改；`save()`/`update()`/`bulk_*`/`delete()` 绕过保护必须保留。
5. `IntegrationAuditLog` append-only；`masked_detail` 只允许引用 ID、掩码、版本、状态、受控错误码、操作者。
6. 全局身份键算法固定：`SHA-256(lower(platform) + ":" + upper(region) + ":" + platform_store_id)`；`platform + platform_identity_key` 全局唯一。
7. 权限目录固定为 `integrations.store.view/authorize/revoke/sync/retry` 与 `integrations.credential.rotate`。
8. 状态机沿用 A-PR1：`pending/active/expired/revoked/error`，`revoked` 为终态。

A-PR1 已有服务复用关系：

| A-PR1 资产 | PR-A2 用法 |
|---|---|
| `create_store_authorization` | callback 成功后创建授权记录的唯一入口 |
| `transition_store_authorization` | 激活、过期、撤销、错误转换 |
| `rotate_store_authorization_references` | Token 刷新后的引用轮换（含版本保护与旧引用撤销审计） |
| `revoke_synthetic_references` / `_revoke_old_references` | synthetic 撤销适配器；真实撤销适配器需专项审批 |
| `marketplace_identity_key` | 门店映射与 callback 身份校验共用 |

## 2. OAuth 授权会话（OAuthState）

### 2.1 模型增量

新增 `apps/integrations/models.py` 中的 `OAuthStateSession`（命名最终以代码评审为准）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `tenant` | FK Tenant, PROTECT | 发起租户，不允许 callback/前端覆盖 |
| `platform` | Char(30), choices | `shopee` / `tiktok` |
| `initiated_by` | FK User, PROTECT | 发起用户，tenant 必须一致 |
| `store` | FK masterdata.StoreMaster, PROTECT, null | 预绑定内部门店上下文；可空表示先授权后映射 |
| `integration_config` | FK PlatformIntegrationConfig, PROTECT | 发起使用的连接配置，tenant/platform 必须一致 |
| `state_hash` | Char(64), unique | `SHA-256(state 明文)`；数据库不落可重放明文 |
| `redirect_uri` | Char(500) | 发起时冻结的回调地址，callback 必须一致 |
| `requested_scopes` | JSON list | 平台批准的最小 scope 集合 |
| `session_binding` | Char(128) | 发起会话绑定标识（匿名发起 ID/agent 标识的摘要），脱敏存储 |
| `status` | Char(20) | `pending` / `consumed` / `failed` / `expired` |
| `expires_at` | DateTime | 短时有效，建议 10 分钟，配置上限 30 分钟 |
| `consumed_at` | DateTime, null | 一次性消费时间戳 |
| `result_code` | Char(80), blank | 消费结果受控错误码（失败时） |
| `created_at` | auto_now_add | |

约束与索引：

- `UniqueConstraint(fields=["state_hash"], name="uniq_oauth_state_hash")`
- `Index(fields=["tenant", "platform", "status"], name="idx_oauth_state_tenant_status")`
- 消费使用条件更新实现原子一次性：`filter(state_hash=..., status="pending", expires_at__gt=now).update(status="consumed", consumed_at=now)` 返回 0 行即拒绝；禁止先读后写。

### 2.2 服务边界

```text
OAuthStateService.create(*, tenant, platform, actor, integration_config, store, redirect_uri, scopes) -> (state_plaintext, session)
OAuthStateService.consume(*, state_plaintext, platform, callback_context) -> session   # 原子消费，失败抛受控错误
OAuthStateService.expire_before(threshold) -> int                                      # 清理任务用，只改 status
```

规则：

1. 明文 `state` 只在发起响应中返回一次，由前端拼入平台授权 URL；数据库只存哈希。
2. `create` 校验 actor.tenant == tenant、config.tenant/platform 一致、store（如有）归属与平台一致。
3. `consume` 必须比对：平台一致、未过期、未消费、redirect_uri 一致、session_binding 一致（如合同要求）。
4. callback 无论成功或失败都必须消费 state（失败置 `failed` 并记录 `result_code`），之后任何重放返回 `OAUTH_STATE_CONSUMED`。
5. 不允许前端指定 tenant；tenant 一律从已消费 state 恢复。

### 2.3 受控错误码矩阵

| 内部错误码 | 触发条件 | HTTP | 统一 code |
|---|---|---|---|
| `OAUTH_STATE_INVALID` | state 哈希不存在或被篡改 | 400 | `VALIDATION_ERROR` |
| `OAUTH_STATE_EXPIRED` | state 超过 `expires_at` | 400 | `VALIDATION_ERROR` |
| `OAUTH_STATE_CONSUMED` | state 已消费（成功或失败后重放） | 409 | `STATE_CONFLICT` |
| `OAUTH_SESSION_MISMATCH` | session_binding / redirect_uri 不一致 | 400 | `VALIDATION_ERROR` |
| `OAUTH_PLATFORM_MISMATCH` | callback 平台与 state 平台不一致 | 400 | `VALIDATION_ERROR` |
| `OAUTH_CALLBACK_REJECTED` | 平台返回拒绝、签名失败或交换失败 | 409 | `STATE_CONFLICT` |
| `OAUTH_STORE_BOUND_CONFLICT` | 平台门店已被其他 tenant 绑定 | 409 | `STATE_CONFLICT` |
| `OAUTH_PROVIDER_UNAVAILABLE` | synthetic/provider 429、5xx、超时（退避后仍失败） | 502 | `API_SYNC_FAILED` |

错误码常量新增到 `apps/common/error_codes.py` 的注册检查范围；`last_error_code` 与审计沿用大写受控码规则 `[A-Z][A-Z0-9_]{2,79}`。

## 3. Provider 抽象

新增 `apps/integrations/marketplace_providers.py`（命名以评审为准）：

```python
class MarketplaceOAuthProvider:
    platform: str

    def build_authorization_url(self, context): ...
    def validate_callback(self, query_params, context): ...
    def exchange_authorization_code(self, callback_data): ...
    def refresh_authorization(self, authorization): ...
    def revoke_authorization(self, authorization): ...
    def fetch_authorized_stores(self, authorization): ...
    def normalize_error(self, error): ...
```

合同：

1. `exchange_authorization_code` 返回且只返回标准化结果：`credential_id`、`token_id`、`credential_mask`、`reference_version`、`expires_at`、`authorized_scopes`、`platform_subject`、`platform_store_records`、`provider_request_id_mask`。
2. 原始 Token/Secret 不得出现在返回值之外的任何位置：view、serializer、日志、异常、审计、测试快照一律禁止。
3. `normalize_error` 必须把平台错误映射为第 2.3 节受控码；平台原始报文只允许以「字段数量 + 受控标识」形式进入审计。
4. Mock 阶段只注册 synthetic provider：`SyntheticShopeeOAuthProvider`、`SyntheticTikTokOAuthProvider`，只接受/产出 `synthetic-*` 引用（如 `synthetic-shopee-credential-001`、`synthetic-tiktok-token-001`）。真实 HTTP provider 属于专项审批范围，本 PR 不实现、不注册。
5. provider 选择只按 state 的 `platform` 分发，不接受请求体指定。

## 4. Shopee OAuth 合同

### 4.1 发起

- 授权 URL 由 synthetic provider 按 Open Platform v2 参数形状生成：`partner_id`、`redirect`、`state`、（可选）`scope`。精确参数名与域名待获批应用控制台复核，synthetic 实现使用可配置占位基址，不硬编码真实域名。
- 发起接口响应只含：授权 URL、`state`（仅一次）、state 过期时间。

### 4.2 callback 字段与校验

| callback 参数 | 校验 | 失败码 |
|---|---|---|
| `code` | 非空；只用于服务端交换，不落库、不进日志 | `OAUTH_CALLBACK_REJECTED` |
| `state` | 按第 2 节消费 | `OAUTH_STATE_*` |
| `shop_id` | 非空，进入 `platform_store_id` | `OAUTH_CALLBACK_REJECTED` |
| `merchant_id`（交换结果） | 非空，进入 `merchant_subject_id`；与既有绑定的主体冲突时拒绝 | `OAUTH_STORE_BOUND_CONFLICT` |
| HMAC 签名 | 用托管边界内的 app secret 计算（synthetic 用合成密钥），不一致即拒绝 | `OAUTH_CALLBACK_REJECTED` |

多门店返回：交换结果含多个 `shop_id` 时，逐个按 `marketplace_identity_key` 校验并创建/更新授权记录；单条失败不阻断其余条，但整体结果进入受控部分成功审计，错误条目只记录受控码。

### 4.3 业务规则

- 重复 callback：state 已消费 → `OAUTH_STATE_CONSUMED`，不创建第二条授权。
- 已 `revoked` 授权不得被普通 callback 静默恢复；必须新建授权流程（A-PR1 状态机已保证 `revoked` 终态）。
- 同一 `platform_identity_key` 已存在且 tenant 不同 → `OAUTH_STORE_BOUND_CONFLICT`（对应 DB 约束 `uniq_market_store_global_identity`）。
- 成功后：`create_store_authorization`（pending）→ 交换引用写入 → `transition` 到 `active`，审计 `authorize`、`activate`。

## 5. TikTok Shop OAuth 合同

### 5.1 发起

- 参数形状：`app_key`、`state`、`redirect_uri`（与平台登记一致）。版本基线参考 `202309` 授权文档，逐资源冻结。

### 5.2 callback 字段与校验

| callback 参数 | 校验 | 失败码 |
|---|---|---|
| `auth_code` | 非空；只用于服务端交换 | `OAUTH_CALLBACK_REJECTED` |
| `state` | 按第 2 节消费 | `OAUTH_STATE_*` |
| 签名（HMAC-SHA256） | 按平台签名合同校验 | `OAUTH_CALLBACK_REJECTED` |
| 交换结果 `shop_id` | 非空 → `platform_store_id` | `OAUTH_CALLBACK_REJECTED` |
| 交换结果 `shop_cipher` | 非空、格式受控 → `shop_cipher`（仅路由标识，不是凭据） | `OAUTH_CALLBACK_REJECTED` |
| 商家主体 ID | 非空 → `merchant_subject_id`；冲突拒绝 | `OAUTH_STORE_BOUND_CONFLICT` |

多市场/多门店：按 `region + shop_id` 逐个生成 `platform_identity_key`；region 缺失的条目进入 `error` 受控隔离，不写入半身份记录。

### 5.3 业务规则

- TikTok 主体信息（`merchant_subject_id`、`shop_cipher`）不得出现在非必要 API 响应；列表接口默认不返回 `shop_cipher`。
- 轮换与撤销沿用 A-PR1 引用版本规则（版本必须递增、旧引用撤销失败则整体不提交）。
- 平台错误内容先脱敏（只保留错误码类别与受控标识）再转内部错误码。

## 6. Token 刷新与撤销合同

### 6.1 刷新

1. 入口权限：门店操作权限 + `integrations.credential.rotate`；actor.tenant 校验。
2. `select_for_update` 行锁内执行（A-PR1 `rotate_store_authorization_references` 已实现）；同一授权并发刷新只有一个提交成功，其余得 `VERSION_CONFLICT`/`STATE_CONFLICT`。
3. provider `refresh_authorization` 返回标准化新引用；`reference_version` 必须严格递增。
4. 旧引用撤销失败 → 不写入新引用、保留当前有效引用、审计 `rotate_reference(failed)`、抛 `STATE_CONFLICT`。
5. 成功后更新字段：`credential_id`、`token_id`、`credential_mask`、`credential_reference_version`、`expires_at`、`refreshed_at`、状态（`active` 保持）。
6. 认证类失败不无限重试：synthetic 阶段失败即返回受控码，重试次数上限沿用 `SyncJob.max_retry_count` 的默认策略，不新增无限重试路径。

### 6.2 撤销

1. 权限：`integrations.store.revoke` + store scope。
2. 流程：provider `revoke_authorization`（synthetic 撤销引用）→ `transition` 到 `revoked`（`revoked_at=now`）→ 审计 `revoke`。
3. 幂等：对已 `revoked` 记录再次撤销返回成功语义的幂等响应（不重复写引用撤销，只追加一条幂等审计）。
4. 撤销失败：保留原状态或进入 `error`（受控码），禁止删除/覆盖审计证据；失败后不得继续刷新或同步。
5. `revoked` 后所有 refresh/sync 入口返回 `STATE_CONFLICT`。

## 7. 平台门店映射（MarketplaceStoreMapping）

### 7.1 模型增量

复用 `masterdata.StoreMaster`，不新建内部门店主数据。新增 `MarketplaceStoreMapping`：

| 字段 | 说明 |
|---|---|
| `tenant` / `platform` / `store`（StoreMaster） | 归属三元组 |
| `authorization` FK MarketplaceStoreAuthorization | 关联授权；active 映射必须关联有效授权 |
| `platform_store_id` / `platform_identity_key` / `platform_subject_id` | 平台身份，identity key 算法同 A-PR1 |
| `region` / `timezone` / `currency` | 区域元数据；currency 大写 ISO 4217 |
| `status` | `active` / `inactive`（停用优先于删除） |
| `mapping_source` | `oauth_callback` / `manual` / `synthetic_fixture` |
| `mapped_by` / `mapped_at` / `last_verified_at` | 操作者与验证时间 |

约束：

- `UniqueConstraint(fields=["tenant", "platform", "platform_store_id"], name="uniq_store_mapping_tenant_platform_store")`
- 跨 tenant 的平台门店唯一性由授权表 `uniq_market_store_global_identity` 保证；映射创建前必须校验 authorization 的 identity key 一致。

### 7.2 规则

1. 内部门店必须属于当前 tenant 且 `PlatformMaster.platform_type` 与映射平台一致。
2. 授权状态非 `active` 时不得建立 `active` 映射。
3. 停用走 `status=inactive`，不得物理删除；历史可追溯。
4. 跨 tenant/store 详情统一 404（`get_scoped_object_or_404`）。
5. 修改映射记录旧值/新值脱敏审计（新增审计动作 `store_mapping_update`，沿用 `IntegrationAuditLog`）。
6. 请求体不得携带 tenant/操作者字段；serializer 显式拒绝。

## 8. 平台商品与 SKU 映射（MarketplaceProductMapping）

### 8.1 模型增量

| 字段 | 说明 |
|---|---|
| `tenant` / `platform` / `store_mapping` FK | 上下文三元组，禁止脱离 store 上下文 |
| `platform_product_id` / `platform_variant_id` / `platform_sku` | 平台侧标识 |
| `product` FK products.ProductSPU, null | 内部 SPU |
| `sku` FK products.ProductSKU, null | 内部 SKU；`unmapped` 时为空 |
| `status` | `unmapped` / `suggested` / `mapped` / `conflict` / `inactive` |
| `mapping_source` | `synthetic_discovery` / `manual` / `suggested` |
| `confidence` PositiveSmallInt, null | 建议置信度（0-100）；`suggested` 必填 |
| `manually_confirmed` Boolean | 人工确认标志；自动建议不得直接置 true |
| `first_seen_at` / `last_verified_at` / `created_by` / `updated_by` | 审计字段 |

约束：

- `UniqueConstraint(fields=["store_mapping", "platform_variant_id"], name="uniq_product_mapping_variant")`
- 条件唯一：同一 `store_mapping + platform_variant_id` 下 `status=mapped` 且非空 `sku` 只能一条（以约束或事务校验实现，MySQL 8.4 不支持函数条件唯一索引时用 `platform_variant_id + sku` 组合约束 + 服务层校验）。
- `sku` 归属校验：`sku.product` 所属 tenant 必须等于映射 tenant；禁止仅按 SKU 字符串跨 tenant 匹配。

### 8.2 规则与状态

```text
unmapped -> suggested -> mapped
suggested -> conflict
mapped -> conflict          # 冲突不静默覆盖，保留记录待人工处理
任意 -> inactive            # 停用，不参与后续同步选择
```

1. 自动建议（synthetic discovery）只能产生 `suggested`，`mapped` 必须携带 `manually_confirmed=true` 的人工确认。
2. 冲突记录保留旧映射值并进入 `conflict`，由人工接口处理；不得静默覆盖。
3. 映射写入不触发任何订单/库存/财务同步。
4. 内部 SKU 删除（受控失效）时将关联映射置 `inactive` 并记录受控码，不物理删除映射。
5. 候选建议查询只返回当前 tenant 的 SKU；跨 tenant 候选一律过滤。
6. 本 PR 的 synthetic 平台商品发现接口只返回 fixtures 中的合成商品；真实商品批量同步拆入 PR-A3。

## 9. API 清单与权限矩阵

路由挂载于现有 `urls_internal.py`（前缀 `/api/internal/integrations/`）；callback 是否走 internal 前缀以路由与平台回调合同评审为准，但身份只依赖一次性 state，不依赖登录会话。

| 方法与路径 | 权限 | 说明 |
|---|---|---|
| `POST store-authorizations/oauth/start/` | `integrations.store.authorize` + store scope | 创建 state，返回授权 URL |
| `GET store-authorizations/oauth/callback/shopee/` | 无登录态要求；凭已验证 state 恢复主体 | 消费 state、交换、建授权 |
| `GET store-authorizations/oauth/callback/tiktok/` | 同上 | 同上 |
| `POST store-authorizations/{id}/refresh/` | 门店操作权限 + `integrations.credential.rotate` | Token 引用刷新 |
| `POST store-authorizations/{id}/revoke/` | `integrations.store.revoke` | 撤销授权 |
| `GET store-authorizations/`、`GET store-authorizations/{id}/` | `integrations.store.view` | A-PR1 已有，保持只读 |
| `GET/POST store-mappings/`、`GET/PATCH store-mappings/{id}/` | `integrations.store.view`（读）/ `integrations.store.authorize`（写） | 门店映射 |
| `GET/POST product-mappings/`、`GET/PATCH product-mappings/{id}/` | `integrations.store.view`（读）；写入权限需合同评审决定（建议复用 `integrations.store.authorize`，不新增过宽权限） | 商品/SKU 映射 |

硬性拒绝项：

- serializer 显式拒绝字段：`access_token`、`refresh_token`、`secret`、`api_key`、`api_secret`、`credentials`、`credential_ciphertext`、`cookie`、`session`（返回 `FORBIDDEN_FIELD`）。
- 缺失、空、未知或非法 scope 拒绝（沿用 A-PR1 data_scope 规则）。
- 本 PR 不新增销售、库存、finance、RPA API；`integrations.store.sync`/`retry` 仅预留权限定义。

## 10. 凭据与日志红线（与任务书第 10 节一致）

1. 真实 Token/Secret/Cookie/Session/私钥不落库、不进日志、异常、审计、响应、测试快照、fixture。
2. callback 不接受前端提交 Token；交换只发生在 provider 服务端边界内。
3. 审计只存引用 ID、掩码、版本、状态、受控错误码、操作者。
4. Mock/CI/单测只用 `synthetic-*` 引用。
5. 测试失败输出不得包含完整 callback query 或 provider 原始响应。
6. 未经审批不连接真实 Shopee/TikTok Shop 应用；能力状态保持 `pending/mock`。

## 11. 安全威胁检查表

| 威胁 | 缓解 |
|---|---|
| CSRF/state 伪造 | state 哈希存储、绑定 tenant/user/platform/session、短时一次性 |
| callback 重放 | 条件更新原子消费；成功/失败后均不可再消费 |
| 授权码拦截 | 交换在服务端完成，code 不落库不进日志；redirect_uri 冻结比对 |
| 跨 tenant 门店抢占 | `platform_identity_key` 全局唯一约束 + 服务层冲突码 |
| Token 泄露 | 引用式托管、serializer 禁用字段、日志脱敏、Git 扫描 |
| 并发刷新覆盖 | `select_for_update` + 版本递增校验 |
| 撤销失败误覆盖 | 旧引用撤销失败即回滚，不写新引用 |
| Admin/bulk 绕过 | A-PR1 QuerySet/save 保护层扩展到新模型（映射模型的状态字段同样禁止普通写入路径修改归属字段） |
| 状态绕过 | 状态转换只经服务层；`revoked` 终态 |

## 12. 迁移要求摘要

1. 仅新增本文定义的三张表（OAuth state、store mapping、product mapping）与索引；不改动 A-PR1 表结构，不恢复旧明文凭据列。
2. 数据迁移无（全新表）；若正式基线含未知遗留映射数据，先全量只读预检，未知即整体阻断。
3. MySQL 8.4 同版本验证 `migrate` 与 `makemigrations --check --dry-run` 无漂移。
4. 回滚只需 drop 新表；不得声称可恢复已撤销引用。
