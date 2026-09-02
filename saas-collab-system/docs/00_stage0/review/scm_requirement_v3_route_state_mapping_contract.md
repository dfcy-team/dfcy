# SCM-V3 路线、模式与状态映射合同

- 编号：`SCM-V3-MAP-0`
- 状态：`FROZEN_FOR_P1_RECHECK`
- 范围：需求映射，不授权模型、迁移、API或客户端修改

## 1. 路线决定

采购订单创建时 `shipping_route=undecided`。供应商完成生产后、首个装箱下游消费前，由具有 `supply.purchase_order.assign_shipping_route` 权限且 DataScope 命中的内部采购人员选择：

- `loose_cargo`：散货；同时必须选择发运模式。
- `container_cargo`：本企业柜货装柜。

供应商不得决定或修改路线。已有下游消费后不得直接改路线，只能通过受控撤销/更正合同处理。

## 2. 散货发运模式

为同时承接最新完整需求和既有区域集货要求，`loose_cargo` 下冻结两个互斥模式：

| 模式 | 流程 | 选择主体 | 发货事实 |
| --- | --- | --- | --- |
| `direct_dispatch` | 完成装箱/审核 -> 上传货运单 -> 出货审核 -> 直发 -> 送达 | 有权限采购/物流 | 审核后的直发动作 |
| `regional_groupage` | 完成装箱 -> 采购按区域分配集货点 -> 供应商交接 -> 集货收货 -> 拼柜/报关 -> 统一发运 -> 到港/到仓/清货 | 有权限采购/物流 | Shipment dispatch |

同一完整箱只能进入一种模式且同时最多一个有效消费。模式变更必须在没有交接、收货、报关或发货事实时受控撤回。货运单、交接证据和照片全部使用受控附件，不接受任意 URL。

## 3. 柜货

`container_cargo` 使用独立 `Container` 聚合，承载装柜参与者、柜号、箱号、封条、装柜审核、报关、发运、到港、到仓、清货和箱号调换。当前 `Shipment` 可复用后段运输能力，但不得替代尚未实现的 Container 权威聚合。

## 4. 采购订单8态映射

| 最新需求状态 | 权威动作/来源 | 当前映射决定 |
| --- | --- | --- |
| `pending` | 平台下发 | `SupplyPurchaseOrder.pending` |
| `accepted` | 供应商接单 | `accepted` |
| `in_production` | 开始生产 | `in_production` |
| `production_completed` | 明细完工投影收敛 | `production_completed`；路线仍可未决定 |
| `ready_to_ship` | 至少一个有效待发货履约 | 订单只读派生，不由单张发货单覆盖 |
| `shipping_review_pending` | 直发出货审核或批次审核待处理 | 只读派生摘要，权威状态在审核对象 |
| `shipping` | 至少一个履约已发出且尚未全部送达/清货 | 明细履约台账派生 |
| `shipped` | 所有应履约数量达到所选流程终点 | 台账派生；终点按 direct/groupage/container 合同确定 |

## 5. 发货单5态映射

源5态是跨模式展示合同：

| 源状态 | `direct_dispatch` 权威状态 | `regional_groupage` 映射 |
| --- | --- | --- |
| `pending` | 新建待提交 | Shipment `draft/loading` 的展示映射 |
| `shipping_review_pending` | 货运单/照片审核中 | 集货/附件审核中的展示映射，不写 Shipment |
| `shipping` | 审核通过待发 | Shipment `customs_declared` 或可发运状态的展示映射 |
| `in_transit` | 已确认直发 | Shipment `dispatched/port_arrived/warehouse_arrived` |
| `delivered` | 直发已送达 | Shipment `warehouse_cleared` 或合同终点 |

`cancelled` 为协同系统安全扩展状态，不计入源5态但必须保留审计。未知旧值进入人工映射队列。

## 6. 货柜9态映射

| 源状态 | Container权威含义 | 与当前 Shipment 的关系 |
| --- | --- | --- |
| `loading` | 装柜中 | 可关联 Shipment `loading`，不等价 |
| `loading_review_pending` | 装载审核中 | Container审核状态 |
| `loaded` | 装载审核通过 | Container状态 |
| `fully_loaded` | 全部供应商装柜完成 | Container状态 |
| `customs_cleared` | 报关完成 | 可触发/关联 Shipment `customs_declared` |
| `shipped` | 货柜发运 | 关联 Shipment `dispatched` |
| `arrived` | 到港 | 关联 Shipment `port_arrived` |
| `arrived_warehouse` | 到仓待清单 | 关联 Shipment `warehouse_arrived` |
| `warehouse_cleared` | 清单完成 | 关联 Shipment `warehouse_cleared` |

Container 模型实现前不得用 Shipment 字段伪造装柜参与者、封条或箱号调换事实。

## 7. 装箱审核状态映射

| 源 `admin_status` | 权威组合 |
| --- | --- |
| `in_progress` | PackingBatch `draft/in_progress` |
| `completed` | PackingBatch `completed`，附件审核尚未提交 |
| `pending_loading` | 已完成且等待所选路线的下游分配 |
| `pending_review` | Review/ControlledAttachment 存在待审证据 |
| `review_approved` | 规定证据全部 accepted，批次版本未变 |
| `review_rejected` | 至少一项规定证据 rejected，等待替代证据 |

`admin_status` 是服务端派生展示字段，不新增第二个可被客户端直接写入的状态源。

## 8. 单批次开关与多批次

`single_packing_batch_per_order=true` 时，同一订单只能有一个未结束批次；`false` 时允许多个未结束批次。无论开关值如何，明细预留总量不得超过完工量，同箱不得双消费，批次完成/结束必须幂等并保留事件。开关按租户受控配置，变更不追溯破坏已有合法批次。

## 9. 迁移和失败处理

- 本合同不授权立即迁移。
- 迁移前生成旧值分布、未知值、冲突订单和下游消费清单。
- 未知/矛盾数据不得按比例或名称猜测，进入人工队列并阻断新下游动作。
- 使用新增字段/双读校验/回填/切换/退役的分波方式；每波均需 MySQL 正反向、并发和 ORM 绕过门禁。
- 当前正式线上系统继续保持隔离。
