<template>
  <AdminResourcePage
    ref="resourcePage"
    eyebrow="MASTER DATA"
    title="店铺档案"
    subtitle="维护平台、站点、业务身份、履约方式及建联信息。"
    boundary-note="平台站点档案不是授权连接；账号、Token 和凭据仍由独立授权中心管理。"
    entity-label="店铺"
    :loader="fetchStores"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="(payload) => createMasterData('stores', payload)"
    :edit-handler="(id, payload) => updateMasterData('stores', id, payload)"
    :delete-handler="(id) => deleteMasterData('stores', id)"
    :status-handler="(row, status) => updateMasterDataStatus('stores', row.id, status)"
    create-permission="masterdata.manage"
    manage-permission="masterdata.manage"
  >
    <template #actions>
      <el-button type="primary" plain @click="openMigrationPreview">站点映射预览</el-button>
      <el-button type="primary" plain @click="importOpen = true">导入店铺档案</el-button>
      <el-button type="primary" plain @click="downloadTemplate">下载 CSV 导入模板</el-button>
    </template>
    <template #row-actions="{ row }">
      <el-button link type="primary" @click.stop="openApiAccess(row)">API 接入</el-button>
      <el-button link type="primary" @click.stop="openCapabilityMatrix(row)">能力矩阵</el-button>
    </template>
  </AdminResourcePage>

  <el-dialog v-model="migrationOpen" title="历史店铺 · 站点映射预览" width="min(1240px, 96vw)" :close-on-click-modal="false">
    <el-alert
      title="预览只读取当前租户中尚未关联平台站点的店铺；只有同租户、同平台、同国家代码且唯一命中的 exact 项可应用。不会创建站点、覆盖已有站点或自动处理 ambiguous / unmatched。"
      type="info"
      :closable="false"
      show-icon
    />
    <div class="migration-toolbar">
      <div class="migration-counts" aria-label="映射预览统计">
        <span>exact <strong>{{ migrationCounts.exact }}</strong></span>
        <span>ambiguous <strong>{{ migrationCounts.ambiguous }}</strong></span>
        <span>unmatched <strong>{{ migrationCounts.unmatched }}</strong></span>
      </div>
      <div class="migration-actions">
        <el-checkbox
          :model-value="allExactSelected"
          :indeterminate="exactSelectionIndeterminate"
          :disabled="!exactRows.length"
          @change="toggleAllExact"
        >全选 exact</el-checkbox>
        <el-button plain :loading="migrationLoading" @click="loadMigrationPreview">刷新预览</el-button>
      </div>
    </div>
    <el-alert v-if="migrationError" :title="migrationError" type="error" :closable="false" show-icon />
    <el-table
      ref="migrationTable"
      v-loading="migrationLoading"
      :data="migrationRows"
      row-key="store_id"
      border
      empty-text="暂无待映射的历史店铺"
      @selection-change="handleMigrationSelection"
    >
      <el-table-column type="selection" width="54" :selectable="isExactMigrationRow" />
      <el-table-column label="匹配状态" width="112" fixed="left">
        <template #default="{ row }">
          <el-tag :type="migrationStatusType(row)" effect="plain">{{ migrationStatus(row) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="店铺" min-width="210">
        <template #default="{ row }">
          <div>{{ row.store_name || row.name || '-' }}</div>
          <small>{{ row.store_code || row.code || `#${row.store_id}` }}</small>
        </template>
      </el-table-column>
      <el-table-column prop="platform_name" label="平台" min-width="140" />
      <el-table-column prop="country_code" label="国家" width="90" />
      <el-table-column label="候选站点" min-width="230">
        <template #default="{ row }">
          <div v-if="migrationCandidates(row).length" class="candidate-list">
            <span v-for="candidate in migrationCandidates(row)" :key="candidate.id || candidate.site_code">
              {{ candidate.name || candidate.site_code || `#${candidate.id}` }}<small v-if="candidate.site_code">（{{ candidate.site_code }}）</small>
            </span>
          </div>
          <span v-else class="muted">无候选</span>
        </template>
      </el-table-column>
      <el-table-column label="变更前" min-width="150">
        <template #default="{ row }">{{ migrationSiteLabel(row, 'before') }}</template>
      </el-table-column>
      <el-table-column label="变更后" min-width="150">
        <template #default="{ row }">{{ migrationSiteLabel(row, 'after') }}</template>
      </el-table-column>
      <el-table-column prop="reason" label="原因" min-width="260" show-overflow-tooltip />
      <el-table-column label="置信度" width="100">
        <template #default="{ row }">{{ migrationConfidence(row) }}</template>
      </el-table-column>
    </el-table>
    <div class="migration-selection-note">
      已选择 {{ selectedMigrationStoreIds.length }} 条 exact；应用前后端会重新计算匹配状态，并跳过已有关联或发生冲突的店铺。
    </div>
    <template #footer>
      <el-button @click="migrationOpen = false">关闭</el-button>
      <el-button
        type="primary"
        :loading="migrationApplying"
        :disabled="!migrationManageAccess.allowed || !selectedMigrationStoreIds.length"
        @click="confirmMigration"
      >应用选中的 exact 映射</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="importOpen" title="导入店铺档案" width="min(680px, 94vw)">
    <el-alert title="支持 CSV / XLSX；按店铺档案编码幂等更新。导入列：店铺档案编码、店铺名称、平台、平台店铺名、类目、负责运营、BD、组长、是否建联、战斧客户端、国家代码、币种、时区。" type="info" :closable="false" show-icon />
    <el-upload drag :auto-upload="false" :limit="1" accept=".csv,.xlsx" :on-change="onFileChange" :on-remove="() => (importFile = null)">
      <el-icon><UploadFilled /></el-icon>
      <div class="el-upload__text">将文件拖到此处，或点击选择</div>
    </el-upload>
    <template #footer>
      <el-button @click="importOpen = false">取消</el-button>
      <el-button type="primary" :loading="importing" :disabled="!importFile" @click="submitImport">开始导入</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="capabilityOpen" :title="`${selectedStore?.name || ''} · 连接能力矩阵`" width="min(980px, 96vw)">
    <el-alert v-if="!authorizationOptions.length && !capabilityLoading" title="该店铺尚无授权连接，不能配置同步能力。" type="warning" :closable="false" show-icon />
    <el-select v-if="authorizationOptions.length > 1" v-model="selectedAuthorizationId" placeholder="选择授权连接" @change="loadCapabilities">
      <el-option v-for="item in authorizationOptions" :key="item.id" :label="`${item.platform} · ${item.status} · #${item.id}`" :value="item.id" />
    </el-select>
    <el-alert v-if="selectedAuthorization && selectedAuthorization.status !== 'active'" title="当前授权不是 Active，只能查看或保存非激活状态；后端会拒绝激活能力。" type="warning" :closable="false" show-icon />
    <el-alert v-if="capabilitySuggestions.length" :title="`检测到 ${capabilitySuggestions.length} 条能力建议；载入后只覆盖本地表单，仍需复核 scopes/evidence 并点击保存确认。`" type="info" :closable="false" show-icon />
    <el-table v-loading="capabilityLoading" :data="capabilityRows" border empty-text="暂无能力数据">
      <el-table-column prop="capability_code" label="能力" min-width="150" />
      <el-table-column label="读取" width="90"><template #default="{ row }"><el-switch v-model="row.read_enabled" /></template></el-table-column>
      <el-table-column label="写入" width="90"><template #default="{ row }"><el-switch :model-value="false" disabled /></template></el-table-column>
      <el-table-column label="同步方式" min-width="130"><template #default="{ row }"><el-select v-model="row.sync_mode"><el-option label="定时" value="scheduled"/><el-option label="实时" value="realtime"/><el-option label="Webhook" value="webhook"/><el-option label="人工" value="manual"/></el-select></template></el-table-column>
      <el-table-column label="来源优先级" width="130"><template #default="{ row }"><el-input-number v-model="row.source_priority" :min="1" :max="65535" controls-position="right" /></template></el-table-column>
      <el-table-column label="状态" min-width="120"><template #default="{ row }"><el-select v-model="row.status"><el-option label="禁用" value="disabled"/><el-option label="已配置" value="configured"/><el-option label="启用" value="active"/><el-option label="错误" value="error"/></el-select></template></el-table-column>
    </el-table>
    <template #footer><el-button @click="capabilityOpen = false">关闭</el-button><el-button plain :disabled="!capabilitySuggestions.length || capabilityLoading" @click="applyCapabilitySuggestions">载入建议</el-button><el-button type="primary" :loading="capabilitySaving" :disabled="!selectedAuthorizationId" @click="saveCapabilities">确认保存</el-button></template>
  </el-dialog>

  <SubjectApiAccessDialog
    v-model="apiAccessOpen"
    subject-type="store"
    :row="selectedStore"
    @changed="resourcePage?.loadData()"
  />
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { UploadFilled } from '@element-plus/icons-vue';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import SubjectApiAccessDialog from '../../components/SubjectApiAccessDialog.vue';
import { fetchUsers } from '../../api/systemAdmin';
import { fetchProductCategories } from '../../api/products';
import { fetchConnectionCapabilities, fetchStoreAuthorizations, updateConnectionCapabilities } from '../../api/integrations';
import { getActionAccess } from '../../utils/actionAccess';
import { useAuthStore } from '../../stores/auth';
import {
  applyPlatformSiteMigration, createMasterData, deleteMasterData, fetchCountrySites, fetchPlatforms, fetchPlatformSiteMigrationPreview,
  fetchPlatformSites, fetchStores, importStores,
  updateMasterData, updateMasterDataStatus,
} from '../../api/masterData';

const columns = [
  { prop: 'code', label: '店铺档案编码', width: 170 }, { prop: 'name', label: '店铺名称', width: 190 },
  { prop: 'platform_store_name', label: '平台店铺名', width: 180 }, { prop: 'platform_name', label: '所属平台', width: 150 },
  { prop: 'platform_site_name', label: '平台站点', width: 170 }, { prop: 'external_store_id', label: '外部店铺 ID', width: 150 },
  { prop: 'business_model', label: '业务模式', width: 130 }, { prop: 'fulfillment_modes', label: '履约模式', type: 'list', width: 210 },
  { prop: 'category_name', label: '类目', width: 130 }, { prop: 'operator_name', label: '负责运营', width: 120 },
  { prop: 'bd_name', label: 'BD', width: 120 }, { prop: 'leader_name', label: '组长', width: 120 },
  { prop: 'is_connected', label: '是否建联', type: 'boolean', width: 100 },
  { prop: 'tactical_client', label: '战斧客户端', width: 150 }, { prop: 'country_code', label: '国家' },
  { prop: 'currency', label: '币种' }, { prop: 'settlement_currency', label: '结算币种' }, { prop: 'timezone', label: '时区', width: 170 },
  { prop: 'status', label: '状态', type: 'status' },
];

const platformOptions = ref([]); const platformSites = ref([]); const platformSiteOptions = ref([]); const countryOptions = ref([]); const categoryOptions = ref([]); const userOptions = ref([]);
const importOpen = ref(false); const importFile = ref(null); const importing = ref(false); const apiAccessOpen = ref(false);
const capabilityOpen = ref(false); const capabilityLoading = ref(false); const capabilitySaving = ref(false);
const selectedStore = ref(null); const authorizationOptions = ref([]); const selectedAuthorizationId = ref(null); const capabilityRows = ref([]);
const capabilitySuggestions = ref([]);
const capabilityCodes = ['PRODUCT', 'CATEGORY', 'LISTING', 'PRICE', 'ORDER', 'INVENTORY', 'FULFILLMENT', 'WAREHOUSE', 'RETURN_REFUND', 'SETTLEMENT', 'PAYMENT', 'ADVERTISING', 'AFFILIATE', 'REVIEW', 'REPORT', 'WEBHOOK'];
const selectedAuthorization = computed(() => authorizationOptions.value.find((item) => item.id === selectedAuthorizationId.value));

const auth = useAuthStore();
const resourcePage = ref(null);
const migrationTable = ref(null);
const migrationOpen = ref(false); const migrationLoading = ref(false); const migrationApplying = ref(false); const migrationError = ref('');
const migrationRows = ref([]); const migrationSummary = ref({}); const selectedMigrationRows = ref([]);
const migrationManageAccess = computed(() => getActionAccess(auth, { permission: 'masterdata.manage' }));

function applyCountryDefaults(value, form) {
  const countryCode = String(value || '').trim().toUpperCase();
  const country = countryOptions.value.find((option) => option.value === countryCode);
  if (!country) return;
  form.currency = country.currency || ''; form.timezone = country.timezone || '';
}

function toPlatformSiteOption(item) { return { label: `${item.platform_name || ''} · ${item.name || item.site_code} (${item.site_code})`, value: item.id }; }
function applyPlatform(value, form) {
  platformSiteOptions.value = platformSites.value.filter((item) => item.platform_id === value).map(toPlatformSiteOption);
  if (!platformSiteOptions.value.some((item) => item.value === form.platform_site_id)) form.platform_site_id = null;
}
function applyPlatformSite(value, form) {
  const site = platformSites.value.find((item) => item.id === value); if (!site) return;
  form.country_code = site.country_code || form.country_code || '';
  form.currency = site.currency_code || form.currency || '';
  form.settlement_currency = site.currency_code || form.settlement_currency || '';
  form.timezone = site.timezone || form.timezone || 'UTC';
}

function openApiAccess(row) {
  selectedStore.value = row;
  apiAccessOpen.value = true;
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

const formFields = computed(() => [
  { key: 'platform_id', label: '平台', type: 'select', required: true, default: platformOptions.value[0]?.value || '', options: platformOptions.value, onChange: applyPlatform },
  { key: 'platform_site_id', label: '平台站点', type: 'select', options: platformSiteOptions.value, onChange: applyPlatformSite, placeholder: '可选；旧店铺可继续使用国家档案' },
  { key: 'code', label: '店铺档案编码', required: true }, { key: 'name', label: '店铺名称', required: true },
  { key: 'platform_store_name', label: '平台店铺名' },
  { key: 'external_store_id', label: '外部店铺 ID' }, { key: 'seller_entity_id', label: '经营主体 ID' },
  { key: 'business_model', label: '业务模式', type: 'select', default: 'other', options: [{ label: '本土店', value: 'local' }, { label: '跨境店', value: 'cross_border' }, { label: '全托管', value: 'full_managed' }, { label: '半托管', value: 'semi_managed' }, { label: '其他', value: 'other' }] },
  { key: 'fulfillment_modes', label: '履约模式', type: 'select', multiple: true, options: [{ label: '平台履约', value: 'platform_fulfillment' }, { label: '第三方仓', value: 'third_party_warehouse' }, { label: '本地自发货', value: 'local_self_fulfillment' }, { label: '跨境直发', value: 'cross_border_direct' }, { label: '混合', value: 'hybrid' }] },
  { key: 'category_id', label: '类目（大类）', type: 'select', options: categoryOptions.value },
  { key: 'operator_id', label: '负责运营', type: 'select', options: userOptions.value },
  { key: 'bd_id', label: 'BD', type: 'select', options: userOptions.value },
  { key: 'leader_id', label: '组长', type: 'select', options: userOptions.value },
  { key: 'is_connected', label: '是否建联', type: 'select', options: [{ label: '否', value: false }, { label: '是', value: true }] },
  { key: 'tactical_client', label: '战斧客户端' },
  { key: 'country_code', label: '国家', type: 'select', required: true, options: countryOptions.value, placeholder: '请选择国家档案', onChange: applyCountryDefaults },
  { key: 'currency', label: '币种', required: true, placeholder: '例如 SGD' }, { key: 'settlement_currency', label: '结算币种', placeholder: '例如 SGD' }, { key: 'timezone', label: '时区', required: true, default: 'UTC' },
]);

function results(response) {
  const data = response?.data;
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.results)) return data.results;
  if (Array.isArray(data?.items)) return data.items;
  return [];
}

function migrationStatus(row) {
  const value = row?.match_status || row?.mapping_status || row?.classification || row?.status || 'unmatched';
  return String(value).toLowerCase();
}

function migrationStatusType(row) {
  return { exact: 'success', ambiguous: 'warning', unmatched: 'info', applied: 'success' }[migrationStatus(row)] || 'info';
}

function migrationCandidates(row) {
  if (Array.isArray(row?.candidates)) return row.candidates;
  if (Array.isArray(row?.candidate_sites)) return row.candidate_sites;
  if (Array.isArray(row?.matches)) return row.matches;
  if (row?.candidate && typeof row.candidate === 'object') return [row.candidate];
  return [];
}

function migrationSiteLabel(row, side) {
  const snapshot = row?.[side] || {};
  if (typeof snapshot === 'string') return snapshot || '-';
  const id = snapshot.platform_site_id ?? snapshot.site_id ?? snapshot.id;
  const name = snapshot.platform_site_name || snapshot.site_name || snapshot.name || '';
  if (name) return id ? `${name} (#${id})` : name;
  return id ? `#${id}` : '-';
}

function migrationConfidence(row) {
  const value = row?.confidence;
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'number') return `${Math.round(value <= 1 ? value * 100 : value)}%`;
  return String(value);
}

function isExactMigrationRow(row) {
  return migrationStatus(row) === 'exact';
}

const exactRows = computed(() => migrationRows.value.filter(isExactMigrationRow));
const selectedMigrationStoreIds = computed(() => selectedMigrationRows.value.map((row) => row.store_id ?? row.id).filter((id) => id !== null && id !== undefined));
const allExactSelected = computed(() => exactRows.value.length > 0 && exactRows.value.every((row) => selectedMigrationStoreIds.value.includes(row.store_id ?? row.id)));
const exactSelectionIndeterminate = computed(() => selectedMigrationStoreIds.value.length > 0 && !allExactSelected.value);
const migrationCounts = computed(() => {
  const count = (status) => {
    const reported = migrationSummary.value?.[status];
    if (reported !== undefined && reported !== null && Number.isFinite(Number(reported))) return Number(reported);
    return migrationRows.value.filter((row) => migrationStatus(row) === status).length;
  };
  return { exact: count('matched') || count('exact'), ambiguous: count('ambiguous'), unmatched: count('unmatched') };
});

function normalizeMigrationRow(row = {}) {
  const status = migrationStatus(row);
  const storeId = row.store_id ?? row.store?.id ?? row.id;
  return {
    ...row,
    store_id: storeId,
    match_status: status,
    status,
    candidates: migrationCandidates(row),
    before: row.before || row.before_data || { platform_site_id: row.before_platform_site_id ?? null },
    after: row.after || row.after_data || { platform_site_id: row.after_platform_site_id ?? null },
  };
}

function resetMigrationSelection() {
  selectedMigrationRows.value = [];
  migrationTable.value?.clearSelection?.();
}

function handleMigrationSelection(rows) {
  selectedMigrationRows.value = rows.filter(isExactMigrationRow);
}

function toggleAllExact(checked) {
  if (migrationTable.value?.toggleRowSelection) {
    exactRows.value.forEach((row) => migrationTable.value.toggleRowSelection(row, checked));
  } else {
    selectedMigrationRows.value = checked ? exactRows.value.slice() : [];
  }
}

async function loadMigrationPreview() {
  migrationLoading.value = true;
  migrationError.value = '';
  try {
    const response = await fetchPlatformSiteMigrationPreview();
    if (!response?.success) {
      migrationRows.value = [];
      migrationSummary.value = {};
      migrationError.value = response?.message || '站点映射预览加载失败';
      return;
    }
    const payload = response.data;
    const rows = Array.isArray(payload)
      ? payload
      : (payload?.rows || payload?.results || payload?.items || []);
    migrationRows.value = rows.map(normalizeMigrationRow);
    migrationSummary.value = Array.isArray(payload) ? {} : payload || {};
    resetMigrationSelection();
  } catch (error) {
    migrationRows.value = [];
    migrationSummary.value = {};
    migrationError.value = error?.message || '站点映射预览加载失败';
  } finally {
    migrationLoading.value = false;
  }
}

async function openMigrationPreview() {
  migrationOpen.value = true;
  await loadMigrationPreview();
}

function migrationIdempotencyKey() {
  return `platform-site-migration-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

async function confirmMigration() {
  if (!migrationManageAccess.value.allowed) {
    ElMessage.warning(migrationManageAccess.value.reason || '当前角色无权应用站点映射');
    return;
  }
  const storeIds = selectedMigrationStoreIds.value.filter((id) => isExactMigrationRow(migrationRows.value.find((row) => (row.store_id ?? row.id) === id)));
  if (!storeIds.length) {
    ElMessage.warning('请先选择至少一条 exact 映射');
    return;
  }
  try {
    await ElMessageBox.confirm(
      `请再次确认：仅应用 ${storeIds.length} 条当前 exact 映射。后端会重新计算并跳过已有关联、ambiguous 或 unmatched 店铺；不会创建站点或覆盖已有站点。`,
      '二次确认站点映射',
      { type: 'warning', confirmButtonText: '确认应用', cancelButtonText: '取消' },
    );
  } catch {
    return;
  }

  migrationApplying.value = true;
  try {
    const payload = { confirmed: true, store_ids: storeIds, idempotency_key: migrationIdempotencyKey() };
    const response = await applyPlatformSiteMigration(payload);
    if (!response?.success) {
      ElMessage.error(response?.message || '站点映射应用失败');
      return;
    }
    const result = response.data || {};
    ElMessage.success(`站点映射完成：应用 ${result.applied ?? storeIds.length} 条`);
    await resourcePage.value?.loadData?.();
    await loadMigrationPreview();
  } catch (error) {
    ElMessage.error(error?.message || '站点映射应用失败');
  } finally {
    migrationApplying.value = false;
  }
}

async function loadReferenceOptions() {
  const [platformResponse, platformSiteResponse, siteResponse, categoryResponse, usersResponse] = await Promise.all([
    fetchPlatforms({ status: 'active', page: 1, page_size: 100 }), fetchPlatformSites({ page: 1, page_size: 100, status: 'active' }), fetchCountrySites({ status: 'active', page: 1, page_size: 100 }),
    fetchProductCategories({ page: 1, page_size: 100, level: 1 }), fetchUsers({ page: 1, page_size: 100, status: 'active' }),
  ]);
  const platforms = results(platformResponse); platformSites.value = results(platformSiteResponse); const sites = results(siteResponse); const categories = results(categoryResponse); const users = results(usersResponse);
  platformOptions.value = platforms
    .filter((row) => !String(row.platform_type || '').startsWith('warehouse_'))
    .map((item) => ({ label: `${item.name || item.code} · ${item.code}`, value: item.id }));
  platformSiteOptions.value = platformSites.value.map(toPlatformSiteOption);
  countryOptions.value = sites.map((item) => ({ label: `${item.name || item.code} · ${String(item.country_code || '').toUpperCase()}`, value: String(item.country_code || '').toUpperCase(), currency: String(item.currency || '').trim().toUpperCase(), timezone: String(item.timezone || '').trim() })).filter((item) => item.value);
  categoryOptions.value = categories.filter((item) => item.level === 1 && item.is_active !== false).map((item) => ({ label: `${item.code} · ${item.name}`, value: item.id }));
  userOptions.value = users.filter((item) => item.is_active !== false).map((item) => ({ label: item.full_name || item.username, value: item.id }));
}

async function openCapabilityMatrix(row) {
  selectedStore.value = row; capabilityOpen.value = true; capabilityLoading.value = true; capabilityRows.value = [];
  const response = await fetchStoreAuthorizations({ store_id: row.id, page: 1, page_size: 100 });
  authorizationOptions.value = results(response); selectedAuthorizationId.value = authorizationOptions.value[0]?.id || null;
  if (selectedAuthorizationId.value) await loadCapabilities(selectedAuthorizationId.value);
  capabilityLoading.value = false;
}

async function loadCapabilities(authorizationId) {
  capabilityLoading.value = true; const response = await fetchConnectionCapabilities(authorizationId); capabilityLoading.value = false;
  capabilitySuggestions.value = [];
  if (!response?.success) return ElMessage.error(response?.message || '能力矩阵加载失败');
  const existing = new Map((response.data?.results || []).map((item) => [item.capability_code, item]));
  const codes = response.data?.available_codes || capabilityCodes;
  capabilitySuggestions.value = Array.isArray(response.data?.suggestions) ? response.data.suggestions : [];
  capabilityRows.value = codes.map((code) => ({ capability_code: code, read_enabled: false, write_enabled: false, sync_mode: 'manual', source_priority: 100, status: 'disabled', ...(existing.get(code) || {}), write_enabled: false }));
}

function applyCapabilitySuggestions() {
  if (!capabilitySuggestions.value.length) return;
  const suggestions = new Map(capabilitySuggestions.value.map((item) => [item.capability_code, item]));
  capabilityRows.value = capabilityRows.value.map((row) => {
    const suggestion = suggestions.get(row.capability_code);
    if (!suggestion) return row;
    return {
      ...row,
      read_enabled: Boolean(suggestion.read_enabled),
      write_enabled: false,
      sync_mode: suggestion.sync_mode || row.sync_mode,
      source_priority: suggestion.source_priority ?? row.source_priority,
      status: suggestion.status || row.status,
      suggestion_confidence: suggestion.confidence,
      suggestion_scope_verification: suggestion.scope_verification,
      suggestion_evidence: suggestion.evidence,
      suggestion_reason: suggestion.reason,
    };
  });
  ElMessage.info('建议已载入本地表单；请复核 scopes/evidence 后点击“确认保存”。');
}

async function saveCapabilities() {
  try { await ElMessageBox.confirm('仅保存读取能力和同步配置；平台写入能力继续保持关闭。是否继续？', '确认能力配置', { type: 'warning' }); } catch { return; }
  capabilitySaving.value = true;
  const payload = capabilityRows.value.map(({ capability_code, read_enabled, sync_mode, source_priority, status }) => ({ capability_code, read_enabled, write_enabled: false, sync_mode, source_priority, status }));
  const response = await updateConnectionCapabilities(selectedAuthorizationId.value, payload); capabilitySaving.value = false;
  if (!response?.success) return ElMessage.error(response?.message || '能力矩阵保存失败');
  ElMessage.success('能力矩阵已保存，写入能力仍保持关闭。'); await loadCapabilities(selectedAuthorizationId.value);
}

function onFileChange(uploadFile) { importFile.value = uploadFile?.raw || null; }
async function submitImport() {
  if (!importFile.value) return;
  importing.value = true;
  const response = await importStores(importFile.value);
  importing.value = false;
  if (!response?.success) return ElMessage.error(response?.message || '导入失败');
  const result = response.data || {};
  if (result.errors?.length) return ElMessage.error(`导入失败：${result.errors[0].message}`);
  ElMessage.success(`导入完成：新增 ${result.created || 0} 条，更新 ${result.updated || 0} 条`);
  importOpen.value = false; importFile.value = null;
}

onMounted(loadReferenceOptions);
</script>

<style scoped>
.migration-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin: 16px 0 12px;
}

.migration-counts,
.migration-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.migration-counts span {
  color: #64748b;
  font-size: 13px;
}

.migration-counts strong {
  margin-left: 4px;
  color: #172033;
  font-size: 16px;
}

.migration-selection-note {
  margin-top: 10px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

.candidate-list {
  display: grid;
  gap: 3px;
}

.candidate-list span {
  display: block;
}

.candidate-list small,
.resource-table small {
  color: #64748b;
}

.muted {
  color: #94a3b8;
}

@media (max-width: 760px) {
  .migration-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
