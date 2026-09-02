# SCM-V3-MAP-1 Exact Permission 与 DataScope 矩阵

| 领域 | exact permission codes | 通道 | DataScope决定 |
| --- | --- | --- | --- |
| Carrier | `supply.carrier.view`, `supply.carrier.create`, `supply.carrier.update`, `supply.carrier.deactivate` | internal | ALL或完整CUSTOM `carrier_ids,region_codes`；OWN/DEPARTMENT拒绝 |
| Container | `supply.container.view`, `supply.container.create`, `supply.container.update`, `supply.container.allocate`, `supply.container.review`, `supply.container.customs`, `supply.container.dispatch`, `supply.container.arrival`, `supply.container.clearance`, `supply.container.cancel` | internal | ALL或CUSTOM同时覆盖container,carrier,supplier,order,batch,box,warehouse IDs |
| Box change | internal：`supply.container.box_change.view`, `supply.container.box_change.review`；supplier只使用`container_box_change_submit` capability | supplier/internal | supplier仅本人箱；review仅internal exact permission |
| Direct shipment | `supply.direct_shipment.view`, `supply.direct_shipment.create`, `supply.direct_shipment.review`, `supply.direct_shipment.dispatch`, `supply.direct_shipment.deliver`, `supply.direct_shipment.cancel` | internal；supplier使用`direct_shipment_submit` capability | CUSTOM覆盖shipment,supplier,order,batch,box,carrier IDs；supplier binding+capability |
| Cost | `supply.cost.view`, `supply.cost.manage`, `supply.cost.allocate`, `supply.cost.settle`, `supply.cost.export` | internal | ALL或CUSTOM覆盖order,carrier,supplier,container,shipment IDs；OWN拒绝 |
| Clearance | `supply.clearance.view`, `supply.clearance.create`, `supply.clearance.update`, `supply.clearance.complete`, `supply.clearance.export` | internal | ALL或CUSTOM覆盖clearance,warehouse,order,container,shipment IDs |
| Report | `supply.report.production.view`, `supply.report.production.export`, `supply.report.cost.view`, `supply.report.cost.export`, `supply.report.supplier_rating.view`, `supply.report.supplier_rating.export` | internal | 查询和导出使用相同DataScope，不允许导出扩大范围 |
| Notification | `supply.notification.view`, `supply.notification.send`, `supply.notification.retry`, `supply.notification.template.manage` | internal；supplier只读自身无需内部permission | internal CUSTOM覆盖supplier/order/事件；supplier binding裁剪 |
| Setting | `supply.setting.view`, `supply.setting.manage`, `supply.integration.wechat.manage`, `supply.integration.feishu.manage` | internal | tenant ALL；CUSTOM/OWN/DEPARTMENT拒绝；密钥不可读回 |
| Existing | 现有 `supply.purchase_order.* / production.* / packing.* / consolidation.* / shipment.*` | 既有合同 | 沿用已冻结permission-specific DataScope |

授权顺序：channel/user type→tenant/supplier binding→exact permission/capability→permission-specific DataScope→对象状态/version→写动作。internal、supplier_web、miniapp令牌互斥；未命中对象统一404。角色admin/purchaser/logistics/staff/supplier只用于配置模板，不在代码判断。
