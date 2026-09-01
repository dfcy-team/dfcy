<template>
  <AdminResourcePage
    eyebrow="MASTER DATA"
    title="仓库档案"
    subtitle="统一维护仓库身份，并绑定对应的仓储服务平台后接入库存 API。"
    boundary-note="三方仓和平台仓必须绑定启用的对应仓储服务平台；仅受支持且已绑定的平台开放 API 接入。"
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
      <el-button v-if="apiAccess.visible && row.api_access_available" link type="primary" @click.stop="openApiAccess(row)">API 接入</el-button>
      <el-button v-else-if="apiAccess.visible" link type="info" @click.stop="notifyApiAccessBlocked(row)">
        API 接入（待配置）
      </el-button>
    </template>
    <SubjectApiAccessDialog
      v-model="apiAccessOpen"
      subject-type="warehouse"
      :row="selectedWarehouse"
    />
  </AdminResourcePage>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import SubjectApiAccessDialog from '../../components/SubjectApiAccessDialog.vue';
import {
  createMasterData,
  fetchCountrySites,
  fetchPlatforms,
  fetchWarehouses,
  updateMasterData,
  updateMasterDataStatus,
} from '../../api/masterData';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';

const auth = useAuthStore();
const countryRows = ref([]);
const platformRows = ref([]);
const apiAccessOpen = ref(false);
const selectedWarehouse = ref(null);
const apiAccess = computed(() => getActionAccess(auth, { permission: 'integrations.view' }));

const warehouseTypes = [
  { label: '自营仓', value: 'owned' },
  { label: '三方仓', value: 'third_party' },
  { label: '平台仓', value: 'platform' },
];

const servicePlatformTypeByWarehouseType = {
  owned: 'warehouse_owned',
  third_party: 'warehouse_third_party',
  platform: 'warehouse_platform',
};

const countryOptions = computed(() => countryRows.value.map((row) => ({
  label: `${row.name}（${row.country_code}）`, value: row.country_code,
})));

const columns = [
  { prop: 'code', label: '仓库编码', width: 170 },
  { prop: 'name', label: '仓库名称', width: 200 },
  { prop: 'country_code', label: '国家', width: 100 },
  { prop: 'warehouse_type', label: '仓库类型', width: 150, options: warehouseTypes },
  { prop: 'service_platform_name', label: '仓储服务平台', width: 180 },
  { prop: 'status', label: '状态', type: 'status', width: 100 },
];

const formFields = computed(() => [
  { key: 'code', label: '仓库编码', required: true },
  { key: 'name', label: '仓库名称', required: true },
  { key: 'country_code', label: '国家代码', type: 'select', required: true, options: countryOptions.value },
  {
    key: 'warehouse_type', label: '仓库类型', type: 'select', required: true, default: 'owned', options: warehouseTypes,
    onChange: clearMismatchedServicePlatform,
  },
  {
    key: 'service_platform_id',
    label: '仓储服务平台（第三方/平台仓必填）',
    type: 'select',
    clearable: true,
    placeholder: '请选择与仓库类型匹配的启用平台',
    options: (form) => servicePlatformOptions(form.warehouse_type),
  },
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

function servicePlatformOptions(warehouseType) {
  const expectedType = servicePlatformTypeByWarehouseType[warehouseType];
  if (!expectedType) return [];
  return platformRows.value
    .filter((row) => row.status === 'active' && row.platform_type === expectedType)
    .map((row) => ({ label: `${row.name}（${row.code}）`, value: row.id }));
}

function clearMismatchedServicePlatform(warehouseType, form) {
  const expectedType = servicePlatformTypeByWarehouseType[warehouseType];
  const selected = platformRows.value.find((row) => row.id === form.service_platform_id);
  if (!selected || selected.platform_type !== expectedType) form.service_platform_id = '';
}

async function loadPlatformOptions() {
  const response = await fetchPlatforms({ status: 'active', page: 1, page_size: 100 });
  if (response?.success) platformRows.value = response.data?.results || [];
}

function openApiAccess(row) {
  selectedWarehouse.value = row;
  apiAccessOpen.value = true;
}

function notifyApiAccessBlocked(row) {
  ElMessage.warning(row.service_platform_id
    ? '当前仓储服务平台尚未接入受支持的库存 API，请先维护平台档案。'
    : '请先绑定启用且匹配仓库类型的仓储服务平台。');
}

onMounted(() => Promise.all([loadCountryOptions(), loadPlatformOptions()]));
</script>
