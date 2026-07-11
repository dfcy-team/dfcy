import { successResponse } from './index';

export const mockBusinessOverview = () => successResponse({
  status: 'mock',
  api_status: 'mock',
  quality: {
    status: 'good',
    score: 96,
    metric_version: 'demo-v3.0',
    refreshed_at: '2026-07-11 09:30'
  },
  metrics: [
    { code: 'BI_SALES_AMOUNT', label: '销售额', value: '486,320', unit: '元', change: '较上期 +8.4%', change_direction: 'up' },
    { code: 'BI_ORDER_COUNT', label: '订单量', value: '3,842', unit: '单', change: '较上期 +5.1%', change_direction: 'up' },
    { code: 'BI_AVAILABLE_STOCK', label: '可售库存', value: '18,640', unit: '件', change: '较上期 -2.3%', change_direction: 'down' },
    { code: 'BI_STOCKOUT_RISK', label: '缺货风险', value: '12', unit: '项', change: '其中高风险 3 项', change_direction: 'down' }
  ],
  trend: [
    { label: '07-05', value: 52 },
    { label: '07-06', value: 61 },
    { label: '07-07', value: 58 },
    { label: '07-08', value: 74 },
    { label: '07-09', value: 69 },
    { label: '07-10', value: 83 },
    { label: '07-11', value: 88 }
  ],
  items: [
    { area: '库存', signal: '3 个 SKU 覆盖天数低于安全线', level: 'high', owner: '采购组', updated_at: '2026-07-11 09:18' },
    { area: '商品', signal: '5 个商品进入滞销观察', level: 'medium', owner: '商品组', updated_at: '2026-07-11 08:55' },
    { area: '同步', signal: '演示店铺数据刷新延迟', level: 'low', owner: '运营组', updated_at: '2026-07-11 08:42' }
  ]
});
