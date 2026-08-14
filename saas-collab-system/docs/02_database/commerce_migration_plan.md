# Commerce 第一轮迁移计划

## 1. 本轮 migration 图

1. `integrations.0007_rawpayload_syncqualityresult`
   - 依赖 integrations `0006`、masterdata `0002`、tenants `0001`。
   - 为 `SyncJob.resource_type` 增加 `refund_return`，建立 `RawPayload` 与 `SyncQualityResult`。
2. `commerce.0001_initial`
   - 建立七个事实/映射模型的基础字段。
3. `commerce.0002_initial`
   - 依赖 integrations `0007` 以及 masterdata、products、accounts、tenants。
   - 增加跨应用外键、索引和数据库约束。

Django 自动拆成两个 commerce migration，用于解除 `RawPayload.store → masterdata` 与 commerce 事实表引用 integrations 的依赖环。

## 2. 安全执行顺序

1. 记录 Git SHA、`showmigrations`、`migrate --plan` 和实际表结构。
2. 复制 schema 到专用克隆库；生产数据必须脱敏，且不得进入仓库。
3. 在克隆库应用 integrations `0007`、commerce `0001–0002`。
4. 执行模型约束、幂等、跨租户和金额精度测试。
5. 回滚 commerce 到 zero，再回滚 integrations 到 `0006`。
6. 重新正向应用并复测。
7. MySQL 8 重复步骤 3–6，并检查查询索引。

## 3. 回滚边界

- 本轮 migration 只创建新表，不转换或删除现有业务数据。
- 回滚顺序必须先 commerce、后 integrations `0007`，避免外键依赖。
- 禁止在桌面漂移 SQLite 上直接运行，也禁止使用 `--fake`。
- 真实写入启用后，回滚前必须先停止同步任务并导出新表备份；本轮尚未启用写入，因此没有数据回填回滚。

## 4. Marketplace OAuth 汇合计划

当前权威分支没有 `MarketplaceStoreAuthorization`。后续必须先选择权威 OAuth migration 链，再新增独立 migration：

1. 为订单事实增加 nullable 门店授权外键。
2. 通过 `tenant + platform + store` 从现有配置生成可审计映射。
3. 对无法唯一映射的数据停止迁移并产生质量报告，不能猜测。
4. 验证完成后再移除临时 `integration_config` 引用。

该步骤不属于第一轮，不得通过复制桌面 SQLite 表结构替代 Git migration。

## 5. 下一阶段门禁

- 用户确认 ER 图和字段字典。
- Marketplace OAuth migration 权威链明确。
- SQLite/MySQL 正反迁移和全量测试通过。
- 服务账号权限仅覆盖获准事实/staging 表的 SELECT/INSERT/UPDATE，无 DDL 权限。
- 写入服务具备 tenant 校验、幂等键、游标提交顺序和脱敏审计。
