# 采购订单完工后散货/柜货分流需求补充基线

## 1. 文档控制

| 项目 | 冻结值 |
| --- | --- |
| 变更编号 | `SC-SHIP-ROUTE-CR-001` |
| 需求修订 | `R2_ROUTE_ACTION_BOUNDARY` |
| 主题 | 采购订单完工后由采购指定散货或柜货并分流 |
| 状态 | `REQUIREMENT_FROZEN_PENDING_IMPLEMENTATION_BASELINE_REVIEW` |
| 执行环境 | 架构员主机、本地隔离开发环境 |
| 影响工作包 | SC-F1 采购单、SC-F2 装箱、后续 SC-F3 发运/装柜 |
| 线上系统修改授权 | 无 |
| 生产数据迁移授权 | 无 |
| 客户端发布授权 | 无 |

本文件记录新增业务规则，不原位改写已经通过审核的历史基线。后续模型、迁移、API、网页端、小程序端和 F3 实现必须先形成独立开发与审核基线。

## 2. 业务原话与规范化结论

业务规则：采购订单下单时无法确定是散货还是柜货；生产完工后，由采购人员指定散货或柜货。散货当前只处理供应商上传发货快递单照片及信息、到仓、清货；柜货在供应商装柜后继续处理报关、发货、到岸、到仓和清货。

规范化结论：

1. 采购订单创建、确认、接单和生产阶段，发运路线必须保持“未指定”；
2. 生产完工后，订单进入待采购分流状态；
3. 只有具备授权及 DataScope 的内部采购人员可以指定路线；
4. 指定 `loose_cargo` 后，只能进入散货发货流程；
5. 指定 `container_cargo` 后，只能进入柜货装柜发货流程；
6. 供应商、网页通用 PATCH、小程序通用更新、ORM 直接写入和导入任务均不得替代专用分流动作；
7. 路线不是下单必填项，也不得由数量、体积、供应商、SKU、箱数或历史订单自动推断。
8. 散货路线不建立装柜、报关、海运发货或到岸动作；
9. 柜货路线的装柜、报关、发货、到岸、到仓和清货必须按顺序推进，不得跳步；
10. “报关”是柜货的海关申报动作；“清货”是货物到仓后的清货/理货完成动作，两者不得合并或共用状态。

## 3. 领域语义

### 3.1 独立属性

发运路线必须作为采购单独立受控属性，不得复用采购单 `status`、装箱批次状态或备注字段。

建议字段：

`shipping_route`

冻结枚举：

| 值 | 语义 |
| --- | --- |
| `undecided` | 尚未由采购指定；采购单创建后的默认且唯一合法初始值 |
| `loose_cargo` | 散货路线 |
| `container_cargo` | 柜货路线 |

不得用 `NULL`、空字符串和 `undecided` 混合表示同一状态。目标 MySQL 字段应为非空并以 `undecided` 为默认值。

建议同时记录：

- `shipping_route_decided_at`；
- `shipping_route_decided_by`；
- `shipping_route_version` 或复用采购单受控 `version`；
- 不可变动作事件中的选择原因、前后值、操作者和请求摘要。

### 3.2 状态关系

```text
pending
  -> accepted
  -> in_production
  -> production_completed + shipping_route=undecided
       -> 采购指定 loose_cargo
            -> 散货发货流程
       -> 采购指定 container_cargo
            -> 柜货装柜发货流程
```

路线指定动作本身不应伪造“已发货”或“装柜中”等状态。后续 F3 聚合成功创建后，才由各自专用动作推进发运状态。

## 4. 动作合同

### 4.1 初次指定

建议动作名：

`assign_shipping_route`

动作必须同时满足：

- 订单属于当前租户；
- 操作者是内部采购人员；
- 具备独立权限 `supply.purchase_order.assign_shipping_route`；
- DataScope 覆盖该采购单或供应商；
- 订单状态严格为 `production_completed`；
- 当前 `shipping_route=undecided`；
- 请求携带 `expected_version` 和 `Idempotency-Key`；
- 目标值只能是 `loose_cargo` 或 `container_cargo`。

建议端点：

`POST /api/supply/purchase-orders/{id}/actions/assign-shipping-route/`

建议请求：

```json
{
  "expected_version": 7,
  "shipping_route": "loose_cargo",
  "reason": "Purchasing confirmed the post-production shipping arrangement."
}
```

创建采购单 API 不接受散货/柜货作为可写字段。列表和详情 API 可以只读返回 `shipping_route`、决定人和决定时间。

### 4.2 更正

为防止误选，允许在任何下游装箱、散货发运、装柜方案、货柜分配或发运记录创建前，通过独立受控动作更正路线。更正必须提供原因、期望版本和新幂等 key，并形成不可变审计。

一旦任一有效下游业务聚合已经创建，路线必须锁定。此后不得直接改字段或删除下游记录来改道；如确需改道，必须另立“撤销下游流程并重新分流”审核项目。

## 5. 分流与边界

### 5.1 散货路线

`shipping_route=loose_cargo` 时：

- 允许进入散货发货聚合；
- 由当前订单绑定供应商上传发货快递单照片及相应信息；
- 快递单提交后，后续只保留“到仓”和“清货”两个处理动作；
- 禁止创建装柜方案、货柜、箱柜分配、报关、柜货发货和到岸动作；
- 当前范围不扩展运单轨迹、报关、到岸、结算或其他国际物流节点。

冻结动作顺序：

```text
route_assigned(loose_cargo)
  -> awaiting_loose_waybill
  -> loose_waybill_submitted
  -> warehouse_arrived
  -> warehouse_cleared
```

动作建议：

| 动作 | 操作者 | 前置状态 | 结果状态 | 最小证据 |
| --- | --- | --- | --- | --- |
| `submit_loose_waybill` | 当前订单绑定供应商 | `awaiting_loose_waybill` | `loose_waybill_submitted` | 至少一张快递单照片、供应商提交时间；承运商和单号有值时结构化保存 |
| `confirm_warehouse_arrival` | 有权内部仓储/物流人员 | `loose_waybill_submitted` | `warehouse_arrived` | 到仓时间、仓库或收货点、操作人 |
| `complete_warehouse_clearance` | 有权内部仓储人员 | `warehouse_arrived` | `warehouse_cleared` | 清货完成时间、结果、差异说明（如有） |

供应商上传快递单是散货“已发出”的业务证据，但不能由上传动作直接伪造到仓或清货结果。`warehouse_cleared` 是散货当前终态。

### 5.2 柜货路线

`shipping_route=container_cargo` 时：

- 允许进入后续柜货装柜聚合；
- 必须先完成装柜方案、货柜及箱柜分配，由当前订单绑定供应商完成装柜；
- 供应商装柜完成后，依次执行报关、发货、到岸、到仓和清货；
- 禁止从散货发货入口绕过装柜流程。

冻结动作顺序：

```text
route_assigned(container_cargo)
  -> container_loading_pending
  -> container_loaded
  -> customs_declared
  -> container_shipped
  -> port_arrived
  -> warehouse_arrived
  -> warehouse_cleared
```

动作建议：

| 动作 | 操作者 | 前置状态 | 结果状态 | 最小证据 |
| --- | --- | --- | --- | --- |
| `complete_container_loading` | 当前订单绑定供应商 | `container_loading_pending` | `container_loaded` | 货柜、装柜完成时间、装柜结果及后续专项冻结的装柜证据 |
| `confirm_customs_declaration` | 有权内部物流/报关人员 | `container_loaded` | `customs_declared` | 报关时间和受控报关引用；不在普通日志记录敏感报关全文 |
| `confirm_container_shipment` | 有权内部物流人员 | `customs_declared` | `container_shipped` | 实际发货时间、承运信息及受控运输引用 |
| `confirm_port_arrival` | 有权内部物流人员 | `container_shipped` | `port_arrived` | 到岸时间、港口或到岸地点 |
| `confirm_warehouse_arrival` | 有权内部仓储/物流人员 | `port_arrived` | `warehouse_arrived` | 到仓时间、仓库或收货点 |
| `complete_warehouse_clearance` | 有权内部仓储人员 | `warehouse_arrived` | `warehouse_cleared` | 清货完成时间、结果、差异说明（如有） |

`customs_declared` 与 `warehouse_cleared` 是不同状态：前者表示装柜后的报关节点，后者表示到仓后的清货/理货完成。`warehouse_cleared` 是柜货当前终态。

### 5.3 附件与证据边界

- 快递单照片、装柜证据和后续单证必须使用受控附件引用，不得把客户端本地路径或任意外部 URL 直接写入领域记录；
- 附件上传必须校验租户、订单、供应商绑定、文件类型、大小、摘要和恶意内容；
- 领域动作只能引用已成功准入的附件，不得先推进状态再异步补必需证据；
- 附件替换、补充和作废必须保留版本及审计，不得覆盖原证据；
- 本需求只冻结证据语义，不授权当前接入对象存储或迁移原线上附件。

### 5.4 SC-F2 装箱影响

SC-F2 的装箱数据可以作为两条路线的共同上游结果，但不能决定路线。为落实“完工后由采购指定、订单再分流”，新增装箱批次和任何路线专属下游聚合都必须确认采购单已完成路线指定。

因此，现有“状态为 `production_completed` 即可创建装箱批次”的条件需要在后续整改基线中补充：

- `shipping_route` 必须为 `loose_cargo` 或 `container_cargo`；
- 同一装箱批次关联多采购单时，所有采购单必须已指定路线；
- 首期禁止一个批次混合散货路线和柜货路线；
- 标签可只读展示路线，但路线不得由标签生成动作修改。

当前中文标签 renderer 合同可以继续本地实现，因为它不负责业务分流；在 SC-F2 面向客户端或进入 F3 前，必须完成本变更对应的模型/API/服务整改和独立复核。

## 6. 原子性、并发与幂等

专用动作必须在最外层 MySQL 事务中：

1. 完成权限与 DataScope 校验；
2. `select_for_update` 锁定采购单；
3. 校验期望版本、生产完工状态和当前路线；
4. 校验不存在锁定路线的下游聚合；
5. 写入路线、决定人、决定时间并递增版本；
6. 写入不可变采购单事件和操作日志；
7. 保存确定性响应快照后一次性提交。

幂等请求摘要至少包含：订单、目标路线、期望版本和规范化原因。同 key 同 payload 重放原响应；同 key 不同 payload 返回稳定冲突。并发指定只能有一个请求成功，数据库最终值、事件、日志和幂等记录必须一致。

失败时不得留下部分路线、孤立事件、孤立日志或伪成功幂等记录。

## 7. 数据迁移原则

- 本轮不生成迁移，不连接生产数据库；
- 新字段不得根据现有订单数量、箱数、体积或状态自动猜测；
- 本地/测试既有数据迁移后统一为 `undecided`；
- 将来生产迁移必须先输出待人工确认清单；
- 历史上已存在明确散货或装柜证据的订单，也必须由受控迁移规则及审核记录映射，不允许临时 SQL 随意更新；
- 所有批量回填都必须可追溯、可复核并有租户边界。

## 8. 权限与客户端要求

- 新权限与现有查看、创建、供应商动作、装箱和标签权限分离；
- 供应商端不得写入或更正路线；路线确定后，只能在绑定订单及正确前置状态下执行本文件明确授权的快递单提交或装柜完成动作；
- 报关、柜货发货、到岸、到仓和清货动作必须使用各自独立内部权限及 DataScope；
- 网页端应在生产完工后向有权采购人员显示待分流任务；
- 下单页面不得强制选择散货/柜货；
- 小程序端不得通过隐藏字段、通用 PATCH 或本地缓存写入路线；
- UI 隐藏不是安全边界，后端服务、模型防绕过和数据库约束必须共同生效。

## 9. 后续审核与测试门禁

后续实现至少覆盖：

1. 下单时路线只能为 `undecided`；
2. 未完工订单不能指定路线；
3. 供应商和无权限内部人员不能指定；
4. DataScope 外订单不可见且不可操作；
5. 只允许两个最终路线值；
6. 通用 PATCH、实例 `save()`、QuerySet update、bulk update/create 和 admin 无法绕过；
7. 首次指定、同 key 重放、同 key 异载荷冲突；
8. 两种路线并发竞争仅一方成功；
9. 版本冲突及事务回滚零脏写；
10. 下游聚合创建后禁止更正；
11. 散货订单不能进入装柜入口；
12. 柜货订单不能绕过装柜直接走散货发货入口；
13. 多采购单装箱禁止未指定路线和混合路线；
14. MySQL 并发与 ORM 绕过实证；
15. 操作日志、事件和响应快照不泄露无关敏感数据；
16. 散货只能按快递单提交、到仓、清货顺序推进，且不能调用柜货动作；
17. 柜货只能按装柜、报关、发货、到岸、到仓、清货顺序推进；
18. 报关与清货状态、权限、时间和审计完全分离；
19. 必需附件未准入时动作原子失败且状态零变化；
20. 供应商不能伪造到仓、到岸、报关、发货或清货动作。

## 10. 当前决定与下一步

本需求补充立即成为后续融合规划的约束，但不授权当前直接修改生产代码或数据库。

后续应按顺序单独启动：

`SC-SHIP-ROUTE-1 完工后发运路线模型、API、权限与状态机审核基线冻结`

`SC-F3-0 散货/柜货动作、附件证据与流程状态机审核基线冻结`

在该基线通过并完成本地实现前：

- SC-F2 中文标签 renderer 本地开发可继续；
- 不得宣称 SC-F2 已具备完整业务分流能力；
- 不得启动散货发货或柜货装柜的客户端融合；
- 不得部署、切流或修改供应链正式线上系统。
