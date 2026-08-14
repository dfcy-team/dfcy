const envelope = (data, message = '销售管理演示数据') => ({
  success: true,
  code: 'OK',
  message,
  data: {
    api_status: 'mock',
    source_status: 'partial',
    refreshed_at: '2026-08-12 09:40 UTC',
    quality: { status: 'attention', score: 92, refreshed_at: '2026-08-12 09:40 UTC' },
    ...data
  }
});

const metrics = [
  { code: 'gross_sales', label: '销售额', value: '286,420', unit: 'SGD', change: '环比 +8.4%', change_direction: 'up' },
  { code: 'net_sales', label: '净销售额', value: '271,180', unit: 'SGD', change: '环比 +7.1%', change_direction: 'up' },
  { code: 'order_count', label: '订单量', value: '4,286', unit: '单', change: '环比 +5.7%', change_direction: 'up' },
  { code: 'units_sold', label: '销售件数', value: '5,931', unit: '件', change: '环比 +6.2%', change_direction: 'up' },
  { code: 'average_order_value', label: '客单价', value: '63.27', unit: 'SGD', change: '环比 +1.3%', change_direction: 'up' },
  { code: 'refund_amount', label: '退款金额', value: '15,240', unit: 'SGD', change: '环比 +2.1%', change_direction: 'down' },
  { code: 'refund_rate', label: '退款率', value: '5.32', unit: '%', change: '低于警戒线 0.7pp', change_direction: 'up' }
];

const overviewRows = [
  { id: 1, store_id: 'Shopee SG 旗舰店', platform: 'Shopee', region: 'SG', net_sales: '128,600 SGD', order_count: 1920, refund_rate: '4.2%', source_updated_at: '2026-08-12 09:40 UTC' },
  { id: 2, store_id: 'TikTok UK Store', platform: 'TikTok Shop', region: 'GB', net_sales: '89,430 GBP', order_count: 1348, refund_rate: '7.1%', source_updated_at: '2026-08-12 09:31 UTC' },
  { id: 3, store_id: 'Shopee US Outlet', platform: 'Shopee', region: 'US', net_sales: '53,150 USD', order_count: 1018, refund_rate: '3.8%', source_updated_at: '2026-08-12 09:18 UTC' }
];

const orderRows = [
  { id: 11, platform: 'Shopee', region: 'SG', store_id: 'Shopee SG 旗舰店', order_reference: 'SHP…281', ordered_at: '2026-08-12 08:36 UTC', order_status: 'confirmed', fulfillment_status: 'pending', refund_status: 'none', item_count: 3, gross_amount: '128.60 SGD', net_amount: '121.20 SGD', buyer_region: 'Central Singapore', source_updated_at: '2026-08-12 09:40 UTC' },
  { id: 12, platform: 'TikTok Shop', region: 'GB', store_id: 'TikTok UK Store', order_reference: 'TKS…914', ordered_at: '2026-08-12 08:14 UTC', order_status: 'completed', fulfillment_status: 'fulfilled', refund_status: 'partial', item_count: 2, gross_amount: '74.50 GBP', net_amount: '61.00 GBP', buyer_region: 'Greater London', source_updated_at: '2026-08-12 09:31 UTC' }
];

const returnRows = [
  { id: 21, source_return_id: 'RET-00821', order_reference: 'TKS…914', store_id: 'TikTok UK Store', sku: 'SKU-TSHIRT-04', quantity: 1, requested_amount: '13.50 GBP', refunded_amount: '13.50 GBP', normalized_reason: '尺码不合适', status: 'completed', requested_at: '2026-08-11 12:20 UTC', completed_at: '2026-08-12 07:45 UTC' },
  { id: 22, source_return_id: 'RET-00822', order_reference: 'SHP…402', store_id: 'Shopee SG 旗舰店', sku: 'SKU-MUG-02', quantity: 1, requested_amount: '19.90 SGD', refunded_amount: '0.00 SGD', normalized_reason: '等待平台处理', status: 'pending', requested_at: '2026-08-12 06:20 UTC', completed_at: null }
];

const skuRows = [
  { id: 31, spu: 'SPU-BAG-01', sku: 'SKU-BAG-BLK', product_name: '轻量通勤包 / 黑色', store_id: 'Shopee SG 旗舰店', units_sold: 428, gross_sales: '32,240 SGD', net_sales: '31,190 SGD', order_count: 390, refund_units: 8, refund_rate: '1.9%', inventory_risk: 'healthy', source_updated_at: '2026-08-12 09:40 UTC' },
  { id: 32, spu: 'SPU-TSHIRT-04', sku: 'SKU-TSHIRT-04', product_name: '基础款 T 恤 / M', store_id: 'TikTok UK Store', units_sold: 316, gross_sales: '9,860 GBP', net_sales: '8,920 GBP', order_count: 284, refund_units: 31, refund_rate: '9.8%', inventory_risk: 'warning', source_updated_at: '2026-08-12 09:31 UTC' }
];

const exportRows = [
  { id: 'EXP-240812-018', export_type: '订单汇总', filter_summary: '最近 30 天 · 全部可见门店', scope_summary: '3 家授权门店', created_by: 'demo-operator', created_at: '2026-08-12 09:12 UTC', status: 'completed', record_count: 4286, expires_at: '2026-08-13 09:12 UTC' },
  { id: 'EXP-240812-019', export_type: '退款退货', filter_summary: 'TikTok Shop · GB', scope_summary: '1 家授权门店', created_by: 'demo-operator', created_at: '2026-08-12 09:28 UTC', status: 'processing', record_count: 0, expires_at: null }
];

const qualityIssues = [
  { id: 41, severity: 'high', issue_type: 'SKU 未映射', platform: 'TikTok Shop', region: 'GB', store_id: 'TikTok UK Store', message: '18 条订单行尚未匹配内部 SKU', status: 'open', detected_at: '2026-08-12 09:32 UTC' },
  { id: 42, severity: 'medium', issue_type: '迟到数据', platform: 'Shopee', region: 'US', store_id: 'Shopee US Outlet', message: '来源数据比预期延迟 47 分钟', status: 'open', detected_at: '2026-08-12 09:20 UTC' }
];

const syncSources = [
  { id: 51, platform: 'Shopee', region: 'SG', store_id: 'Shopee SG 旗舰店', credential_mask: '授权连接 …001', authorization_status: 'active', run_status: 'success', last_success_at: '2026-08-12 09:40 UTC', data_delay_seconds: 180, error_summary: '' },
  { id: 52, platform: 'TikTok Shop', region: 'GB', store_id: 'TikTok UK Store', credential_mask: '授权连接 …014', authorization_status: 'active', run_status: 'partial', last_success_at: '2026-08-12 09:31 UTC', data_delay_seconds: 540, error_summary: '第 4 页读取超时，已保留前三页结果' }
];

export const salesManagementMocks = {
  overview: () => envelope({ metrics, trend: [
    { label: '08-06', value: 36 }, { label: '08-07', value: 42 }, { label: '08-08', value: 39 },
    { label: '08-09', value: 51 }, { label: '08-10', value: 47 }, { label: '08-11', value: 58 }, { label: '08-12', value: 64 }
  ], results: overviewRows, anomalies: qualityIssues, count: overviewRows.length, definition: { currency_basis: '按所选币种；跨币种不直接相加', timezone_basis: '门店时区归一至 UTC', refund_basis: '实际退款金额 / 销售额' } }),
  orders: () => envelope({ results: orderRows, count: orderRows.length }),
  orderDetail: (id) => envelope({
    ...orderRows.find((row) => row.id === id),
    discount_amount: '7.40', tax_amount: '4.10', shipping_amount: '3.80', source_batch: 'sync-20260812-0940',
    lines: [{ id: 1, sku: 'SKU-BAG-BLK', product_name: '轻量通勤包 / 黑色', quantity: 2, unit_price: '60.00' }],
    returns: []
  }),
  returns: () => envelope({ metrics: metrics.slice(5), results: returnRows, count: returnRows.length }),
  stores: () => envelope({ results: overviewRows.map((row) => ({ ...row, gross_sales: row.net_sales, units_sold: row.order_count + 420, average_order_value: '63.20', refund_amount: '4,820', period_start: '2026-07-14', period_end: '2026-08-12' })), count: overviewRows.length }),
  skus: () => envelope({ results: skuRows, count: skuRows.length }),
  exports: () => envelope({ results: exportRows, count: exportRows.length }),
  'data-quality': () => envelope({ issues: qualityIssues, sources: syncSources, counts: { sku_unmapped: 18, late_data: 1 } }),
  createExport: (payload) => envelope({ id: 'EXP-NEW', ...payload, status: 'pending', record_count: 0 }),
  requestRerun: (payload) => envelope({ id: 'RERUN-NEW', ...payload, status: 'requested' })
};
