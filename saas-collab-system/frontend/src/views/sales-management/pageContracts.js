const dateFilter = { key: 'date_range', label: '统计日期', type: 'daterange' };
const platformFilter = { key: 'platform', label: '平台', type: 'select', optionSource: 'platforms' };
const storeFilter = { key: 'store_id', label: '门店', type: 'select', optionSource: 'stores' };
const currencyFilter = { key: 'currency', label: '币种口径', type: 'select', optionSource: 'currencies' };

export const salesPageContracts = {
  overview: {
    eyebrow: '销售管理 / 只读分析',
    title: '销售总览',
    description: '订单报告 · 核对订单概览、汇总趋势与按日明细。',
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
    description: '核对平台订单、商品明细和关联售后；退款退货页面可进一步筛选售后记录。',
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
    description: '店铺报告 · 核对各门店的订单、销售与退款表现。',
    permission: 'sales_management.stores.view',
    filters: [dateFilter, platformFilter, storeFilter, currencyFilter],
    columns: [
      { prop: 'store_code', label: '门店' }, { prop: 'platform', label: '平台' }, { prop: 'region', label: '站点' },
      { prop: 'currency', label: '币种' }, { prop: 'order_count', label: '订单', numeric: true },
      { prop: 'valid_order_count', label: '非取消订单数', numeric: true },
      { prop: 'units_sold', label: '件数', numeric: true }, { prop: 'gross_sales', label: '非取消订单销售额', numeric: true, width: 175 },
      { prop: 'refund_amount', label: '退款额', numeric: true }, { prop: 'net_sales', label: '净额', numeric: true },
      { prop: 'refund_case_count', label: '退款售后单数', numeric: true },
      { prop: 'cancelled_order_count', label: '取消订单数', numeric: true },
      { prop: 'cancelled_amount', label: '取消订单金额', numeric: true },
      { prop: 'average_order_value', label: '平均订单金额', numeric: true }, { prop: 'refund_rate', label: '退款率', numeric: true },
      { prop: 'source_updated_at', label: '最近同步', width: 180 }
    ],
    tableTitle: '汇总明细', tableNote: '按门店、站点和币种汇总；点击表头对全部筛选结果排序。金额跨币种不可直接比较。',
    emptyText: '尚无可比较门店。'
  },
  skus: {
    eyebrow: '销售管理 / 商品洞察', title: 'SKU 销售',
    description: '销量报告 · 按店铺 SKU 或内部商品 SKU 核对商品销量与退款。',
    permission: 'sales_management.skus.view',
    filters: [dateFilter, platformFilter, storeFilter, currencyFilter, { key: 'sku', label: 'SKU 编号（模糊搜索）', type: 'input' }],
    columns: [
      { prop: 'store_name', label: '门店名称', width: 200 },
      { prop: 'platform', label: '平台' }, { prop: 'region', label: '站点' },
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
    emptyText: '当前筛选未返回质量问题；不代表所有同步成功，请同时核对上方任务状态。'
  }
};

// One field contract for list and detail display; raw identifiers remain unchanged.
const moneyFields = new Set(['gross_sales', 'refund_amount', 'net_sales', 'cancelled_amount', 'average_order_value', 'order_total_amount', 'refund_summary.refund_amount']);
const dateFields = new Set(['source_updated_at', 'created_at_utc', 'requested_at_utc', 'completed_at_utc', 'created_at', 'completed_at', 'detected_at']);
for (const contract of Object.values(salesPageContracts)) {
  contract.filters = contract.filters.map(filter => filter.label === 'Seller SKU' ? { ...filter, label: '平台 SKU' } : filter);
  contract.columns = contract.columns.flatMap(column => {
    if (column.prop === 'store_code') return [
      { prop: 'store_name', label: '门店名称', width: 200, fallback: 'store_code' },
      { ...column, label: '门店编码', width: 190 }
    ];
    return [column];
  }).map(column => {
    const field = { ...column };
    if (moneyFields.has(field.prop)) field.format = 'money';
    if (field.prop === 'refund_rate') { field.format = 'ratio'; field.label = '退款金额占比'; }
    if (dateFields.has(field.prop)) { field.format = 'datetime'; field.label += '（UTC）'; field.width = 195; }
    if (field.prop === 'source_updated_at') field.label = '来源更新时间（UTC）';
    if (field.prop === 'platform') field.format = 'platform';
    if (['case_type', 'export_type'].includes(field.prop)) field.format = 'enum';
    if (field.prop === 'internal_sku') field.empty = '未关联';
    if (field.prop === 'seller_sku') { field.label = '平台 SKU'; field.width = 190; }
    if (field.prop === 'store.name') { field.label = '门店名称'; field.width = 200; }
    if (field.prop === 'store_id') field.label = '门店标识';
    if (field.prop === 'raw_status') field.label = '平台原始状态';
    if (field.prop === 'net_sales') field.label = '净销售额';
    if (field.prop === 'order_count') field.label = '订单数（单）';
    if (['units_sold', 'item_count'].includes(field.prop)) field.label = '销售数量（件）';
    if (field.prop === 'normalized_status' && contract === salesPageContracts.orders) field.label = '订单状态';
    if (field.numeric) field.width ||= 135;
    return field;
  });
}

