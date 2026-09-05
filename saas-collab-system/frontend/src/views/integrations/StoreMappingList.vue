<template>
  <AppPage
    eyebrow="API DATA INTEGRATION"
    title="店铺平台关联"
    subtitle="兼容入口：店铺平台身份关联已归集到店铺档案。"
    boundary-note="请选择已授权的平台身份建立关联；平台身份字段由授权关系派生，关联只能停用不能删除。"
    :capability="capability"
  >
    <StoreMappingPanel
      :store-id="route.query.store_id || null"
      standalone
      @open-api="openApiAccess"
    />
  </AppPage>
</template>

<script setup>
import { useRoute, useRouter } from 'vue-router';
import AppPage from '../../components/AppPage.vue';
import StoreMappingPanel from '../../components/StoreMappingPanel.vue';
import { useMock } from '../../api/request';

const route = useRoute();
const router = useRouter();
const capability = useMock ? 'mock' : 'pending';

function openApiAccess(store) {
  if (!store?.id) return;
  router.push({ path: '/master-data/stores', query: { store_id: store.id, panel: 'api' } });
}
</script>
