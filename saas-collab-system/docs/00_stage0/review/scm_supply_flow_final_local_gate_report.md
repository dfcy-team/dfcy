# SC-SUPPLY-FLOW 最终本地门禁报告

日期：2026-08-08  
范围：SC-F2-MULTI-1、SC-CONSOLIDATION-1、SC-CONSOLIDATION-ATTACH-1、SC-SHIPMENT-1、SC-SUPPLY-FLOW-API-2、SC-SUPPLY-FLOW-CLIENT-3/4，以及本轮产品迁移漂移收敛。所有验证均为本机临时环境，未连接线上系统，未提交 Git。

## 1. products 漂移与迁移策略

在生成迁移前执行了 `makemigrations products --dry-run --verbosity 3` 并审查 SQL。当前模型与历史迁移的唯一差异是两个 `package_volume` 字段：`ProductSKU`、`ProductLegacyItem` 的 `DecimalField` 由 `decimal_places=3` 变为 `decimal_places=6`，`max_digits=12`、可空和可空白属性不变。`product_name` 已由现有 `0013_productsku_product_name` 对齐，本轮没有再次生成或修改它。

新增 `backend/apps/products/migrations/0014_alter_productlegacyitem_package_volume_and_more.py`，仅包含两个 `AlterField`。SQLite 的 `sqlmigrate` 所显示的临时表重建是 Django 的标准 ALTER 模拟，复制全部既有列后替换原表；迁移本身没有 `RemoveField`、`RenameField` 或数据删除操作。MySQL 侧为列精度元数据调整。没有 fake migration，也没有手工标记迁移状态。

新增 `backend/tests/test_products_migration_gate.py` 检查迁移操作集合、六位小数写入/读取 round-trip 及 `ProductSKU.product_name` 历史字段存在；该测试在正常迁移和 MySQL 门禁中均通过。

## 2. 后端门禁结果

- Django `check`：通过（0 issues）。
- `makemigrations --check --dry-run`：通过，输出 `No changes detected`。
- 全新 SQLite 文件 `backend/sc_supply_flow_final_gate.sqlite3`：从零执行 `manage.py migrate --noinput` 成功，随后 `check`、`migrate --plan` 均无待执行项。
- 全新 MySQL：`mysql:8.4`，镜像 digest `mysql@sha256:c592c15aaf4a1961e15d82eb31ea5987dda862d1c4b1e93424438c0e91dc1f8d`，版本 `8.4.10`，`utf8mb4` / `utf8mb4_0900_ai_ci`，事务隔离级别 `REPEATABLE-READ`。仅绑定 `127.0.0.1:13315`，从零迁移、check、迁移漂移检查和 plan 全部通过。
- 正常迁移的 SQLite 供应链合并套件：86 passed（55.88 s），覆盖 F1/F2 packing、multi、consolidation、attachment、shipment、API2 和本迁移回归。
- 同一 86 项在上述隔离 MySQL 测试库：86 passed（190.31 s）。测试期间出现一次迁移 `ALTER TABLE` 等待 handler commit，最终完成且无失败。
- 另行运行 `--nomigrations` 的 SQLite 诊断得到 72 passed/14 failed；失败均源于跳过数据迁移 seed 后缺少 `PackingStandardVersion` 和标准路由（create 返回 409、standard 返回 404），不是模型或迁移回归，未将该结果冒充门禁通过。

## 3. 客户端门禁结果

- Web `npm exec vitest run tests/supply-flow-client.spec.js`：3 passed。
- Web `npm run build`：通过（Vite 2016 modules transformed）。构建仅有上游 `@vueuse` PURE 注释提示，无构建错误。
- 小程序 `npm test`：29 passed；`npm run validate`：通过（10 pages、32 JavaScript files）。上传/下载仍按 API2 的本地开关和 fail-closed 合同显示，不伪装生产二进制能力。
- `git diff --check`：退出码 0；Git 输出的 LF/CRLF 提示为工作区换行提示，不是 whitespace error。

## 4. 本轮确认的客户端收敛点

Web shipment 状态已统一为后端状态 `draft/loading/customs_declared/dispatched/port_arrived/warehouse_arrived/warehouse_cleared/cancelled`；dispatch 只选择 `transferred` allocation，clear 使用 `warehouse_cleared`。集货 ready 使用 `supply.consolidation.receive`。转入输入明确标注“集货箱分配 ID”和“装箱物理箱 ID”。

供应商 assignment DTO 增加裁剪后的 `accepted_evidence_ids`/`accepted_evidence`（仅 ID 与状态）及 `release_version`，不返回 hash 或业务绑定字段；小程序首次 handover 从 accepted 集合读取，并在缺少 release 版本或 accepted 证据时 fail-closed。

## 5. 清理与残余风险

MySQL 测试库由 pytest teardown 删除；临时容器 `sc-supply-flow-final-mysql8`、其匿名存储、`127.0.0.1:13315` 及 SQLite 临时数据库在报告完成后清理并复核。仅删除本轮生成的明确 `__pycache__` 目录，不触碰源码或其他工作者的修改。

仓库全量前端历史测试仍有与本阶段无关的既有失败（product-coding、ui-p5、ui-p3 旧断言，以及 development competitor 的网络/旧服务超时）；本轮未越权修改这些测试。后端本阶段合并矩阵已在正常迁移 SQLite/MySQL 全部通过。生产对象存储、真实第三方连接、HTTP 二进制上传和下载票据仍按 API2/客户端合同保持关闭，需后续独立波次实现。
