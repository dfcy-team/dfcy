# SC-F2-MULTI-0 多批次、多次发货领域契约

- 编号：`SC-F2-MULTI-0`
- 日期：2026-08-08
- 状态：`FROZEN_FOR_INDEPENDENT_REVIEW`
- 上游基线：`SCM-REQ-V2-R1`
- 环境：仅本机开发；禁止连接或修改供应链正式系统

## 1. 本阶段目标

解除当前“一张采购订单只能有一个活动装箱批次”的限制，同时保证任何并发、重放、ORM 调用或迁移路径都不能造成超量装箱、重复装箱、重复发货或跨租户消费。

本阶段只冻结多批次与多发运公共核心。散货集货地点、集货单、报关、到仓和清货的具体模型/API 在 `SC-CONSOLIDATION-0` 冻结，但必须复用本文的箱消费和履约台账。

## 2. 现有实现差异

| 当前实现 | 目标合同 |
| --- | --- |
| `PackingBatchOrder(order, active_guard)` 唯一 | 保留批次—订单唯一链接，取消订单级单活动批次限制 |
| 生产进度主要记录在订单级 `completed_quantity` | 增加订单明细级履约投影和事件；订单级字段降为可重建兼容摘要 |
| 完成批次要求覆盖订单全部数量 | 完成批次只冻结本批次实际箱明细 |
| 取消批次把 `active_guard` 置空 | 草稿/进行中取消释放预留；已完成批次通过反向事件受控更正 |
| 没有箱消费/发运分配模型 | 增加完整箱消费分配，防止一个箱进入两个有效下游单据 |

## 3. 聚合与权威源

### 3.1 `SupplyOrderLineFulfillment`

每条 `SupplyPurchaseOrderLine` 一条当前投影，建议字段：

- `tenant_id`、`order_id`、`order_line_id`；
- `ordered_quantity` 快照；
- `production_completed_quantity`；
- `packing_reserved_quantity`；
- `packed_quantity`；
- `shipped_quantity`；
- `warehouse_received_quantity`；
- `warehouse_cleared_quantity`；
- `version`、`created_at`、`updated_at`。

约束：

- `order_line_id` 唯一；tenant/order/line 必须一致。
- 所有数量非负。
- `production_completed + 0 <= ordered_quantity`。
- `packing_reserved + packed <= production_completed`。
- `packed >= shipped >= warehouse_received >= warehouse_cleared`。
- 投影只能由领域服务在事务内更新；QuerySet `update/bulk_update/delete` 及模型直接状态写入必须拒绝。

### 3.2 `SupplyFulfillmentEvent`

不可变事件是审计权威源，至少包含：

- `tenant`、`order`、`order_line`、`stage`、`delta_quantity`；
- `source_type`、`source_id`、`source_version`；
- `action`、`actor`、`channel`、`reason`；
- `idempotency_key`、`request_hash`、`before_snapshot`、`after_snapshot`；
- `occurred_at`、`created_at`。

唯一约束：

- `(tenant, idempotency_key)` 全局唯一，保持与现有供应链写动作一致；
- `(tenant, source_type, source_id, source_version, order_line, stage, action)` 唯一，防止同一业务版本重复记账。

事件只追加，不更新、不删除。反向动作生成负向事件并引用原事件，不覆盖原记录。

### 3.3 `PackingBatchLineAllocation`

批次与订单明细的数量合同，建议字段：

- `tenant`、`batch`、`order_line`、`quantity`；
- `state`: `reserved/frozen/released/reversed`；
- `allocation_version`、`created_by`、`created_at`、`frozen_at/released_at`。

约束：

- `(batch, order_line)` 唯一，数量必须大于零。
- 其数量必须等于该批次所有箱中同一订单明细 `PackingBoxItem.quantity` 之和。
- 草稿/进行中批次使用 `reserved`；批次完成时原子转换为 `frozen`；取消时转为 `released`。
- 批次完成后不得直接编辑 allocation 或箱明细。

### 3.4 `PackingBoxConsumption`

完整箱进入集货或发运聚合的防重合同，建议字段：

- `tenant`、`box`、`consumer_type`、`consumer_id`、`consumer_version`；
- `state`: `reserved/committed/released/reversed`；
- `idempotency_key`、`actor`、时间和原因。

数据库必须保证一个 `box` 同时最多只有一个 `reserved/committed` 有效消费。由于 MySQL 条件唯一约束能力有限，使用可空 `active_guard=TRUE/NULL` 或独立活动占用表实现，并配合服务锁；不得只依赖应用层查询。

集货单到发运单不是对同一箱建立第二个活动消费，而是执行原子“消费权转移”：锁定箱及当前集货消费，验证目标发运单引用该集货单后，将集货消费结束并建立发运消费；两个历史记录通过 `transferred_from_id` 关联。任一写入失败则全部回滚，任何时刻活动消费仍最多一个。

## 4. 数量与身份不变量

1. `PackingBoxItem.order_line.order` 必须存在于当前批次的 `PackingBatchOrder` 链接中。
2. 同一批次只允许同一租户、同一供应商的订单；同一订单的运输路线必须一致且已确定。
3. 批次可包含一个供应商的多个订单，但不得跨供应商拼成供应商装箱批次。
4. 每条明细满足：
   - `reserved + packed <= production_completed <= ordered`；
   - `shipped <= packed`；
   - `received <= shipped`；
   - `cleared <= received`。
5. 完成批次时：本批次所有箱非空、箱项数量正数、allocation 与箱项汇总相等，且所有关联明细投影仍满足守恒。
6. 一个已完成箱只能由一个有效下游消费记录占用。拆箱必须先释放未提交消费，再走受控重新装箱；已提交发运的箱不得拆箱。
7. 所有快照保留原订单号、SKU 和商品名，后续主数据修改不得改变历史标签和单据。
8. 路线更正只允许在订单没有任何 `reserved/frozen` 装箱 allocation 且没有箱消费时执行；已经开始装箱的订单必须先受控取消/撤销至零占用，禁止直接改变批次继承路线。

## 5. 动作状态机

| 动作 | 前态/条件 | 结果 | 权限/主体 | 并发资源 |
| --- | --- | --- | --- | --- |
| 创建批次 | 订单生产完成、路线已确定、有可装数量 | `draft`，建立预留 | 既有 `supply.packing.create` 或供应商 capability | tenant、订单、明细投影 |
| 增改箱明细 | `draft/in_progress` | 调整预留及版本 | `supply.packing.manage` 或绑定供应商 | batch、明细投影 |
| 完成批次 | `draft/in_progress` 且校验通过 | allocation `frozen`、packed 增加、reserved 减少 | `supply.packing.complete` 或绑定供应商 | batch、订单、明细投影、箱 |
| 取消未完成批次 | `draft/in_progress`、未被下游消费 | allocation `released`、释放 reserved | `supply.packing.manage` 或绑定供应商 | batch、明细投影 |
| 提交完成批次更正 | `completed` | 产生待审请求，不改账 | 供应商或 `supply.packing.manage` | batch |
| 批准完成批次更正 | 无已提交发运；审批通过 | 反向 packed，生成新版本/重新装箱 | 既有 review 权限 | batch、箱消费、明细投影 |
| 预留箱到下游单据 | `completed`、箱未占用、路线兼容 | consumption `reserved` | 后续集货/发运权限 | box、活动消费槽 |
| 提交发运 | 所有箱预留有效 | consumption `committed`、shipped 增加 | `supply.shipment.dispatch` | shipment、box、明细投影 |
| 取消未发运预留 | 尚未 committed | consumption `released` | 后续单据管理权限 | consumer、box |
| 集货转发运 | 集货箱已确认且目标发运单引用该集货单 | 原子转移活动消费权，不重复记 packed | `supply.shipment.create/update` | consolidation、shipment、box、消费槽 |

供应商 capability 不是内部 Permission；必须继续校验 external 用户、supplier binding、批次所属供应商、对象状态和渠道。

## 6. 事务、锁与幂等合同

### 6.1 确定性加锁顺序

所有写动作统一按以下顺序取锁，集合内部按主键升序：

1. `Tenant`（仅确有全租户序列需求时）；
2. `SupplyPurchaseOrder`；
3. `SupplyPurchaseOrderLine`；
4. `SupplyOrderLineFulfillment`；
5. `PackingBatch`；
6. `PackingBox`；
7. `PackingBoxConsumption`/下游聚合。

不得在持有后序资源锁时反向获取前序锁。MySQL 死锁或锁等待超时只允许有限次数退避重试，并要求客户端使用相同幂等键。

### 6.2 幂等

- 所有写 API 强制 `Idempotency-Key` 和 `expected_version`。
- 重放前重新执行当前用户、渠道、Permission/DataScope 或供应商绑定检查。
- 同键同主体同动作同资源同请求哈希返回原响应；任何一项不同返回 409。
- 失败事务不得保存成功响应快照；未知提交结果必须用同键查询/重放，不得换键盲重试。

### 6.3 ORM 绕过

- 受控模型的 `save/delete`、QuerySet `update/delete`、bulk API 必须拒绝未经领域上下文的数量/状态修改。
- Django admin、management command、Celery/后台任务和数据迁移必须使用专用受审入口。
- 数据库唯一/检查约束作为最后防线，不能用 serializer 校验代替。

## 7. 订单汇总合同

订单主状态继续表达采购生命周期，不由某一个批次或发运单直接覆盖。API 新增只读 `fulfillment_summary`：

- `ordered_quantity`
- `production_completed_quantity`
- `packing_reserved_quantity`
- `packed_quantity`
- `shipped_quantity`
- `warehouse_received_quantity`
- `warehouse_cleared_quantity`
- `packing_state`: `not_started/partial/full`
- `shipping_state`: `not_started/partial/full`
- `warehouse_state`: `not_started/partial/full`

所有状态由明细投影汇总派生。现有 `completed_quantity` 在兼容期只读映射为生产完成汇总，禁止成为新写入口；退役需单独 API 版本决定。

## 8. 权限与 DataScope

本阶段不新增硬编码角色。继续使用既有 packing 权限，后续发运动作使用 V2 基线拟定权限。

- 内部列表/详情：tenant -> exact permission -> permission-specific DataScope -> object state。
- 多订单批次创建时，调用者必须同时拥有所有关联 `supplier_ids` 和 `supply_purchase_order_ids`；不得用任一订单授权覆盖其他订单。
- 新增 `order_line_ids` 只作为对象一致性校验，不作为绕过订单 DataScope 的独立授权维度。
- 历史批次的 DataScope 继续按全部历史订单链接判断，不因 allocation released/reversed 而隐藏审计记录。
- 外部供应商只能访问自身绑定供应商的批次、箱和集货安排，不得看到同一集货单中其他供应商的数据。

## 9. 迁移与切换合同

### M0 只读盘点

输出每个订单的批次状态、`active_guard`、箱项总数、订单数量和异常分类；不写数据库。

### M1 加法迁移

新增履约投影、事件、批次明细 allocation 和箱消费表；保留旧约束与旧服务。

### M2 本地回填与双读

- 合法历史完成批次回填 `frozen` allocation 与 packed 事件。
- 草稿/进行中批次回填 `reserved`；取消批次为 `released`。
- 当前旧约束理论上每订单只有一个活动批次；若盘点不符，进入人工异常清单。
- `production_completed` 且订单级完成量等于订单总量时，每条订单明细按订购量回填生产完成量；订单级完成量为零时按零回填；处于部分生产且只有订单级累计量时，因无法证明各明细分配，必须进入人工明细分配清单并阻断该订单的新装箱入口，禁止按比例猜测。
- 新旧汇总不一致时阻断切换，不自动覆盖。

### M3 新写服务切换

先切换领域服务和测试，再移除 `uniq_pack_active_order` 与 `active_guard` 业务依赖。迁移不得在同一步同时删除旧字段；字段仅在稳定波次后退役。

### M4 回滚

在新系统产生一个订单多个活动批次后，不能直接回滚至旧单批次写服务。回滚只允许关闭新写入口、保留新表并继续只读，或通过受审数据收敛操作恢复旧不变量。

## 10. 必测矩阵

### 10.1 MySQL 并发

1. 同明细两个批次并发预留，合计不超生产完成量。
2. 同批次两个完成请求只记一次 packed 事件。
3. 一个箱并发加入两个下游单据，最多一个成功。
4. 完成批次与取消批次并发，结果满足单一合法终态。
5. 发运与完成批次更正并发，不允许已发运箱被反向修改。
6. 多订单批次以不同请求顺序提交，不因加锁顺序不同长期死锁。

### 10.2 权限与隔离

- tenant、supplier、order、batch、box、下游单据逐层越权；
- permission-specific DataScope 的 ALL/OWN/CUSTOM/缺失/非法配置；
- internal JWT、miniapp JWT、external supplier、RPA 渠道互斥；
- 幂等重放时权限或 supplier binding 已撤销。

### 10.3 ORM 与迁移

- `save/update/bulk_update/delete` 绕过；
- admin/command/background task 绕过；
- 零数据、合法历史、取消历史、异常超量、重复源数据；
- M2 重复执行结果一致；中途失败无部分台账；只读回滚可用。

## 11. 实施文件所有权建议

独立编码阶段交给一个 `luna-worker` 负责以下范围，避免模型和服务跨代理冲突：

- `backend/apps/purchasing/models.py` 及新增迁移；
- `backend/apps/packing/models.py`、`services.py` 及新增迁移；
- 对应 backend tests 和本阶段实现报告。

API serializer/view、Web、小程序和散货集货模型不进入第一实现任务。主代理负责审查迁移安全、接口兼容、测试证据及未授权文件变化。

## 12. 退出条件

本文必须先通过 `SC-F2-MULTI-0 独立审核`。审核关闭全部 P1 后，才允许启动 `SC-F2-MULTI-1 本地模型、迁移与领域服务开发`，并按模型路由交给 `luna-worker`。
