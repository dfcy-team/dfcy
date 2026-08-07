# PR-A2 Shopee / TikTok Shop OAuth 与映射发布说明

- 任务编号：`A-PR2-MARKETPLACE-OAUTH`；分支 `feature/module-a-marketplace-oauth`，stacked 于 A-PR1 `feature/module-a-platform-auth-foundation` @ `05308bd`。PR #37/#39 合并后须 rebase 最新基线并重跑全量用例。
- 合同：`docs/03_api/pr_a2_marketplace_oauth_contract.md`；测试报告：`docs/05_test/pr_a2_marketplace_oauth_test_report.md`；回滚指南：`docs/06_release/pr_a2_marketplace_oauth_rollback_guide.md`。

## 发布内容

- 一次性 OAuth state 服务：明文 state 只在发起响应返回一次，DB 只存哈希，支持过期/重复消费/平台错配/会话错配受控拒绝。
- marketplace OAuth provider 抽象与 synthetic 实现（shopee/tiktok），授权 URL 为 synthetic 域名，callback 走合成签名。
- Shopee / TikTok Shop OAuth 发起与 callback：callback 不接受前端 Token，tenant 一律从已消费 state 恢复；成功创建 `active` 门店授权，只保存 `synthetic-*` 引用与掩码。
- 凭据刷新（authorize+rotate 双权限，引用版本原子递增）与撤销（终态、幂等）端点。
- 门店映射：`MarketplaceStoreMapping` 平台身份全部从授权记录派生，前端不可提交身份字段；复用 `integrations.store.authorize` 权限与 store scope。
- 商品/SKU 映射：`MarketplaceProductMapping` 状态机（unmapped→suggested→mapped；冲突保留旧值；任意→inactive 终态）；`mapped` 必须人工确认；SKU 受控失效批量停用；候选 SKU 仅限当前 tenant。
- 数据范围：`filter_store_mappings`/`filter_product_mappings` 支持 `platforms`/`store_ids` CUSTOM scope。
- 三个新模型均带服务层写保护（直接 save/update/bulk 拒绝、物理删除禁止）与只读 Admin。
- 安全专项测试：全端点 401、用户类型 403、scope 受控码、九个 raw 凭据字段拒绝、callback 会话无关、映射零业务写入。

## 非发布内容

不包含真实平台请求、webhook 业务处理、订单/库存/财务同步写入、真实 Sandbox、Pilot、Production 或 VM 部署；不含前端改动。

## 迁移门禁

1. 新增迁移 `integrations.0010/0011/0012` 全部为纯新增表，不改动既有表；可在全量预检后直接应用。
2. 上线前确认 `makemigrations --check --dry-run` 与 `manage.py check` 通过；本地已验证。
3. MySQL 8.4 条件唯一索引限制以 DB 普通唯一约束 + 服务层预检等价实现；MySQL 专项演练按 CI/sandbox 流程另行记录。
4. 本地 `db.sqlite3*.bak` 备份文件仅用于开发留档，禁止提交与部署。

## 已知限制

- 能力状态保持 `pending/mock`；synthetic provider 不代表真实平台已连接或获准生产使用。
- 本地全量回归基于 SQLite（499 passed / 2 MySQL-only skipped）；MySQL 8.4 与 Local Sandbox 场景清单按既有流程另行执行。
- stacked 分支尚未 rebase 到 #37/#39 合并后的基线，合并前必须重跑全量。
