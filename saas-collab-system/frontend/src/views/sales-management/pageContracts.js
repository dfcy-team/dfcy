const platformOptions = [
  { label: 'Shopee', value: 'shopee' },
  { label: 'TikTok Shop', value: 'tiktok_shop' }
];

const regionOptions = [
  { label: '新加坡', value: 'SG' },
  { label: '英国', value: 'GB' },
  { label: '美国', value: 'US' }
];

const dateFilter = { key: 'date_range', label: '统计日期', type: 'daterange' };
const platformFilter = { key: 'platform', label: '平台', type: 'select', options: platformOptions };
const regionFilter = { key: 'region', label: '区域', type: 'select', options: regionOptions };
const storeFilter = { key: 'store_id', label: '门店', type: 'input', placeholder: '门店名称或编号' };
const currencyFilter = {
  key: 'currency', label: '币种口径', type: 'select',
  options: [{ label: 'SGD', value: 'SGD' }, { label: 'GBP', value: 'GBP' }, { label: 'USD', value: 'USD' }]
};

export const salesPageContracts = {
  overview: {
    eyebrow: '销售管理 / 只读分析',
    title: '销售总览',
    description: '判断当前销售表现、变化来源，以及需要优先关注的门店和 SKU。',
    permission: 'sales_management.view',
    filters: [dateFilter, platformFilter, regionFilter, storeFilter, currencyFilter],
    columns: [
      { prop: 'store_id', label: '门店' }, { prop: 'platform', label: '平台' }, { prop: 'region', label: '区域' },
      { prop: 'net_sales', label: '净销售额', numeric: true }, { prop: 'order_count', label: '订单量', numeric: true },
      { prop: 'refund_rate', label: '退款率', status: true }, { prop: 'source_updated_at', label: '更新时间', width: 180 }
    ],
    tableTitle: '重点门店',
    tableNote: '按净销售额排序，结合退款率与更新时间判断优先级。',
    emptyText: '当前范围还没有销售数据，请先确认门店授权和同步状态。'
  },
  orders: {
    eyebrow: '销售管理 / 订单核对', title: '销售订单',
    description: '按授权范围查询订单与订单行；客户信息默认脱敏。',
    permission: 'sales_management.orders.view',
    filters: [
      { ...dateFilter, label: '下单时间' }, platformFilter, regionFilter, storeFilter,
      { key: 'order_no', label: '订单号', type: 'input', placeholder: '平台或系统订单号' },
      { key: 'order_status', label: '订单状态', type: 'input' },
      { key: 'fulfillment_status', label: '履约状态', type: 'input' },
      { key: 'refund_status', label: '退款状态', type: 'input' },
      { key: 'sku', label: 'SKU', type: 'input' }, currencyFilter
    ],
    columns: [
      { prop: 'platform', label: '平台' }, { prop: 'region', label: '区域' }, { prop: 'store_id', label: '门店' },
      { prop: 'order_reference', label: '平台订单号', width: 150 }, { prop: 'ordered_at', label: '下单时间', width: 180 },
      { prop: 'order_status', label: '订单状态', status: true }, { prop: 'item_count', label: '商品数量', numeric: true },
      { prop: 'gross_amount', label: '原币金额', numeric: true }, { prop: 'net_amount', label: '本位币金额', numeric: true },
      { prop: 'buyer_region', label: '买家地区' }, { prop: 'refund_status', label: '退款状态', status: true },
      { prop: 'source_updated_at', label: '来源更新时间', width: 180 }
    ],
    tableTitle: '订单明细', tableNote: '只读核对，不提供编辑、发货、取消或退款操作。',
    emptyText: '没有匹配订单。可调整时间范围，或前往“数据同步与质量”检查同步状态。'
  },
  returns: {
    eyebrow: '销售管理 / 损失分析', title: '退款退货',
    description: '核对退款、退货和取消原因，分析损失及处理状态。',
    permission: 'sales_management.returns.view',
    filters: [
      { ...dateFilter, label: '申请时间' }, platformFilter, regionFilter, storeFilter,
      { key: 'order_no', label: '订单号', type: 'input' }, { key: 'return_type', label: '退款/退货类型', type: 'input' },
      { key: 'status', label: '状态', type: 'input' }, { key: 'reason', label: '原因', type: 'input' },
      { key: 'sku', label: 'SKU', type: 'input' }
    ],
    columns: [
      { prop: 'source_return_id', label: '退款单号', width: 150 }, { prop: 'order_reference', label: '订单号' },
      { prop: 'store_id', label: '门店' }, { prop: 'sku', label: 'SKU' }, { prop: 'quantity', label: '数量', numeric: true },
      { prop: 'requested_amount', label: '申请金额', numeric: true }, { prop: 'refunded_amount', label: '实际退款', numeric: true },
      { prop: 'normalized_reason', label: '统一原因' }, { prop: 'status', label: '状态', status: true },
      { prop: 'requested_at', label: '申请时间', width: 180 }, { prop: 'completed_at', label: '完成时间', width: 180 }
    ],
    tableTitle: '退款退货记录', tableNote: '首期只读，不在此处审批或发起平台退款。',
    emptyText: '当前范围没有退款退货记录。'
  },
  stores: {
    eyebrow: '销售管理 / 门店比较', title: '门店销售',
    description: '比较平台、区域和门店的销售、客单价、退款及同步表现。',
    permission: 'sales_management.stores.view',
    filters: [dateFilter, platformFilter, regionFilter, storeFilter, currencyFilter],
    columns: [
      { prop: 'store_id', label: '门店' }, { prop: 'platform', label: '平台' }, { prop: 'region', label: '区域' },
      { prop: 'gross_sales', label: '销售额', numeric: true }, { prop: 'net_sales', label: '净销售额', numeric: true },
      { prop: 'order_count', label: '订单量', numeric: true }, { prop: 'units_sold', label: '销量', numeric: true },
      { prop: 'average_order_value', label: '客单价', numeric: true }, { prop: 'refund_amount', label: '退款金额', numeric: true },
      { prop: 'refund_rate', label: '退款率', status: true }, { prop: 'source_updated_at', label: '最后同步', width: 180 }
    ],
    tableTitle: '门店表现', tableNote: '授权配置由 API 数据接入模块维护，此处仅展示安全引用。',
    emptyText: '尚无可比较门店，请先完成门店授权并等待同步。'
  },
  skus: {
    eyebrow: '销售管理 / 商品洞察', title: 'SKU 销售',
    description: '识别畅销、滞销和高退款 SKU，并引用最新库存风险。',
    permission: 'sales_management.skus.view',
    filters: [
      dateFilter, platformFilter, regionFilter, storeFilter,
      { key: 'spu', label: 'SPU', type: 'input' }, { key: 'sku', label: 'SKU', type: 'input' },
      { key: 'category', label: '品类', type: 'input' }, { key: 'inventory_risk', label: '动销/库存风险', type: 'input' }
    ],
    columns: [
      { prop: 'spu', label: 'SPU' }, { prop: 'sku', label: 'SKU' }, { prop: 'product_name', label: '商品名称', width: 180 },
      { prop: 'store_id', label: '门店' }, { prop: 'units_sold', label: '销售件数', numeric: true },
      { prop: 'gross_sales', label: '销售额', numeric: true }, { prop: 'net_sales', label: '净销售额', numeric: true },
      { prop: 'order_count', label: '订单量', numeric: true }, { prop: 'refund_units', label: '退款件数', numeric: true },
      { prop: 'refund_rate', label: '退款率', status: true }, { prop: 'inventory_risk', label: '库存风险', status: true },
      { prop: 'source_updated_at', label: '来源更新时间', width: 180 }
    ],
    tableTitle: 'SKU 表现', tableNote: '库存仅作只读风险参考，调整仍在库存/供应链模块完成。',
    emptyText: '没有匹配 SKU 销售数据，可检查 SKU 映射或同步新鲜度。'
  },
  exports: {
    eyebrow: '销售管理 / 受控操作', title: '销售明细导出',
    description: '在当前租户、角色和数据范围内创建脱敏导出任务。',
    permission: 'sales_management.export', filters: [],
    columns: [
      { prop: 'id', label: '任务号' }, { prop: 'export_type', label: '导出类型' },
      { prop: 'filter_summary', label: '筛选摘要', width: 220 }, { prop: 'scope_summary', label: '数据范围', width: 180 },
      { prop: 'created_by', label: '创建人' }, { prop: 'created_at', label: '创建时间', width: 180 },
      { prop: 'status', label: '状态', status: true }, { prop: 'record_count', label: '记录数', numeric: true },
      { prop: 'expires_at', label: '文件失效时间', width: 180 }
    ],
    tableTitle: '导出任务', tableNote: '创建、完成、下载和失败均写入审计；到期文件不可访问。',
    emptyText: '还没有导出任务。点击“新建导出”从当前授权范围开始。'
  },
  'data-quality': {
    eyebrow: '销售管理 / 数据可信度', title: '数据同步与质量',
    description: '查看来源、新鲜度和质量问题，并对授权失败任务提交重跑申请。',
    permission: 'sales_management.data_quality.view',
    filters: [platformFilter, regionFilter, storeFilter, { key: 'issue_type', label: '问题类型', type: 'input' }],
    columns: [
      { prop: 'severity', label: '级别', status: true }, { prop: 'issue_type', label: '问题类型' },
      { prop: 'platform', label: '平台' }, { prop: 'region', label: '区域' }, { prop: 'store_id', label: '门店' },
      { prop: 'message', label: '问题说明', width: 260 }, { prop: 'status', label: '状态', status: true },
      { prop: 'detected_at', label: '发现时间', width: 180 }
    ],
    tableTitle: '质量问题', tableNote: '重点检查重复、金额不平、退款回补、SKU 映射、币种、时区和迟到数据。',
    emptyText: '当前没有数据质量问题。仍建议核对最新同步时间。'
  }
};
