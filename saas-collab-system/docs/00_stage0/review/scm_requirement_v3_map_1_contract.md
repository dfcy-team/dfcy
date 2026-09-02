# SCM-V3-MAP-1 状态、实体、API、权限与历史数据映射合同

- 编号：`SCM-V3-MAP-1`
- 日期：2026-08-12
- 状态：`P1_REMEDIATED_READY_FOR_DOMAIN_CONTRACTS`
- 输入：SCM-REQ-V3、V3追踪矩阵、冲突台账、MAP-0路线状态合同
- 环境：仅架构员本机和隔离数据库
- 禁止：本合同不授权模型、迁移、API、客户端、历史数据或正式系统变更

## 1. 映射原则

1. 两份最新需求定义业务语义；当前协同架构定义实现方式。
2. 每份数据只有一个权威聚合；展示状态和报表字段只读派生。
3. 所有业务对象必须具备租户或供应商归属、审计时间和受控写入口。
4. 源 `profiles/role/RLS/RPC/Storage URL` 不原样迁移；转换到 accounts、Permission/DataScope、DRF领域服务和受控附件。
5. 历史数据只按可证明事实映射；未知、矛盾、超量和跨租户记录进入人工队列。

## 2. 核心实体映射

| 源实体/表 | 目标聚合 | 决定 | 权威字段与约束 |
| --- | --- | --- | --- |
| `profiles` | `accounts.CustomUser` + Internal/External profile + `MiniAppIdentity` | 扩展映射 | 用户类型、激活、供应商绑定、微信subject分离；不迁移明文密钥 |
| `role_permissions/custom_roles/custom_role_permissions` | accounts Role/Permission/UserRole/DataScope | 弃用旧表 | 角色仅模板；授权按exact permission及DataScope |
| `product_categories` | `products.ProductCategory` | 复用/字段核对 | 租户、编码、父级、层级、启停唯一性 |
| `products` | `ProductSPU` + `ProductSKU`及受控图片 | 拆分扩展 | SPU/SKU、尺寸重量、采购属性、图片附件；禁止公开写bucket |
| `suppliers` | `masterdata.SupplierMaster` + External profile/capability | 复用扩展 | 租户内编号唯一、启停、联系人PII、装箱/集货能力 |
| `shipping_companies` | 新建 `CarrierMaster` | 新建 | 租户内编码唯一、运输方式、区域、税率、联系人；删除改停用 |
| `purchase_orders` | `purchasing.SupplyPurchaseOrder` | 复用扩展 | 订单号、供应商、路线undecided/loose/container、路线模式、状态版本 |
| `purchase_order_items` | `SupplyPurchaseOrderLine` | 复用扩展 | SKU快照、订购/完工数量、价格；数量累计不由客户端写 |
| `production_progress_logs` | 采购事件/履约事件 | 转换 | 追加式事件；预计日期与周期形成动作快照 |
| 履约累计 | `SupplyOrderLineFulfillment` + `SupplyFulfillmentEvent` | 复用 | production/reserved/packed/shipped/received/cleared守恒与可重建 |
| `packing_batches` | `packing.PackingBatch` + Order/Allocation/Event | 复用扩展 | 多订单、多批次、version、完成冻结；`admin_status`只读派生 |
| `packing_boxes/items` | `PackingBox` + `PackingBoxItem` | 复用 | 箱号、尺寸重量体积、明细数量；同箱有效消费唯一 |
| 装箱审核/变更 | ChangeRequest + ControlledAttachment/Event | 复用扩展 | 审核原因、规定证据、accepted历史不可篡改 |
| `dispatch_photos/inspection_videos/settlement_attachments` | `files.ControlledAttachment` | 合并转换 | 服务端派生绑定、哈希、MIME/大小/扫描、替代链；拒绝任意URL |
| `site_settings` | 新建租户级 `SupplyChainSetting` | 新建 | typed key、value、version、权限、审计；含单批次开关 |
| `containers/container_orders/container_boxes` | 新建 Container/Participant/BoxAllocation | 新建 | 柜号、9态、参与供应商、封条、箱消费、版本；不得由Shipment冒充 |
| `container_box_change_requests/logs` | 新建 ContainerBoxChangeRequest/Event | 新建 | 前后箱快照、理由>=10、审批、通知、追加审计 |
| 区域集货 | `ConsolidationSite`、`LooseCargoConsolidation`、Allocation/Event | 复用 | regional_groupage专用；站点、发布、交接、收货、消费权转移 |
| 散货发运 | `LooseCargoShipment`、Allocation/Event | 扩展 | 增加direct/groupage模式映射；状态权威按MAP-0 |
| `order_costs` | 新建 OrderCost/CostAllocation/Event | 新建 | 币种、汇率、分摊基数、舍入、版本、结算与修改日志 |
| 货运/供应商费用 | 新建 CarrierSettlement/SupplierSettlement | 新建 | 期间、应付、已付、状态、引用与审计 |
| `warehouse_clearance*` | 新建 WarehouseClearance/Item/OrderLink/Event | 新建 | 清单号、来源、采购/实收/差异、pending/completed、导出快照 |
| `wechat_notifications/supplier_notifications/feishu_logs` | 新建/复用统一 Notification/DeliveryAttempt/Preference | 新建映射 | 事件、渠道、模板、状态、偏好、跳转目标；密钥不入业务表 |
| `miniprogram_pages` | 发布配置/合规内容聚合 | 新建 | 路径、内容版本、发布审核、同意/注销审计 |
| 供应商评级视图 | 查询服务/快照或受控视图 | 新建 | 公式版本、时间窗、零分母、权限、导出快照 |

## 3. 状态权威边界

- Order、Shipment、Container和Packing审核映射严格引用 `scm_requirement_v3_route_state_mapping_contract.md`。
- `ready_to_ship/shipping_review_pending/shipping/shipped` 等订单后段状态由履约及审核对象派生，不允许发货单最后写入覆盖。
- `PackingBatch.admin_status`、源5态发货状态属于DTO展示映射，不新增客户端可写字段。
- Container 9态由未来Container聚合写入；Shipment只保存运输后段事实。
- 未知旧状态保存原值和来源，标记 `MANUAL_REVIEW_REQUIRED`，阻断新下游动作。

## 4. API动作映射

| 源RPC/能力 | DRF/领域映射 | 状态 | 写门禁 |
| --- | --- | --- | --- |
| 接单、开始生产、更新进度、完工 | purchasing orders actions | 已存在/扩展DTO | supplier binding或exact permission、version、idempotency |
| `mark_production_complete` | 领域服务完工动作 | 已存在/扩展 | 服务端反查明细，数量守恒 |
| 路线选择 | order `assign-shipping-route` | 已存在/扩展模式 | 授权采购、生产完成、无下游消费 |
| `check_unfinished_packing_batch` | packing创建前领域查询/校验 | 新增设置适配 | 租户开关；数据库数量约束不依赖开关 |
| `end_packing_batch` | batch complete | 已存在 | expected_version、Idempotency-Key |
| 标签PDF | batch/box generate-label | 已存在/补客户端 | 准入字体、renderer输入快照 |
| 装箱审核 | change/review + controlled attachments | 扩展 | 规定证据accepted、权限分离 |
| `create_shipment` | direct shipment或groupage Shipment创建 | 需扩展 | 明确模式、箱有效消费唯一 |
| 散货运单/出货审核 | 新建direct-dispatch动作API | 新建 | 受控附件、审核与发货权限分离 |
| 集货安排/交接/收货/转发运 | consolidation既有API | 已存在 | DataScope全维度、供应商裁剪DTO |
| 报关/发货/到港/到仓/清货 | shipping既有actions | 已存在/扩展 | Idempotency-Key、expected_version、事件 |
| 货柜装柜/调箱 | Container专用API | 新建 | 独立权限、箱锁、审批、审计 |
| 图片/视频上传 | upload-session/finalize/status/ticket | 部分存在 | token、hash、scan fail-closed、生产存储另审 |
| 费用分摊/结算 | Cost领域API | 新建 | 公式版本、原子重算、日志 |
| 仓库清单/导出 | Clearance API | 新建 | 数据范围、完成冻结、受控下载 |
| 评级查询/Excel | Report API/异步导出 | 新建 | 报表权限、DataScope、筛选快照 |
| 微信绑定/通知偏好 | accounts/notification API | 部分/新建 | 原生wx.login、服务端换取、用户只能改自身偏好 |

所有写API统一要求适用的 `Idempotency-Key`、`expected_version`、服务端权威字段反查和确定性错误码。旧RPC名只保留在需求追踪，不作为新公开接口。

## 5. 权限与DataScope映射

| 业务模板角色 | exact permission族 | DataScope/归属 |
| --- | --- | --- |
| admin | 配置、用户、角色、全供应链动作 | tenant内ALL；不可跨租户 |
| purchaser | purchase_order、production、route、部分consolidation | supplier/order/batch/site/consolidation IDs |
| logistics | packing review、carrier、container、shipment、customs | carrier/container/shipment及相关全链维度 |
| staff/warehouse | 被授权查询、收货、到仓、清货 | warehouse/order/shipment清单维度 |
| supplier | 不分配内部角色 | external/miniapp channel + supplier binding + capability + 对象归属 |

新增领域权限须按动作拆分，至少包括 carrier、container、container box-change、cost、clearance、report、notification、settings。集货/发运沿用现有 `supply.consolidation.*`、`supply.shipment.*`；OWN/DEPARTMENT不能用于多供应商聚合，必须ALL或完整CUSTOM。未命中统一404防枚举。

## 6. 客户端映射

- Web一级菜单固定 `产品开发 -> 供应链协同 -> 多平台刊登`；供应链子页面按V3 WEB ID逐波次增加。
- 当前 `SupplyFlowConsole` 仅代表集货/发运部分能力，不代表完整供应链网页端。
- 小程序当前10页保留；按 `MINI-FR/AC` 增加装箱、发货、货柜、消息、记录、账号与合规页面。
- Vue和原生小程序只提交目标ID、动作数据和受控引用，不提交租户、供应商、累计状态或扫描结论。
- Android/iPhone真机证据是客户端完成条件。

## 7. 历史数据迁移波次

1. `DISCOVER`：只读统计源租户、用户绑定、订单状态、路线、批次、箱、附件URL、费用和未知值。
2. `CLASSIFY`：分为可证明映射、需补主数据、状态冲突、数量冲突、跨租户、附件不可验证、人工处理。
3. `ADD`：只新增目标字段/表/约束和审计，不删除旧字段。
4. `BACKFILL`：按租户和稳定源ID幂等回填，记录摘要；禁止按比例猜测明细。
5. `DUAL_READ_VERIFY`：新旧读取对账，累计由事件重建；异常阻断切换。
6. `SWITCH_WRITE`：仅经审核的领域服务写新权威源；旧入口只读。
7. `RETIRE`：在观察期、回滚演练和独立批准后退役旧字段/视图。

每波要求空库/合法历史/异常历史/正反向迁移、MySQL并发1205/1213、ORM绕过、跨租户和幂等重放门禁。正式线上迁移必须另立项，不复用本机凭据或数据库。

## 8. MAP-1退出条件

- 实体、状态、API、权限、客户端和迁移矩阵经独立审核；
- 新建聚合（Carrier/Container/Cost/Clearance/Notification/Setting/Rating）逐个形成领域合同；
- 未解决映射不得进入代码；
- 本合同本身不构成实现授权。
