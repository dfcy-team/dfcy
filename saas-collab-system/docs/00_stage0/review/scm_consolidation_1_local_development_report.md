# SC-CONSOLIDATION-1 本地开发与 MySQL 门禁报告

## 结论

本轮已完成集货（loose-cargo consolidation）领域底座的本地实现，并在 SQLite 与隔离的本地 MySQL 8.4 上完成定向验证。模型、受控领域服务、追加式事件账本、幂等键约束、租户/路线/完成批次校验及 ORM 绕过防护已落盘。MySQL 全新业务库从零执行项目迁移成功；针对同箱独占、幂等重放和模型写入闸门的两项 MySQL 定向测试成功。

本轮明确未实现供应商交接凭证、附件上传、shipment transfer、外部集货 API/路由、Web/miniapp，以及下游散货集货具体 API。这些边界按合同留待后续阶段，不以本报告的本地通过结果替代。

## 修改范围

- `backend/apps/consolidation/`：新增 `apps.py`、`models.py`、`services.py` 及 `migrations/0001_initial.py`。
  - `ConsolidationSite`：租户内站点编码唯一，支持创建、更新、停用及有效期/版本控制。
  - `LooseCargoConsolidation`：草稿、已发布、收货中、待发运、取消等状态；发布时冻结站点和箱分配快照。
  - `ConsolidationBoxAllocation`：完整箱分配、收货、异常、受控释放等状态；同集货单同箱唯一，并复用 packing 的 consolidation 消费槽。
  - `ConsolidationEvent`：追加式事件、租户全局幂等键、请求哈希和审计快照。
  - QuerySet/模型层禁止 `update`、`bulk_update`、`bulk_create`、`delete` 等绕过领域服务的写入。
- `backend/config/settings/base.py`：注册 `apps.consolidation`。
- `backend/apps/permissions/migrations/0025_seed_consolidation_permissions.py`：按合同写入 11 个集货权限标识；本阶段不改既有角色命名逻辑，也未注册 API。
- `backend/tests/test_sc_consolidation_1_local.py`：SQLite 领域生命周期、批量分配回滚、异常/取消、发布快照、ORM 闸门和幂等冲突测试。
- `backend/tests/test_sc_consolidation_1_mysql.py`：MySQL 同箱唯一消费槽和模型写入/事件幂等测试。

## 迁移策略

`consolidation.0001_initial` 依赖现有 `packing.0006_packingboxconsumptionaction`，只新增集货表、索引和检查/唯一约束，不回填或改写历史 packing 数据。站点和发布快照在受控服务中写入，事件账本保留 before/after、原因、操作者和派生子键。权限迁移 `0025_seed_consolidation_permissions` 依赖现有权限种子迁移并使用幂等 `get_or_create` 语义。

迁移检查命令：

```text
DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: python manage.py check
DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: python manage.py makemigrations --check --dry-run --noinput
```

结果：`System check identified no issues`、`No changes detected`。

## SQLite 定向结果

使用项目虚拟环境、内存 SQLite 和无迁移模式运行：

```text
.venv\Scripts\python.exe -m pytest tests/test_sc_consolidation_1_local.py tests/test_sc_consolidation_1_mysql.py -q --create-db --nomigrations
```

结果：`5 passed, 2 skipped`。两个 skip 是 MySQL-only 测试在 SQLite 连接上的预期行为。覆盖点包括：

1. 发布冻结站点/分配快照，内部 receive/ready 不增加 shipped；
2. 多箱分配遇到无效箱时整批回滚且不遗留 packing active consumption；
3. 取消仅接受仍处于 allocated 的箱并释放消费，重复取消按原幂等键重放；
4. 异常箱可走受控释放后 ready，收货后禁止取消；
5. 模型、QuerySet 直写被阻断，重复幂等键同主体可重放、不同请求产生确定性冲突。

## 隔离 MySQL 8.4 门禁

门禁使用一次性容器 `sc-consolidation-mysql8`，镜像 `mysql:8.4`（本机 digest：`sha256:c592c15aaf4a1961e15d82eb31ea5987dda862d1c4b1e93424438c0e91dc1f8d`），仅绑定 `127.0.0.1:13309`。使用临时数据库和专用本地账号；报告不记录密码。启动时观测：MySQL `8.4.10`、字符集 `utf8mb4`、排序规则 `utf8mb4_0900_ai_ci`、事务隔离级别 `REPEATABLE-READ`。

在全新业务库上执行：

```text
DB_ENGINE=django.db.backends.mysql DB_HOST=127.0.0.1 DB_PORT=13309 \
DB_NAME=sc_consolidation_mysql DB_USER=<local-only> DB_PASSWORD=<redacted> \
.venv\Scripts\python.exe manage.py migrate --noinput
```

结果：项目迁移从零完成，包括 `consolidation.0001` 和权限 `0025`。随后以同一隔离实例运行：

```text
.venv\Scripts\python.exe -m pytest tests/test_sc_consolidation_1_local.py -q --create-db --nomigrations
.venv\Scripts\python.exe -m pytest tests/test_sc_consolidation_1_mysql.py -q --create-db --nomigrations
```

结果分别为 `5 passed`（既有本地服务矩阵，约 97.78 秒）和 `2 passed in 94.39s`。MySQL 新增测试实际验证：

- 两个集货单竞争同一完成箱时最多一个 active consolidation consumption；失败方不产生分配；
- 同箱分配幂等键可重放；模型 QuerySet 绕过写入被拒绝；事件键按租户全局唯一，重复请求返回原事件。

测试结束后已显式删除临时数据库，停止并移除 `sc-consolidation-mysql8`，删除其匿名临时卷，并确认容器、该卷及 `13309` 端口均无残留。未触碰仓库已有 MySQL 容器、pilot/sandbox 卷或任何 `.env`。

## 未覆盖项与残余风险

- 本轮没有实现 shipment transfer、供应商 handover evidence/附件或 API 层，因此真实发运计数仍由 packing shipment 领域服务负责；receive/ready 路径本身不增加 shipped。
- MySQL 测试覆盖了数据库唯一约束和真实连接，但未在本轮构造多进程 1205/1213 死锁压力矩阵；服务已保留锁顺序和错误映射入口，后续应在独立 worker/数据库中补齐并发压力证据。
- 迁移型 pytest 曾与其他并行工作进程共用测试库而发生数据库名称碰撞，本报告不将其计为通过；全新业务库的 `manage.py migrate` 已独立通过，后续全量迁移测试应使用单独数据库名和单 worker。
- 本阶段不处理既有 products 历史迁移与当前模型字段的漂移；定向测试使用新 schema/无迁移模式，完整项目迁移已在上述 fresh MySQL 库验证。

## P1 整改补充（2026-08-08）

本轮在原授权范围内完成以下收敛：

1. `mark_exception` 现在只接受 `allocated`/`handover_submitted`；`received`、`transferred`、`released` 不能再次标记异常。`ready` 只接受所有 active allocation 均为 `received`，异常箱必须先 `receive` 或 `controlled_release`，不再把未处置的 `exception` 视为可发运。
2. `ConsolidationBoxAllocation` 增加 `order_ids_snapshot`、`order_nos_snapshot` JSON 字段；`consolidation.0002` 将旧 singular/嵌入快照稳定回填为排序列表。箱快照、allocation 快照以及 allocate/release 事件均保留完整多订单列表，兼容保留原 singular 字段。
3. 站点已被任何 consolidation 使用后，`site_code` 不可修改；创建、更新和发布按动作时点校验 `effective_from/effective_to`，发布同时校验 collection cutoff/expected dispatch 均处于站点有效区间（半开区间 `[effective_from, effective_to)`）。
4. 站点、集货和事件写入同时处理 `Model.full_clean()` 的唯一性 `ValidationError` 与数据库 `IntegrityError`；同租户同键同主体同 payload 稳定回放，异键/异 payload 返回领域冲突。

### P1 测试实证

```text
# SQLite 当前模型（无迁移模式）
.venv\Scripts\python.exe -m pytest tests/test_sc_consolidation_1_local.py -q --create-db --nomigrations
7 passed

# 隔离 MySQL 8.4.10，127.0.0.1:13310，当前模型 schema（无迁移模式）
.venv\Scripts\python.exe -m pytest tests/test_sc_consolidation_1_mysql.py -q --create-db --nomigrations
5 passed in 102.51s
.venv\Scripts\python.exe -m pytest tests/test_sc_consolidation_1_local.py -q --create-db --nomigrations
7 passed in 93.05s
```

MySQL 并发矩阵覆盖：同键双线程 create site（一个创建、一个原结果重放）、异键/异 payload 冲突、release/cancel 竞争单一终态、同箱双分配唯一 active slot、批量一箱有效一箱冲突整批回滚，以及 ORM update/bulk 与事件租户全局键约束。线程执行前后均调用 `close_old_connections()`，测试后的 active consumption 数量按胜出终态守恒。

### 迁移型测试边界

在同一隔离 MySQL 上从零执行 `manage.py migrate --noinput`（含 `consolidation.0002`）成功。但 pytest 自动创建的迁移测试库运行依赖 packing/products 测试夹具时暴露既有 `products_productsku.product_name` 缺列（当前 products 模型与历史迁移漂移），故迁移型 pytest 的连锁失败不计为 consolidation 失败，也未越权修改 products；本轮 P1 领域行为使用真实 MySQL 当前模型 schema（`--nomigrations`）完成验证。该迁移漂移仍是后续全仓门禁前置风险。

P1 测试完成后已删除临时 MySQL 数据库、停止/移除 `sc-consolidation-p1-mysql8` 及匿名卷，并确认 13310 端口无残留。
