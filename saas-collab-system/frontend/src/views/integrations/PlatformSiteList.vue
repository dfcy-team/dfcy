<template>
  <AdminResourcePage
    eyebrow="API DATA INTEGRATION"
    title="平台站点"
    subtitle="维护平台国家/区域站点、币种、时区和 API 区域，供店铺授权与映射使用。"
    boundary-note="平台站点是租户内的连接基础资料，不保存 App Secret、Token 或授权凭据；停用前由后端检查店铺引用。"
    entity-label="平台站点"
    :loader="fetchPlatformSites"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="(payload) => createMasterData('platform-sites', payload)"
    :edit-handler="(id, payload) => updateMasterData('platform-sites', id, payload)"
    :status-handler="(row, status) => updateMasterDataStatus('platform-sites', row.id, status)"
    create-permission="masterdata.manage"
    manage-permission="masterdata.manage"
    search-label="站点"
    show-filter-labels
    show-page-size
    :operation-width="170"
  />
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import { createMasterData, fetchPlatformSites, fetchPlatforms, updateMasterData, updateMasterDataStatus } from '../../api/masterData';

const platformOptions = ref([]);
const formFields = computed(() => [
  { key: 'platform_id', label: '平台', type: 'select', required: true, options: platformOptions.value, placeholder: '选择平台' },
  { key: 'site_code', label: '站点编码', required: true, placeholder: '例如 SG' },
  { key: 'name', label: '站点名称', required: true },
  { key: 'country_code', label: '国家代码', required: true, placeholder: '例如 SG' },
  { key: 'region_code', label: '区域代码', placeholder: '例如 SEA' },
  { key: 'currency_code', label: '币种代码', placeholder: '例如 SGD' },
  { key: 'timezone', label: '时区', required: true, default: 'UTC' },
  { key: 'api_region', label: 'API 区域' },
  { key: 'api_base_url', label: 'API 基础地址', type: 'url', placeholder: 'https://...' },
  { key: 'status', label: '状态', type: 'select', required: true, default: 'active', options: [{ label: '启用', value: 'active' }, { label: '停用', value: 'inactive' }] }
]);
const columns = [
  { prop: 'platform_name', label: '平台', width: 170 },
  { prop: 'site_code', label: '站点编码', width: 130 },
  { prop: 'name', label: '站点名称', width: 180 },
  { prop: 'country_code', label: '国家', width: 90 },
  { prop: 'region_code', label: '区域', width: 100 },
  { prop: 'currency_code', label: '币种', width: 90 },
  { prop: 'timezone', label: '时区', width: 170 },
  { prop: 'api_region', label: 'API 区域', width: 120 },
  { prop: 'status', label: '状态', type: 'status' }
];

onMounted(async () => {
  const response = await fetchPlatforms({ status: 'active', page: 1, page_size: 100 });
  const rows = response?.data?.results || response?.data?.items || response?.data || [];
  if (response?.success) platformOptions.value = (Array.isArray(rows) ? rows : []).map((item) => ({ value: item.id, label: `${item.name || item.code || item.id}（${item.code || item.id}）` }));
});
</script>
