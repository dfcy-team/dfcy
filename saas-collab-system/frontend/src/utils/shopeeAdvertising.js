export const advertisingKinds = [
  { value: 'shop_daily', label: '店铺日报' },
  { value: 'shop_hourly', label: '店铺整体小时报表' },
  { value: 'campaign_daily', label: '商品活动日报' },
  { value: 'campaign', label: '活动配置（最近快照）' },
  { value: 'balance', label: '广告余额快照（含赠送金）' },
  { value: 'campaign_hourly', label: '商品活动小时报表' },
  { value: 'gms_campaign', label: 'GMS 活动效果（区间汇总）' },
  { value: 'gms_item', label: 'GMS 商品效果（区间汇总）' },
  { value: 'shop_toggle', label: '广告开关状态（只读快照）' },
  { value: 'recommended_item', label: '推荐投放商品（最近快照）' }
];
export const defaultAdvertisingDatasets = ['campaign', 'campaign_daily', 'shop_daily', 'balance'];
