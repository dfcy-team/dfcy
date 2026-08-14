# Commerce 第一轮 Schema 漂移审计

## 1. 审计边界

- 审计日期：2026-08-14（Asia/Shanghai）。
- 权威开发基线：`codex/system-v2.44.6-reviewed-baseline`，提交 `a4818a7c3fb69f5c4b62cded53595e12695bafb2`。
- 当前功能分支：`feature/module-a-sales-management`。
- 数据库检查使用 Node `DatabaseSync(path, { readOnly: true })`，连接后执行 `PRAGMA query_only=ON`。
- 未对两个被审计 SQLite 执行 migration、DDL、INSERT、UPDATE 或 DELETE；未读取或输出业务行、凭据、令牌或 PII。

## 2. 只读核验结果

### 2.1 当前工作区数据库

路径：`saas-collab-system/backend/db.sqlite3`。

- `integrations`：已应用 `0001` 至 `0006`，与当前源码一致。
- `products`：已应用 `0001` 至 `0013`，与当前源码一致。
- `development`：已应用 `0001`、`0002`，`development_productsalessnapshot` 已存在。
- `sales_management`：已应用 `0001`、`0002`，销售管理原型表已存在。
- `integrations_marketplacestoreauthorization` 不存在。
- `integrations_platformintegrationconfig` 仍含当前基线定义的 `credential_ciphertext` 字段。

### 2.2 交接文档所指桌面数据库

路径：`C:/Users/Administrator/Desktop/开发/dfcy/saas-collab-system/backend/saas_collab_local_dev.sqlite3`。

- `integrations`：迁移记录已到 `0017_register_access_evidence_baseline`。
- `products`：迁移记录仅到 `0004`，落后于当前基线的 `0013`。
- 存在 `integrations_marketplacestoreauthorization` 以及引用式凭据字段。
- 不存在 `development_productsalessnapshot`。
- 不存在 `sales_management_salesorder` 及本分支销售表。

## 3. 漂移判定

两套 SQLite 来自不同且不可直接拼接的迁移历史：

| 范围 | 当前源码/工作区 DB | 桌面 DB | 结论 |
|---|---|---|---|
| integrations | `0006` | `0017` | 桌面 DB 超前，且对应 migration 不在当前权威分支 |
| products | `0013` | `0004` | 桌面 DB 落后 |
| development | 销售快照存在 | 不存在 | 结构不一致 |
| sales management | 原型表存在 | 不存在 | 结构不一致 |

禁止对桌面 DB 直接执行当前分支 migration，也禁止伪造、`--fake` 或重写 migration 记录来消除差异。

## 4. 第一轮权威选择

按已确认的开发基线，当前 Git 源码及其 migration 图是本轮唯一权威输入。新建 `commerce` 事实模型，并通过新的 `integrations 0007` 增加原始载荷引用和运行级质量结果。

当前权威分支尚无 `MarketplaceStoreAuthorization` 模型，因此 `commerce_sales_order.integration_config` 暂时引用现有 `PlatformIntegrationConfig`。这只是迁移兼容边界，不代表复制或使用明文凭据。Marketplace OAuth 权威迁移完成重基或合并后，必须以独立 migration 升级为门店授权引用，并重新验证历史数据转换。

## 5. 允许进入下一阶段的前置条件

1. 选定并评审 Marketplace OAuth 的权威 Git migration 链，不能仅以某个 SQLite 的迁移记录为依据。
2. 在脱敏克隆库演练 integrations 历史的汇合方案。
3. 证明 `PlatformIntegrationConfig → MarketplaceStoreAuthorization` 的映射可回滚且不会暴露凭据。
4. MySQL 8 正向、反向迁移和租户隔离测试继续通过。
5. 获得用户对 schema、ER 图和字段字典的明确确认后，才允许设计真实数据写入。
