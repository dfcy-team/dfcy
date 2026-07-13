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

export const mockSalesAnalysis = () => successResponse({
  status: 'mock',
  api_status: 'mock',
  quality: { status: 'good', score: 94, metric_version: 'demo-v3.0', refreshed_at: '2026-07-11 09:30' },
  metrics: [
    { code: 'BI_SALES_AMOUNT', label: '销售额', value: '486,320', unit: '元', change: '较上期 +8.4%', change_direction: 'up' },
    { code: 'BI_ORDER_COUNT', label: '订单量', value: '3,842', unit: '单', change: '较上期 +5.1%', change_direction: 'up' },
    { code: 'BI_UNITS_SOLD', label: '销量', value: '5,906', unit: '件', change: '较上期 +6.7%', change_direction: 'up' },
    { code: 'BI_AVG_ORDER_VALUE', label: '客单价', value: '126.58', unit: '元', change: '较上期 +3.2%', change_direction: 'up' }
  ],
  trend: [
    { label: '07-05', value: 58 }, { label: '07-06', value: 63 }, { label: '07-07', value: 55 },
    { label: '07-08', value: 71 }, { label: '07-09', value: 76 }, { label: '07-10', value: 84 },
    { label: '07-11', value: 90 }
  ],
  items: [
    { country: 'DEMO-CN', platform: 'DemoMall', store: '演示店铺 A', product: '演示商品 01', sales_amount: '128,600', order_count: 986, units_sold: 1420, quality_status: 'good' },
    { country: 'DEMO-US', platform: 'SampleShop', store: '演示店铺 B', product: '演示商品 02', sales_amount: '96,420', order_count: 742, units_sold: 1186, quality_status: 'good' },
    { country: 'DEMO-GB', platform: 'DemoMall', store: '演示店铺 C', product: '演示商品 03', sales_amount: '72,310', order_count: 554, units_sold: 831, quality_status: 'warning' }
  ]
});

export const mockInventoryAnalysis = () => successResponse({
  status: 'mock',
  api_status: 'mock',
  quality: { status: 'warning', score: 88, metric_version: 'demo-v3.0', refreshed_at: '2026-07-11 09:20' },
  metrics: [
    { code: 'BI_AVAILABLE_STOCK', label: '可售库存', value: '18,640', unit: '件', change: '较上期 -2.3%', change_direction: 'down' },
    { code: 'BI_IN_TRANSIT_STOCK', label: '在途库存', value: '4,280', unit: '件', change: '预计 7 日内到仓', change_direction: 'up' },
    { code: 'BI_INVENTORY_TURNOVER_DAYS', label: '周转天数', value: '34.6', unit: '天', change: '较上期 -1.8 天', change_direction: 'up' },
    { code: 'BI_SLOW_MOVING_STOCK', label: '滞销库存', value: '1,260', unit: '件', change: '需关注 5 个 SKU', change_direction: 'down' }
  ],
  trend: [
    { label: '07-05', value: 66 }, { label: '07-06', value: 64 }, { label: '07-07', value: 62 },
    { label: '07-08', value: 61 }, { label: '07-09', value: 59 }, { label: '07-10', value: 57 },
    { label: '07-11', value: 55 }
  ],
  items: [
    { sku_code: 'DEMO-SKU-001', product_name: '演示商品 01', warehouse: '演示华东仓', available_stock: 48, in_transit_stock: 100, cover_days: 6, risk_level: 'high' },
    { sku_code: 'DEMO-SKU-002', product_name: '演示商品 02', warehouse: '演示华南仓', available_stock: 860, in_transit_stock: 0, cover_days: 92, risk_level: 'medium' },
    { sku_code: 'DEMO-SKU-003', product_name: '演示商品 03', warehouse: '演示华东仓', available_stock: 320, in_transit_stock: 80, cover_days: 31, risk_level: 'low' }
  ]
});
