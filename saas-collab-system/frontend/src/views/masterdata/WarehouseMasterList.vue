<template>
  <section>
  <el-tabs v-if="canMaster && canSupply" v-model="surface">
    <el-tab-pane label="业务维护" name="supply" />
    <el-tab-pane label="基础与 API 维护" name="basic" />
  </el-tabs>
  <AppPage v-if="canSupply && (!canMaster || surface === 'supply')" title="仓库档案" subtitle="维护各国合作仓资料及旧编码，发运与入库共用同一份仓库档案。" capability="connected"><SupplyWarehouseArchiveV2 /></AppPage>
  <AdminResourcePage
    v-else-if="canMaster && (!canSupply || surface === 'basic')"
    ref="resourcePage"
    eyebrow="MASTER DATA"
    title="仓库档案"
    subtitle="统一维护仓库身份，并绑定对应的仓储服务平台后接入库存 API。"
    boundary-note="三方仓和平台仓必须绑定启用的对应仓储服务平台；仅受支持且已绑定的平台开放 API 接入。"
    entity-label="仓库"
    :loader="fetchWarehouses"
    :columns="columns"
    :form-fields="formFields"
    form-notice="此处仅维护仓库档案。保存后，在该仓库行的“API 接入”中选择接入配置、填写 Email 和 Token，并完成授权及只读校验；档案保存不代表已连通。"
    :create-handler="(payload) => createMasterData('warehouses', warehousePayload(payload))"
    :edit-handler="(id, payload) => updateMasterData('warehouses', id, warehousePayload(payload))"
    :delete-handler="(id) => deleteMasterData('warehouses', id)"
    :status-handler="(row, status) => updateMasterDataStatus('warehouses', row.id, status)"
    create-permission="masterdata.manage"
    manage-permission="masterdata.manage"
    search-label="仓库"
    show-filter-labels
    show-page-size
    :operation-width="240"
  >
    <template #row-actions="{ row }">
      <el-button
        v-if="apiAccess.visible && row.api_access_available"
        link
        type="primary"
        :disabled="apiAccess.disabled"
        :title="apiAccess.disabled ? apiAccess.reason : '打开当前仓库的库存 API 接入'"
        @click.stop="openApiAccess(row)"
      >API 接入</el-button>
      <el-button
        v-else-if="apiAccess.visible"
        link
        type="info"
        :disabled="apiAccess.disabled"
        :title="apiAccess.disabled ? apiAccess.reason : '当前仓库尚未达到库存 API 接入条件'"
        @click.stop="notifyApiAccessBlocked(row)"
      >
        API 接入（待配置）
      </el-button>
    </template>
    <SubjectApiAccessDialog
      v-model="apiAccessOpen"
      subject-type="warehouse"
      :row="selectedWarehouse"
      @changed="handleApiAccessChanged"
    />
  </AdminResourcePage>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import AppPage from '../../components/AppPage.vue';
import SupplyWarehouseArchiveV2 from '../../components/supply-chain/SupplyWarehouseArchiveV2.vue';
import SubjectApiAccessDialog from '../../components/SubjectApiAccessDialog.vue';
import {
  createMasterData,
  deleteMasterData,
  fetchCountrySites,
  fetchPlatforms,
  fetchWarehouses,
  updateMasterData,
  updateMasterDataStatus,
} from '../../api/masterData';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';

const auth = useAuthStore();
const canMaster = computed(() => !auth.authorizationStale && (auth.hasPermission('masterdata.view') || auth.hasRouteViewPermission?.('masterdata.view')));
const canSupply = computed(() => !auth.authorizationStale && (auth.hasPermission('supply.v2.view') || auth.hasRouteViewPermission?.('supply.v2.view')));
const surface = ref(auth.hasPermission('supply.v2.manage') ? 'supply' : 'basic');
const countryRows = ref([]);
const platformRows = ref([]);
const resourcePage = ref(null);
const apiAccessOpen = ref(false);
const selectedWarehouse = ref(null);
const apiAccess = computed(() => {
  const integrationViewAccess = getActionAccess(auth, { permission: 'integrations.view' });
  const warehouseViewAccess = getActionAccess(auth, { permission: 'integrations.warehouse.view' });
  const allowed = integrationViewAccess.allowed && warehouseViewAccess.allowed;
  const visible = integrationViewAccess.visible && warehouseViewAccess.visible;
  const reason = [integrationViewAccess, warehouseViewAccess]
    .filter((access) => !access.allowed && access.reason)
    .map((access) => access.reason)
    .join('；');
  return {
    allowed,
    visible,
    disabled: integrationViewAccess.disabled || warehouseViewAccess.disabled || !allowed,
    reason: allowed ? '' : reason || '当前角色无权查看仓库 API 接入',
  };
});

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
  { prop: 'address', label: '仓库地址', width: 220 },
  { prop: 'region', label: '区域', width: 140 },
  { prop: 'legacy_codes', label: '飞书旧编码', type: 'list', width: 180 },
  { prop: 'notes', label: '备注', width: 220 },
  { prop: 'status', label: '状态', type: 'status', width: 100 },
  { prop: 'api_validation_status', label: 'API 校验', width: 120, options: [
    { value: 'unconfigured', label: '未配置' },
    { value: 'incomplete', label: '待补充' }, { value: 'pending', label: '待校验' },
    { value: 'verified', label: '校验通过' }, { value: 'failed', label: '校验失败' },
  ] },
];

const formFields = computed(() => [
  { key: 'code', label: '仓库编码', required: true },
  { key: 'name', label: '仓库名称', required: true },
  { key: 'address', label: '仓库地址' },
  { key: 'region', label: '区域' },
  { key: 'legacy_codes', label: '飞书旧编码（逗号或换行分隔）', placeholder: '仅用于展示和搜索，不参与 WMS 身份匹配' },
  { key: 'notes', label: '备注' },
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

function warehousePayload(form) {
  const payload = Object.fromEntries(Object.entries(form).filter(([key]) => !key.startsWith('api_')));
  if (typeof payload.legacy_codes === 'string') {
    payload.legacy_codes = payload.legacy_codes.split(/[\n,，]/).map((value) => value.trim()).filter(Boolean);
  }
  return payload;
}

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
  if (!apiAccess.value.allowed) {
    ElMessage.warning(apiAccess.value.reason || '当前角色无权查看仓库 API 接入');
    return;
  }
  if (!row?.api_access_available) {
    notifyApiAccessBlocked(row);
    return;
  }
  selectedWarehouse.value = row;
  apiAccessOpen.value = true;
}

function notifyApiAccessBlocked(row) {
  if (!apiAccess.value.allowed) {
    ElMessage.warning(apiAccess.value.reason || '当前角色无权查看仓库 API 接入');
    return;
  }
  ElMessage.warning(row.service_platform_id
    ? '当前仓储服务平台尚未接入受支持的库存 API，请先维护平台档案。'
    : '请先绑定启用且匹配仓库类型的仓储服务平台。');
}

async function handleApiAccessChanged() {
  await resourcePage.value?.loadData?.();
}

function loadBasicOptions() {
  if (canMaster.value && (!canSupply.value || surface.value === 'basic')) {
    Promise.all([loadCountryOptions(), loadPlatformOptions()]);
  }
}

watch(surface, loadBasicOptions);
onMounted(loadBasicOptions);
</script>
