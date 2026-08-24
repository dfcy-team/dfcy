<template>
  <ControlledPendingPage
    :title="initialStatus === 'published' ? '在线商品' : '多国家刊登资料'"
    :contract="initialStatus === 'published' ? 'pending: listings.online-products（默认筛选已发布商品）' : 'pending: listings.sites（后端接口未实现）'"
    :loader="loadSiteProfiles"
    :fields="fields"
    :actions="['生成 RPA 任务（禁用）', '复制刊登（禁用）']"
  />
</template>

<script setup>
import ControlledPendingPage from '../_ControlledPendingPage.vue';
import { fetchSiteProfiles } from '../../api/listings';

const props = defineProps({
  initialStatus: { type: String, default: '' }
});
const initialStatus = props.initialStatus;
const fields = [
  { prop: 'sku', label: 'SKU' },
  { prop: 'platform', label: '平台' },
  { prop: 'country', label: '国家' },
  { prop: 'listing_status', label: '刊登状态' }
];
const loadSiteProfiles = () => fetchSiteProfiles(initialStatus ? { status: initialStatus } : {});
</script>
