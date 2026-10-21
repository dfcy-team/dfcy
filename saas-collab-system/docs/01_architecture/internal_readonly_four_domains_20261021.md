# 销售、库存、财务、广告只读接入增量

基线：`f31e061ea584636d2247092cceb7ba93881994ea`。此文描述本地候选代码，正式可调用范围以目标环境 `GET /api/internal-readonly/v1/capabilities/` 返回为准。

## 数据块范围

本批将原先 20 个待接入块中的 19 个接入真实数据源，新增 8 个独立授权的数据块，增强已有 3 个数据块。广告费用对账仍待接入，返回具体原因。

| 模块 | 原目录补齐的代码 | 来源及口径 |
|---|---|---|
| 销售 | `operating_orders_v2` | 国家运营订货单，不是客户销售订单；商品行另授权 `operating_order_items` |
| 销售 | `sales_overview`、`store_sales` | 非取消订单，按平台、店铺、业务日期、币种汇总订单数和订单总额；不扣退款，不混币种 |
| 销售 | `sku_sales` | 非取消订单商品行，按平台、店铺、业务日期、SKU、卖家SKU、币种汇总数量和行金额；不扣退款 |
| 销售 | `sales_exports` | 已存在的 `sales_details` 导出申请状态和行数；无任务执行及文件下载能力 |
| 销售 | `sales_data_quality` | 历史销售同步质量检查的类型、状态和时间；不提供原始请求、详情JSON、错误自由文本 |
| 销售 | `prices` | 店铺商品价格快照：原价、促销价、有效价、币种及采集时间；不是供应商采购价 |
| 库存 | `inventory_workbench` | 每站点/仓库/来源SKU最新快照；先选择最新记录，再筛选与分页 |
| 库存 | `inventory_alerts` | 已持久化的库存预警、级别、库存口径、状态和事件时间 |
| 库存 | `replenishment_suggestions` | 已持久化的补货参数、建议数量/日期、置信度、状态和公式版本 |
| 财务 | `finance_imports` | CSV导入审计批次的类型、总行数、新增行数、跳过行数与时间；无导入执行能力 |
| 财务 | `finance_analytics` | 按账期/平台/币种汇总账单原额、已确认匹配金额、未解决异常数量及金额 |
| 财务 | `platform_statements` | 平台结算账单：原额、费用、净额、来源类型和状态；与平台逐笔费用明细分别提供 |
| 财务 | `withdrawal_records` | 提现金额、预计到账金额、申请/完成时间和状态 |
| 财务 | `bank_receipts` | 到账金额、日期、流水参考号、状态；账号仅脱敏值 |
| 财务 | `reconciliation_matches` | 账单、提现、到账的匹配关联、匹配金额、差额、置信度和状态 |
| 财务 | `reconciliation_exceptions` | 匹配异常的类型、差额、状态、发生与解决时间 |
| 广告 | `advertising_overview` | Shopee 店铺日报固定指标，不与活动日报叠加 |
| 广告 | `advertising_performance` | Shopee 活动日报固定指标，不与店铺日报叠加 |

新增的 8 个独立授权数据块：

| 代码 | 名称 | 主要内容 |
|---|---|---|
| `sales_order_items` | 销售订单商品明细 | 原订单、内部/平台商品标识、SKU、商品快照、数量、单价、折扣、税额、行总额和币种 |
| `sales_return_items` | 退款退货商品明细 | 退货单、原订单行、SKU、数量、退款金额和币种 |
| `operating_order_items` | 运营订货商品明细 | 运营订货单、SKU快照、数量、有效状态与版本 |
| `sales_sync_runs` | 销售同步运行记录 | 销售/退货同步状态、时间、获取/新增/更新/跳过/失败数量和错误代码 |
| `inventory_inbounds` | 库存入库明细 | 仓库、SKU、入库单及行号、计划/实收数量、状态与时间 |
| `inventory_shipments` | 库存发运明细 | 店铺、订单及商品行、SKU、发运单/行号、数量、状态与时间 |
| `finance_transactions` | 平台财务费用明细 | 平台/店铺/订单关联、费用类别、源金额、标准化带符号金额、币种、业务日期和匹配状态 |
| `advertising_tiktok_spend` | TikTok 广告日花费 | 广告主体、店铺、日期、花费、币种与采集时间；仅 BASIC/AUCTION_CAMPAIGN 范围 |

已有块增强：`sales_orders` 补充订单时间、分项金额、折扣和税费；`sales_returns` 补充案件类型、申请/完成时间、退款分项和退货标志；`inventory_snapshots` 补充在手、在途、待上架、瑕疵等数量。

库存数量字段须结合 `provided_quantity_fields` 判断源系统是否实际提供。未提供字段的默认零不代表已采集为零。入库、发运行也不代表系统已具备完整调拨/盘点/库存交易流水。

## 尚未接入的广告费用对账

`advertising_reconciliation` 继续可选，但不会发布为可读，调用返回 404 和 `reason`。仍缺少广告账户实际扣费账单、财务入账记录及二者与广告报表的关联规则。通用平台结算对账不能代替广告费用对账。

广告报表消耗不等于实际扣费。直接归因、广泛归因分别输出，不能相加；最近七天数据可能回补。Shopee 指标缺失、非法或非有限数返回 `null`，不补零。不提供未实现平台的展示量、点击量或订单指标。

## 调用配置与查询

管理员在“内部系统数据接口”选择模块和数据块，配置来源IP、有效期、分页和限流；另一位管理员审核通过后启用。每个块默认返回服务端定义的全部可读字段，不选择单个字段。

新增块需要显式授权；现有调用方不会自动获得新商品行、财务明细等数据块。已授权块的新增字段随完整块合同返回。旧版字段列表保存格式仍可提交，后端规范化为当前完整字段。

```http
GET /api/internal-readonly/v1/capabilities/
GET /api/internal-readonly/v1/sales_order_items/?sales_order_id=123&limit=100&cursor=0
GET /api/internal-readonly/v1/store_sales/?date_from=2026-10-01&date_to=2026-10-21&currency=USD
GET /api/internal-readonly/v1/inventory_workbench/?warehouse_id=12&limit=100
GET /api/internal-readonly/v1/finance_transactions/?store_id=5&date_from=2026-10-01
```

业务数据请求使用 HTTP Basic `client_id:client_secret`，仅由调用方服务端保存。实时能力目录中每个块提供 `fields`、`filters` 和 `note`；只有公布的筛选项有效。日期格式为 `YYYY-MM-DD`，起止日期均包含边界；财务账单/分析的日期筛选按账期开始日，其他块按各自业务/发生日期。无权块403，身份/来源错误401，未接入404，非法筛选400，超限429，业务写方法405。

分页读取 `data.items`，当 `has_more=true` 时使用 `next_cursor` 继续。聚合块先完整分组，再按组的最小记录ID分页；币种始终分组。ID游标只是本次扫描的分页位置，不是修改时间游标。后续数据回补、订单状态变化、已有价格更新时应从 `cursor=0` 重扫所需日期范围，不能仅记录最大ID来同步更新。

新建/增强块的 Decimal 金额、数量按精确字符串返回，空值保持 `null`，不经过浮点转换。调用方应使用十进制金额类型。

“接入资料”复制内容携带所选已接入块的字段、可用筛选项和口径说明，以及所选待接入块的明确缺口。密钥仅创建/轮换时一次性复制。

## 验证与发布边界

本批复用当前机器身份认证、来源地址、审核启用、限流与分页能力，新增读查询对直接及父级关联作租户过滤。无数据库结构迁移，无菜单/路由/权限目录变动。所有业务数据接口仅GET；不触发同步、导入、导出、计算、审批或回写。

测试覆盖真实非空数据、跨租户和异常关联、币种汇总、取消订单排除、聚合分页、最新库存、广告指标白名单、精度、授权和GET以外方法拒绝。最终测试结果见同批 review 记录。部署后须根据实际能力目录确认目标环境状态。
