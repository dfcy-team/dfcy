<template>
  <Phase2DataPage
    title="商品状态流转历史"
    note="GET /api/internal/products/status-transitions/"
    :loader="fetchProductStatusTransitions"
    :filters="['SPU', 'SKU', '来源']"
    :columns="columns"
    empty-text="暂无状态流转历史"
  />
</template>

<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchProductStatusTransitions } from '../../api/productStatus';

const columns = [
  { prop: 'spu_code', label: 'SPU' },
  { prop: 'sku_code', label: 'SKU' },
  { prop: 'from_status', label: '原状态', type: 'status' },
  { prop: 'to_status', label: '目标状态', type: 'status' },
  { prop: 'source_type', label: '来源' },
  { prop: 'reason_code', label: '原因码' },
  { prop: 'changed_by', label: '确认人' },
  { prop: 'changed_at', label: '确认时间' }
];
</script>
