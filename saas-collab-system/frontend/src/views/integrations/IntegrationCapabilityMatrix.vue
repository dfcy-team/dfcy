<template>
  <AppPage
    eyebrow="API DATA INTEGRATION"
    title="能力矩阵"
    subtitle="店铺按能力选择商城或广告 API；仓库按共享接入配置管理只读检查。"
    boundary-note="生产阶段只允许读取能力。写入能力在页面和请求两侧均保持关闭，任何 write_enabled=true 都会被后端拒绝。"
    :capability="capability"
  >
    <template #action>
      <el-button :loading="loading" @click="subjectKind === 'warehouse' ? warehouseMatrix?.load() : loadAuthorizations()">刷新</el-button>
      <el-button
        v-if="subjectKind === 'store' && selectedStore && canManage"
        type="primary"
        :loading="saving"
        :disabled="!canSave"
        :title="canSave ? '' : '只有有效授权（active/authorized）可以保存能力矩阵'"
        @click="save"
      >保存只读能力</el-button>
    </template>

    <section class="toolbar" aria-label="主体类型">
      <el-radio-group v-model="subjectKind" aria-label="店铺或仓库">
        <el-radio-button value="store">店铺</el-radio-button>
        <el-radio-button value="warehouse">仓库</el-radio-button>
      </el-radio-group>
    </section>
    <WarehouseCapabilityMatrix v-if="subjectKind === 'warehouse'" ref="warehouseMatrix" />
    <template v-else>
    <section class="toolbar" aria-label="店铺选择">
      <el-select v-model="selectedStoreId" filterable clearable placeholder="选择店铺" @change="loadCapabilities">
        <el-option
          v-for="item in stores"
          :key="item.store_id"
          :value="item.store_id"
          :label="`${item.platform || '-'} · ${item.store_name || item.store_code || `店铺 #${item.store_id}`}`"
        />
      </el-select>
      <el-tag v-if="selectedStore" effect="plain">{{ authorizations.length }} 个 API 连接</el-tag>
    </section>

    <div class="pagination" aria-label="能力矩阵店铺分页">
      <span class="pagination-total">共 {{ authorizationTotal }} 个店铺</span>
      <el-pagination
        v-model:current-page="authorizationPage"
        v-model:page-size="authorizationPageSize"
        :page-sizes="[20, 50, 100]"
        :total="authorizationTotal"
        layout="sizes, prev, pager, next, jumper"
        @current-change="loadAuthorizations"
        @size-change="handleAuthorizationSizeChange"
      />
    </div>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="page-alert" />
    <template v-if="selectedStore">
      <section class="summary-grid" aria-label="能力摘要">
        <article><span>可用代码</span><strong>{{ availableCodes.length }}</strong></article>
        <article><span>已配置</span><strong>{{ capabilityRows.length }}</strong></article>
        <article><span>只读启用</span><strong>{{ capabilityRows.filter((row) => row.read_enabled).length }}</strong></article>
        <article><span>写入启用</span><strong class="safe-zero">0</strong></article>
      </section>

      <el-table v-loading="loading" :data="capabilityRows" border stripe empty-text="当前授权暂无平台能力建议">
        <el-table-column label="能力代码 · 中文名称" min-width="180">
          <template #default="{ row }">{{ capabilityLabel(row.capability_code) }}</template>
        </el-table-column>
        <el-table-column label="对应 API 连接" min-width="280">
          <template #default="{ row }">
            <el-select v-model="row.authorization_id" :disabled="!canSave" size="small" @change="onSourceChange(row)">
              <el-option v-for="source in sourceOptions(row.capability_code)" :key="source.id" :value="source.id" :label="authorizationSourceLabel(source)" :disabled="!['active', 'authorized'].includes(source.status)" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="读取" width="120">
          <template #default="{ row }">
            <el-switch v-model="row.read_enabled" :disabled="!canSave || !sourceIsUsable(row)" active-text="开启" inactive-text="关闭" />
          </template>
        </el-table-column>
        <el-table-column label="写入" width="110">
          <template #default="{ row }">
            <el-tag type="info" effect="plain">关闭</el-tag>
            <span class="sr-only">write_enabled=false</span>
          </template>
        </el-table-column>
        <el-table-column label="同步方式" width="150">
          <template #default="{ row }">
              <el-select v-model="row.sync_mode" :disabled="!canSave || !sourceIsUsable(row)" size="small">
              <el-option label="手动" value="manual" />
              <el-option label="定时" value="scheduled" />
              <el-option label="实时" value="realtime" />
              <el-option label="Webhook" value="webhook" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="来源优先级" width="150">
          <template #default="{ row }">
            <el-input-number v-model="row.source_priority" :disabled="!canSave || !sourceIsUsable(row)" :min="1" :max="65535" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-select v-model="row.status" :disabled="!canSave || !sourceIsUsable(row)" size="small">
              <el-option label="启用" value="active" />
              <el-option label="停用" value="disabled" />
              <el-option label="已配置" value="configured" />
              <el-option label="错误" value="error" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column prop="last_success_at" label="最近成功" min-width="180">
          <template #default="{ row }">{{ row.last_success_at || '尚未运行' }}</template>
        </el-table-column>
        <el-table-column label="只读检查" min-width="160">
          <template #default="{ row }">
            <el-button v-if="checkResources[row.capability_code]" :disabled="!canCheck || !row.read_enabled || row.status !== 'active' || !sourceIsUsable(row) || Boolean(checking)" :loading="checking === row.capability_code" @click="checkCapability(row)">检查连接</el-button>
            <span v-else>尚未接入检查</span>
          </template>
        </el-table-column>
      </el-table>

      <section v-if="suggestions.length" class="suggestions" aria-label="平台能力建议">
        <header><h2>平台建议</h2><p>建议只用于填充本地表单，保存前请结合已授权 scopes 人工复核。</p></header>
        <el-table :data="suggestions" size="small" border empty-text="暂无能力建议">
          <el-table-column label="能力代码 · 中文名称" min-width="180"><template #default="{ row }">{{ capabilityLabel(row.capability_code) }}</template></el-table-column>
          <el-table-column prop="reason" label="建议依据" min-width="250" />
          <el-table-column prop="read_enabled" label="建议读取" width="110">
            <template #default="{ row }">{{ row.read_enabled ? '开启' : '关闭' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }"><el-button link type="primary" :disabled="!canSave" @click="applySuggestion(row)">载入建议</el-button></template>
          </el-table-column>
        </el-table>
      </section>
    </template>
    <el-empty v-else description="请选择店铺后维护能力矩阵" />
    </template>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import WarehouseCapabilityMatrix from '../../components/WarehouseCapabilityMatrix.vue';
import { useAuthStore } from '../../stores/auth';
import { useMock } from '../../api/request';
import { fetchStoreAuthorizations, fetchStoreAuthorizationDetail, fetchStoreCapabilityMatrix, updateStoreCapabilityMatrix, checkIntegrationReadonlyConnection } from '../../api/integrations';
import { authorizationSourceLabel, capabilityLabel } from '../../utils/integrationCapabilityLabels';

const route = useRoute();
const subjectKind = ref(route.query.subject_type === 'warehouse' ? 'warehouse' : 'store');
const warehouseMatrix = ref(null);
const checking = ref('');
const checkResources = { PRODUCT: 'platform_product', ORDER: 'sales_order', RETURN_REFUND: 'refund_return', SETTLEMENT: 'settlement_bill' };
const auth = useAuthStore();
const capability = ref(useMock ? 'mock' : 'pending');
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const stores = ref([]);
const authorizations = ref([]);
let requestedAuthorizationId = String(route.query.authorization_id || '').trim();
const pendingDeepLink = ref(Boolean(requestedAuthorizationId));
const selectedStoreId = ref(null);
const authorizationPage = ref(1);
const authorizationPageSize = ref(20);
const authorizationTotal = ref(0);
const capabilityRows = ref([]);
const availableCodes = ref([]);
const suggestions = ref([]);

const selectedStore = computed(() => stores.value.find((item) => String(item.store_id) === String(selectedStoreId.value)) || null);
const canManage = computed(() => auth.hasPermission('integrations.store.authorize'));
const canCheck = computed(() => auth.hasPermission('integrations.run_live_readonly'));
const canSave = computed(() => canManage.value && authorizations.value.some((item) => ['active', 'authorized'].includes(item.status)));

function responseRows(response) {
  const data = response?.data;
  return Array.isArray(data) ? data : (data?.results || data?.items || []);
}
function sourceOptions(code) {
  return authorizations.value.filter((item) => item.api_type === 'advertising'
    ? ['ADVERTISING', 'REPORT'].includes(code)
    : code !== 'ADVERTISING');
}
function sourceIsUsable(row) {
  const source = authorizations.value.find((item) => String(item.id) === String(row.authorization_id));
  return Boolean(source && ['active', 'authorized'].includes(source.status));
}
function onSourceChange(row) {
  row.read_enabled = false;
  row.status = 'disabled';
  row.last_success_at = null;
}

async function loadAuthorizations() {
  loading.value = true;
  error.value = '';
  const response = await fetchStoreAuthorizations({ group_by_store: '1', page: authorizationPage.value, page_size: authorizationPageSize.value });
  capability.value = response?.data?.api_status || (useMock ? 'mock' : response?.success ? 'connected' : 'degraded');
  if (!response?.success) {
    stores.value = [];
    authorizations.value = [];
    authorizationTotal.value = 0;
    capabilityRows.value = [];
    error.value = response?.message || '读取店铺能力列表失败。';
  } else {
    const data = response?.data;
    stores.value = responseRows(response);
    authorizationTotal.value = Number(data?.count ?? data?.total ?? stores.value.length);
    if (pendingDeepLink.value) {
      const detailResponse = await fetchStoreAuthorizationDetail(requestedAuthorizationId);
      const storeId = detailResponse?.data?.store_id;
      if (detailResponse?.success && storeId) {
        selectedStoreId.value = storeId;
        if (!stores.value.some((item) => String(item.store_id) === String(storeId))) {
          const pinned = await fetchStoreAuthorizations({ group_by_store: '1', store_id: storeId, page: 1, page_size: 1 });
          if (pinned?.success && responseRows(pinned).length) stores.value.unshift(responseRows(pinned)[0]);
        }
      }
      pendingDeepLink.value = false;
    }
    if (!stores.value.some((item) => String(item.store_id) === String(selectedStoreId.value))) {
      selectedStoreId.value = stores.value[0]?.store_id || null;
    }
    if (selectedStoreId.value) await loadCapabilities();
  }
  loading.value = false;
}

function handleAuthorizationSizeChange(size) {
  authorizationPageSize.value = size;
  authorizationPage.value = 1;
  loadAuthorizations();
}

async function loadCapabilities() {
  if (!selectedStoreId.value) { authorizations.value = []; capabilityRows.value = []; suggestions.value = []; return; }
  loading.value = true;
  const response = await fetchStoreCapabilityMatrix(selectedStoreId.value);
  loading.value = false;
  if (!response?.success) { authorizations.value = []; capabilityRows.value = []; suggestions.value = []; error.value = response?.message || '读取能力矩阵失败。'; return; }
  const data = response.data || {};
  authorizations.value = data.authorizations || selectedStore.value?.authorizations || [];
  availableCodes.value = data.available_codes || [];
  suggestions.value = data.suggestions || [];
  const existing = new Map((data.results || []).map((row) => [row.capability_code, row]));
  const suggested = new Map(suggestions.value.map((row) => [row.capability_code, row]));
  capabilityRows.value = availableCodes.value.map((code) => {
    const source = sourceOptions(code).find((item) => String(item.id) === String(existing.get(code)?.authorization_id))
      || sourceOptions(code).find((item) => ['active', 'authorized'].includes(item.status))
      || sourceOptions(code)[0];
    return {
      capability_code: code,
      authorization_id: source?.id || null,
      read_enabled: Boolean(existing.get(code)?.read_enabled ?? false),
      write_enabled: false,
      sync_mode: existing.get(code)?.sync_mode || suggested.get(code)?.sync_mode || 'manual',
      source_priority: existing.get(code)?.source_priority || suggested.get(code)?.source_priority || 100,
      status: existing.get(code)?.status || 'disabled',
      last_success_at: existing.get(code)?.last_success_at || null,
    };
  });
}

function applySuggestion(suggestion) {
  const row = capabilityRows.value.find((item) => item.capability_code === suggestion.capability_code);
  if (!row) return;
  if (suggestion.authorization_id && sourceOptions(row.capability_code).some((item) => item.id === suggestion.authorization_id)) {
    row.authorization_id = suggestion.authorization_id;
  }
  row.read_enabled = Boolean(suggestion.read_enabled);
  row.sync_mode = suggestion.sync_mode || row.sync_mode;
  row.source_priority = suggestion.source_priority || row.source_priority;
  row.status = suggestion.status || (row.read_enabled ? 'active' : 'disabled');
  ElMessage.success(`${capabilityLabel(suggestion.capability_code)} 建议已载入表单，请保存前复核。`);
}

async function save() {
  if (!selectedStore.value) return ElMessage.warning('请先选择店铺。');
  if (!canManage.value) return ElMessage.error('当前角色没有维护能力矩阵的权限。');
  if (!canSave.value) return ElMessage.warning('该店铺没有有效授权，无法保存能力矩阵。');
  if (capabilityRows.value.some((row) => !row.authorization_id)) return ElMessage.warning('请为每项能力选择对应的 API 连接。');
  try { await ElMessageBox.confirm('确认保存当前只读能力？所有 write_enabled 将强制保持 false。', '保存能力矩阵', { type: 'warning', confirmButtonText: '确认保存' }); } catch { return; }
  saving.value = true;
  const response = await updateStoreCapabilityMatrix(
    selectedStore.value.store_id,
    capabilityRows.value.map((row) => ({
      capability_code: row.capability_code,
      authorization_id: row.authorization_id,
      read_enabled: Boolean(row.read_enabled),
      write_enabled: false,
      sync_mode: row.sync_mode || 'manual',
      source_priority: Number(row.source_priority) || 100,
      status: row.status || 'disabled'
    }))
  );
  saving.value = false;
  if (!response?.success) return ElMessage.error(response?.message || '能力矩阵保存失败。');
  ElMessage.success('能力矩阵已保存，写入能力仍保持关闭。');
  await loadCapabilities();
}

async function checkCapability(row) {
  if (!canCheck.value || !row.read_enabled || row.status !== 'active' || checking.value || !checkResources[row.capability_code]) return;
  const source = authorizations.value.find((item) => String(item.id) === String(row.authorization_id));
  if (!source || !sourceIsUsable(row)) return;
  try { await ElMessageBox.confirm('按已保存的能力和授权调用只读接口；不会保存表单、刷新令牌或启用任务。是否继续？', '确认只读检查', { type: 'warning' }); } catch { return; }
  checking.value = row.capability_code;
  try {
    const response = await checkIntegrationReadonlyConnection(source.integration_config_id, { store_authorization_id: source.id, resource_type: checkResources[row.capability_code] });
    if (!response?.success) throw new Error(response?.message || '只读检查失败');
    ElMessage.success('只读检查通过，任务启停状态未改变。');
  } catch (reason) { ElMessage.error(reason?.message || '只读检查失败'); }
  finally { checking.value = ''; }
}
watch(() => route.query.subject_type, (value) => { subjectKind.value = value === 'warehouse' ? 'warehouse' : 'store'; });
watch(() => route.query.authorization_id, (value) => {
  requestedAuthorizationId = String(value || '').trim();
  if (requestedAuthorizationId) { pendingDeepLink.value = true; loadAuthorizations(); }
});
watch(subjectKind, (value) => { if (value === 'store' && !stores.value.length) loadAuthorizations(); });
onMounted(() => { if (subjectKind.value === 'store') loadAuthorizations(); });
</script>

<style scoped>
.toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin: 18px 0; }
.toolbar .el-select { width: min(440px, 100%); }
.pagination { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 0 2px 4px; color: #64748b; font-size: 13px; }
.pagination :deep(.el-pagination) { margin-left: auto; }
.page-alert { margin-bottom: 14px; }
.summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }
.summary-grid article { padding: 14px 16px; border: 1px solid #dbe3ec; border-radius: 8px; background: #fff; }
.summary-grid span { display: block; color: #64748b; font-size: 12px; }
.summary-grid strong { display: block; margin-top: 6px; color: #172033; font-size: 22px; }
.safe-zero { color: #15803d !important; }
.suggestions { margin-top: 22px; padding: 16px; border: 1px solid #dbe3ec; border-radius: 8px; background: #f8fafc; }
.suggestions h2 { margin: 0; color: #172033; font-size: 17px; }
.suggestions p { margin: 5px 0 14px; color: #64748b; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (max-width: 760px) { .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) { .pagination { align-items: flex-start; flex-direction: column; } .pagination :deep(.el-pagination) { margin-left: 0; } }
</style>
