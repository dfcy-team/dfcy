# SC-SHIPMENT-0 散货拼柜发运领域、API、权限与握手合同

- 日期：2026-08-08
- 状态：`FROZEN_APPROVED_FOR_LOCAL_IMPLEMENTATION`
- 上游：`SCM-REQ-V2-R1`、`SC-F2-MULTI-1`、`SC-CONSOLIDATION-0/1`、`SC-CONSOLIDATION-ATTACH-1`
- 环境：仅本机冻结；不连接货代、报关、承运商或正式线上系统

## 1. 权威边界

新建 `shipping` 领域作为本企业散货拼柜发运的权威源。现有 `suppliers.SupplierShipment` 仅保留供应商历史自报记录，不得作为 consolidation transfer 目标，也不得驱动 packing shipped 投影。

本系统只保存本企业箱件、受控外部引用和本企业动作事件；不保存其他公司货物的订单、商品、供应商或箱明细。外部货代/报关/承运系统仍是其自身业务账本权威源，首期只允许人工录入受控引用。

## 2. 聚合模型

### 2.1 `LooseCargoShipment`

- `tenant`、租户内唯一 `shipment_no`、`route_type=loose_cargo_groupage`。
- `region_code`、起运集货站点快照、目的国家/港口/仓库快照。
- `status`、`version`、计划/实际时间。
- 受控外部引用：forwarder/groupage/container/customs/transport reference；不保存其他公司货物明细。
- 创建、更新、发布、报关、发货、到岸、到仓、清货、取消的操作者和时间。

### 2.2 `ShipmentBoxAllocation`

- shipment、consolidation、consolidation allocation、box、packing consumption。
- supplier/order/batch/box/数量/重量/体积及来源集货发布版本快照。
- `reserved -> transferred -> dispatched -> arrived_port -> arrived_warehouse -> cleared`；异常采用 append-only 事件，不从不可逆状态回退。
- 同箱只允许一个活动 shipment allocation；必须与 packing 的 active consumption 唯一槽一致。

### 2.3 `ShipmentEvent`

append-only，记录 tenant、shipment、allocation/box、action、actor/channel、before/after、reason、幂等键、请求 hash、证据/外部引用、版本和时间。禁止 update/bulk/delete。

## 3. 状态机与人工确认

`draft -> loading -> customs_declared -> dispatched -> port_arrived -> warehouse_arrived -> warehouse_cleared`

- draft：内部物流创建，可分多次从一个或多个 ready consolidation 预留完整箱。
- loading：至少一箱已原子从 consolidation consumption 转为 shipment consumption；仍未计 shipped。
- customs_declared：有权报关人员人工确认受控报关引用。
- dispatched：有权物流人员人工确认实际发货；此动作才 commit shipment consumption，并且每条履约投影只增加一次 shipped。
- port_arrived、warehouse_arrived、warehouse_cleared：依序由有权人员确认；到仓清货与报关不得混同。

取消只允许 draft 且所有箱尚未 transferred；已转移但未 dispatch 的纠错必须走受控转回 consolidation 的独立补偿合同，首期默认禁止。dispatched 后禁止取消或回退，异常追加事件。

系统不得自动报关、发货、到岸、到仓或清货；所有关键动作均需人工确认。

## 4. consolidation transfer 握手

- 只接受同 tenant、`ready_for_shipment`、有效 allocation 均为 received 的 consolidation。
- 目标必须是真实、同租户、draft/loading 且 region/route/目的地兼容的 `LooseCargoShipment`，禁止任意整数 consumer ID。
- 支持一个 consolidation 分多次转入多个 shipment，也支持一个 shipment 接收多个 consolidation；最小单位为完整物理箱。
- 按 shipment、consolidation、box ID 确定性加锁；批量任一箱失败整批回滚。
- 每箱调用既有 `transfer_box_consumption(consolidation -> shipment)`；转移不增加 packed 或 shipped。
- consolidation 仅在所有可发运箱均 transferred 时成为 transferred；部分转移时保持 ready 并由 allocation 派生进度。
- shipment dispatch 对全部本次 dispatch 箱调用 shipment commit；幂等重放不得重复增加 shipped。

## 5. 权限与 DataScope

exact permissions：

- `supply.shipment.view`
- `supply.shipment.create`
- `supply.shipment.update`
- `supply.shipment.allocate`
- `supply.shipment.customs.confirm`
- `supply.shipment.dispatch`
- `supply.shipment.port_arrival.confirm`
- `supply.shipment.warehouse_arrival.confirm`
- `supply.shipment.clearance.complete`
- `supply.shipment.exception.manage`
- `supply.shipment.cancel`

授权顺序：有效 internal 用户、非 supplier miniapp/RPA 通道、tenant、exact permission、permission-specific DataScope、对象状态与 expected_version。不得判断角色名称。

DataScope：ALL 或完整 CUSTOM。CUSTOM 同一配置必须覆盖 `shipment_ids`（已存在对象时）、`consolidation_ids`、`consolidation_site_ids`、全部 `supplier_ids`、`supply_purchase_order_ids`、`packing_batch_ids`；不得把残缺 scope 拼接授权。OWN/DEPARTMENT 拒绝。未命中对象统一 404 防枚举。

## 6. API 冻结

内部前缀：`/api/internal/supply-chain/shipments/`

- GET/POST shipments；GET/PUT shipment detail。
- POST `{id}/boxes/` 从 ready consolidation 分配完整箱。
- POST `{id}/actions/customs-declare/`。
- POST `{id}/actions/dispatch/`，可选择尚未 dispatched 的结构化 box allocation IDs；支持多次发货。
- POST `{id}/actions/port-arrival/`。
- POST `{id}/actions/warehouse-arrival/`。
- POST `{id}/actions/warehouse-clearance/`。
- POST `{id}/actions/exception/`、`cancel/`。

所有写动作要求 `Idempotency-Key` 和适用的 `expected_version`。客户端只提交目标 ID、动作数据和受控引用；tenant、route、supplier/order/batch、数量与消费权由服务端反查。

## 7. 并发、错误与审计

- tenant 全局幂等作用域：同键、主体、通道、动作、资源、请求 hash 重放；任一不同 409。
- MySQL 1205/1213 映射可重试冲突，客户端保留同键。
- 批量 allocation/dispatch 按 box ID 升序锁定，部分失败整批回滚。
- 错误沿用 400/401/403/404/409/422；外部系统不可用不影响首期人工引用录入。
- 审计不得保存报关全文、附件二进制、token、密钥、完整联系电话或其他公司货物数据。

## 8. API 与客户端边界

本合同批准本地领域模型实现，不等于 API 或页面准入。shipment 首期仅内部 Web；供应商小程序只显示自身原有交接状态，不暴露同柜其他供应商、拼柜商业信息、报关全文或其他公司货物。

Android/iPhone 必须验证时区 ISO 8601 显示、长引用换行、弱网重复提交、状态刷新和安全区；但不得在客户端推导权威状态。

## 9. 验收与停止条件

至少覆盖 2 tenant、3 supplier、多个 consolidation、多 shipment、部分转移、多次 dispatch、同箱并发双分配、dispatch 重放、跨租户/跨范围、ORM 绕过和 MySQL 约束。

守护指标：零同箱双消费、零 transfer 提前 shipped、零 dispatch 重复 shipped、零跨租户/供应商泄漏、零状态跳跃、零其他公司货物明细入库。任一失败停止进入 API/客户端阶段。

## 10. 明确不在本阶段

- 第三方货代、报关、船司、承运商 API。
- 自动报关、自动发货、费用结算、税费或财务凭证。
- 柜货路线的独立装柜聚合重构；本合同只承接散货集货后的拼柜发运。
- 生产部署与真实数据迁移。
