# SC-SUPPLY-FLOW-UAT-2-1 本地短期凭据开发报告

日期：2026-08-09  
范围：仅本机 `SC-UAT-DATA-V1` 短期账号凭据工具、到期认证拦截、定向测试；未连接线上系统、远程数据库、正式 WeChat 或对象存储，未提交 Git。

## 1. 实现结果

本轮为 `CustomUser` 增加四个可空/无秘密租约字段，并新增迁移 `accounts/0004_customuser_uat_credential_lease.py`：

- `uat_credential_activated_at`、`uat_credential_expires_at`：租约起止时间；
- `uat_credential_batch_digest`：激活批次 SHA-256 摘要，不含口令；
- `uat_credential_status`：`never`、`active`、`revoked` 等状态。

新增 `apps.accounts.credential_auth` 与 `UATAwareJWTAuthentication`。本地 UAT 用户必须同时满足 `SC-UAT-` 用户名/租户标识、active 状态、有效时间、批次摘要和 `active` 状态；租约过期、撤销或未激活时，登录、refresh、已有 access token 和小程序 token 均 fail-closed。普通非 UAT 用户（字段为空）保持原有行为。内部 refresh 路由改用到期感知 serializer；`base.py` 仅将默认 JWT authentication 替换为自有类。

新增 `apps.purchasing.uat_credentials` 及 management command `uat_credentials`，提供 `activate`、`revoke`、`status`：

- 固定白名单、租户 marker、角色/权限/DataScope、supplier binding 逐项预检；拒绝非 UAT、跨租户、非白名单、inactive、superuser、staff、RPA 和不一致角色绑定；
- 默认 dry-run；写操作必须显式 `--apply`，激活还必须使用交互式 TTY；时长严格 `>0` 且不超过 8 小时；同一有效租约重复激活不会续期，必须先 revoke；
- 使用 `secrets.token_urlsafe` 生成随机口令，调用 Django 密码校验。口令仅在内存中传给一次性终端 sink，不进入返回 JSON、异常、日志、数据库字段或测试输出；命令不接受口令参数/环境变量，`activate --apply --json` 直接拒绝；
- 激活/撤销采用事务和行锁，任意批次失败整体回滚；sink 失败也回滚。数据库只保留无秘密时间、批次摘要和状态元数据，返回值为 JSON-native ISO 时间字符串；
- 撤销只更新精确选择的 UAT 用户并设为不可用口令，不影响普通租户账号；status 只读。
- 新增受控 `supplier_web` 登录/refresh：仅 active external 用户、active tenant、唯一且同租户 `ExternalUserProfile`、active `SupplierMaster` 可登录；token 固定携带 `channel=supplier_web`、`tenant_id`、`supplier_id`，refresh 与 access 每次重读当前 binding 和 lease。supplier A/B/C 因此可在本地工具中激活并通过该专用端点进行 UAT；通用 external placeholder 仍保持关闭。
- 自有 JWT authentication 对 `supplier_web` token 执行路径门禁，仅允许 `/api/external/supplier/`（以及必要的 external auth 前缀），拒绝 internal、miniapp 和其他路径；API2 原有 user type/channel/binding 校验继续生效。

## 2. 修改文件

- `backend/apps/accounts/models.py`
- `backend/apps/accounts/migrations/0004_customuser_uat_credential_lease.py`
- `backend/apps/accounts/credential_auth.py`
- `backend/apps/accounts/external_auth.py`
- `backend/apps/accounts/authentication.py`
- `backend/apps/accounts/serializers.py`
- `backend/apps/accounts/views.py`
- `backend/apps/accounts/urls_internal.py`
- `backend/apps/accounts/miniapp_auth.py`
- `backend/apps/accounts/urls_external.py`
- `backend/config/settings/base.py`（仅默认认证类引用）
- `backend/apps/purchasing/uat_credentials.py`
- `backend/apps/purchasing/management/commands/uat_credentials.py`
- `backend/tests/test_sc_supply_flow_uat_2_1_credentials.py`

## 3. 验证记录

以下命令均在本机 SQLite 内存测试库执行（`DJANGO_SETTINGS_MODULE=config.settings.dev`、`DB_ENGINE=django.db.backends.sqlite3`、`DB_NAME=:memory:`、显式 `DB_ALLOW_INMEMORY_TEST=1`）：

| 检查 | 结果 |
| --- | --- |
| `pytest tests/test_sc_supply_flow_uat_2_1_credentials.py -q --nomigrations` | **PASS：12 passed** |
| UAT-1：`pytest tests/test_sc_supply_flow_uat_1_local.py -q --nomigrations` | **PASS：8 passed** |
| auth + miniapp + API2：`pytest tests/test_auth_api.py tests/test_miniapp_auth_api.py tests/test_sc_supply_flow_api_2.py -q --nomigrations` | **PASS：22 passed** |
| `manage.py check` | **PASS：no issues** |
| 迁移图断言（0004 依赖 0002、仅四个 AddField） | **PASS** |
| `manage.py makemigrations accounts --check --dry-run` | **BLOCKED：当前 dirty 工作区并行存在 accounts/0003 与 0004 两个 leaf；不改写并行 0003，留待主代理在干净提交图复核** |
| 受限模块 `py_compile` | **PASS** |
| `git diff --check` | **PASS（exit 0；Git 仅报告既有换行格式提示）** |

定向测试覆盖：默认 dry-run 无秘密、随机口令和一次性激活、重复激活不延长、双账号批次 sink 失败全回滚、staff/superuser/RPA/inactive/非 UAT 拒绝、supplier_web 登录/refresh/claims/binding、supplier 租约过期时 login/refresh/access 拒绝、internal/RPA/miniapp 通道互斥、普通 external 空租约字段兼容、迁移独立依赖、精确撤销与普通账号隔离、8 小时上限及 JSON 不泄露口令。

## 4. 边界与残余风险

- 本轮只完成本地工具和受控 supplier_web 认证，不执行真实人工 UAT，不启动服务，不生成可直接登录的长期凭据；人工短期凭据激活与终端保管仍属于下一独立步骤。通用 external 登录及外部身份提供商仍未实现。
- 没有实现浏览器密码修改、生产密钥托管、外部身份提供商或真实文件交付。TTY sink 故意不落盘；交付端仍需由人工遵守一次性显示和清理要求。
- UAT 迁移仅依赖已提交的 `accounts/0002_miniappidentity`，只新增四个 CustomUser 租约字段，不依赖并行的 `0003_user_full_name_and_profile_departments`；当前 dirty 工作区因此出现双 leaf，主代理需在精确提交/干净迁移图中复核，不应通过 fake/merge 或改写 0003 掩盖。全仓历史 products 迁移漂移不在本轮范围，未越权修复。
- 本轮未运行隔离 MySQL 门禁；UAT 工具复用 UAT-1 的本地设置/数据库/loopback 校验，生产、pilot、sandbox、远程数据库会在命令入口被拒绝。
