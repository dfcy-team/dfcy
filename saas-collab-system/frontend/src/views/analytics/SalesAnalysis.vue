<template>
  <Phase3AnalyticsPage
    eyebrow="经营分析"
    title="销售分析"
    subtitle="按国家、平台、店铺和商品查看销售趋势与结构。"
    boundary-note="销售数据为只读分析，缺失指标显示 N/A，不用于自动决策。"
    :loader="fetchSalesAnalysis"
    :options-loader="fetchAnalyticsFilters"
    :filters="filters"
    :columns="columns"
    presentation="operating"
    metrics-key="summary_metrics"
    trend-value-key="order_count"
    trend-count-unit="个数据点"
    :show-metric-code="false"
    trend-title="销售趋势"
    trend-note="当前筛选范围内按事实表汇总的订单表现"
    table-title="维度钻取"
    table-note="逐层核对国家、平台、店铺与商品表现"
  />
</template>

<script setup>
import Phase3AnalyticsPage from '../../components/Phase3AnalyticsPage.vue';
import { fetchAnalyticsFilters, fetchSalesAnalysis } from '../../api/analytics';

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
