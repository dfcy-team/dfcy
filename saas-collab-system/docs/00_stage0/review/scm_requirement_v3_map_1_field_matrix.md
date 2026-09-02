# SCM-V3-MAP-1 逐实体字段映射矩阵

- 状态：`FROZEN_FOR_P1_RECHECK`
- 说明：`EXISTING`为当前模型；`PROPOSED`须经领域合同后实现；`ARCHIVE/MANUAL`不进入权威写模型。

## 字段通用合同

所有租户业务表必须有tenant FK `PROTECT` 和created/updated审计；租户停用而不物理删除。主数据及跨聚合FK统一`PROTECT`；聚合私有明细使用`CASCADE`，但完成/发布/发运聚合禁止物理删除，只能受控取消或反向事件。业务编号租户内唯一并索引。金额Decimal(18,6)+currency，数量PositiveBigInteger，重量/体积Decimal(18,6)，时间使用UTC aware datetime。附件二进制不入数据库。

保留分类：`RET-AUDIT`业务/事件长期保留且只追加；`RET-PII`账号停用后立即禁用访问，期限由租户合规配置，到期匿名化联系字段而保留业务主体ID；`RET-MEDIA`附件随业务审计期保留，到期删除二进制并保留hash/删除事件；`RET-TRANSIENT`上传会话/token过期即删除。任何实际期限必须由合规配置和删除作业审核，不得由开发人员硬编码。API默认脱敏，日志禁止PII、token和密钥。

| Map ID | 源实体 | 字段/字段组 → 目标 | 类型、约束与转换 | 安全/保留 |
| --- | --- | --- | --- | --- |
| `FIELD-001` | Profile | id/email/username/status→CustomUser；supplier_id→ExternalUserProfile；openid→MiniAppIdentity.subject_digest；notify_*→PROPOSED NotificationPreference | email/username唯一；supplier FK PROTECT；明文openid不迁移，哈希匹配 | `RET-PII`；日志脱敏 |
| `FIELD-002` | Supplier | id/code/name/status/contact/address/capabilities→SupplierMaster+capability | tenant+code unique；停用替代删除；联系人字段nullable；订单FK PROTECT | `RET-PII`联系人；主体`RET-AUDIT` |
| `FIELD-003` | PurchaseOrder | number/supplier/status/dates/bigseller/destination/route→SupplyPurchaseOrder | tenant+number unique；route默认undecided；旧cargo_type按MAP-0分类 | 业务审计长期保留 |
| `FIELD-004` | PurchaseOrderItem | product/sku/name/quantity/produced/shipped/price→Line+Fulfillment | SKU/名称快照；quantity bigint；price decimal；累计从事件回填，客户端只读 | 金额受财务权限 |
| `FIELD-005` | PackingBatch | supplier/batch/status/admin/review/is_finished/tracking→PackingBatch+Event+Review派生 | tenant+batch_no unique；admin/review为派生；tracking按direct合同 | 不原地改完成历史 |
| `FIELD-006` | PackingBox | batch/number/sequence/volume/weight→PackingBox | batch+box_no unique；decimal(18,6)；batch私有明细FK CASCADE；完成批次禁止物理删除 | `RET-AUDIT`标签快照 |
| `FIELD-007` | PackingBoxItem | box/order/item/sku/name/quantity→PackingBoxItem | FK PROTECT；数量>0；总量受allocation约束 | 商品快照审计 |
| `FIELD-008` | Shipment | carrier/tracking/estimated/actual/status/orders/batches→PROPOSED DirectShipment或现有LooseCargoShipment | mode决定唯一聚合；编号tenant unique；关联通过allocation，不存无约束数组 | 运单号受限展示 |
| `FIELD-009` | ShipmentOrder | shipment/order/quantity→ShipmentOrderAllocation | tenant一致；shipment+order+line unique/index；数量守恒 | ARCHIVE源ID |
| `FIELD-010` | ShipmentPackingBatch | shipment/batch→ShipmentBatchLink/BoxAllocation | 禁止仅批次链接绕过箱消费；箱分配是权威 | 源链接留审计 |
| `FIELD-011` | Container | number/status/type/destination/carrier/cbm/weight/cost→PROPOSED Container | tenant+number unique；9态；carrier PROTECT；version | 财务字段分权 |
| `FIELD-012` | ContainerOrder | container/order/loaded/departed→ContainerParticipant/OrderLink | tenant一致；loaded数量由箱/明细汇总 | 不允许JSON作为权威量 |
| `FIELD-013` | ContainerBox | container/box/order/cost/cbm/weight→ContainerBoxAllocation | box active消费唯一；金额decimal；FK PROTECT | 分摊事件可重建 |
| `FIELD-014` | ContainerBoxChangeRequest | container/supplier/status/before/after/reason→Request+Event | reason>=10；前后结构化快照；version/idempotency | 追加审计，不覆盖 |
| `FIELD-015` | DispatchPhoto | order/type/url/review/uploader→ControlledAttachment | order/binding FK PROTECT；url→storage_key仅在可验证时；type枚举；review派生 | `RET-MEDIA` |
| `FIELD-016` | PackingBatchReviewPhoto | batch/type/review→ControlledAttachment binding | batch FK PROTECT；business_type/id/version强绑定；accepted不可回退 | `RET-MEDIA`；扫描fail-closed |
| `FIELD-017` | InspectionVideo | order/video/review/uploader→ControlledAttachment | order FK PROTECT；MIME/size/hash/scan；任意URL归ATTACHMENT_UNVERIFIED | `RET-MEDIA` |
| `FIELD-018` | PackingBatchInspectionVideo | batch/video/review→ControlledAttachment | 同FIELD-016；条件必传由服务端能力派生 | 不向同柜他商泄露 |
| `FIELD-019` | ProductionProgressLog | order/item/previous/current/estimate/cycle→SupplyFulfillmentEvent/OrderEvent | append-only；request_key unique per tenant/action | 操作者审计 |
| `FIELD-020` | Notification | type/title/content/related/read/status→PROPOSED Notification+DeliveryAttempt | tenant/related主体FK PROTECT；attempt为notification私有明细CASCADE；tenant+event key unique | `RET-PII`内容；禁密钥/完整电话 |
| `FIELD-021` | SiteSettings | key/value/description/version→PROPOSED SupplyChainSetting | tenant+typed key unique；JSON按schema验证；乐观version | 敏感值不回显 |
| `FIELD-022` | ProductCategory | name/code/parent/level→ProductCategory | tenant+code unique；parent同tenant；PROTECT有商品分类 | 非PII |
| `FIELD-023` | Product | sku/spu/name/category/unit/image/price/dimensions/origin/HS→SPU/SKU+Attachment | SKU tenant unique；尺寸decimal；图片受控；旧公开URL仅ARCHIVE | 采购价受权限 |
| `FIELD-024` | ShippingCompany | code/name/method/rate/tax/region/contact→PROPOSED CarrierMaster | tenant+code unique；Decimal；停用；订单/柜/发运FK PROTECT | `RET-PII`联系人；主体`RET-AUDIT` |
| `FIELD-025` | OrderCost | order/costs/tax/status/parent/bigseller/cbm/shipping_no→PROPOSED OrderCost/Allocation/Event | Decimal(18,6)+currency；公式版本；parent PROTECT；事件追加 | 财务保留/导出审计 |
| `FIELD-026` | WarehouseClearance | no/order/container/status/time→PROPOSED Clearance+OrderLink | tenant+no unique；来源二选一/合同校验；完成冻结 | 仓库权限 |
| `FIELD-027` | WarehouseClearanceItem | clearance/product/purchase/actual/difference→ClearanceItem | difference=actual-purchase服务端派生；数量bigint | 只读差异 |
| `FIELD-028` | Role/CustomRole | role/menu→accounts Role/Permission/DataScope | 旧menu_id转exact code；无法映射→MANUAL | 不迁移旧RLS策略 |
| `FIELD-029` | Notification logs | wechat/feishu status/method/stage→DeliveryAttempt | provider_message_id索引；内容摘要而非密钥 | provider响应脱敏 |
| `FIELD-030` | MiniprogramPage | path/title/status/remark→PROPOSED PublishedContent/PageReview | path+version unique；内容hash；发布审计 | 合规内容长期版本化 |
| `FIELD-031` | 供应商评级视图 | supplier/time/metrics/score→VersionedReportRow/Query | Decimal比例；formula_version；筛选snapshot | 导出受控、有过期票据 |

未列出的源字段必须在DISCOVER清单中标记 `ARCHIVE`、`DROP_APPROVED` 或 `MANUAL`；默认不得静默丢弃。FK跨租户、未知枚举和不合法精度均阻断回填。
