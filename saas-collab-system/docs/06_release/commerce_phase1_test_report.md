# Commerce 第一轮测试报告

## 1. 结论

第一轮模型、迁移、回滚和定向约束验证通过。没有修改当前工作区数据库或桌面开发数据库；所有写入验证发生在 SQLite 克隆和无数据卷临时 MySQL 容器中。

## 2. 环境

- 日期：2026-08-14（Asia/Shanghai）
- Django：5.2.17
- SQLite：Python 3.11 运行时所带 SQLite
- Docker：29.5.3
- MySQL：8.4.11，`utf8mb4_0900_ai_ci`
- 测试数据：全部为合成数据，不含真实店铺、订单、凭据、令牌或 PII

## 3. 已执行验证

| 检查 | 结果 |
|---|---|
| `manage.py check` | PASS，0 issues |
| `makemigrations --check --dry-run` | PASS，No changes detected |
| SQLite commerce 定向测试 | PASS，9/9，58.07s |
| SQLite 克隆迁移计划 | PASS，只包含 integrations `0007` 与 commerce `0001–0002` |
| SQLite 克隆正向迁移 | PASS |
| SQLite commerce/integrations 回滚 | PASS |
| SQLite 回滚后再次正向迁移 | PASS |
| MySQL 8.4.11 全仓正向迁移 | PASS |
| MySQL commerce/integrations 回滚 | PASS |
| MySQL 回滚后再次正向迁移 | PASS |
| MySQL commerce 定向测试 | PASS，9/9，125.78s |
| SQLite 后端全量测试 | PASS，464/464，104.05s |

定向测试覆盖：

- 相同租户/平台/门店/外部订单 ID 不可重复，不同租户可复用平台 ID。
- 跨租户门店关系在 `full_clean()` 阶段拒绝。
- 负金额在模型/数据库约束阶段拒绝。
- 退款订单关联允许为空，一笔退款可包含多个商品行。
- 原始载荷只保存加密对象引用和哈希，不存在原始 payload 字段。
- 原始载荷、质量检查和库存快照具备幂等唯一键。
- `save()`、`objects.create()`、`bulk_create()`、`bulk_update()`、`QuerySet.update()` 以及 Django `_base_manager` 均执行模型校验；表达式更新被禁用。
- 删除 SyncRun 时，Django Collector 可通过受保护的 `_base_manager` 将订单和 RawPayload 的可空引用安全置空。
- 库存 `snapshot_key` 由模型内部生成；不同调用方键不能写入重复快照，`save(update_fields=...)` 和 `bulk_update()` 会同步写入重新计算的派生键。
- 退款保存平台 `source_updated_at_utc`，并索引租户 + 平台更新时间。
- 退款订单、原始载荷、同步运行与事实记录必须满足同租户、同门店、同平台及同业务归属。
- RawPayload、订单、退款和库存会校验 SyncJob 与 RawPayload 资源类型；inventory 不能关联 sales_order SyncRun，订单、退款和库存也不能关联其他业务资源族的 RawPayload。

## 4. 临时资源清理

- SQLite 克隆 `.commerce_review3_clone.sqlite3`：已删除。
- MySQL 容器 `codex-commerce-review3-mysql`：已删除。
- 未创建 Docker 数据卷或保留测试数据库。

## 5. 未完成门禁

- 尚未完成 MarketplaceStoreAuthorization 权威 migration 的选择与外键升级。
- 尚未实现真实数据写入、查询 API、页面替换、后台导出或同步游标推进。
- 当前变更尚未提交或推送；PR #53 的旧 Code Review SHA 不覆盖本轮改动。
