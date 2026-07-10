<template>
  <Phase2DataPage
    title="商品状态建议详情"
    note="GET /api/internal/products/status-recommendations/{id}/"
    risk-note="清仓、停售、归档为高风险状态，真正确认必须调用后端授权接口。"
    mode="detail"
    :loader="() => fetchProductStatusRecommendationDetail(route.params.id || 1)"
    :detail-fields="fields"
    :actions="['确认占位', '拒绝占位']"
    empty-text="暂无建议详情"
  />
</template>

<script setup>
import { useRoute } from 'vue-router';
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchProductStatusRecommendationDetail } from '../../api/productStatus';

const route = useRoute();
const fields = [
  { prop: 'spu_code', label: 'SPU' },
  { prop: 'sku_code', label: 'SKU' },
  { prop: 'current_status', label: '当前状态', type: 'status' },
  { prop: 'suggested_status', label: '建议状态', type: 'status' },
  { prop: 'reason_code', label: '原因码' },
  { prop: 'reason_detail', label: '原因详情' },
  { prop: 'confidence', label: '置信度' },
  { prop: 'source_type', label: '数据来源' },
  { prop: 'calculated_at', label: '计算时间' },
  { prop: 'confirmed_by', label: '确认人' },
  { prop: 'confirmed_at', label: '确认时间' },
  { prop: 'evidence', label: '证据摘要', type: 'json' }
];
</script>
