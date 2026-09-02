<template>
  <AppPage
    eyebrow="API DATA INTEGRATION"
    title="能力矩阵"
    subtitle="按店铺授权连接维护可用的只读 API 能力、同步方式和来源优先级。"
    boundary-note="生产阶段只允许读取能力。写入能力在页面和请求两侧均保持关闭，任何 write_enabled=true 都会被后端拒绝。"
    :capability="capability"
  >
    <template #action>
      <el-button :loading="loading" @click="loadAuthorizations">刷新</el-button>
      <el-button
        v-if="selectedAuthorization && canManage"
        type="primary"
        :loading="saving"
        @click="save"
      >保存只读能力</el-button>
    </template>

    <section class="toolbar" aria-label="授权连接选择">
      <el-select v-model="selectedAuthorizationId" filterable clearable placeholder="选择店铺授权" @change="loadCapabilities">
        <el-option
          v-for="item in authorizations"
          :key="item.id"
          :value="item.id"
          :label="`${item.platform || '-'} · ${item.store_name || item.store_code || `店铺 #${item.store_id}`} · #${item.id}`"
        />
      </el-select>
      <el-tag v-if="selectedAuthorization" :type="authorizationType(selectedAuthorization.status)" effect="plain">
        {{ authorizationLabel(selectedAuthorization.status) }}
      </el-tag>
    </section>

    <div class="pagination" aria-label="能力矩阵授权分页">
      <span class="pagination-total">共 {{ authorizationTotal }} 个授权</span>
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
    <el-alert
      v-if="selectedAuthorization && selectedAuthorization.status !== 'active' && selectedAuthorization.status !== 'authorized'"
      title="当前授权未处于有效状态，保存后端也不会允许激活能力。"
      type="warning"
      show-icon
      :closable="false"
      class="page-alert"
    />

    <template v-if="selectedAuthorization">
      <section class="summary-grid" aria-label="能力摘要">
        <article><span>可用代码</span><strong>{{ availableCodes.length }}</strong></article>
        <article><span>已配置</span><strong>{{ capabilityRows.length }}</strong></article>
        <article><span>只读启用</span><strong>{{ capabilityRows.filter((row) => row.read_enabled).length }}</strong></article>
        <article><span>写入启用</span><strong class="safe-zero">0</strong></article>
      </section>

      <el-table v-loading="loading" :data="capabilityRows" border stripe empty-text="当前授权暂无平台能力建议">
        <el-table-column prop="capability_code" label="能力代码" width="170" />
        <el-table-column label="读取" width="120">
          <template #default="{ row }">
            <el-switch v-model="row.read_enabled" :disabled="!canManage" active-text="开启" inactive-text="关闭" />
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
            <el-select v-model="row.sync_mode" :disabled="!canManage" size="small">
              <el-option label="手动" value="manual" />
              <el-option label="定时" value="scheduled" />
              <el-option label="实时" value="realtime" />
              <el-option label="Webhook" value="webhook" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="来源优先级" width="150">
          <template #default="{ row }">
            <el-input-number v-model="row.source_priority" :disabled="!canManage" :min="1" :max="65535" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-select v-model="row.status" :disabled="!canManage" size="small">
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
      </el-table>

      <section v-if="suggestions.length" class="suggestions" aria-label="平台能力建议">
        <header><h2>平台建议</h2><p>建议只用于填充本地表单，保存前请结合已授权 scopes 人工复核。</p></header>
        <el-table :data="suggestions" size="small" border empty-text="暂无能力建议">
          <el-table-column prop="capability_code" label="能力代码" width="170" />
          <el-table-column prop="reason" label="建议依据" min-width="250" />
          <el-table-column prop="read_enabled" label="建议读取" width="110">
            <template #default="{ row }">{{ row.read_enabled ? '开启' : '关闭' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }"><el-button link type="primary" :disabled="!canManage" @click="applySuggestion(row)">载入建议</el-button></template>
          </el-table-column>
        </el-table>
      </section>
    </template>
    <el-empty v-else description="请选择店铺授权后维护能力矩阵" />
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import { useAuthStore } from '../../stores/auth';
import { useMock } from '../../api/request';
import { fetchStoreAuthorizations, fetchStoreAuthorizationDetail, fetchConnectionCapabilities, updateConnectionCapabilities } from '../../api/integrations';

const route = useRoute();
const auth = useAuthStore();
const capability = ref(useMock ? 'mock' : 'pending');
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const authorizations = ref([]);
const requestedAuthorizationId = String(route.query.authorization_id || '').trim();
const selectedAuthorizationId = ref(requestedAuthorizationId || null);
const authorizationPage = ref(1);
const authorizationPageSize = ref(20);
const authorizationTotal = ref(0);
const capabilityRows = ref([]);
const availableCodes = ref([]);
const suggestions = ref([]);

const selectedAuthorization = computed(() => authorizations.value.find((item) => String(item.id) === String(selectedAuthorizationId.value)) || null);
const canManage = computed(() => auth.hasPermission('integrations.store.authorize'));

function responseRows(response) {
  const data = response?.data;
  return Array.isArray(data) ? data : (data?.results || data?.items || []);
}
function authorizationLabel(value) { return ({ active: '有效', authorized: '已授权', pending: '待授权', expired: '已过期', revoked: '已撤销', failed: '失败' })[value] || value || '未知'; }
function authorizationType(value) { return ({ active: 'success', authorized: 'success', pending: 'warning', expired: 'warning', revoked: 'info', failed: 'danger' })[value] || 'info'; }

async function loadAuthorizations() {
  loading.value = true;
  error.value = '';
  const response = await fetchStoreAuthorizations({ page: authorizationPage.value, page_size: authorizationPageSize.value });
  capability.value = response?.data?.api_status || (useMock ? 'mock' : response?.success ? 'connected' : 'degraded');
  if (!response?.success) {
    authorizations.value = [];
    authorizationTotal.value = 0;
    capabilityRows.value = [];
    error.value = response?.message || '读取授权连接失败。';
  } else {
    const data = response?.data;
    authorizations.value = responseRows(response);
    authorizationTotal.value = Number(data?.count ?? data?.total ?? authorizations.value.length);
    // A deep link must keep working even when the requested authorization is
    // not on the first page. Fetch just that record and prepend it to the
    // selector; the list itself remains paged and does not load 100 rows.
    if (requestedAuthorizationId && !authorizations.value.some((item) => String(item.id) === requestedAuthorizationId)) {
      const detailResponse = await fetchStoreAuthorizationDetail(requestedAuthorizationId);
      if (detailResponse?.success && detailResponse.data) authorizations.value.unshift(detailResponse.data);
    }
    if (requestedAuthorizationId && authorizations.value.some((item) => String(item.id) === requestedAuthorizationId)) {
      selectedAuthorizationId.value = requestedAuthorizationId;
    } else if (!authorizations.value.some((item) => String(item.id) === String(selectedAuthorizationId.value))) {
      selectedAuthorizationId.value = authorizations.value[0]?.id || null;
    }
    if (selectedAuthorizationId.value) await loadCapabilities();
  }
  loading.value = false;
}

function handleAuthorizationSizeChange(size) {
  authorizationPageSize.value = size;
  authorizationPage.value = 1;
  loadAuthorizations();
}

async function loadCapabilities() {
  if (!selectedAuthorizationId.value) { capabilityRows.value = []; suggestions.value = []; return; }
  loading.value = true;
  const response = await fetchConnectionCapabilities(selectedAuthorizationId.value);
  loading.value = false;
  if (!response?.success) { capabilityRows.value = []; suggestions.value = []; error.value = response?.message || '读取能力矩阵失败。'; return; }
  const data = response.data || {};
  availableCodes.value = data.available_codes || [];
  suggestions.value = data.suggestions || [];
  const existing = new Map((data.results || []).map((row) => [row.capability_code, row]));
  const suggested = new Map(suggestions.value.map((row) => [row.capability_code, row]));
  capabilityRows.value = availableCodes.value.map((code) => ({
    capability_code: code,
    read_enabled: Boolean(existing.get(code)?.read_enabled ?? suggested.get(code)?.read_enabled ?? false),
    write_enabled: false,
    sync_mode: existing.get(code)?.sync_mode || suggested.get(code)?.sync_mode || 'manual',
    source_priority: existing.get(code)?.source_priority || suggested.get(code)?.source_priority || 100,
    status: existing.get(code)?.status || suggested.get(code)?.status || 'disabled',
    last_success_at: existing.get(code)?.last_success_at || null
  }));
}

function applySuggestion(suggestion) {
  const row = capabilityRows.value.find((item) => item.capability_code === suggestion.capability_code);
  if (!row) return;
  row.read_enabled = Boolean(suggestion.read_enabled);
  row.sync_mode = suggestion.sync_mode || row.sync_mode;
  row.source_priority = suggestion.source_priority || row.source_priority;
  row.status = suggestion.status || (row.read_enabled ? 'active' : 'disabled');
  ElMessage.success(`${suggestion.capability_code} 建议已载入表单，请保存前复核。`);
}

async function save() {
  if (!selectedAuthorization.value || !canManage.value) return ElMessage.error('当前角色没有维护能力矩阵的权限。');
  try { await ElMessageBox.confirm('确认保存当前只读能力？所有 write_enabled 将强制保持 false。', '保存能力矩阵', { type: 'warning', confirmButtonText: '确认保存' }); } catch { return; }
  saving.value = true;
  const response = await updateConnectionCapabilities(
    selectedAuthorization.value.id,
    capabilityRows.value.map((row) => ({
      capability_code: row.capability_code,
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

onMounted(loadAuthorizations);
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
