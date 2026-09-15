<template>
  <Phase3AnalyticsPage
    eyebrow="经营分析"
    title="广告投放分析"
    subtitle="按广告计划、商品和 SKU 分析曝光、点击、转化与投放成本。"
    boundary-note="广告明细和归因链路尚未接入；本页只定义分析维度，不执行预算、关键词或投放状态变更。"
    :loader="fetchAdvertisingPerformance"
    :filters="filters"
    :columns="columns"
    trend-title="投放效果趋势"
    trend-note="接入计划级报表后按日期展示"
    trend-unit="指数"
    table-title="计划与商品明细"
    table-note="指标口径以平台广告报表和订单归因规则为准"
    empty-text="广告明细尚未接入，暂无可展示数据"
  />
</template>

<script setup>
import Phase3AnalyticsPage from '../../components/Phase3AnalyticsPage.vue';
import { fetchAdvertisingPerformance } from '../../api/advertising';

const filters = [
  { key: 'date_range', label: '日期', type: 'daterange' },
  { key: 'platform', label: '平台', options: [] },
  { key: 'campaign', label: '广告计划', options: [] },
  { key: 'sku', label: '商品/SKU', options: [] }
];

const columns = [
  { prop: 'campaign', label: '广告计划', width: 180 },
  { prop: 'product', label: '商品' },
  { prop: 'sku', label: 'SKU' },
  { prop: 'impressions', label: '曝光量' },
  { prop: 'clicks', label: '点击量' },
  { prop: 'ctr', label: 'CTR' },
  { prop: 'cpc', label: 'CPC' },
  { prop: 'orders', label: '归因订单' },
  { prop: 'quality_status', label: '质量', type: 'status' }
];
</script>
