const dateFilter = { key: 'date_range', label: '统计日期', type: 'daterange' };
const platformFilter = { key: 'platform', label: '平台', type: 'select', optionSource: 'platforms' };
const storeFilter = { key: 'store_id', label: '门店', type: 'select', optionSource: 'stores' };
const currencyFilter = { key: 'currency', label: '币种口径', type: 'select', optionSource: 'currencies' };

export const salesPageContracts = {
  overview: {
    eyebrow: '销售管理 / 只读分析',
    title: '销售总览',
    description: '按授权店铺和来源币种核对订单、销售、退款与净销售表现。',
    permission: 'sales_management.view',
    filters: [dateFilter, platformFilter, storeFilter, currencyFilter],
    columns: [
      { prop: 'store_code', label: '门店' }, { prop: 'platform', label: '平台' },
      { prop: 'region', label: '站点' }, { prop: 'currency', label: '币种' },
      { prop: 'gross_sales', label: '销售额', numeric: true }, { prop: 'refund_amount', label: '退款额', numeric: true },
      { prop: 'net_sales', label: '净销售额', numeric: true }, { prop: 'order_count', label: '订单数', numeric: true },
      { prop: 'units_sold', label: '件数', numeric: true }, { prop: 'source_updated_at', label: '更新时间', width: 180 }
    ],
    tableTitle: '门店概览',
    tableNote: '金额始终按币种分组；没有受控汇率时不生成跨币种合计。',
    emptyText: '当前授权范围还没有销售事实数据。'
  },
  orders: {
    eyebrow: '销售管理 / 订单与售后', title: '销售订单',
    description: '在订单列表与详情中合并展示退款退货，不提供独立退款页面。',
    permission: 'sales_management.orders.view',
    filters: [
      { ...dateFilter, label: '下单时间' }, platformFilter, storeFilter, currencyFilter,
      { key: 'external_order_id', label: '平台订单号', type: 'input' },
      { key: 'status', label: '订单状态', type: 'select', optionSource: 'order_statuses' },
      { key: 'has_refund_return', label: '是否有退款退货', type: 'select', options: [{ label: '有', value: 'true' }, { label: '无', value: 'false' }] },
      { key: 'refund_status', label: '退款状态', type: 'select', optionSource: 'refund_statuses' },
      { key: 'sku', label: 'Seller SKU', type: 'input' }
    ],
    columns: [
      { prop: 'platform', label: '平台' }, { prop: 'store.name', label: '门店' }, { prop: 'store.region', label: '站点' },
      { prop: 'external_order_id', label: '平台订单号', width: 180 }, { prop: 'raw_status', label: '原始状态' },
      { prop: 'normalized_status', label: '规范状态', status: true }, { prop: 'created_at_utc', label: '下单时间', width: 180 },
      { prop: 'currency', label: '币种' }, { prop: 'order_total_amount', label: '订单金额', numeric: true },
      { prop: 'item_count', label: '件数', numeric: true }, { prop: 'refund_summary.case_count', label: '退款单数', numeric: true },
      { prop: 'refund_summary.refund_amount', label: '退款金额', numeric: true },
      { prop: 'refund_summary.latest_status', label: '最新售后状态', status: true }
    ],
    tableTitle: '订单与退款摘要', tableNote: '取消订单不会被推导为退款，退款金额只取退款事实表。',
    emptyText: '没有匹配订单，请调整筛选或在 API 数据接入模块检查同步。'
  },
  stores: {
    eyebrow: '销售管理 / 门店比较', title: '门店销售',
    description: '按授权 Store、站点和币种比较销售、退款及最近同步。',
    permission: 'sales_management.stores.view',
    filters: [dateFilter, platformFilter, storeFilter, currencyFilter],
    columns: [
      { prop: 'store_code', label: '门店' }, { prop: 'platform', label: '平台' }, { prop: 'region', label: '站点' },
      { prop: 'currency', label: '币种' }, { prop: 'order_count', label: '订单', numeric: true },
      { prop: 'units_sold', label: '件数', numeric: true }, { prop: 'gross_sales', label: '销售额', numeric: true },
      { prop: 'refund_amount', label: '退款额', numeric: true }, { prop: 'net_sales', label: '净额', numeric: true },
      { prop: 'average_order_value', label: '客单价', numeric: true }, { prop: 'refund_rate', label: '退款率', numeric: true },
      { prop: 'source_updated_at', label: '最近同步', width: 180 }
    ],
    tableTitle: '门店表现', tableNote: '按来源币种分别汇总，不做无依据换算。',
    emptyText: '尚无可比较门店。'
  },
  skus: {
    eyebrow: '销售管理 / 商品洞察', title: 'SKU 销售',
    description: '按内部 SKU 或平台 Seller SKU 核对销量、退款与映射状态。',
    permission: 'sales_management.skus.view',
    filters: [dateFilter, platformFilter, storeFilter, currencyFilter, { key: 'spu', label: 'SPU', type: 'input' }, { key: 'sku', label: 'SKU', type: 'input' }],
    columns: [
      { prop: 'internal_sku', label: '内部 SKU' }, { prop: 'seller_sku', label: 'Seller SKU' },
      { prop: 'platform_product_id', label: '平台商品 ID' }, { prop: 'platform_variant_id', label: '平台规格 ID' },
      { prop: 'mapping_status', label: '映射状态', status: true }, { prop: 'product_name', label: '商品快照', width: 180 },
      { prop: 'currency', label: '币种' }, { prop: 'units_sold', label: '销量', numeric: true },
      { prop: 'gross_sales', label: '销售额', numeric: true }, { prop: 'refund_units', label: '退款数量', numeric: true },
      { prop: 'refund_amount', label: '退款额', numeric: true }, { prop: 'net_sales', label: '净额', numeric: true }
    ],
    tableTitle: 'SKU 表现', tableNote: '未映射 SKU 保持平台、店铺和 Seller SKU 粒度，不按名称误合并。',
    emptyText: '没有匹配 SKU 销售数据。'
  },
  returns: {
    eyebrow: '销售管理 / 订单与售后', title: '退款退货',
    description: '按授权门店查看退款、退货和取消相关事实，不执行平台侧写回。',
    permission: 'sales_management.returns.view',
    filters: [
      { ...dateFilter, label: '申请时间' }, platformFilter, storeFilter, currencyFilter,
      { key: 'status', label: '处理状态', type: 'select', optionSource: 'refund_statuses' },
      { key: 'case_type', label: '售后类型', type: 'input' },
      { key: 'sku', label: 'Seller SKU', type: 'input' }
    ],
    columns: [
      { prop: 'external_return_id', label: '售后单号', width: 170 },
      { prop: 'external_refund_id', label: '退款单号', width: 170 },
      { prop: 'platform', label: '平台' }, { prop: 'store.name', label: '门店' },
      { prop: 'store.region', label: '站点' }, { prop: 'external_order_id', label: '平台订单号', width: 170 },
      { prop: 'case_type', label: '类型' }, { prop: 'reason_code', label: '原因' },
      { prop: 'normalized_status', label: '处理状态', status: true },
      { prop: 'requested_at_utc', label: '申请时间', width: 180 },
      { prop: 'completed_at_utc', label: '完成时间', width: 180 },
      { prop: 'currency', label: '币种' }, { prop: 'refund_amount', label: '退款金额', numeric: true },
      { prop: 'requires_physical_return', label: '需实物退回', status: true }
    ],
    tableTitle: '退款退货事实', tableNote: '退款金额仅取退款事实；状态由平台来源映射，不支持直接修改。',
    emptyText: '没有匹配的退款退货记录。'
  },
  exports: {
    eyebrow: '销售管理 / 脱敏导出', title: '销售明细导出',
    description: '查看当前租户授权范围内的导出任务，并按当前筛选创建脱敏导出。',
    permission: 'sales_management.export',
    filters: [
      { key: 'status', label: '任务状态', type: 'input', placeholder: '输入任务状态' },
      { key: 'created_by', label: '申请人', type: 'input' }
    ],
    columns: [
      { prop: 'id', label: '任务编号', width: 180 }, { prop: 'export_type', label: '导出类型' },
      { prop: 'created_by', label: '申请人' }, { prop: 'record_count', label: '记录数', numeric: true },
      { prop: 'status', label: '任务状态', status: true }, { prop: 'created_at', label: '创建时间', width: 180 },
      { prop: 'completed_at', label: '完成时间', width: 180 }
    ],
    tableTitle: '导出任务', tableNote: '下载文件需继续经过租户、角色、数据范围和脱敏策略校验。',
    emptyText: '当前还没有销售明细导出任务。'
  },
  'data-quality': {
    eyebrow: '销售管理 / 同步质量', title: '数据同步与质量',
    description: '查看销售事实同步状态和数据质量问题；重跑、授权和凭证操作统一在 API 数据接入完成。',
    permission: 'sales_management.data_quality.view',
    filters: [
      { key: 'platform', label: '平台', type: 'select', optionSource: 'platforms' },
      { key: 'store_id', label: '门店', type: 'select', optionSource: 'stores' },
      { key: 'status', label: '问题状态', type: 'input', placeholder: '输入问题状态' }
    ],
    columns: [
      { prop: 'issue_type', label: '问题类型' }, { prop: 'severity', label: '级别', status: true },
      { prop: 'status', label: '状态', status: true }, { prop: 'platform', label: '平台' },
      { prop: 'region', label: '站点' }, { prop: 'store_id', label: '门店' },
      { prop: 'message', label: '问题说明', width: 260 }, { prop: 'detected_at', label: '发现时间', width: 180 }
    ],
    tableTitle: '质量问题', tableNote: '问题只读展示；重跑申请必须在同步任务模块发起并写入审计。',
    emptyText: '当前授权范围没有待处理的数据质量问题。'
  }
};

