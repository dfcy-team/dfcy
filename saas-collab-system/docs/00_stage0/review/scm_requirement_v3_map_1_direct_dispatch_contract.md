# SCM-V3-MAP-1 Direct Dispatch权威聚合合同

- 决定：新建 `DirectShipment` 聚合；不得复用或污染regional groupage专用`LooseCargoShipment`。
- 状态：`PROPOSED_CONTRACT_ONLY`

## 聚合

`DirectShipment`：tenant、shipment_no、supplier、carrier、tracking、estimated/actual、status、version、review/dispatch/delivery/cancel审计。`DirectShipmentBoxAllocation`引用已完成PackingBox及唯一活动PackingBoxConsumption；`DirectShipmentEvent`追加式；附件通过ControlledAttachment绑定聚合版本。

状态：`pending -> shipping_review_pending -> shipping -> in_transit -> delivered`，另有安全扩展`cancelled`。pending创建并预留箱；提交规定附件进入待审；审核通过shipping；dispatch提交一次shipped履约事实；deliver提交received/流程终点；拒绝不推进。所有转换要求允许前态、expected_version、幂等键和事件。

箱消费：同箱最多一个有效消费。创建为reserved，dispatch原子commit；取消仅在未dispatch时释放。不得把同箱同时分配给DirectShipment、Consolidation、Container或其他Shipment。

权限：供应商只能查看自身裁剪DTO、上传证据和提交审核；内部人员创建、审核、发货、送达、取消使用exact permission及完整DataScope。审核人与供应商提交者权限分离。

更正：已dispatch/delivered不得原地取消或覆盖；另立反向事件/更正合同。运单变更在发货前生成新version和事件。历史源shipment按明确货运单、无集货事实且箱关系可证明时映射；否则MANUAL_REVIEW_REQUIRED。

关系：DirectShipment承接散货直发；LooseCargoConsolidation/LooseCargoShipment承接区域集货；Container承接柜货。三种下游模式互斥但共用履约事件与箱消费底座。
