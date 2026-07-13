<template>
  <Phase3AnalyticsPage
    eyebrow="经营分析"
    title="销售分析"
    subtitle="按国家、平台、店铺和商品查看销售趋势与结构。"
    boundary-note="销售数据为只读分析，缺失指标显示 N/A，不用于自动决策。"
    :loader="fetchSalesAnalysis"
    :filters="filters"
    :columns="columns"
    trend-title="销售趋势"
    trend-note="当前筛选范围内的演示销售指数"
    trend-unit="指数"
    table-title="维度钻取"
    table-note="逐层核对国家、平台、店铺与商品表现"
  />
</template>

<script setup>
import Phase3AnalyticsPage from '../../components/Phase3AnalyticsPage.vue';
import { fetchSalesAnalysis } from '../../api/analytics';

const filters = [
  { key: 'date_range', label: '日期', type: 'daterange' },
  { key: 'country', label: '国家', options: [{ label: 'DEMO-CN', value: 'DEMO-CN' }, { label: 'DEMO-US', value: 'DEMO-US' }] },
  { key: 'platform', label: '平台', options: [{ label: 'DemoMall', value: 'DemoMall' }, { label: 'SampleShop', value: 'SampleShop' }] },
  { key: 'store', label: '店铺', options: [{ label: '演示店铺 A', value: 'demo-store-a' }, { label: '演示店铺 B', value: 'demo-store-b' }] }
];

const columns = [
  { prop: 'country', label: '国家' }, { prop: 'platform', label: '平台' }, { prop: 'store', label: '店铺', width: 150 },
  { prop: 'product', label: '商品', width: 150 }, { prop: 'sales_amount', label: '销售额' },
  { prop: 'order_count', label: '订单量' }, { prop: 'units_sold', label: '销量' },
  { prop: 'quality_status', label: '质量', type: 'status' }
];
</script>
