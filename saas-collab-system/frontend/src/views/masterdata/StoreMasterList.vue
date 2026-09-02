<template>
  <AdminResourcePage
    ref="resourcePage"
    eyebrow="MASTER DATA"
    title="店铺档案"
    subtitle="维护店铺身份，并在档案内管理商城与广告 API 授权。"
    boundary-note="Token 只以加密引用绑定；TikTok Shop 不自动刷新，也不设置到期拦截。"
    entity-label="店铺"
    :loader="fetchStores"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="(payload) => createMasterData('stores', payload)"
    :edit-handler="(id, payload) => updateMasterData('stores', id, payload)"
    :status-handler="(row, status) => updateMasterDataStatus('stores', row.id, status)"
    create-permission="masterdata.manage"
    manage-permission="masterdata.manage"
    search-label="店铺"
    show-filter-labels
    show-page-size
    :table-max-height="640"
    :operation-width="250"
  >
    <template #header-actions>
      <el-button
        v-if="importAccess.visible"
        :disabled="importAccess.disabled"
        :title="importAccess.reason"
        @click="openImport"
      >
        导入店铺档案
      </el-button>
    </template>
    <template #row-actions="{ row }">
      <el-button v-if="apiAccess.visible" link type="primary" @click.stop="openApiAccess(row)">API 接入</el-button>
    </template>

    <el-dialog v-model="importOpen" title="导入店铺档案" width="min(620px, 94vw)" destroy-on-close>
      <el-alert
        title="按店铺编码更新或新增当前租户数据；平台、国家、类目及人员引用会在服务端校验。"
        type="info"
        :closable="false"
        show-icon
      />
      <el-upload
        class="store-import"
        drag
        :auto-upload="false"
        :limit="1"
        accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        :on-change="handleImportFile"
        :on-remove="clearImportFile"
      >
        <div>拖放 CSV / XLSX 到此处，或点击选择文件</div>
        <template #tip><span>单次导入以服务器校验结果为准，不包含任何平台凭据。</span></template>
      </el-upload>
      <el-button link type="primary" @click="downloadTemplate">下载 CSV 导入模板</el-button>
      <template #footer>
        <el-button @click="importOpen = false">取消</el-button>
        <el-button type="primary" :loading="importing" :disabled="!importFile" @click="submitImport">开始导入</el-button>
      </template>
    </el-dialog>

    <SubjectApiAccessDialog
      v-model="apiAccessOpen"
      subject-type="store"
      :row="selectedStore"
      @changed="resourcePage?.loadData()"
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
  fetchStores,
  importStores,
  updateMasterData,
  updateMasterDataStatus,
} from '../../api/masterData';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';

const auth = useAuthStore();
const resourcePage = ref(null);
const platformRows = ref([]);
const countryRows = ref([]);
const importOpen = ref(false);
const importFile = ref(null);
const importing = ref(false);
const apiAccessOpen = ref(false);
const selectedStore = ref(null);

const importAccess = computed(() => getActionAccess(auth, { permission: 'masterdata.manage' }));
const apiAccess = computed(() => getActionAccess(auth, { permission: 'integrations.view' }));
const platformOptions = computed(() => platformRows.value
  .filter((row) => !String(row.platform_type || '').startsWith('warehouse_'))
  .map((row) => ({
  label: `${row.name}（${row.code}）`, value: row.id,
  })));
const countryOptions = computed(() => countryRows.value.map((row) => ({
  label: `${row.name}（${row.country_code}）`, value: row.country_code,
})));

const columns = [
  { prop: 'code', label: '店铺档案编码', width: 170 },
  { prop: 'name', label: '店铺名称', width: 190 },
  { prop: 'platform_store_name', label: '平台店铺名', width: 180 },
  { prop: 'platform_name', label: '所属平台', width: 150 },
  { prop: 'api_connected', label: 'API 接入', type: 'api', width: 120 },
  { prop: 'category_name', label: '类目', width: 130 },
  { prop: 'operator_name', label: '负责运营', width: 120 },
  { prop: 'bd_name', label: 'BD', width: 120 },
  { prop: 'leader_name', label: '组长', width: 120 },
  { prop: 'is_connected', label: '是否建联', width: 100 },
  { prop: 'tactical_client', label: '战斧客户端', width: 150 },
  { prop: 'country_code', label: '国家', width: 90 },
  { prop: 'currency', label: '币种', width: 90 },
  { prop: 'timezone', label: '时区', width: 170 },
  { prop: 'status', label: '状态', type: 'status', width: 100 },
];

const formFields = computed(() => [
  { key: 'code', label: '店铺编码', required: true },
  { key: 'name', label: '店铺名称', required: true },
  { key: 'platform_store_name', label: '平台店铺名' },
  { key: 'platform_id', label: '平台编码', type: 'select', required: true, options: platformOptions.value },
  {
    key: 'country_code', label: '国家代码', type: 'select', required: true, options: countryOptions.value,
    onChange: applyCountryDefaults,
  },
  { key: 'currency', label: '币种', required: true },
  { key: 'timezone', label: '时区', required: true, default: 'UTC' },
  { key: 'status', label: '状态', type: 'select', required: true, default: 'active', filterable: false, options: [
    { label: '启用', value: 'active' }, { label: '停用', value: 'inactive' },
  ] },
  { key: 'is_connected', label: '是否建联', type: 'select', default: false, filterable: false, options: [
    { label: '是', value: true }, { label: '否', value: false },
  ] },
  { key: 'tactical_client', label: '战斧客户端' },
]);

function applyCountryDefaults(countryCode, form) {
  const country = countryRows.value.find((row) => row.country_code === countryCode);
  if (!country) return;
  form.currency = country.currency || '';
  form.timezone = country.timezone || 'UTC';
}

async function loadReferenceOptions() {
  const [platformResponse, countryResponse] = await Promise.all([
    fetchPlatforms({ status: 'active', page: 1, page_size: 100 }),
    fetchCountrySites({ status: 'active', page: 1, page_size: 100 }),
  ]);
  if (platformResponse?.success) platformRows.value = platformResponse.data?.results || [];
  if (countryResponse?.success) {
    const unique = new Map();
    for (const row of countryResponse.data?.results || []) if (!unique.has(row.country_code)) unique.set(row.country_code, row);
    countryRows.value = [...unique.values()];
  }
}

function openApiAccess(row) {
  selectedStore.value = row;
  apiAccessOpen.value = true;
}

function openImport() {
  if (!importAccess.value.allowed) return ElMessage.warning(importAccess.value.reason);
  importFile.value = null;
  importOpen.value = true;
}

function handleImportFile(file) {
  importFile.value = file.raw;
}

function clearImportFile() {
  importFile.value = null;
}

async function submitImport() {
  if (!importFile.value || !importAccess.value.allowed) return;
  importing.value = true;
  try {
    const response = await importStores(importFile.value);
    if (!response?.success) throw new Error(response?.message || '导入失败');
    const result = response.data || {};
    if (result.errors?.length) throw new Error(`导入校验未通过：${result.errors[0].message}`);
    ElMessage.success(`导入完成：新增 ${result.created || 0} 条，更新 ${result.updated || 0} 条`);
    importOpen.value = false;
    await resourcePage.value?.loadData();
  } catch (error) {
    ElMessage.error(error?.message || '导入失败');
  } finally {
    importing.value = false;
  }
}

function downloadTemplate() {
  const headers = ['code', 'name', 'platform_store_name', 'platform', 'country_code', 'currency', 'timezone', 'category', 'operator', 'bd', 'leader', 'is_connected', 'tactical_client', 'status'];
  const blob = new Blob([`\uFEFF${headers.join(',')}\r\n`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'stores-import-template.csv';
  link.click();
  URL.revokeObjectURL(url);
}

onMounted(loadReferenceOptions);
</script>

<style scoped>
.store-import { margin: 16px 0 8px; }
</style>
