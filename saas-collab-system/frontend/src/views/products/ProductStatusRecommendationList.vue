<template>
  <Phase2DataPage
    title="商品状态建议"
    note="GET /api/internal/products/status-recommendations/"
    risk-note="API/RPA/规则数据只生成状态建议；清仓、停售、归档等高风险状态必须人工确认。"
    :loader="fetchProductStatusRecommendations"
    :filters="['建议状态', '来源', '状态']"
    :columns="columns"
    empty-text="暂无状态建议"
  />
</template>

<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchProductStatusRecommendations } from '../../api/productStatus';

const columns = [
  { prop: 'spu', label: 'SPU ID' },
  { prop: 'sku', label: 'SKU ID' },
  { prop: 'recommended_status', label: '建议状态', type: 'status' },
  { prop: 'reason_code', label: '原因码' },
  { prop: 'confidence', label: '置信度' },
  { prop: 'status', label: '推荐状态', type: 'status' },
  { prop: 'created_at', label: '创建时间' },
  { prop: 'confirmed_by_id', label: '确认人' },
  { prop: 'confirmed_at', label: '确认时间' }
];
</script>
