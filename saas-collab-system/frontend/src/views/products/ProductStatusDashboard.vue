<template>
  <Phase2DataPage
    title="商品状态看板"
    note="GET /api/internal/products/status-recommendations/，仅展示状态统计与建议入口"
    risk-note="自动识别只能生成建议，清仓、停售、归档必须由后端授权人工确认。"
    :loader="fetchProductStatusDashboard"
    :columns="columns"
    :actions="['evaluate-mock 占位']"
    empty-text="暂无状态统计"
  />
</template>

<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchProductStatusDashboard } from '../../api/productStatus';

const columns = [
  { prop: 'status_name', label: '商品状态' },
  { prop: 'count', label: '数量' }
];
</script>
