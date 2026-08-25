<template>
  <Phase3AnalyticsPage
    eyebrow="经营分析"
    title="经营总览"
    subtitle="按授权范围查看经营指标、数据质量和来源摘要。"
    boundary-note="本页仅提供分析结果，不触发采购、改价、商品状态、RPA或资金动作。"
    :loader="fetchBusinessOverview"
    :options-loader="fetchAnalyticsFilters"
    :filters="filters"
    :columns="columns"
    presentation="operating"
    metrics-key="summary_metrics"
    trend-value-key="order_count"
    trend-count-unit="个数据点"
    :show-metric-code="false"
    trend-title="经营指标趋势"
    trend-note="订单规模与净销售额逐日变化。"
    table-title="指标明细"
    table-note="所有维度来自当前租户授权店铺的本地事实数据。"
  />
</template>

<script setup>
import Phase3AnalyticsPage from '../../components/Phase3AnalyticsPage.vue';
import { fetchAnalyticsFilters, fetchBusinessOverview } from '../../api/analytics';

const filters = [
  { key: 'date_from', label: '开始日期', type: 'date', placeholder: '年/月/日' },
  { key: 'date_to', label: '结束日期', type: 'date', placeholder: '年/月/日' },
  { key: 'platform', label: '平台', optionSource: 'platforms', placeholder: '全部平台', clears: ['store_id'] },
  { key: 'store_id', label: '店铺', optionSource: 'stores', placeholder: '全部店铺', dependsOn: 'platform', optionField: 'platform' },
  { key: 'currency', label: '币种', optionSource: 'currencies', placeholder: '全部币种' }
];

const columns = [
  { prop: 'store_name', secondaryProp: 'store_code', label: '店铺', type: 'primary', width: 190 },
  { prop: 'platform', label: '平台', type: 'platform' },
  { prop: 'region', label: '国家/站点' },
  { prop: 'order_count', label: '订单量', type: 'number' },
  { prop: 'units_sold', label: '销售件数', type: 'number' },
  { prop: 'gross_sales', label: '销售额', type: 'money', width: 150 },
  { prop: 'refund_amount', label: '退款金额', type: 'money', width: 150 },
  { prop: 'net_sales', label: '净销售额', type: 'money', emphasis: true, width: 150 },
  { prop: 'quality', label: '质量', type: 'status' },
  { prop: 'source_updated_at', label: '更新时间', type: 'datetime', width: 180 }
];
</script>
