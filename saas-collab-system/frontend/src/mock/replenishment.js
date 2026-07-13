import { successResponse } from './index';

const evidence = {
  metric_version: 'demo-v3.0',
  source_batch: 'DEMO-BATCH-0711',
  available_stock: 48,
  in_transit_stock: 100,
  average_daily_sales: 22,
  data_quality: 'good'
};

export const mockInventoryAlerts = () => successResponse({
  status: 'mock', api_status: 'mock',
  summary: [
    { label: '全部预警', value: 12 }, { label: '缺货风险', value: 5 }, { label: '超储风险', value: 4 }, { label: '数据待核查', value: 3 }
  ],
  items: [
    { alert_id: 'DEMO-INV-001', sku_code: 'DEMO-SKU-001', warehouse: '演示华东仓', alert_type: 'stockout', risk_level: 'high', cover_days: 6, reason: '覆盖天数低于安全线', quality_status: 'good', evidence },
    { alert_id: 'DEMO-INV-002', sku_code: 'DEMO-SKU-002', warehouse: '演示华南仓', alert_type: 'overstock', risk_level: 'medium', cover_days: 92, reason: '覆盖天数高于演示阈值', quality_status: 'warning', evidence: { ...evidence, available_stock: 860 } }
  ]
});

export const mockReplenishmentSuggestions = () => successResponse({
  status: 'mock', api_status: 'mock',
  summary: [
    { label: '待复核建议', value: 8 }, { label: '高置信度', value: 5 }, { label: '需补充数据', value: 2 }, { label: '已人工确认', value: 0 }
  ],
  items: [
    { suggestion_id: 'DEMO-REP-001', sku_code: 'DEMO-SKU-001', warehouse: '演示华东仓', suggested_quantity: 420, suggested_date: '2026-07-14', confidence: 0.92, reason: '预计 6 天后触及安全库存', status: 'pending', evidence },
    { suggestion_id: 'DEMO-REP-002', sku_code: 'DEMO-SKU-004', warehouse: '演示华南仓', suggested_quantity: 180, suggested_date: '2026-07-18', confidence: 0.68, reason: '销售波动较大，建议人工复核', status: 'pending', evidence: { ...evidence, data_quality: 'warning' } }
  ]
});
