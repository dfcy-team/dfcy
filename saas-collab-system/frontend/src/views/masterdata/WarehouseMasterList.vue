<template>
  <AdminResourcePage
    eyebrow="MASTER DATA"
    title="仓库档案"
    subtitle="统一维护仓库身份，并在档案内管理库存 API Token。"
    boundary-note="极风 WMS Token 在服务端到期前自动刷新，可在 API 接入中调用只读接口检查；库存数量仍由同步任务写入。"
    entity-label="仓库"
    :loader="fetchWarehouses"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="(payload) => createMasterData('warehouses', payload)"
    :edit-handler="(id, payload) => updateMasterData('warehouses', id, payload)"
    :status-handler="(row, status) => updateMasterDataStatus('warehouses', row.id, status)"
    create-permission="masterdata.manage"
    manage-permission="masterdata.manage"
    search-label="仓库"
    show-filter-labels
    show-page-size
    :operation-width="240"
  >
    <template #row-actions="{ row }">
      <el-button link type="primary" @click.stop="goToAccess(row)">API 接入</el-button>
    </template>
  </AdminResourcePage>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import {
  createMasterData,
  fetchCountrySites,
  fetchWarehouses,
  updateMasterData,
  updateMasterDataStatus,
} from '../../api/masterData';

const router = useRouter();
const countryRows = ref([]);

const warehouseTypes = [
  { label: '自营仓', value: 'owned' },
  { label: '三方仓', value: 'third_party' },
  { label: '平台仓', value: 'platform' },
];

const countryOptions = computed(() => countryRows.value.map((row) => ({
  label: `${row.name}（${row.country_code}）`, value: row.country_code,
})));

const columns = [
  { prop: 'code', label: '仓库编码', width: 170 },
  { prop: 'name', label: '仓库名称', width: 200 },
  { prop: 'country_code', label: '国家', width: 100 },
  { prop: 'warehouse_type', label: '仓库类型', width: 150, options: warehouseTypes },
  { prop: 'status', label: '状态', type: 'status', width: 100 },
];

const formFields = computed(() => [
  { key: 'code', label: '仓库编码', required: true },
  { key: 'name', label: '仓库名称', required: true },
  { key: 'country_code', label: '国家代码', type: 'select', required: true, options: countryOptions.value },
  { key: 'warehouse_type', label: '仓库类型', type: 'select', required: true, default: 'owned', options: warehouseTypes },
  { key: 'status', label: '状态', type: 'select', required: true, default: 'active', filterable: false, options: [
    { label: '启用', value: 'active' }, { label: '停用', value: 'inactive' },
  ] },
]);

async function loadCountryOptions() {
  const response = await fetchCountrySites({ status: 'active', page: 1, page_size: 100 });
  if (!response?.success) return;
  const unique = new Map();
  for (const row of response.data?.results || []) if (!unique.has(row.country_code)) unique.set(row.country_code, row);
  countryRows.value = [...unique.values()];
}

function goToAccess(row) {
  router.push({ path: '/integrations/configs', query: { warehouse: row.code } });
}

onMounted(loadCountryOptions);
</script>
