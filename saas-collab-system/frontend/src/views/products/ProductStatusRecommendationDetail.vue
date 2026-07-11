<template>
  <Phase2DataPage
    title="商品状态建议详情"
    note="GET /api/internal/products/status-recommendations/{id}/"
    risk-note="清仓、停售、归档为高风险状态；确认或拒绝必须调用后端授权接口。"
    mode="detail"
    :loader="() => fetchProductStatusRecommendationDetail(route.params.id || 1)"
    :detail-fields="fields"
    :action-configs="actionConfigs"
    empty-text="暂无建议详情"
  />
</template>

<script setup>
import { useRoute } from 'vue-router';
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import {
  confirmProductStatusRecommendation,
  fetchProductStatusRecommendationDetail,
  rejectProductStatusRecommendation
} from '../../api/productStatus';

const route = useRoute();

const fields = [
  { prop: 'spu', label: 'SPU ID' },
  { prop: 'sku', label: 'SKU ID' },
  { prop: 'recommended_status', label: '建议状态', type: 'status' },
  { prop: 'reason_code', label: '原因码' },
  { prop: 'reason_detail', label: '原因详情' },
  { prop: 'confidence', label: '置信度' },
  { prop: 'source_snapshot', label: '来源快照', type: 'json' },
  { prop: 'status', label: '推荐状态', type: 'status' },
  { prop: 'created_at', label: '创建时间' },
  { prop: 'confirmed_by_id', label: '确认人' },
  { prop: 'confirmed_at', label: '确认时间' }
];

const actionConfigs = [
  {
    label: '确认建议',
    type: 'primary',
    confirmMessage: '确认商品状态建议属于高风险动作，必须以后端权限校验为准。',
    handler: () => confirmProductStatusRecommendation(route.params.id || 1)
  },
  {
    label: '拒绝建议',
    confirmMessage: '拒绝商品状态建议将调用后端 reject 接口。',
    handler: () => rejectProductStatusRecommendation(route.params.id || 1)
  }
];
</script>
