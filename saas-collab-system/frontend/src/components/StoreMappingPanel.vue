<template>
  <section
    class="store-mapping-panel"
    :class="{ 'store-mapping-panel--standalone': standalone }"
    aria-label="店铺平台关联"
  >
    <header class="panel-heading">
      <div>
        <h2>平台身份与店铺关联</h2>
        <p>
          选择已授权的平台身份建立受控关联；平台店铺 ID、区域和授权来源由服务端派生。
        </p>
      </div>
      <div class="panel-actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button
          v-if="showApiAccess && currentStore"
          link
          type="primary"
          :disabled="!apiEnabled || apiAccessDisabled"
          :title="!apiEnabled ? apiDisabledReason : apiAccessDisabledReason"
          @click="emit('open-api', currentStore)"
        >API 接入</el-button>
        <el-button
          v-if="mappingManageAccess.visible"
          type="primary"
          :disabled="mappingManageAccess.disabled || !apiEnabled"
          :title="mappingManageAccess.disabled ? mappingManageAccess.reason : apiDisabledReason"
          @click="openCreate"
        >新建平台关联</el-button>
      </div>
    </header>

    <el-alert
      v-if="!apiEnabled"
      title="API 数据接入模块当前未启用，平台关联操作暂不可用。"
      :description="apiDisabledReason"
      type="warning"
      show-icon
      :closable="false"
      class="panel-alert"
    />
    <el-alert
      v-else-if="!mappingViewAccess.allowed"
      title="当前角色没有查看店铺平台关联的权限。"
      :description="mappingViewAccess.reason"
      type="warning"
      show-icon
      :closable="false"
      class="panel-alert"
    />
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="panel-alert" />

    <section v-if="standalone" class="mapping-toolbar" aria-label="平台关联筛选">
      <el-select v-model="filters.platform" clearable placeholder="全部平台" @change="applyFilters">
        <el-option label="Shopee" value="shopee" />
        <el-option label="TikTok Shop" value="tiktok" />
      </el-select>
      <el-select
        v-model="filters.store_id"
        clearable
        filterable
        remote
        reserve-keyword
        placeholder="全部店铺"
        :remote-method="searchStores"
        :loading="optionsLoading"
        @change="applyFilters"
      >
        <el-option
          v-for="item in storeOptions"
          :key="item.id"
          :label="storeOptionLabel(item)"
          :value="String(item.id)"
        />
      </el-select>
      <el-select v-model="filters.status" clearable placeholder="全部状态" @change="applyFilters">
        <el-option label="启用" value="active" />
        <el-option label="停用" value="inactive" />
      </el-select>
      <el-button type="primary" @click="applyFilters">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </section>

    <el-table
      v-loading="loading"
      :data="rows"
      border
      stripe
      empty-text="暂无平台关联，请先完成店铺授权"
      class="mapping-table"
    >
      <el-table-column prop="platform" label="平台" width="125" />
      <el-table-column label="店铺档案" min-width="190">
        <template #default="{ row }">
          <div>{{ row.store_name || row.store_code || (row.store_id ? `店铺 #${row.store_id}` : '-') }}</div>
          <small>{{ row.store_code || (row.store_id ? `store_id=${row.store_id}` : '') }}</small>
        </template>
      </el-table-column>
      <el-table-column label="授权身份" min-width="190">
        <template #default="{ row }">
          <div>{{ authorizationLabel(row) }}</div>
          <small v-if="authorizationFor(row)?.id">授权 #{{ authorizationFor(row).id }}</small>
        </template>
      </el-table-column>
      <el-table-column label="平台店铺 ID" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">{{ row.platform_store_id || row.platform_store_id_masked || '-' }}</template>
      </el-table-column>
      <el-table-column prop="region" label="区域" width="90" />
      <el-table-column label="来源" width="150">
        <template #default="{ row }">{{ sourceLabel(row.mapping_source) }}</template>
      </el-table-column>
      <el-table-column label="最近验证" min-width="165">
        <template #default="{ row }">{{ formatDate(row.last_verified_at) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="plain">
            {{ row.status === 'active' ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" fixed="right" width="145">
        <template #default="{ row }">
          <el-button
            v-if="mappingManageAccess.visible"
            link
            :type="row.status === 'active' ? 'danger' : 'success'"
            :disabled="mappingManageAccess.disabled || !apiEnabled"
            :title="mappingManageAccess.disabled ? mappingManageAccess.reason : apiDisabledReason"
            @click="toggleStatus(row)"
          >{{ row.status === 'active' ? '停用' : '启用' }}</el-button>
          <el-button
            v-if="currentStore && showApiAccess"
            link
            type="primary"
            :disabled="!apiEnabled || apiAccessDisabled"
            :title="!apiEnabled ? apiDisabledReason : apiAccessDisabledReason"
            @click="emit('open-api', currentStore)"
          >API 接入</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="standalone" class="panel-pagination" aria-label="平台关联分页">
      <span>共 {{ total }} 条</span>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :page-sizes="[20, 50, 100]"
        :total="total"
        layout="sizes, prev, pager, next, jumper"
        @current-change="load"
        @size-change="handleSizeChange"
      />
    </div>

    <el-dialog v-model="createOpen" title="新建平台关联" width="min(640px, 94vw)" destroy-on-close>
      <el-alert
        title="关联只接受当前租户可见的已授权身份；平台店铺 ID、区域、授权来源和身份摘要不会由页面手工录入。"
        type="info"
        show-icon
        :closable="false"
      />
      <el-form label-position="top" class="mapping-form">
        <el-form-item v-if="!currentStore" label="店铺档案" required>
          <el-select
            v-model="createForm.store_id"
            filterable
            clearable
            remote
            reserve-keyword
            :remote-method="searchStores"
            :loading="optionsLoading"
            placeholder="选择店铺档案"
            style="width: 100%"
            @change="handleCreateStoreChange"
          >
            <el-option
              v-for="item in storeOptions"
              :key="item.id"
              :label="storeOptionLabel(item)"
              :value="String(item.id)"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="已授权平台身份" required>
          <el-select
            v-model="createForm.authorization_id"
            filterable
            clearable
            remote
            reserve-keyword
            :remote-method="searchAuthorizations"
            :loading="optionsLoading"
            :disabled="!createForm.store_id"
            placeholder="选择有效授权"
            style="width: 100%"
          >
            <el-option
              v-for="item in availableAuthorizations"
              :key="item.id"
              :label="authorizationOptionLabel(item)"
              :value="String(item.id)"
            />
          </el-select>
        </el-form-item>
        <el-alert
          v-if="createForm.store_id && !availableAuthorizations.length"
          title="当前店铺没有可用于建立关联的有效授权。"
          type="warning"
          show-icon
          :closable="false"
        />
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button
          type="primary"
          :loading="saving"
          :disabled="!createForm.store_id || !createForm.authorization_id || mappingManageAccess.disabled || !apiEnabled"
          @click="submitCreate"
        >确认建立关联</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useAuthStore } from '../stores/auth';
import { getActionAccess } from '../utils/actionAccess';
import {
  createStoreMapping,
  fetchStoreMappingOptions,
  fetchStoreMappings,
  updateStoreMapping,
} from '../api/integrations';

const props = defineProps({
  store: { type: Object, default: null },
  storeId: { type: [String, Number], default: null },
  standalone: { type: Boolean, default: false },
  showApiAccess: { type: Boolean, default: true },
  autoLoad: { type: Boolean, default: true },
});

const emit = defineEmits(['changed', 'open-api']);
const auth = useAuthStore();
const loading = ref(false);
const saving = ref(false);
const optionsLoading = ref(false);
const error = ref('');
const rows = ref([]);
const storeOptions = ref([]);
const authorizationOptions = ref([]);
const createOpen = ref(false);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const filters = reactive({ platform: '', status: '', store_id: '' });
const createForm = reactive({ store_id: '', authorization_id: '' });

const mappingViewAccess = computed(() => getActionAccess(auth, {
  permission: 'integrations.store_mapping.view',
  unauthorizedBehavior: 'disable',
}));
const mappingManageAccess = computed(() => getActionAccess(auth, {
  permission: 'integrations.store_mapping.manage',
  unauthorizedBehavior: 'disable',
}));
const integrationViewAccess = computed(() => getActionAccess(auth, {
  permission: 'integrations.view',
  unauthorizedBehavior: 'disable',
}));
const storeApiViewAccess = computed(() => getActionAccess(auth, {
  permission: 'integrations.store.view',
  unauthorizedBehavior: 'disable',
}));
const apiAccessAllowed = computed(() => integrationViewAccess.value.allowed && storeApiViewAccess.value.allowed);
const apiAccessDisabled = computed(() => !apiAccessAllowed.value);
const apiAccessDisabledReason = computed(() => (
  integrationViewAccess.value.allowed
    ? (storeApiViewAccess.value.reason || '当前角色无权查看店铺 API 接入')
    : (integrationViewAccess.value.reason || '当前角色无权查看 API 数据接入')
));
const apiEnabled = computed(() => auth.isModuleEnabled('api_integrations'));
const apiDisabledReason = computed(() => {
  const status = auth.moduleStatuses?.api_integrations;
  return status ? `API 数据接入模块当前状态：${status}` : 'API 数据接入模块当前未启用';
});
const contextStoreId = computed(() => props.store?.id ?? props.storeId ?? null);
const currentStore = computed(() => props.store || storeOptions.value.find((item) => String(item.id) === String(contextStoreId.value)) || null);
const availableAuthorizations = computed(() => {
  const selectedStoreId = currentStore.value?.id ?? createForm.store_id ?? contextStoreId.value;
  return authorizationOptions.value.filter((item) => (
    !selectedStoreId || String(item.store_id) === String(selectedStoreId)
  ) && ['active', 'authorized'].includes(String(item.status || '').toLowerCase()));
});

function responseData(response) {
  const data = response?.data;
  return data && typeof data === 'object' ? data : {};
}

function normalizeStoreOptions(data) {
  return (Array.isArray(data?.stores) ? data.stores : []).map((item) => ({
    ...item,
    id: item.id ?? item.store_id,
  })).filter((item) => item.id !== null && item.id !== undefined);
}

function normalizeAuthorizationOptions(data) {
  return (Array.isArray(data?.authorizations) ? data.authorizations : []).map((item) => ({
    ...item,
    id: item.id ?? item.authorization_id,
  })).filter((item) => item.id !== null && item.id !== undefined);
}

function mergeOptions(current, incoming, selectedIds = []) {
  const byId = new Map();
  [...incoming, ...current.filter((item) => selectedIds.includes(String(item.id)))].forEach((item) => {
    if (item?.id !== null && item?.id !== undefined) byId.set(String(item.id), item);
  });
  return [...byId.values()];
}

function normalizeMappingRows(data) {
  const rows = Array.isArray(data?.results)
    ? data.results
    : (Array.isArray(data?.items) ? data.items : (Array.isArray(data?.store_mappings) ? data.store_mappings : []));
  return rows.map((item) => ({
    ...item,
    store_id: item.store_id ?? item.store?.id,
  }));
}

function queryParams() {
  const storeId = contextStoreId.value || filters.store_id || undefined;
  return {
    page: page.value,
    page_size: pageSize.value,
    ...(filters.platform ? { platform: filters.platform } : {}),
    ...(filters.status ? { status: filters.status } : {}),
    ...(storeId ? { store_id: storeId } : {}),
  };
}

async function load() {
  if (!apiEnabled.value || !mappingViewAccess.value.allowed) {
    rows.value = [];
    storeOptions.value = [];
    authorizationOptions.value = [];
    total.value = 0;
    return;
  }
  loading.value = true;
  error.value = '';
  try {
    const [mappingResponse, optionResponse] = await Promise.all([
      fetchStoreMappings(queryParams()),
      fetchStoreMappingOptions({
        page: 1,
        page_size: 100,
        ...(filters.platform ? { platform: filters.platform } : {}),
        ...(contextStoreId.value ? { store_id: contextStoreId.value } : {}),
      }),
    ]);
    if (!mappingResponse?.success) throw new Error(mappingResponse?.message || '读取店铺平台关联失败');
    const mappingData = responseData(mappingResponse);
    const optionData = responseData(optionResponse);
    const optionStores = normalizeStoreOptions(optionData);
    if (optionStores.length || !contextStoreId.value) storeOptions.value = optionStores;
    authorizationOptions.value = normalizeAuthorizationOptions(optionData);
    rows.value = normalizeMappingRows(mappingData).filter((row) => (
      !contextStoreId.value || String(row.store_id) === String(contextStoreId.value)
    ));
    total.value = Number(mappingData.count ?? mappingData.total ?? rows.value.length);
    if (!optionResponse?.success && !authorizationOptions.value.length) {
      error.value = optionResponse?.message || '店铺关联已读取，但授权身份选项暂不可用';
    }
  } catch (reason) {
    rows.value = [];
    total.value = 0;
    error.value = reason?.message || '读取店铺平台关联失败';
  } finally {
    loading.value = false;
  }
}

async function searchStores(keyword = '') {
  if (!apiEnabled.value || !mappingViewAccess.value.allowed) return;
  optionsLoading.value = true;
  try {
    const response = await fetchStoreMappingOptions({
      page: 1,
      page_size: 100,
      search: String(keyword || '').trim(),
      ...(filters.platform ? { platform: filters.platform } : {}),
    });
    if (!response?.success) throw new Error(response?.message || '店铺选项搜索失败');
    const stores = normalizeStoreOptions(responseData(response));
    storeOptions.value = mergeOptions(storeOptions.value, stores, [filters.store_id, createForm.store_id].filter(Boolean));
  } catch (reason) {
    error.value = reason?.message || '店铺选项搜索失败';
  } finally {
    optionsLoading.value = false;
  }
}

async function searchAuthorizations(keyword = '') {
  if (!apiEnabled.value || !mappingViewAccess.value.allowed) return;
  const storeId = createForm.store_id || contextStoreId.value;
  if (!storeId) {
    authorizationOptions.value = [];
    return;
  }
  optionsLoading.value = true;
  try {
    const response = await fetchStoreMappingOptions({
      page: 1,
      page_size: 100,
      store_id: storeId,
      search: String(keyword || '').trim(),
      ...(filters.platform ? { platform: filters.platform } : {}),
    });
    if (!response?.success) throw new Error(response?.message || '授权身份搜索失败');
    const authorizations = normalizeAuthorizationOptions(responseData(response));
    authorizationOptions.value = mergeOptions(
      authorizationOptions.value,
      authorizations,
      [createForm.authorization_id].filter(Boolean),
    );
  } catch (reason) {
    error.value = reason?.message || '授权身份搜索失败';
  } finally {
    optionsLoading.value = false;
  }
}

function storeOptionLabel(item) {
  return `${item.name || item.store_name || item.code || `店铺 #${item.id}`} · ${item.code || item.store_code || `#${item.id}`}`;
}

function authorizationFor(row) {
  if (row.authorization_id) {
    return authorizationOptions.value.find((item) => String(item.id) === String(row.authorization_id));
  }
  const sameStore = authorizationOptions.value.filter((item) => String(item.store_id) === String(row.store_id));
  return sameStore.find((item) => String(item.platform_store_id || item.platform_store_id_masked) === String(row.platform_store_id))
    || sameStore.find((item) => item.status === 'active')
    || sameStore[0]
    || null;
}

function authorizationLabel(row) {
  const authorization = authorizationFor(row);
  if (!authorization) return row.authorization_id ? `授权 #${row.authorization_id}` : '已关联授权';
  const platformId = authorization.platform_store_id_masked || authorization.platform_store_id || row.platform_store_id;
  return `${authorization.platform || row.platform || '-'} · ${platformId || `授权 #${authorization.id}`}`;
}

function authorizationOptionLabel(item) {
  const platformId = item.platform_store_id_masked || item.platform_store_id || '平台身份已掩码';
  return `${item.platform || '-'} · ${item.region || '-'} · ${platformId} · ${item.status || '未知'}`;
}

function sourceLabel(value) {
  return ({ oauth_callback: 'OAuth 回调', manual: '人工建立', synthetic_fixture: '演练数据' })[value] || value || '-';
}

function formatDate(value) {
  if (!value) return '未验证';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false });
}

function applyFilters() {
  page.value = 1;
  load();
}

function resetFilters() {
  Object.assign(filters, { platform: '', status: '', store_id: '' });
  applyFilters();
}

function handleSizeChange(size) {
  pageSize.value = size;
  page.value = 1;
  load();
}

async function openCreate() {
  if (!mappingManageAccess.value.allowed || !apiEnabled.value) {
    ElMessage.warning(mappingManageAccess.value.reason || apiDisabledReason.value);
    return;
  }
  if (!authorizationOptions.value.length && !storeOptions.value.length) await load();
  createForm.store_id = String(currentStore.value?.id ?? filters.store_id ?? '');
  createForm.authorization_id = '';
  createOpen.value = true;
}

async function handleCreateStoreChange(storeId) {
  createForm.authorization_id = '';
  if (!storeId || contextStoreId.value) return;
  await searchAuthorizations('');
}

async function submitCreate() {
  if (!mappingManageAccess.value.allowed || !apiEnabled.value) return;
  const storeId = Number(createForm.store_id);
  const authorizationId = Number(createForm.authorization_id);
  if (!Number.isInteger(storeId) || storeId < 1 || !Number.isInteger(authorizationId) || authorizationId < 1) {
    ElMessage.warning('请选择店铺档案和已授权平台身份。');
    return;
  }
  const authorization = authorizationOptions.value.find((item) => String(item.id) === String(authorizationId));
  if (!authorization || String(authorization.store_id) !== String(storeId)) {
    ElMessage.warning('所选授权与店铺档案不匹配，请重新选择。');
    return;
  }
  try {
    await ElMessageBox.confirm('确认建立当前店铺与平台授权身份的关联？操作将写入集成审计。', '确认建立关联', {
      type: 'warning',
      confirmButtonText: '确认建立',
      cancelButtonText: '取消',
    });
  } catch (_reason) {
    return;
  }
  saving.value = true;
  try {
    const response = await createStoreMapping({
      store_id: storeId,
      authorization_id: authorizationId,
      timezone: authorization.timezone || currentStore.value?.timezone || '',
      currency: authorization.currency || currentStore.value?.currency || '',
    });
    if (!response?.success) throw new Error(response?.message || '建立店铺平台关联失败');
    ElMessage.success('店铺平台关联已建立。');
    createOpen.value = false;
    await load();
    emit('changed');
  } catch (reason) {
    ElMessage.error(reason?.message || '建立店铺平台关联失败');
  } finally {
    saving.value = false;
  }
}

async function toggleStatus(row) {
  if (!mappingManageAccess.value.allowed || !apiEnabled.value) {
    ElMessage.warning(mappingManageAccess.value.reason || apiDisabledReason.value);
    return;
  }
  const nextStatus = row.status === 'active' ? 'inactive' : 'active';
  try {
    await ElMessageBox.confirm(
      nextStatus === 'inactive' ? '停用后该平台身份不会参与后续关联数据处理，确认停用？' : '确认重新启用该平台关联？',
      nextStatus === 'inactive' ? '停用平台关联' : '启用平台关联',
      { type: nextStatus === 'inactive' ? 'warning' : 'info', confirmButtonText: nextStatus === 'inactive' ? '确认停用' : '确认启用', cancelButtonText: '取消' },
    );
  } catch (_reason) {
    return;
  }
  saving.value = true;
  try {
    const response = await updateStoreMapping(row.id, { status: nextStatus });
    if (!response?.success) throw new Error(response?.message || `${nextStatus === 'inactive' ? '停用' : '启用'}平台关联失败`);
    ElMessage.success(nextStatus === 'inactive' ? '平台关联已停用。' : '平台关联已启用。');
    await load();
    emit('changed');
  } catch (reason) {
    ElMessage.error(reason?.message || '平台关联状态更新失败');
  } finally {
    saving.value = false;
  }
}

watch(contextStoreId, () => {
  if (props.autoLoad) load();
});

onMounted(() => {
  if (props.autoLoad) load();
});

defineExpose({ load, openCreate, toggleStatus, searchStores, searchAuthorizations });
</script>

<style scoped>
.store-mapping-panel { padding: 2px 0; }
.store-mapping-panel--standalone { padding: 0; }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 16px; }
.panel-heading h2 { margin: 0; color: #253247; font-size: 18px; line-height: 1.35; }
.panel-heading p { margin: 5px 0 0; color: #64748b; font-size: 13px; line-height: 1.55; }
.panel-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px; }
.panel-alert { margin-bottom: 14px; }
.mapping-toolbar { display: flex; flex-wrap: wrap; gap: 10px; margin: 14px 0; }
.mapping-toolbar .el-select { width: 165px; }
.mapping-table { width: 100%; }
.mapping-table small { color: #64748b; }
.panel-pagination { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 2px 0; color: #64748b; font-size: 13px; }
.panel-pagination :deep(.el-pagination) { margin-left: auto; }
.mapping-form { margin-top: 18px; }
@media (max-width: 760px) {
  .panel-heading { flex-direction: column; }
  .panel-actions { justify-content: flex-start; }
  .panel-pagination { align-items: flex-start; flex-direction: column; }
  .panel-pagination :deep(.el-pagination) { margin-left: 0; }
}
</style>
