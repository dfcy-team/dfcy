# SC-SHIP-ROUTE-1 完工后发运路线本地开发报告

## 1. 结论

| 项目 | 结果 |
| --- | --- |
| 工作包 | `SC-SHIP-ROUTE-1` |
| 状态 | `IMPLEMENTED_PENDING_LOCAL_CODE_REVIEW` |
| 开发环境 | 架构员主机、本地隔离环境 |
| 目标数据库 | MySQL 8 |
| 线上数据库连接 | 无 |
| 线上系统修改 | 无 |
| 散货/柜货后续动作 | 未提前实现，保留给 `SC-F3-0` |

本轮已经把采购订单完工后由采购指定散货或柜货的新增需求整合到现有 SC-F1 采购单和 SC-F2 装箱代码中。实现只开放本地审核，不授权客户端发布、部署、切流或生产迁移。

## 2. 当前融合进度

本轮开始时的相关已完成基线：

- SC-F1 采购单模型、动作、API、DataScope、幂等及 MySQL 并发审核已完成；
- SC-F2 装箱模型、领域服务、API、权限、DataScope、原子幂等及最终本地审核已完成；
- SC-F2 中文字体四文件资产已准入；
- renderer 合同门禁已通过，只授权进入本地中文标签 renderer 实现；
- `SC-SHIP-ROUTE-CR-001 R2` 已冻结散货与柜货的业务分流和后续动作边界。

本轮新增完成：

- 采购订单发运路线受控字段及 MySQL 一致性约束；
- 完工后采购初次指定和装箱前更正动作；
- 独立权限、DataScope、版本、幂等、事件和操作日志；
- 采购单创建 API 禁止提前传入路线；
- 供应商通道禁止指定或更正路线；
- SC-F2 装箱入口拒绝未分流订单和散货/柜货混合批次；
- SQLite 功能/回归及真实 MySQL 并发验证。

## 3. 模型与迁移

### 3.1 `SupplyPurchaseOrder`

新增：

- `shipping_route`：`undecided | loose_cargo | container_cargo`，非空，默认 `undecided`；
- `shipping_route_decided_at`；
- `shipping_route_decided_by`；
- 数据库约束 `supply_po_route_decision_consistent`。

约束保证：

- `undecided` 时决定人和决定时间必须同时为空；
- 两种已决定路线必须同时具有决定人和决定时间；
- 不接受 NULL、空字符串或其他枚举值表达路线；
- 新订单不能通过普通 `save()` 带入已决定路线；
- 已有订单不能通过实例保存、QuerySet update 或 bulk update 绕过动作服务。
- 受控保存使用 ContextVar 领域写上下文，伪造旧 `_action_service_write` 实例属性不能开启写入。

### 3.2 `SupplyPurchaseOrderEvent`

新增动作：

- `assign_shipping_route`；
- `change_shipping_route`。

新增前后路线快照：

- `before_shipping_route`；
- `after_shipping_route`。

迁移：

- `purchasing/0005_shipping_route.py`；
- `permissions/0019_seed_shipping_route_permission.py`。

既有订单和既有事件只回填为 `undecided`，不根据状态、数量、箱数或历史数据猜测路线。

## 4. API、权限与 DataScope

新增内部动作端点：

- `POST /api/internal/purchasing/supply-orders/{id}/actions/assign-shipping-route/`；
- `POST /api/internal/purchasing/supply-orders/{id}/actions/change-shipping-route/`。

请求字段：

- `expected_version`；
- `shipping_route`；
- `reason`，更正路线时必填。

新增权限：

`supply.purchase_order.assign_shipping_route`

动作要求：

- 仅内部采购人员；
- 权限和 DataScope 均覆盖目标订单；
- 状态严格为 `production_completed`；
- 初次指定只能从 `undecided` 开始；
- 更正只能在有效装箱批次建立前执行；
- 更正后的路线必须不同；
- 供应商网页端和小程序端均不识别该动作。

订单创建接口显式拒绝 `shipping_route`、决定时间或决定人输入。列表和详情只读返回路线信息。

## 5. 原子性与幂等

动作在最外层事务内完成：

1. API 层完成权限与 DataScope 校验；
2. `select_for_update` 锁定采购订单；
3. 优先核验已有幂等事件；
4. 校验版本、完工状态、当前路线及下游装箱；
5. 写入路线、决定人、决定时间并递增版本；
6. 写入不可变订单事件和操作日志；
7. 冻结响应快照后一次性提交。

请求摘要覆盖动作、期望版本、目标路线和规范化原因。同 key 同载荷返回原响应快照；同 key 异载荷、异动作或异操作者返回冲突。失败时事务回滚，不留下半条路线、孤立事件或日志。

## 6. SC-F2 装箱整合

`create_packing_batch` 在锁定全部采购单后新增：

- 任一订单为 `undecided`：拒绝；
- 同批同时含 `loose_cargo` 与 `container_cargo`：拒绝；
- 同供应商、同路线且全部完工：保持原 SC-F2 行为。

路线由采购单动作决定，装箱服务和标签 renderer 均只能读取，不能修改。

## 7. 测试证据

### 7.1 SQLite 定向与回归

| 测试集 | 结果 |
| --- | ---: |
| `test_supply_chain_shipping_route.py` | 7 passed |
| SC-F1 API + SC-F2 service/API 回归 | 48 passed |

覆盖创建提前传值、完工前动作、权限、DataScope、供应商越权、初次指定、重放、异载荷冲突、版本冲突、路线更正、装箱后锁定、未分流装箱、混合路线装箱、ORM 绕过及伪造旧服务标记。

### 7.2 MySQL 8

| 测试集 | 结果 |
| --- | ---: |
| 新增路线并发 + 既有 SC-F1/SC-F2 并发回归 | 12 passed |

竞争性的散货/柜货指定在真实 MySQL `select_for_update` 下只有一个成功；最终订单版本为 2，事件和操作日志各一条。

本机工作树另有未提交 `development` 应用迁移，其中在原子迁移中执行 MySQL 视图 DDL，会阻断全量测试库迁移。为不修改不属于本任务的并行工作，本次 MySQL 并发门禁使用 `--no-migrations --create-db` 从当前 Django 模型建立隔离测试表。SC-SHIP-ROUTE-1 自身迁移另行通过以下验证：

- `makemigrations --check --dry-run`：No changes detected；
- `manage.py check`：0 issues；
- `sqlmigrate purchasing 0005`：生成三个采购单字段、两个事件字段、外键和 MySQL CHECK 约束 SQL。

### 7.3 静态验证

- 受影响 Python 文件 `py_compile` 通过；
- 专项路径 `git diff --check` 通过。

## 8. 未实施边界

本轮没有实现：

- 散货快递单照片/信息上传、到仓和清货动作；
- 柜货装柜、报关、发货、到岸、到仓和清货动作；
- 受控附件、对象存储、病毒扫描和历史附件迁移；
- 网页端或小程序端业务页面；
- 中文标签 v2 renderer；
- 生产数据回填、部署或线上切换。

这些内容继续由 `SC-F3-0`、中文标签 renderer 专项和后续客户端阶段分别审核。

## 9. 下一步

下一步执行：

`SC-SHIP-ROUTE-1 本地代码审核`

审核重点包括模型/数据库防绕过、创建接口提前字段注入、权限/DataScope 先于幂等重放、并发动作唯一结果、装箱门禁及迁移与并行工作树的兼容性。
