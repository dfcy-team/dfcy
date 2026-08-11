# SC-SHIP-ROUTE-1 本地代码审核

## 1. 审核结论

| 项目 | 结论 |
| --- | --- |
| 审核对象 | `6ed83af0b2d0adc60fae4aeb9cb1f0dc56c454c4` |
| 审核范围 | 完工后散货/柜货路线模型、API、权限、幂等、装箱门禁及测试 |
| P0 | 0 |
| P1 | 2 |
| P2 | 2 |
| 结论 | `REQUIRES_SC_SHIP_ROUTE_1_P1_REMEDIATION` |
| 线上系统授权 | 无 |

本轮实现的正常 API 路径、数据库路线一致性约束、幂等快照、装箱路线门禁和 MySQL 并发行为基本成立，但新建采购单状态仍可通过普通 ORM 伪造，路线领域服务也没有在自身边界执行权限与 DataScope。两项问题能够串联形成真实越权分流路径，因此当前不能通过本地代码审核。

## 2. 审核边界

审核提交只包含预期 15 个文件：

- purchasing 模型、迁移、serializer、service、view、admin 和本地种子命令；
- shipping-route 权限迁移；
- packing 创建入口门禁；
- SC-F1/SC-F2 兼容测试和路线专项/MySQL 并发测试；
- 本地开发报告。

未发现产品开发、刊登、前端并行工作、试点部署或其他工作树内容进入审核提交。审核后相关业务文件没有未提交漂移。

## 3. P1 问题

### SC-SHIP-ROUTE-1-R1-P1-001：新建采购单可通过普通 ORM 伪造生产完工状态

位置：

- `backend/apps/purchasing/models.py:266-284`

问题：

`SupplyPurchaseOrder.save()` 对新实例只限制非 `undecided` 路线及路线决定元数据，没有限制同属 `CONTROLLED_FIELDS` 的 `status`、完成数量、生产时间和版本。`QuerySet.bulk_create()` 虽然被拒绝，但 `objects.create()` 会进入模型 `save()`，因此普通 ORM 可以直接建立 `status=production_completed` 的订单。

隔离内存数据库实证：

```text
DIRECT_CREATE_STATUS production_completed 0 None
```

即订单在完成数量为 0、完工时间为空且没有经过接单、生产和完工事件的情况下，被成功保存为生产完工。路线服务只校验 `status == production_completed`，所以伪造订单可继续进入路线分流。

影响：

- 绕过 SC-F1 已冻结状态机和不可变事件；
- 产生没有生产事实的散货/柜货路线；
- 后续装箱只读取状态和路线，会把伪造订单视为可装箱订单；
- 当前 ORM 测试只覆盖新建时直接带最终路线，没有覆盖新建时伪造受控状态。

整改验收：

1. 普通新建实例只能是 `pending + undecided + completed_quantity=0 + version=1`；
2. `accepted_at`、`production_started_at`、`production_completed_at` 和路线决定元数据必须为空；
3. `objects.create()`、实例 `save()`、bulk、admin 和伪造旧标记均不能带入其他受控初始状态；
4. 正常采购单创建服务保持可用；
5. 补充 SQLite 与 MySQL ORM 绕过实证。

### SC-SHIP-ROUTE-1-R1-P1-002：路线领域服务自身未执行权限与 DataScope

位置：

- `backend/apps/purchasing/supply_services.py:241-286`
- `backend/apps/purchasing/views_supply.py:239-256`

问题：

API view 在调用服务前执行新权限及 DataScope，正常 HTTP 路径正确；但 `perform_shipping_route_action()` 自身只检查 `actor.user_type == internal` 和同租户，没有检查：

- `supply.purchase_order.assign_shipping_route`；
- 操作者是否具有至少一个有效 DataScope；
- DataScope 是否覆盖订单或供应商。

该函数被作为可复用领域服务公开导入，专项及 MySQL 测试也直接调用它。隔离实证中，同租户但没有任何 Role、Permission 或 DataScope 的内部用户直接调用服务成功：

```text
NO_PERMISSION_ROUTE_SUCCEEDED loose_cargo True False
```

结合 P1-001，无权限内部调用者可以先构造伪完工订单，再绕过 API 完成路线指定、事件和操作日志写入。

整改验收：

1. 权限与 DataScope 必须在可复用服务边界执行，且先于订单内容、幂等记录和响应快照读取；
2. 无权限返回稳定 403，DataScope 外对象保持稳定 404；
3. API 与服务调用复用同一授权实现，避免两套规则漂移；
4. 增加无角色、无权限、无 DataScope、OWN、CUSTOM supplier/order 以及跨租户的直接服务测试；
5. 已存在幂等记录也不得绕过当前授权。

## 4. P2 问题

### SC-SHIP-ROUTE-1-R1-P2-001：MySQL 测试未实际执行专项迁移

开发报告记录 MySQL 12 项并发测试通过，但因并行工作树中的 `development` 视图迁移在 MySQL 原子迁移中执行 DDL，测试最终使用：

```text
--no-migrations --create-db
```

这能证明当前 Django 模型生成表下的行锁、唯一性和并发行为，但不能证明 `purchasing/0005_shipping_route.py` 和 `permissions/0019_seed_shipping_route_permission.py` 能在既有 MySQL 迁移链及历史数据上真实应用。`sqlmigrate` 只证明 SQL 可生成。

处理决定：整改复核前补充仓库外临时 MySQL 库的定向迁移实证，至少包括：

- 从 `purchasing 0004` 升级至 `0005`；
- 从 `permissions 0018` 升级至 `0019`；
- 既有采购单及事件回填为 `undecided`；
- `SHOW CREATE TABLE` 存在外键和 `supply_po_route_decision_consistent`；
- 非法路线/元数据组合由 MySQL 拒绝；
- 正反向迁移边界及并行 migration leaf 检查。

### SC-SHIP-ROUTE-1-R1-P2-002：服务输入校验弱于 API serializer

位置：

- `backend/apps/purchasing/supply_services.py:258-275`
- `backend/apps/purchasing/supply_serializers.py` 的路线动作 serializer

API serializer 将 `reason` 限制为 2,000 字符、`expected_version` 限制为正整数，并保证幂等 key 来自字符串 header；领域服务直接调用时只执行 `strip()`，且幂等 key 直接调用 `len()`。内部调用者可以绕过长度/类型合同，甚至因非字符串 key 触发非业务 TypeError。

处理决定：在服务边界统一校验 idempotency key 类型和长度、正整数版本、路线枚举、reason 类型与 2,000 字符上限；serializer 只负责 HTTP 解码，不应成为唯一业务输入边界。

## 5. 已通过项

### 5.1 数据模型与迁移设计

- `shipping_route` 非空且默认 `undecided`；
- MySQL CHECK SQL 覆盖未决定/已决定元数据一致性及枚举白名单；
- 决定人外键采用 PROTECT；
- route、决定人、决定时间均进入 QuerySet update/bulk update 防护；
- 采购单事件新增前后路线快照；
- 事件普通创建、更新及伪造旧实例标记被 ContextVar 写上下文阻断。

### 5.2 API 与幂等

- 创建 API 显式拒绝提前传入 `shipping_route`；
- 供应商网页和小程序动作表没有分流动作；
- HTTP 权限和 DataScope 位于幂等重放之前；
- 同 key 同载荷重放原快照；异载荷、异动作或异操作者冲突；
- 期望版本、完工状态、初次指定和更正语义清晰；
- 路线、事件、日志及响应快照处于同一外层事务。

### 5.3 装箱与并发

- packing 创建先锁定采购单，再校验完工状态和路线；
- 未指定路线及散货/柜货混合批次均被拒绝；
- 路线更正与装箱创建使用相同的采购单行锁顺序，没有发现互相越过的提交窗口；
- 有效装箱关联建立后路线更正被拒绝；
- MySQL 竞争性散货/柜货指定只有一个结果提交，事件和日志各一条；
- 未实现 SC-F3 快递单、装柜、报关、发货、到岸、到仓或清货动作，范围边界正确。

## 6. 独立复测

| 验证 | 结果 |
| --- | --- |
| 固定提交文件边界 | 15 个预期文件，通过 |
| 专项 SQLite 测试 | 7 passed |
| 开发阶段 SQLite + SC-F1/SC-F2 回归 | 55 passed |
| 开发阶段真实 MySQL 并发回归 | 12 passed |
| `makemigrations --check --dry-run` | No changes detected |
| Django system check | 0 issues |
| `sqlmigrate purchasing 0005` | SQL 生成通过 |
| 普通 ORM 伪完工负向实证 | 失败，确认 P1-001 |
| 无权限直接服务调用负向实证 | 失败，确认 P1-002 |

测试通过不能抵消未覆盖的负向路径。本轮结论保持 `REQUIRES_SC_SHIP_ROUTE_1_P1_REMEDIATION`。

## 7. 下一步

下一步应修复：

- `SC-SHIP-ROUTE-1-R1-P1-001`；
- `SC-SHIP-ROUTE-1-R1-P1-002`。

并对两项 P2 给出关闭证据或明确的后续门禁决定。整改完成后执行：

`SC-SHIP-ROUTE-1 P1 整改复核`
