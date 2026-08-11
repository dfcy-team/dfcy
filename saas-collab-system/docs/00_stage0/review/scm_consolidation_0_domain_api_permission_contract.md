# SC-CONSOLIDATION-0 散货区域集货领域、API、权限与 DataScope 契约

- 日期：2026-08-08
- 状态：`FROZEN_APPROVED_FOR_LOCAL_IMPLEMENTATION`
- 上游：`SCM-REQ-V2-R1`、`SC-F2-MULTI-0/1`、`SC-F2-MULTI-1-MYSQL`
- 环境：仅本机契约冻结；不连接正式系统，不导入真实数据，不开放路由

## 1. 操作者、问题与 MVP 承诺

- 主要操作者：后端采购人员。
- 协作人员：供应商、物流/报关人员、仓库人员。
- 触发：散货路线订单产生一个或多个已完成装箱批次。
- 当前风险：不同供应商的散货箱缺少区域归集、明确集货地点、交接状态和统一发运衔接，容易发生错送、漏箱、重复发运和跨供应商信息泄露。
- MVP 承诺：采购能够把本企业不同供应商的已完成散货箱按区域分配到受控集货地点，供应商只查看自己的交接要求，集货点确认收货后将箱件原子转交发运聚合；所有数量、箱身份、权限和动作可审计。
- 行动级别：本机 L2 变更集；任何线上写入、货代连接、报关提交或正式发布均不在本阶段授权范围。

## 2. 系统边界与权威源

### 2.1 本系统权威数据

- 本企业采购订单、装箱批次、箱及箱明细；
- 本企业集货地点主数据；
- 本企业散货集货单、箱分配、交接要求、收货状态和异常；
- 本企业箱从 packing 到 consolidation、再到 shipment 的消费权转移；
- 与本企业货物相关的货代、拼柜、报关、运输引用编号；
- 操作者、通道、幂等键、请求哈希、前后版本、证据引用和审计事件。

### 2.2 系统外数据

- 其他公司货物的订单、商品、供应商、箱明细和商业资料；
- 货代/报关系统的完整业务账本；
- 承运商实时轨迹的原始权威数据。

首期只允许受控人工录入外部拼柜号、柜号、报关号和运输号，不连接第三方账号。外部引用不是本系统对其他公司货物的所有权声明。

## 3. 聚合定义

### 3.1 `ConsolidationSite` 集货地点

租户内受控主数据，建议字段：

- `tenant`、`site_code`、`name`、`region_code`；
- `country_code`、`province_state`、`city`、`district`、`address_line`、`postal_code`；
- `timezone`、`contact_name`、`contact_phone`、`delivery_instructions`；
- `is_active`、`effective_from`、`effective_to`、`version`；
- `created_by`、`updated_by`、`created_at`、`updated_at`。

约束：

- `(tenant, site_code)` 唯一；站点代码一经业务使用不得复用。
- `region_code` 是采购归集维度，由本企业维护；首期不从供应商地址自动决定。
- 停用站点不得用于新集货单，但历史单据继续显示快照。
- 地址、联系人和交接说明在集货单发布时生成快照，后续主数据变更不能重写历史安排。
- 联系电话属于受控个人信息，仅对需要交接的供应商和有权限内部用户返回。

### 3.2 `LooseCargoConsolidation` 散货集货单

一个采购确认的区域集货安排，建议字段：

- `tenant`、`consolidation_no`、`region_code`、`site`；
- `site_*_snapshot`、`collection_cutoff_at`、`expected_dispatch_at`；
- `status`、`version`、`note`；
- `external_forwarder_ref`、`external_groupage_ref`；
- `created_by`、`released_by/at`、`ready_by/at`、`cancelled_by/at/reason`；
- `created_at`、`updated_at`。

租户内 `consolidation_no` 唯一。集货单不保存其他公司货物明细。

### 3.3 `ConsolidationBoxAllocation` 集货箱分配

集货单与已完成物理箱之间的显式关系：

- `tenant`、`consolidation`、`box`；
- `packing_box_consumption`；
- `supplier/order/batch/box_no/quantity/weight/volume` 快照；
- `state`、`version`；
- `handover_method`、`handover_reference`；
- `handover_evidence_id/submitted_by/submitted_at`；
- `received_by/received_at`、`exception_code/exception_note`；
- `created_by`、`created_at`、`updated_at`。

约束：

- `(consolidation, box)` 唯一；一个箱只能存在一个活动 `PackingBoxConsumption`。
- 箱必须来自同租户、`loose_cargo` 路线、`completed` 装箱批次。
- 同一集货单只接收 `region_code`、站点、时间窗兼容的箱。
- 分配以完整箱为最小单位；拆箱必须回到 packing 受控更正流程。
- 附件只保存受控附件 ID，不接受客户端本地路径或任意 URL。

### 3.4 `ConsolidationEvent`

append-only 审计事件，至少包含：tenant、consolidation、allocation/box、action、actor、channel、before/after、reason、evidence reference、idempotency key、request hash、occurred_at。反向动作追加事件，不覆盖历史。

## 4. 状态机

### 4.1 集货单状态

| 状态 | 含义 |
| --- | --- |
| `draft` | 采购编辑站点、时间窗和箱分配，供应商不可见 |
| `released` | 安排已发布，供应商可查看自身箱的交接要求 |
| `receiving` | 至少一个箱已提交交接或集货点已开始收货 |
| `ready_for_shipment` | 所有有效箱均已收货或已形成明确异常处置，允许建立发运衔接 |
| `transferred` | 所有可发运箱的消费权已原子转移至一个或多个 shipment |
| `cancelled` | 草稿或未产生不可逆下游动作的集货单已受控取消 |

`partial_received`、`received_count` 和异常数由 allocation 汇总派生，不增加可被直接写入的集货单状态。

### 4.2 箱分配状态

`allocated -> handover_submitted -> received -> transferred`

异常支路：

- `allocated/handover_submitted -> exception`
- `allocated -> released`（仅发布前移除或受控取消）
- `exception -> received`（异常处理后确认收货）
- `exception -> released`（采购批准退出本集货单）

不得从 `transferred` 回退。发运后异常通过 shipment/warehouse 反向事件处理。

## 5. 动作与人工审批点

| 动作 | 前置 | 主体 | 结果 |
| --- | --- | --- | --- |
| 创建集货单 | 采购具有站点和目标对象范围 | 内部采购 | `draft` |
| 分配箱 | 箱已完成、散货路线、未被活动消费 | 内部采购 | 创建 consolidation consumption 和 allocation |
| 移除箱 | `draft` 且未交接 | 内部采购 | 释放消费槽，allocation `released` |
| 发布安排 | 有至少一箱、站点有效、截止时间合法 | 内部采购 | 冻结站点快照，状态 `released` |
| 提交交接证据 | 已发布且为自身绑定供应商箱 | 外部供应商 | allocation `handover_submitted` |
| 确认集货收货 | 已发布/接收中且证据满足策略 | 内部物流/收货人员 | allocation `received` |
| 标记异常 | 箱未转发运 | 内部采购/物流 | allocation `exception` |
| 标记待发运 | 所有有效箱已收货或异常已处置 | 内部物流 | consolidation `ready_for_shipment` |
| 转入发运 | shipment 已存在、路线/租户兼容 | 内部物流 | consolidation consumption 原子转为 shipment consumption |
| 取消 | 所有箱仍为 allocated，且无交接/收货/转移事实 | 内部采购 | 释放所有未提交消费，集货单 `cancelled` |

系统可以建议区域或站点，但不能自动发布、收货、报关或发货。所有关键动作需要人工确认。

供应商已经提交交接证据后不得直接取消集货单或移除箱。采购必须先将该箱标记异常，记录货物实际位置和处置原因；只有确认货物未交付/已退回且无 received/transferred 事实时，才能通过受控异常释放动作退出本集货单。

## 6. 发运衔接边界

- 本阶段只冻结与 shipment 的握手，不实现报关、到岸、到仓和清货聚合。
- 一个集货单可以分多次发运；一个 shipment 可以接收多个兼容集货单的箱。
- 每个箱通过 SC-F2 的 `transfer_box_consumption` 从 consolidation 原子转到 shipment；不得同时保留两个活动消费者。服务端必须读取真实、同租户、可接收箱件的 Shipment 聚合并校验版本，禁止仅凭客户端提交的任意整数 `shipment_id` 调用通用消费服务。
- consolidation `transferred` 表示所有可发运箱均已转移，不表示实际发货。
- 只有 shipment dispatch/commit 增加 `shipped_quantity`；集货发布、收货和消费转移均不得增加发货量。
- 外部拼柜号、柜号、报关号和运输号由后续 shipment/customs 契约负责，集货单只保留可选前置引用。

## 7. 权限合同

### 7.1 内部 exact permissions

- `supply.consolidation_site.view`
- `supply.consolidation_site.manage`
- `supply.consolidation.view`
- `supply.consolidation.create`
- `supply.consolidation.manage`
- `supply.consolidation.allocate`
- `supply.consolidation.release`
- `supply.consolidation.receive`
- `supply.consolidation.exception.manage`
- `supply.consolidation.transfer`
- `supply.consolidation.cancel`

角色“采购、物流、仓库”仅是可配置模板，服务和视图不得判断角色名称。

### 7.2 内部授权顺序

`有效 internal 用户 -> 非 miniapp/RPA 通道 -> tenant -> exact permission -> permission-specific DataScope -> 对象状态/版本`

每个动作重新读取自身 exact permission 的 DataScope；view 权限不能替代 allocate/receive/transfer 权限。

### 7.3 外部供应商 capability

外部供应商不分配内部 Permission。固定要求：

- external 用户类型或 MiniApp supplier token；
- 当前 tenant 有效；
- supplier binding 有效；
- allocation 的 supplier 与绑定供应商一致；
- 集货单已发布；
- 动作状态允许；
- capability `supply.consolidation.handover.submit` 有效。

供应商只可读取自身 allocation 的裁剪 DTO，不返回其他供应商、其他订单、集货单箱总量、外部拼柜商业信息或内部备注。

## 8. DataScope 合同

### 8.1 允许的 scope

- `ALL`：当前租户全部集货数据。
- `CUSTOM`：必须在同一个 scope config 中声明动作所需完整维度。
- `OWN`、`DEPARTMENT`：本领域拒绝，返回 `DATA_SCOPE_INVALID`。集货单是多供应商聚合，按创建人或部门授权会泄漏其他供应商数据。

### 8.2 CUSTOM 键

- `consolidation_site_ids`
- `consolidation_ids`
- `supplier_ids`
- `supply_purchase_order_ids`
- `packing_batch_ids`

规则：

- 站点列表/详情至少要求 `consolidation_site_ids`。
- 创建集货单要求 site 命中，且全部目标 supplier/order/batch 同时命中同一有效 CUSTOM scope。
- 查看完整内部详情时，site、全部当前及历史 allocation 的 supplier/order/batch 必须同时包含在同一有效 scope；不能把不同角色的残缺维度拼接成授权。动作授权以全部当前有效 allocation 为对象范围，同时通过 append-only 审计保留历史；若调用者无历史对象范围，详情 DTO 不得返回该历史对象的商业快照，只返回不可枚举的审计摘要。
- `consolidation_ids` 可以进一步缩小范围，不能替代其他对象维度。
- 多个完整合法 scope 之间取并集；每个 scope 内部仍必须完整覆盖目标聚合。
- 缺 scope 返回 `DATA_SCOPE_MISSING`；类型或配置非法返回 `DATA_SCOPE_INVALID`；对象未命中范围返回 404，避免枚举。

## 9. API 路由与动作

### 9.1 内部 Web API

前缀：`/api/internal/supply-chain/consolidations/`

| 方法与路径 | Permission | 结果 |
| --- | --- | --- |
| `GET sites/` | `supply.consolidation_site.view` | 站点分页 |
| `POST sites/` | `supply.consolidation_site.manage` | 创建站点 |
| `GET sites/{id}/` | `supply.consolidation_site.view` | 站点详情 |
| `PUT sites/{id}/` | `supply.consolidation_site.manage` | expected_version 更新 |
| `POST sites/{id}/actions/deactivate/` | `supply.consolidation_site.manage` | 停用站点 |
| `GET consolidations/` | `supply.consolidation.view` | 集货单分页 |
| `POST consolidations/` | `supply.consolidation.create` | 创建草稿 |
| `GET consolidations/{id}/` | `supply.consolidation.view` | 完整内部详情 |
| `PUT consolidations/{id}/` | `supply.consolidation.manage` | 更新草稿基本信息 |
| `POST consolidations/{id}/boxes/` | `supply.consolidation.allocate` | 分配完整箱 |
| `POST consolidations/{id}/boxes/{allocation_id}/actions/remove/` | `supply.consolidation.allocate` | 发布前移除箱 |
| `POST consolidations/{id}/actions/release/` | `supply.consolidation.release` | 发布集货安排 |
| `POST .../boxes/{allocation_id}/actions/receive/` | `supply.consolidation.receive` | 确认收货 |
| `POST .../boxes/{allocation_id}/actions/exception/` | `supply.consolidation.exception.manage` | 标记/处理异常 |
| `POST consolidations/{id}/actions/ready/` | `supply.consolidation.receive` | 标记待发运 |
| `POST consolidations/{id}/actions/transfer/` | `supply.consolidation.transfer` | 转入 shipment |
| `POST consolidations/{id}/actions/cancel/` | `supply.consolidation.cancel` | 受控取消 |

### 9.2 供应商 Web API

前缀：`/api/external/supplier/consolidations/`

- `GET assignments/`
- `GET assignments/{allocation_id}/`
- `POST assignments/{allocation_id}/actions/submit-handover/`

### 9.3 微信小程序 API

前缀：`/api/miniapp/supply-chain/consolidations/`

与供应商 Web 使用相同安全 DTO 和 capability：

- `GET assignments/`
- `GET assignments/{allocation_id}/`
- `POST assignments/{allocation_id}/actions/submit-handover/`

MiniApp token 与 internal JWT、普通 external session、RPA token 必须通道互斥。

## 10. DTO 冻结

### 10.1 创建草稿

```json
{
  "site_id": 10,
  "region_code": "CN-SOUTH",
  "collection_cutoff_at": "2026-08-12T10:00:00+08:00",
  "expected_dispatch_at": "2026-08-13T18:00:00+08:00",
  "note": "internal note"
}
```

### 10.2 分配箱

```json
{
  "box_ids": [101, 102],
  "expected_version": 3
}
```

服务端从 box 反查 batch、supplier、order、route 和 DataScope，客户端不得提交这些权威字段。

### 10.3 发布/收货/异常/取消

所有写动作必须包含 `expected_version`；异常和取消必须包含非空 reason；证据只接收已由附件服务签发且属于当前 tenant/业务对象的 `evidence_id`。

发布冻结规则：`site/region/time window/site snapshot/current allocations` 在 release 时形成发布版本。首期发布后禁止新增或移除箱；变化必须先在无交接/收货事实时执行受控撤回发布，生成新版本后重新发布。已经存在 `handover_submitted/received/transferred` 的集货单不得撤回发布。

### 10.4 供应商 DTO

只返回：allocation ID、该供应商自己的订单号/批次号/箱号、箱数/重量/体积、站点必要地址与联系人、截止时间、交接说明、本人交接状态和证据状态。不得返回内部用户 ID、其他供应商汇总、内部 note、DataScope 或审计前后快照。

## 11. 幂等、并发与锁

- 所有 POST/PUT 强制 `Idempotency-Key`（1-128 printable ASCII）和适用的 `expected_version`。
- API 幂等记录使用 `(tenant, scope_key, idempotency_key)` 与 tenant 全局 key 防跨动作复用；重放前重新鉴权。
- 同键同主体同通道同动作同资源同请求哈希返回原响应；任何一项不同返回 409。
- 确定性加锁顺序：tenant 序列（如需）-> site -> consolidation -> order -> line fulfillment -> batch -> box -> packing consumption -> allocation -> shipment。
- 分配多个箱时按 box ID 升序锁定，任一箱失败整批回滚，不允许部分成功。
- 转发运时按箱 ID 升序调用/复用 packing consumption 原子转移；任一失败整批回滚。
- MySQL 1205/1213 映射为可重试冲突，客户端保持同一幂等键。

## 12. 错误与审计

复用现有统一响应。至少包括：

- 400 `VALIDATION_ERROR`
- 401 `AUTHENTICATION_FAILED`
- 403 `PERMISSION_DENIED` / `DATA_SCOPE_MISSING` / `DATA_SCOPE_INVALID`
- 404 `RESOURCE_NOT_FOUND`
- 409 `STATE_CONFLICT` / `VERSION_CONFLICT` / `IDEMPOTENCY_CONFLICT`
- 422 `BUSINESS_RULE_VIOLATION`

审计必须覆盖站点创建/更新/停用、集货创建/更新、箱分配/移除、发布、供应商交接、收货、异常、ready、转发运和取消。日志不得保存完整联系电话、附件二进制、token 或密钥。

### 12.1 附件前置依赖

仓库当前没有在本契约中已证明可复用的供应链受控附件聚合。因此 `submit-handover` 的编码准入前必须先冻结最小附件合同：tenant、owner、business_type/id/version、media_type、size、hash、storage key、scan status、created_by/at，且禁止任意 URL。附件合同未通过审核时，可以实现集货核心模型，但不得开放交接证据上传 API 或客户端入口。

## 13. 微信小程序兼容门禁

- 供应商交接页遵守既有 Android/iPhone 兼容基线；真机验证地址换行、安全区、键盘和弱网。
- 媒体上传使用专用适配器，处理 Android/iPhone 拍照方向、压缩、HEIC、进度、取消和幂等。
- 站点地址和联系电话只在已发布且属于当前供应商的 allocation 中显示；取消/转移后按业务保留必要历史，不扩大可见范围。
- 所有时间 API 使用带时区 ISO 8601，客户端不得使用区域依赖字符串解析。

## 14. 明确不在本阶段

- 自动区域/站点决策；
- 其他公司货物明细管理；
- 第三方货代、报关或承运 API；
- shipment dispatch、报关、到岸、到仓、清货具体状态机；
- 费用、结算、税费和财务凭证；
- Web/小程序页面实现和线上发布。

## 15. 实现与验证波次

1. `SC-CONSOLIDATION-0-R1`：本文独立审核和 P1 整改。
2. `SC-CONSOLIDATION-1`：模型、迁移、领域服务、MySQL 并发和 ORM 绕过。
3. `SC-CONSOLIDATION-ATTACH-0`：交接证据最小附件合同与安全审核。
4. `SC-SHIPMENT-0`：发运聚合身份与 consolidation transfer 握手契约。
5. `SC-CONSOLIDATION-2`：API、权限、DataScope、三通道 DTO 和幂等；transfer/submit-handover 分别受上述前置门禁控制。
6. `SC-CONSOLIDATION-3`：Web 采购集货界面。
7. `SC-CONSOLIDATION-4`：供应商微信小程序交接页面和双真机门禁。

每波均执行契约冻结、独立审核、P1 整改、复核、实现、代码审核和提交后基线确认。未经生产审批不得部署。

## 16. 验收与停止条件

主要指标：采购能够在不重复消费箱件的前提下，把多个供应商的散货箱准确发布到指定集货地点并形成可追溯交接。

守护指标：零跨租户、零跨供应商数据泄漏、零同箱双消费、零集货动作提前记发货、所有重复请求确定性回放。

本机合成样本至少覆盖 2 个 tenant、3 个 supplier、6 个 order、12 个 batch、30 个 box、3 个 site、4 个 consolidation 和多次 shipment 转移。任一守护指标失败即停止进入客户端开发。
