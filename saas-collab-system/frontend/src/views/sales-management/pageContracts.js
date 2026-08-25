const dateFilters = [
  { key: 'date_from', label: '开始日期', type: 'date' },
  { key: 'date_to', label: '结束日期', type: 'date' }
];
const platformFilter = { key: 'platform', label: '平台', type: 'select', optionSource: 'platforms' };
const storeFilter = { key: 'store_id', label: '店铺', type: 'select', optionSource: 'stores' };
const currencyFilter = { key: 'currency', label: '币种', type: 'select', optionSource: 'currencies' };
const salesFilters = [...dateFilters, platformFilter, storeFilter, currencyFilter];

const storeColumns = [
  { prop: 'platform', label: '平台', format: 'platform' },
  { prop: 'region', label: '区域', width: 72 },
  { prop: 'store_name', label: '门店', secondary: 'source_alias', secondaryPrefix: 'ID ', width: 210 },
  { prop: 'quality', label: '授权/同步状态', format: 'sync-status', width: 130 },
  { prop: 'gross_sales', label: '销售额', format: 'row-money', width: 140 },
  { prop: 'net_sales', label: '净销售额', format: 'row-money', strong: true, width: 140 },
  { prop: 'order_count', label: '订单量', numeric: true },
  { prop: 'units_sold', label: '销量', numeric: true },
  { prop: 'average_order_value', label: '客单价', format: 'row-money', width: 120 },
  { prop: 'refund_rate', label: '退款率', format: 'rate' },
  { prop: 'source_updated_at', label: '最后同步时间', format: 'date-time', width: 170 }
];

export const salesPageContracts = {
  overview: {
    title: '销售总览',
    description: '按授权范围查看销售指标、数据质量和来源摘要。',
    permission: 'sales_management.view',
    filters: salesFilters,
    columns: storeColumns,
    tableTitle: '门店销售',
    emptyText: '当前授权范围还没有销售事实数据。'
  },
  orders: {
    title: '销售订单',
    description: '按授权范围查询订单与商品明细，原始价格、折扣价格和订单状态分别展示。',
    permission: 'sales_management.orders.view',
    filters: salesFilters,
    columns: [
      { prop: 'platform', label: '平台', format: 'platform' },
      { prop: 'store.region', label: '区域', width: 72 },
      { prop: 'store.name', label: '门店', secondary: 'source_alias', width: 190 },
      { prop: 'external_order_id', label: '平台订单号', mono: true, width: 190 },
      { prop: 'created_at_utc', label: '下单时间', format: 'date-time', width: 170 },
      { prop: 'normalized_status', label: '订单状态', format: 'order-status', secondary: 'raw_status', width: 150 },
      { prop: 'item_count', label: '商品数量', format: 'item-count', width: 105 },
      { prop: 'order_total_amount', label: '订单金额', format: 'row-money', width: 120 },
      { prop: 'refund_summary.latest_status', label: '退款状态', format: 'refund-status', width: 105 },
      { prop: 'updated_at_utc', label: '来源更新时间', format: 'date-time', width: 170 }
    ],
    tableTitle: '销售订单',
    emptyText: '没有匹配订单，请调整筛选或检查同步任务。'
  },
  returns: {
    title: '退款退货',
    description: '只读查看退款、退货与取消数据，核对原因、金额和处理状态。',
    permission: 'sales_management.returns.view',
    filters: salesFilters,
    columns: [
      { prop: 'platform', label: '平台', format: 'platform' },
      { prop: 'store.name', label: '门店', secondary: 'store.region', width: 180 },
      { prop: 'external_order_id', label: '平台订单号', mono: true, width: 180 },
      { prop: 'external_return_id', label: '退款/退货单号', mono: true, width: 185 },
      { prop: 'case_type', label: '类型', format: 'return-type', width: 155 },
      { prop: 'reason_code', label: '原因', width: 130 },
      { prop: 'refund_amount', label: '退款金额', format: 'refund-money', width: 120 },
      { prop: 'normalized_status', label: '处理状态', format: 'return-status', width: 205 },
      { prop: 'requested_at_utc', label: '发生时间', format: 'date-time', width: 160 },
      { prop: 'updated_at_utc', label: '同步时间', format: 'date-time', width: 160 }
    ],
    tableTitle: '退款退货',
    emptyText: '没有匹配的退款退货记录。'
  },
  stores: {
    title: '门店销售',
    description: '按区域和授权门店比较销售额、净销售额、订单量、客单价和退款率。',
    permission: 'sales_management.stores.view',
    filters: salesFilters,
    columns: storeColumns,
    tableTitle: '门店销售',
    emptyText: '尚无可比较门店。'
  },
  skus: {
    title: 'SKU销售',
    description: '按 Seller SKU 聚合销量、销售额、退款率和库存风险引用。',
    permission: 'sales_management.skus.view',
    filters: salesFilters,
    columns: [
      { prop: 'seller_sku', label: 'SKU', secondary: 'platform_variant_id', secondaryPrefix: 'SKU ID ', mono: true, width: 160 },
      { prop: 'product_name', label: '商品名称', width: 320 },
      { prop: 'platform', label: '平台', format: 'platform' },
      { prop: 'store_name', label: '门店', width: 150 },
      { prop: 'units_sold', label: '销量', numeric: true },
      { prop: 'gross_sales', label: '销售额', format: 'row-money', width: 120 },
      { prop: 'net_sales', label: '净销售额', format: 'row-money', strong: true, width: 120 },
      { prop: 'refund_units', label: '退款量', numeric: true },
      { prop: 'refund_rate', label: '退款率', format: 'rate' },
      { prop: 'active_days', label: '动销天数' },
      { prop: 'mapping_status', label: '库存风险引用', format: 'inventory-link', width: 145 }
    ],
    tableTitle: 'SKU销售',
    emptyText: '没有匹配 SKU 销售数据。'
  },
  exports: {
    title: '销售明细导出',
    description: '本地环境保留销售数据导出入口；CSV 与 Shopee/TikTok Shop 原始 TXT 由 API 数据接入查询结果生成。',
    permission: 'sales_management.export',
    filters: [],
    columns: [{ prop: 'id', label: '导出入口' }],
    tableTitle: '从已查询数据生成文件',
    emptyText: '当前没有可导出的查询结果。'
  },
  'data-quality': {
    title: '数据同步与质量',
    description: '检查授权引用、同步水位、数据延迟、质量问题和错误摘要。',
    permission: 'sales_management.data_quality.view',
    filters: salesFilters,
    columns: [
      { prop: 'platform', label: '平台', format: 'platform-resource' },
      { prop: 'region', label: '区域' },
      { prop: 'store_id', label: '门店', mono: true, width: 140 },
      { prop: 'authorization', label: '授权引用状态', format: 'authorization' },
      { prop: 'last_success_at', label: '最近成功时间', format: 'date-time', width: 170 },
      { prop: 'run_status', label: '最近运行状态', format: 'sync-run-status' },
      { prop: 'fetched_count', label: '同步水位', format: 'fetched' },
      { prop: 'delay', label: '数据延迟' },
      { prop: 'issue_count', label: '质量问题数' },
      { prop: 'error_summary', label: '错误摘要', width: 130 }
    ],
    tableTitle: '数据同步状态',
    emptyText: '当前授权范围没有同步任务。'
  }
};
