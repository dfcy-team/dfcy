<template>
  <Phase3AnalyticsPage
    eyebrow="经营分析"
    title="广告总览"
    subtitle="按授权范围汇总广告消耗、归因销售和投放效率。"
    boundary-note="广告报表资源尚未接入；当前仅展示数据口径和空状态，不补造消耗、销售或 ROAS。"
    :loader="fetchAdvertisingOverview"
    :filters="filters"
    :columns="columns"
    trend-title="广告消耗趋势"
    trend-note="接入广告报表后按日聚合"
    trend-unit="金额"
    table-title="广告效果摘要"
    table-note="数据将按租户、平台、站点和店铺权限过滤"
    empty-text="广告报表尚未接入，暂无可展示数据"
  />
</template>

<script setup>
import Phase3AnalyticsPage from '../../components/Phase3AnalyticsPage.vue';
import { fetchAdvertisingOverview } from '../../api/advertising';

const filters = [
  { key: 'date_range', label: '日期', type: 'daterange' },
  { key: 'platform', label: '平台', options: [] },
  { key: 'store', label: '店铺', options: [] }
];

const columns = [
  { prop: 'platform', label: '平台' },
  { prop: 'store', label: '店铺' },
  { prop: 'spend', label: '广告消耗' },
  { prop: 'attributed_sales', label: '归因销售额' },
  { prop: 'orders', label: '归因订单' },
  { prop: 'roas', label: 'ROAS' },
  { prop: 'acos', label: 'ACOS' },
  { prop: 'quality_status', label: '质量', type: 'status' }
];
</script>
