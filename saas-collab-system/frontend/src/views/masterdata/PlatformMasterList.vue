<template>
  <AdminResourcePage
    eyebrow="MASTER DATA"
    title="平台档案"
    subtitle="统一维护平台标识，供店铺、接口配置和业务模块引用。"
    boundary-note="平台档案不保存 API Key、Token 或登录凭据；存在启用店铺引用时禁止停用。"
    entity-label="平台"
    :loader="fetchPlatforms"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="(payload) => createMasterData('platforms', payload)"
    :edit-handler="(id, payload) => updateMasterData('platforms', id, payload)"
    :delete-handler="(id) => deleteMasterData('platforms', id)"
    :status-handler="(row, status) => updateMasterDataStatus('platforms', row.id, status)"
    create-permission="masterdata.manage"
    manage-permission="masterdata.manage"
    search-label="平台"
    show-filter-labels
    show-page-size
    :operation-width="190"
  />
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import { createMasterData, deleteMasterData, fetchPlatformCatalog, fetchPlatforms, updateMasterData, updateMasterDataStatus } from '../../api/masterData';

const platformTypes = ref([
  { label: 'Lazada', value: 'lazada' }, { label: 'Shopee', value: 'shopee' },
  { label: 'Temu', value: 'temu' }, { label: 'TikTok', value: 'tiktok' },
  { label: '自营仓服务', value: 'warehouse_owned' },
  { label: '三方仓服务', value: 'warehouse_third_party' },
  { label: '平台仓服务', value: 'warehouse_platform' },
  { label: '其他', value: 'other' }
]);

function platformLabel(value) {
  const labels = { lazada: 'Lazada', shopee: 'Shopee', temu: 'Temu', tiktok: 'TikTok', 'tiktok shop': 'TikTok Shop', bigseller: 'BigSeller' };
  return labels[String(value || '').toLowerCase()] || value || '-';
}

const columns = [
  { prop: 'code', label: '平台编码', width: 170 }, { prop: 'name', label: '平台名称', width: 200, format: platformLabel },
  { prop: 'platform_type', label: '平台类型', options: platformTypes.value },
  { prop: 'connector_status', label: '连接器状态', width: 150 },
  { prop: 'status', label: '状态', type: 'status' }
];
const formFields = computed(() => [
  { key: 'code', label: '平台编码', required: true }, { key: 'name', label: '平台名称', required: true },
  { key: 'platform_type', label: '平台类型', type: 'select', required: true, default: 'other', options: platformTypes.value },
  { key: 'status', label: '状态', type: 'select', required: true, default: 'active', options: [
    { label: '启用', value: 'active' }, { label: '停用', value: 'inactive' }
  ] }
]);

onMounted(async () => {
  const response = await fetchPlatformCatalog();
  const items = response?.data?.results || [];
  if (!response?.success || !items.length) return;
  platformTypes.value = items.map((item) => ({
    value: item.value,
    label: `${item.label}（${item.canonical_code} / ${item.priority_level}）${item.connector_status === 'NOT_IMPLEMENTED' ? ' · 连接器未实现' : ''}`
  }));
});
</script>
