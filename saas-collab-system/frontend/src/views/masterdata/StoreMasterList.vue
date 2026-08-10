<template>
  <AdminResourcePage
    eyebrow="MASTER DATA"
    title="店铺档案"
    subtitle="维护店铺的国家、币种和时区口径，不在业务页面重复建档。"
    boundary-note="店铺档案只描述业务身份；平台账号和凭据由独立加密引用管理。"
    entity-label="店铺"
    :loader="fetchStores"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="(payload) => createMasterData('stores', payload)"
    :status-handler="(row, status) => updateMasterDataStatus('stores', row.id, status)"
    create-permission="masterdata.manage"
    manage-permission="masterdata.manage"
  />
</template>

<script setup>
import { onMounted, ref } from 'vue';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import { createMasterData, fetchPlatforms, fetchStores, updateMasterDataStatus } from '../../api/masterData';

const columns = [
  { prop: 'code', label: '店铺编码', width: 170 }, { prop: 'name', label: '店铺名称', width: 190 },
  { prop: 'platform_name', label: '所属平台', width: 160 }, { prop: 'country_code', label: '国家' },
  { prop: 'currency', label: '币种' }, { prop: 'timezone', label: '时区', width: 170 },
  { prop: 'status', label: '状态', type: 'status' }
];
const platformOptions = ref([]);
const formFields = ref([
  { key: 'platform_id', label: '平台', type: 'select', required: true, options: platformOptions.value },
  { key: 'code', label: '店铺编码', required: true }, { key: 'name', label: '店铺名称', required: true },
  { key: 'country_code', label: '国家代码', required: true, placeholder: '例如 SG' },
  { key: 'currency', label: '币种', required: true, placeholder: '例如 SGD' },
  { key: 'timezone', label: '时区', required: true, default: 'UTC' }
]);

async function loadPlatformOptions() {
  const response = await fetchPlatforms({ page: 1, page_size: 100, status: 'active' });
  const data = response?.data || {};
  const rows = Array.isArray(data.results) ? data.results : (Array.isArray(data.items) ? data.items : []);
  platformOptions.value = rows.map((platform) => ({
    label: `${platform.name} (${platform.code})`,
    value: platform.id
  }));
  formFields.value[0].options = platformOptions.value;
}

onMounted(loadPlatformOptions);
</script>
