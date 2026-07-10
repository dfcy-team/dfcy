<template>
  <Phase2DataPage
    title="商品状态建议"
    note="GET /api/internal/products/status-recommendations/"
    risk-note="前端不自动确认状态；高风险状态仅显示确认提示。"
    :loader="fetchProductStatusRecommendations"
    :filters="['当前状态', '建议状态', '来源']"
    :columns="columns"
    :actions="['确认占位', '拒绝占位']"
    empty-text="暂无状态建议"
  />
</template>

<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchProductStatusRecommendations } from '../../api/productStatus';

const columns = [
  { prop: 'spu_code', label: 'SPU' },
  { prop: 'sku_code', label: 'SKU' },
  { prop: 'current_status', label: '当前状态', type: 'status' },
  { prop: 'suggested_status', label: '建议状态', type: 'status' },
  { prop: 'reason_code', label: '原因码' },
  { prop: 'confidence', label: '置信度' },
  { prop: 'source_type', label: '数据来源' },
  { prop: 'calculated_at', label: '计算时间' },
  { prop: 'recommendation_status', label: '推荐状态', type: 'status' }
];
</script>
