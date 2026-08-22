# SC-SHIPMENT-1 本地开发与 MySQL 门禁报告

## 结论

本轮完成 typed loose-cargo shipment 领域底座：新 shipment authority、可审计的箱转移、部分/多 shipment、分批 dispatch，以及 shipment 目标消费提交时唯一增加 shipped。实现只包含模型、领域服务、迁移、权限 seed 和测试；没有新增 API、view、serializer、URL、Web 或 miniapp。

SQLite 定向测试和隔离 MySQL 8.4 并发门禁均通过。MySQL 从空库执行全量迁移成功；`products` 历史迁移漂移未在本轮扩大修复。

## 修改范围

- `backend/apps/shipping/apps.py`、`models.py`、`services.py`：
  - `LooseCargoShipment`、`ShipmentBoxAllocation`、append-only `ShipmentEvent`；
  - 租户/箱/来源分配唯一约束、版本和快照检查；
  - create/update/allocate/customs/dispatch/arrival/clearance/cancel/exception 受控动作；
  - allocation 批量转移按箱 ID 排序并在同一事务中调用 consolidation typed transfer；
  - dispatch 支持选定箱的部分提交和后续多次提交，只有 shipment packing consumption commit 触发 shipped；
  - 全局租户幂等事件，`full_clean`/QuerySet 阻断 ORM `save/update/bulk/delete` 绕过；
  - MySQL 1205/1213 映射为可重试领域冲突。
- P1 收敛：转移增加 shipment `origin_site_id_snapshot` 与 consolidation site 的一致性校验；customs reference 必须 trim 后非空且不超过 128 字符；显式 dispatch 集合全或无，补齐第二批 dispatch 与 arrival 前置校验；arrival 正确写入 allocation 的 `arrived_*_at` 字段；补充 `reserved` allocation 状态兼容迁移。
- `backend/apps/consolidation/services.py`、`backend/apps/consolidation/migrations/0005_alter_consolidationevent_action.py`：加入 typed `TRANSFER` 事件入口，锁定并校验 ready consolidation、received allocation、真实 shipment 和同区域后原子转移 packing consumption。
- `backend/apps/shipping/migrations/0001_initial.py`、`0002_alter_shipmentboxallocation_state.py`：新三张表及索引、check/unique 约束，并补齐 allocation `reserved` 状态；不回写既有 `SupplierShipment`。
- `backend/apps/permissions/migrations/0026_seed_shipment_permissions.py`：写入合同指定的 11 个 `supply.shipment.*` 权限，反向迁移可删除本批 seed。
- `backend/config/settings/base.py`：注册 `apps.shipping`。
- `backend/tests/test_sc_shipment_1_local.py`、`test_sc_shipment_1_mysql.py`：多 shipment 部分转移、dispatch 幂等/一次 shipped、批量回滚、ORM 绕过、MySQL 多连接 create/transfer/dispatch。

## 迁移与检查

迁移依赖 `consolidation.0005`、`packing.0006` 和现有租户/用户迁移；不改写历史 shipment 表或旧 `suppliers.SupplierShipment` 数据。执行结果：

```text
DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: \
  .venv\Scripts\python.exe manage.py check
System check identified no issues (0 silenced).

.venv\Scripts\python.exe manage.py makemigrations shipping consolidation permissions --check --dry-run --noinput
No changes detected in apps 'permissions', 'consolidation', 'shipping'
```

隔离 MySQL `sc-shipment-mysql8`（`127.0.0.1:13312`、`mysql:8.4`，digest `sha256:c592c15aaf4a1961e15d82eb31ea5987dda862d1c4b1e93424438c0e91dc1f8d`）从空库执行 `manage.py migrate --noinput`，包含 `shipping.0001`、`consolidation.0005`、`permissions.0026`，全部成功。实例信息：MySQL `8.4.10`、`utf8mb4`、`utf8mb4_0900_ai_ci`、`REPEATABLE-READ`。测试账号为本次容器内临时 local-only 账号，密码未记录。

## 测试结果

SQLite：

```text
DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: \
.venv\Scripts\python.exe -m pytest tests/test_sc_shipment_1_local.py -q --nomigrations
6 passed in 2.36s

.venv\Scripts\python.exe -m pytest tests/test_sc_shipment_1_local.py tests/test_sc_shipment_1_mysql.py -q --nomigrations
6 passed, 4 skipped in 2.52s
```

隔离 MySQL（真实多连接，线程入口前后 `close_old_connections()`）：

```text
.venv\Scripts\python.exe -m pytest tests/test_sc_shipment_1_mysql.py -q --create-db --nomigrations
4 passed in 12.99s
```

覆盖证据包括：同一租户同一幂等 key 并发创建只产生一条 shipment/event 且另一请求稳定重放；同一物理箱并发转移最多一个 shipment active allocation；有效箱与不存在箱混合批次在写入前整体回滚；同 key 并发 dispatch 只提交一个箱、packing consumption 只 commit 一次且只生成一个 dispatch event；模型/事件的 QuerySet 和 append-only 写保护生效。SQLite 另验证了跨站点转移拒绝、空白 customs reference 不改变状态、首批 dispatch 后 arrival 拒绝、第二批不同幂等键 dispatch 后全箱 arrival 成功以及每箱 commit action 仅一条。未人工制造 1205/1213 死锁，服务保留统一映射入口，压力注入留待后续门禁。

## 未实现边界与残余风险

- 未实现 shipment API、supplier handover evidence/附件、第三方承运商或外部系统连接。
- `receive/ready` 等 consolidation 动作不增加 shipped；shipment dispatch commit 才增加 shipped。shipment transfer 只接受 consolidation `READY_FOR_SHIPMENT` 且 active allocation 全部 `RECEIVED`，并保留源/目标快照。
- 未覆盖真实 1205/1213 注入和跨进程死锁压力；应在后续 worker 压测中补齐。
- 全量仓库仍可能出现既有 products 历史迁移与当前模型字段漂移；本轮没有 fake、手工标记迁移或越权修改 products。

测试容器、临时库、tmpfs 数据和测试数据库均已停止/清理；`13312` 端口确认空闲。
