# SC-SHIP-ROUTE-1 P1 整改与 P2 处理决定

## 1. 整改结论

| 项目 | 结论 |
| --- | --- |
| 对应审核 | `SC-SHIP-ROUTE-1-R1` |
| P1-001 | 已修复并通过 SQLite/MySQL 普通 ORM 负向验证 |
| P1-002 | 已修复并通过权限、DataScope、跨租户及幂等授权顺序验证 |
| P2-001 | 本轮关闭；已完成隔离 MySQL 定向迁移实证 |
| P2-002 | 本轮关闭；服务边界合同已补齐并测试 |
| 当前状态 | `READY_FOR_SC_SHIP_ROUTE_1_P1_RECHECK` |
| 线上系统授权 | 无；未连接、未迁移、未写入供应链正式环境 |

本轮只修改本机供应链采购单模型、路线领域服务、内部 API 编排、专项测试和本报告。并行的产品开发、刊登、前端、试点部署等工作树内容不在整改边界内。

## 2. P1 整改

### 2.1 SC-SHIP-ROUTE-1-R1-P1-001

`SupplyPurchaseOrder.save()` 现在对所有非领域动作上下文的新实例统一校验受控初始状态：

- `status=pending`；
- `shipping_route=undecided`；
- 路线决定人、路线决定时间及三个生产生命周期时间均为空；
- `completed_quantity=0`；
- `version=1`。

任何偏离均由模型层拒绝，因此 `objects.create()`、实例 `save()`、admin 等普通模型保存入口不能再直接建立伪完工或伪版本订单。原有 QuerySet `update`、`bulk_update`、`bulk_create` 防护以及 ContextVar 领域写入能力保持不变。

新增测试覆盖普通新建时伪造完工状态、完成数量、完工时间和版本；旧实例伪标记及路线字段 bulk 绕过测试继续保留。相同负向用例已在 SQLite 和本机 MySQL 模型表上执行。

### 2.2 SC-SHIP-ROUTE-1-R1-P1-002

`perform_shipping_route_action()` 现将 `supply.purchase_order.assign_shipping_route` 权限与 DataScope 作为领域服务自身的强制前置条件：

- 无角色、角色无权限、权限存在但无 DataScope 均返回 403；
- DataScope 外订单与跨租户订单返回 404；
- `ALL`、`OWN`、CUSTOM supplier 和 CUSTOM order 使用统一过滤器；
- 授权与范围判定先于订单、幂等事件和响应快照读取；
- 即使幂等记录已存在，当前操作者失去授权后也不能重放；
- API 路线分支直接复用服务授权，不再维护第二套路线范围判断。

新增直接服务测试覆盖上述拒绝矩阵及 OWN、CUSTOM supplier/order 的成功路径。

## 3. P2 处理决定

### 3.1 SC-SHIP-ROUTE-1-R1-P2-001：关闭

决定：MySQL 并发测试继续允许使用 `--no-migrations --create-db` 隔离验证当前模型的行锁语义，但它不能单独作为专项迁移准入证据。路线迁移必须另外通过真实 MySQL 定向迁移门禁。

本轮在仓库外独立临时库 `sc_ship_route_migration_test` 上使用 Django `MigrationExecutor` 完成：

1. 迁移至 `purchasing 0004` 与 `permissions 0018` 并插入历史采购单、历史事件；
2. 前进至 `purchasing 0005` 与 `permissions 0019`；
3. 验证历史订单、事件路线均回填为 `undecided`，决定元数据为空；
4. 验证新权限恰好一条；
5. `SHOW CREATE TABLE`/information schema 验证 `supply_po_route_decision_consistent` 和决定人外键存在；
6. 直接执行非法 `loose_cargo + 空决定元数据` 更新，由 MySQL CHECK 拒绝；
7. 反向回到 `0004/0018`，验证字段和权限移除；再次前进至 `0005/0019`，验证默认值及权限恢复；
8. migration graph 验证 purchasing 唯一 leaf 为 `0005_shipping_route`，并行 permissions `0020` 明确依赖 `0019`。

实证摘要：

```text
FORWARD_ORDER_DEFAULTS ('undecided', None, None)
FORWARD_EVENT_DEFAULTS ('undecided', 'undecided')
FORWARD_PERMISSION_COUNT 1
CHECK_PRESENT True
INVALID_COMBINATION_REJECTED True
REVERSE_ORDER_COLUMN_ABSENT True
REVERSE_EVENT_COLUMN_ABSENT True
REVERSE_PERMISSION_COUNT 0
REAPPLY_ORDER_DEFAULT undecided
REAPPLY_PERMISSION_COUNT 1
ROUTE_ACTOR_FK_PRESENT True
TARGETED_MYSQL_MIGRATION_PROOF PASS
```

该临时库在验证结束后删除；不把临时数据库、账号或数据纳入仓库。

### 3.2 SC-SHIP-ROUTE-1-R1-P2-002：关闭

路线领域服务已补齐与 serializer 一致且可独立执行的输入合同：

- action 必须为支持的字符串动作；
- idempotency key 必须为非空字符串且不超过 128 字符；
- expected version 必须为大于等于 1 的整数，布尔值不作为整数接受；
- shipping route 必须为散货或柜货枚举字符串；
- reason 必须为字符串、去除首尾空格且不超过 2,000 字符；路线更正仍要求非空原因。

直接服务测试覆盖非字符串 key、布尔/零版本、非字符串 reason 和超长 reason，均稳定返回 DRF 业务校验错误而非 Python `TypeError`。

## 4. 验证结果

| 验证 | 结果 |
| --- | --- |
| 路线专项 SQLite | 19 passed |
| SC-F1 + SC-F2 + 路线完整 SQLite 回归 | 67 passed |
| F1/F2/路线真实 MySQL 并发 | 12 passed |
| 新建受控状态 MySQL ORM 负向测试 | 4 passed |
| 定向 MySQL 0004→0005、0018→0019、反向及重放 | PASS |
| MySQL CHECK、外键、历史补值及权限种子 | PASS |
| `manage.py check` | 0 issues |
| `makemigrations --check --dry-run` | No changes detected |
| Python 编译及 `git diff --check` | PASS |

## 5. 后续门禁

下一步执行 `SC-SHIP-ROUTE-1 P1 整改复核`。在复核通过前不进入共享环境、试点环境或正式环境部署，也不启动散货快递、柜货装柜、报关、发货、到岸、到仓或清货等 SC-F3 状态动作。
