<template>
  <Phase3AnalyticsPage
    eyebrow="经营分析"
    title="经营总览"
    subtitle="按授权范围查看经营指标、数据质量和来源摘要。"
    boundary-note="本页仅提供分析结果，不触发采购、改价、商品状态、RPA或资金动作。"
    :loader="fetchBusinessOverview"
    :filters="filters"
    :columns="columns"
    trend-title="经营指标趋势"
    trend-note="趋势为空时保持明确空状态，不补造数据。"
    table-title="指标明细"
    table-note="所有维度由后端按tenant、permission和data_scope过滤"
  />
</template>

<script setup>
import Phase3AnalyticsPage from '../../components/Phase3AnalyticsPage.vue';
import { fetchBusinessOverview } from '../../api/analytics';

const filters = [
  { key: 'date_range', label: '日期', type: 'daterange' },
  { key: 'country', label: '国家', options: [] },
  { key: 'platform', label: '平台', options: [] },
  { key: 'store', label: '店铺', options: [] }
];

const columns = [
  { prop: 'metric_code', label: '指标编码', width: 170 },
  { prop: 'metric_name', label: '指标名称', width: 170 },
  { prop: 'value', label: '指标值' },
  { prop: 'unit', label: '单位' },
  { prop: 'metric_version', label: '口径版本' },
  { prop: 'quality_status', label: '质量', type: 'status' },
  { prop: 'updated_at', label: '更新时间', width: 180 }
];
</script>
