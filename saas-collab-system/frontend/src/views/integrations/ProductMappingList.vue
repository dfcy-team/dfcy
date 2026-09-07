<template>
  <AppPage
    eyebrow="MASTER DATA"
    title="平台商品明细数据"
    subtitle="平台商品明细和 SKU 映射统一维护；从平台商品上下文选择本地 SKU，并通过建议、确认和停用完成受控映射。"
    boundary-note="商品映射已归集到平台商品明细数据。当前商品映射仅支持 Shopee、TikTok Shop；未实现平台会显示明确的连接器指引。"
    :capability="capability"
  >
    <ProductMappingPanel standalone :initial-status="route.query.status" :initial-variant-id="route.query.variant_id" :initial-store-id="route.query.store_id" />
  </AppPage>
</template>

<script setup>
import { ref } from 'vue';
import { useRoute } from 'vue-router';
import AppPage from '../../components/AppPage.vue';
import ProductMappingPanel from '../../components/ProductMappingPanel.vue';
import { useMock } from '../../api/request';

const route = useRoute();
const capability = ref(useMock ? 'mock' : 'pending');
</script>
