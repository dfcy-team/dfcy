# 内部系统只读数据块接入审计（2026-09-29）

## 口径与结论

配置目录共有 85 个独立数据块；改动前生产只读业务接口仅上线 8 块。本次代码增量将明确存在租户归属模型、可公开字段投影和稳定 ID 分页的 14 块接入，代码目录达到 **22 已接入、63 待接入**。当前生产仍为 8 块，须另行发布后才会变为 22 块；不能将本地测试通过视作生产已开放。菜单的模块/数据块勾选只是调用方授权，不会自动生成业务 API。

知识库生产调用方已选 38 块：当前其中 7 块可读、31 块待接入。若发布本增量且调用方配置不变，将变为 **17 块可读、21 块待接入**；这会扩大既有已批准调用方的实际读取范围，发布前须复核其授权和交接范围。`suppliers` 已接入但知识库未选，不能读取。

## 本次新增的显式只读映射

| 模块 | 数据块代码 | 事实来源 | 2026-09-29 生产知识库租户行数/说明 |
| --- | --- | --- | --- |
| 基础档案 | `product_attributes`, `product_colors` | 商品属性、颜色档案 | 11、156 |
| 基础档案 | `product_mappings`, `product_bundles`, `platform_products` | 商品平台映射、组合明细、平台商品明细 | 0、2070、36000；映射可查但目前无记录 |
| 产品开发 | `product_research`, `development_projects` | 市调、开发项目 | 0、1；知识库未选 |
| 供应链协同 | `purchase_orders` | 采购订单 | 0；知识库未选 |
| 销售管理 | `sales_orders`, `sales_returns` | 订单及退款退货事实表 | 24802、0；不返回原始载荷哈希或买家信息 |
| 库存管理 | `inventory_snapshots` | 库存快照事实表 | 309224；知识库未选 |
| 达人管理 | `influencers`, `outreach_tasks`, `sample_fulfillments` | 达人、建联、送样实体 | 24945、238、8468；不返回联系电话、邮箱、备注和请求载荷 |

所有新增路由复用现有 HTTP Basic 客户端鉴权、审批/启用/有效期、来源 CIDR、租户过滤、分钟限流和分页上限；模型与字段均为服务端显式白名单。客户端只能 GET，不可指定任意 ORM 字段或进行写入。空数据块返回空列表，不代表同步数据已经建立。

## 模块余项盘点

| 模块 | 本次代码已接入 | 仍待接入的数据块 | 主要原因 |
| --- | ---: | --- | --- |
| 基础档案 | 13 | `product_costs`, `product_specifications`, `foundation_settings` | 成本需独立敏感数据授权；后两项缺清晰独立事实合同 |
| 产品开发 | 2 | `selection_requirements`, `requirement_reviews`, `development_archives`, `development_costs`, `development_sales`, `selection_retrospectives`, `development_dashboard` | 审批/成本/聚合语义需单独定义；不可直接套用单表投影 |
| 全球刊登 | 0 | `listing_tasks`, `listing_workbench`, `online_products`, `listing_category_mappings`, `listing_attribute_mappings`, `listing_logs`, `listing_exceptions`, `listing_profiles`, `listing_templates` | 当前生产对应租户记录均为 0；工作台/在线商品不是单一事实表，需确定可读合同 |
| 供应链协同 | 1 | `consolidations`, `supplier_shipments`, `supplier_performance`, `shipments` | 多业务域和供应商边界需补合同；当前供应商发货/绩效记录为 0 |
| 库存管理 | 1 | `inventory_workbench`, `inventory_alerts`, `replenishment_suggestions` | 工作台是视图/最新态；预警、建议需明确状态与口径 |
| 销售管理 | 2 | `sales_overview`, `store_sales`, `sku_sales`, `sales_exports`, `sales_data_quality`, `prices` | 汇总/导出/质量不是简单事实投影；价格中心仍待真实服务接入 |
| 达人管理 | 3 | `influencer_performance`, `influencer_bd_config` | 绩效/配置需独立合同，避免泄漏内部人员与规则 |
| 广告 | 0 | `advertising_overview`, `advertising_performance`, `advertising_reconciliation` | 当前后端无对应广告事实模型及稳定只读服务，不能只改“已接入”标记 |
| 经营分析 | 0 | `analytics_overview`, `analytics_sales`, `analytics_inventory`（广告两块同属广告模块） | 聚合指标口径、来源和时间窗待定义 |
| 经营决策 | 0 | `lifecycle_reviews`, `lifecycle_history`, `clearance_requests`, `business_alerts` | 决策记录和预警含内部操作语义，需另定投影及审批边界 |
| 财务中心 | 0 | `finance_imports`, `finance_analytics`, `platform_statements`, `withdrawal_records`, `bank_receipts`, `reconciliation_exceptions`, `reconciliation_matches`（广告对账同属广告模块） | 财务独立授权与脱敏要求，不能凭普通数据块勾选开放 |
| 报表中心 | 0 | `basic_reports`, `report_exports` | 报表动态字段及导出文件权限不能套用统一列表接口 |
| 流程协同 | 0 | `approval_records`, `workflow_exceptions`, `collaboration_events` | 审批内容与协同载荷需单独字段合同 |
| RPA 协同 | 0 | `rpa_tasks`, `rpa_runs`, `rpa_devices`, `rpa_manual_queue`, `rpa_stability`, `rpa_account_locks`, `rpa_page_signatures` | 任务载荷、账号/设备及运行证据可能含敏感信息，不宜直接开放 |

同一个广告块可能显示在广告与经营分析/财务两个模块下；总数按独立代码去重，不按表格逐行求和。零行数是该调用方租户在检查时点的聚合值，不代表全系统没有相应模型或 API。

