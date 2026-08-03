# 开发A Shopee / TikTok Shop 授权基础变更日志

## 1. 基线与范围

- 任务：`A-01～A-03 / PR-A1-PLATFORM-AUTH-FOUNDATION`
- 风险：L3
- 分支：`feature/module-a-platform-auth-foundation`
- 上游基线：`bdad2fed25b3897f3f6aeae67d18d5f7239ca4a1`
- A-01 合同先行提交：`0d592aa A-01 freeze Shopee TikTok auth contract`
- 开始时 PR #37 仍为 Open Draft，因此本分支按 stacked PR 规则基于 `bdad2fe` 创建。
- 未找到单独的 `developer_a_shopee_tiktok_store_sync_task.md`；本次以用户提供的完整 PR-A1 执行文本及仓库现有合同为准。

## 2. A-01 合同冻结

- 新增 `shopee_tiktok_store_auth_contract.md` 和 `shopee_tiktok_api_alignment_matrix.md`。
- 官方文档核对日期为 `2026-08-03`。Shopee 冻结 Open Platform v2 边界；TikTok Shop 冻结 OAuth v2、端点日期版本、US/ROW、shop entity、动态限流和错误处理边界。
- 官方控制台才能核实的 scope key 不作猜测；内部最小逻辑 scope 冻结为 `shop.read/order.read/product.read/inventory.read`，正式映射留待 A-04。
- 生产区域允许列表为空。authorize/callback/refresh/revoke/sync/retry 和真实 reference rotate handler 全部为 `pending`。

## 3. A-02 门店授权模型

- 新增 `MarketplaceStoreAuthorization`，复用 `PlatformIntegrationConfig` 和 `StoreMaster`。
- 字段覆盖 tenant、platform、内部 store、平台门店身份、merchant subject、TikTok `shop_cipher`、credential/token reference、mask、版本、状态、scope、授权/过期/刷新/撤销时间、脱敏错误码和创建/更新人。
- 状态固定为 `pending/active/expired/revoked/error`。
- 全局身份键按合同规范化后哈希，`platform + platform_identity_key` 跨 tenant 唯一；内部 store 同平台授权也唯一。
- tenant、StoreMaster 平台类型、连接配置平台和区域执行一致性校验。
- 新建、状态、身份和引用字段只允许服务层写入；直接 save、QuerySet update、bulk create/update 和 delete 均受阻。
- `IntegrationAuditLog` 复用为门店授权审计，改为追加写，并把 tenant/config 外键改为 PROTECT，避免父记录删除绕过不可变审计。

## 4. A-03 凭据边界

- 配置 API 不再接受 `credentials/access_token/refresh_token/credential_ciphertext` 等原始字段。
- 旧 `/configs/{id}/rotate/` 保留原权限与路径，但明确返回校验错误；没有把它静默改成新 action。
- 新 reference Mock 服务只接受 `mock-credential-*` 和 `mock-token-*`，使用事务、`select_for_update()`、版本递增和脱敏审计。
- `PlatformIntegrationConfig` 新增外部引用迁移目标字段，但普通模型/API 写入被阻止。
- `integrations.0007` 在检测到历史非空 `credential_ciphertext` 时立即阻止迁移，不读取、打印、清空或丢弃原值。
- 条件性修改 `accounts/system_views.py`：安全运维查询改为只显示 alias、mask、reference version 和状态，不返回 credential/token reference ID；合同标识改为 `external_reference_metadata_only`。

## 5. 权限与 scope

新增并迁移六个 exact permission：

- `integrations.store.view`
- `integrations.store.authorize`
- `integrations.store.revoke`
- `integrations.store.sync`
- `integrations.store.retry`
- `integrations.credential.rotate`

新权限不继承 `tech_admin/integration_admin/admin` 的旧角色兜底，必须显式授予。门店资源只接受 `platforms + store_ids`；缺失、空、未知、非法和越权 scope 均拒绝，列表/详情按 tenant 与 scope 过滤，详情越权返回 404。旧 `integrations.view/manage/rotate/run` 仍用于旧配置和 Mock sync。

## 6. API 与状态

- 新增只读 `GET /api/internal/integrations/store-authorizations/` 与 `GET .../{id}/`，统一响应和分页。
- 两个只读路径用于模型/scope 基础验证，状态仍为 `pending`。
- synthetic service 状态为 `mock`；Mock 记录出现 `active` 不代表真实平台已连接。
- 本 PR 没有任何 `connected` 新增项，没有 OAuth handler、平台 SDK、真实 HTTP、订单/库存导入或生产网络配置。

## 7. 验证结果

| 检查 | 结果 | 摘要 |
|---|---|---|
| 系统 Python 首次 check | BLOCKED | 系统 Python 缺少 Django；随后使用仓库 `.venv` |
| `manage.py check` | PASS | 0 issues |
| `makemigrations --check --dry-run` | PASS | No changes detected |
| 全新内存库 `migrate --noinput` | PASS | integrations 0007、permissions 0015 均成功 |
| `sync_permissions --check` | PASS | catalog complete |
| 新增专项 pytest | PASS | 15 passed |
| integrations/sync/UI-P2 回归 | PASS | 51 passed（后续全量再次覆盖） |
| 后端全量 pytest | PASS | 427 passed |
| `pip check` | PASS | No broken requirements |
| `npm ci` | PASS_WITH_OBSERVATION | 安装成功；存在弃用提示，audit 另见安全项 |
| 前端测试 | PASS | 12 files / 160 tests passed，单 worker |
| 前端 build | PASS_WITH_OBSERVATION | 构建成功，无 chunk-size warning；Rollup 移除依赖内无法解释的 PURE 注释 |
| Sandbox contract integration | PASS | fixtures、RC 正反例和安全锁通过 |
| Sandbox verify integration | BLOCKED | Docker Desktop Linux engine 未运行，无法取得 `python:3.12-alpine`；未伪造 PASS |
| `git diff --check` | PASS | 无 whitespace error |

## 8. 安全扫描与产物

- 私钥、GitHub token、OpenAI key、AWS key、Slack token 模式：0 命中。
- integrations 新代码真实平台 HTTP client/host：0 命中。
- `npm audit`：完整树 2 个 high（`brace-expansion`、`postcss`）；`--omit=dev` 为 1 个 high（`postcss`）。它们来自既有前端锁文件，本任务禁止修改 frontend，需独立依赖升级处理。
- `pip-audit` 与 `gitleaks` 在本机不可用；已执行 `pip check` 和受控模式扫描。
- `dist/node_modules/.pytest_cache/db.sqlite3/.env.local` 均被忽略，运行产物跟踪数为 0。
- 未提交真实账号、店铺、订单、库存、Token、Cookie、Session、API Secret 或平台配置。

## 9. 复审与后续

- 架构/安全人员需复审全局身份键、PROTECT 审计、迁移阻断策略、六个 exact permission 和 store scope。
- 部署前必须先对所有历史非空 ciphertext 完成外部密钥系统迁移；否则 0007 应保持阻断。
- Docker Desktop 启动后重跑 `sandbox.ps1 verify integration`。
- npm 高危依赖需在允许修改 frontend 的独立 PR 中关闭。
- A-04/A-05 完成批准平台 sandbox、JWT、失败态和字段验证前，所有平台能力继续保持 `pending/mock`。
