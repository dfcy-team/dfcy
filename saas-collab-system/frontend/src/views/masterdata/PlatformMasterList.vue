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
    :status-handler="(row, status) => updateMasterDataStatus('platforms', row.id, status)"
    create-permission="masterdata.manage"
    manage-permission="masterdata.manage"
  />
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import { createMasterData, fetchPlatformCatalog, fetchPlatforms, updateMasterDataStatus } from '../../api/masterData';

const platformTypeOptions = ref([{ label: '其他', value: 'other' }]);

const columns = [
  { prop: 'code', label: '平台编码', width: 170 }, { prop: 'name', label: '平台名称', width: 200 },
  { prop: 'platform_type', label: '平台类型' }, { prop: 'priority_level', label: '优先级', width: 90 },
  { prop: 'connector_status', label: '连接器状态', width: 150 }, { prop: 'status', label: '状态', type: 'status' },
  { prop: 'tenant_id', label: '租户ID' }
];
const formFields = computed(() => [
  { key: 'code', label: '平台编码', required: true }, { key: 'name', label: '平台名称', required: true },
  { key: 'platform_type', label: '平台类型', type: 'select', required: true, default: 'other', options: platformTypeOptions.value }
]);

onMounted(async () => {
  const response = await fetchPlatformCatalog();
  const items = response?.data?.results || [];
  if (!response?.success || !items.length) return;
  platformTypeOptions.value = items.map((item) => ({
    value: item.value,
    label: `${item.label}（${item.canonical_code} / ${item.priority_level}）${item.connector_status === 'NOT_IMPLEMENTED' ? ' · 连接器未实现' : ''}`
  }));
});
</script>
