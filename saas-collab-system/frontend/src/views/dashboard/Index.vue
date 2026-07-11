<template>
  <Phase3AnalyticsPage
    title="经营总览"
    subtitle="集中查看销售、库存与经营风险，所有指标仅用于分析。"
    boundary-note="当前使用阶段3 Mock 指标；建议和预警不会自动创建采购单、改变商品状态或触发 RPA。"
    :loader="fetchBusinessOverview"
    :filters="filters"
    :columns="columns"
    trend-title="近 7 日经营指数"
    trend-note="演示趋势用于页面结构和状态验收"
    trend-unit="指数"
    table-title="需要关注"
    table-note="按业务影响和更新时间排序"
  />
</template>

<script setup>
import Phase3AnalyticsPage from '../../components/Phase3AnalyticsPage.vue';
import { fetchBusinessOverview } from '../../api/analytics';

const filters = [
  { key: 'date_range', label: '日期', type: 'daterange' },
  {
    key: 'dimension',
    label: '维度',
    options: [
      { label: '国家', value: 'country' },
      { label: '平台', value: 'platform' },
      { label: '店铺', value: 'store' },
      { label: '商品', value: 'product' }
    ]
  }
];

const columns = [
  { prop: 'area', label: '业务域', width: 100 },
  { prop: 'signal', label: '关注事项', width: 260 },
  { prop: 'level', label: '等级', type: 'status', width: 100 },
  { prop: 'owner', label: '负责人', width: 120 },
  { prop: 'updated_at', label: '更新时间', width: 160 }
];
</script>
