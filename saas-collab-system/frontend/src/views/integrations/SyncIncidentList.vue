<template>
  <AppPage
    eyebrow="API DATA INTEGRATION"
    title="同步异常"
    subtitle="筛选、确认、记录和解决同步异常，并在受控条件下预览人工重试。"
    boundary-note="事件处置会写入集成审计。人工重试只允许后端判定为 Mock/沙箱模拟运行，必须先预览并人工确认，绝不调用生产外部 API。"
    :capability="capability"
  >
    <template #action><el-button :loading="loading" @click="load">刷新</el-button></template>

    <el-alert v-if="route.query.sync_job_id" type="info" :closable="false" :title="`当前仅显示任务 #${route.query.sync_job_id} 的异常`"><el-button link @click="clearJobContext">显示全部任务异常</el-button></el-alert>
    <section class="toolbar" aria-label="同步异常筛选">
      <IntegrationPlatformPicker v-model="platform" :options="platformOptions" />
      <el-tag v-if="route.query.store_id" effect="plain">店铺：{{ route.query.store_name || route.query.store_id }}</el-tag>
      <el-select v-model="status" clearable placeholder="全部状态" @change="applyFilters">
        <el-option label="未确认" value="open" />
        <el-option label="已确认" value="acknowledged" />
        <el-option label="已解决" value="resolved" />
      </el-select>
      <el-button type="primary" @click="applyFilters">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </section>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="page-alert" />
    <el-table v-loading="loading" :data="visibleRows" border stripe empty-text="暂无同步异常">
      <el-table-column prop="id" label="事件 ID" width="90" />
      <el-table-column prop="sync_job_id" label="任务 ID" width="90" />
      <el-table-column prop="platform" label="平台" width="110" />
      <el-table-column prop="resource_type" label="资源" min-width="150"><template #default="{ row }">{{ resourceLabel(row.resource_type) }}</template></el-table-column>
      <el-table-column prop="status" label="状态" width="110">
        <template #default="{ row }"><el-tag :type="statusType(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag></template>
      </el-table-column>
      <el-table-column prop="assignee_name" label="负责人" min-width="150">
        <template #default="{ row }">{{ row.assignee_name || '未指派' }}</template>
      </el-table-column>
      <el-table-column prop="occurrence_count" label="发生次数" width="100" />
      <el-table-column prop="last_error_code" label="错误码" min-width="165" />
      <el-table-column prop="masked_message" label="脱敏错误" min-width="280" show-overflow-tooltip />
      <el-table-column prop="resolution_note" label="备注" min-width="210" show-overflow-tooltip><template #default="{ row }">{{ row.resolution_note || '-' }}</template></el-table-column>
      <el-table-column label="操作" fixed="right" width="150"><template #default="{ row }"><el-button link type="primary" @click="openIncident(row)">查看/处理</el-button></template></el-table-column>
    </el-table>

    <el-drawer v-model="drawerOpen" title="同步异常处理" size="min(620px, 94vw)" destroy-on-close>
      <template v-if="selected.id">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="事件">#{{ selected.id }} · 任务 #{{ selected.sync_job_id }}</el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag :type="statusType(selected.status)" effect="plain">{{ statusLabel(selected.status) }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="平台/资源">{{ selected.platform || '-' }} · {{ resourceLabel(selected.resource_type) }}</el-descriptions-item>
          <el-descriptions-item label="发生次数">{{ selected.occurrence_count || 0 }}</el-descriptions-item>
          <el-descriptions-item label="当前负责人">{{ selected.assignee_name || '未指派' }}</el-descriptions-item>
          <el-descriptions-item label="错误码">{{ selected.last_error_code || '-' }}</el-descriptions-item>
          <el-descriptions-item label="脱敏错误">{{ selected.masked_message || '-' }}</el-descriptions-item>
          <el-descriptions-item label="当前备注">{{ selected.resolution_note || '暂无' }}</el-descriptions-item>
        </el-descriptions>

        <el-button @click="router.push({ path: '/integrations/sync-jobs', query: { sync_job_id: String(selected.sync_job_id) } })">查看所属任务</el-button>
        <el-button v-if="selected.last_sync_run_id" @click="openRun(selected.last_sync_run_id, selected.sync_job_id)">查看来源运行</el-button>
        <el-button v-if="latestRetryRun" type="primary" @click="openRun(latestRetryRun.id, latestRetryRun.sync_job_id)">查看新重试记录</el-button>
        <el-form label-position="top" class="incident-form">
          <el-form-item label="指派负责人">
            <el-select
              v-model="assigneeId"
              clearable
              filterable
              :loading="assigneeLoading"
              :disabled="!canAssign || Boolean(actionLoading)"
              placeholder="选择当前租户活跃用户"
              style="width: 100%"
            >
              <el-option
                v-for="user in assigneeOptions"
                :key="user.id"
                :label="assigneeLabel(user)"
                :value="user.id"
              />
            </el-select>
            <small v-if="canManage && !canViewUsers" class="form-hint">当前角色缺少 system.users.view，无法加载负责人选项。</small>
          </el-form-item>
          <el-form-item label="处置备注（脱敏）"><el-input v-model="note" type="textarea" :rows="4" maxlength="500" show-word-limit placeholder="填写排查、确认或解决说明" /></el-form-item>
        </el-form>
        <div class="incident-actions">
          <el-button v-if="selected.status === 'open' && canManage" :loading="actionLoading === 'acknowledge'" :disabled="Boolean(actionLoading && actionLoading !== 'acknowledge')" @click="act('acknowledge')">确认事件</el-button>
          <el-button v-if="canManage" :loading="actionLoading === 'note'" :disabled="Boolean(actionLoading && actionLoading !== 'note')" @click="act('note')">保存备注</el-button>
          <el-button v-if="canManage" :loading="actionLoading === 'assign'" :disabled="!canAssign || !assigneeId || Boolean(actionLoading && actionLoading !== 'assign')" :title="canAssign ? '' : '需要 integrations.manage 与 system.users.view'" @click="act('assign')">指派负责人</el-button>
          <el-button v-if="selected.status !== 'resolved' && canManage" type="success" :loading="actionLoading === 'resolve'" :disabled="Boolean(actionLoading && actionLoading !== 'resolve')" @click="act('resolve')">解决事件</el-button>
          <el-button v-if="canRun" type="warning" :loading="retryLoading" :disabled="Boolean(actionLoading)" @click="previewRetry">受控重试预览</el-button>
        </div>
      </template>
    </el-drawer>

    <el-dialog v-model="retryOpen" title="受控重试预览" width="min(620px, 94vw)" destroy-on-close>
      <template v-if="retryPreview">
        <el-alert
          :title="retryPreview.allowed ? '后端允许进入模拟重试确认步骤。' : (retryPreview.blocked_reason || '当前事件不可重试。')"
          :type="retryPreview.allowed ? 'warning' : 'error'"
          show-icon
          :closable="false"
        />
        <el-descriptions :column="1" border class="retry-summary">
          <el-descriptions-item label="运行环境">{{ retryPreview.environment || '-' }}</el-descriptions-item>
          <el-descriptions-item label="执行模式">{{ retryPreview.execution_mode || '-' }}</el-descriptions-item>
          <el-descriptions-item label="来源运行">{{ retryPreview.source_run_id || retryPreview.source_sync_run_id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="外部 API 调用">{{ retryPreview.external_api_called ? '是（禁止）' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="阻塞原因">{{ retryPreview.blocked_reason || '无' }}</el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button @click="retryOpen = false">取消</el-button>
        <el-button type="warning" :disabled="!retryPreview?.allowed" :loading="retryLoading" @click="confirmRetry">确认模拟重试</el-button>
      </template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import IntegrationPlatformPicker from '../../components/IntegrationPlatformPicker.vue';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import { fetchUsers } from '../../api/systemAdmin';
import { useAuthStore } from '../../stores/auth';
import { useMock } from '../../api/request';
import { resources } from '../../utils/syncPresentation';
import { actOnSyncAlertIncident, fetchSyncAlertIncidentRetryPreview, fetchSyncAlertIncidents, retrySyncAlertIncident } from '../../api/integrations';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
let loadSequence = 0, previewSequence = 0;
const retryIntent = ref(null), latestRetryRun = ref(null);
const capability = ref(useMock ? 'mock' : 'pending');
const loading = ref(false);
const error = ref('');
const rows = ref([]);
const platform = ref('');
const platformOptions = computed(() => [...new Set(rows.value.map(row => row.platform).filter(Boolean))]);
const visibleRows = computed(() => !platform.value ? rows.value : rows.value.filter(row => row.platform === platform.value));
const status = ref('');
const drawerOpen = ref(false);
const selected = ref({});
const note = ref('');
const actionLoading = ref('');
const assigneeOptions = ref([]);
const assigneeLoading = ref(false);
const assigneeId = ref(null);
const retryLoading = ref(false);
const retryOpen = ref(false);
const retryPreview = ref(null);
const canManage = computed(() => auth.hasPermission('integrations.manage'));
const canRun = computed(() => auth.hasPermission('integrations.run'));
const canViewUsers = computed(() => auth.hasPermission('system.users.view'));
const canAssign = computed(() => canManage.value && canViewUsers.value);

function responseRows(response) {
  const data = response?.data;
  return Array.isArray(data) ? data : (data?.results || data?.items || []);
}
function statusLabel(value) { return ({ open: '未确认', acknowledged: '已确认', resolved: '已解决' })[value] || value || '未知'; }
function resourceLabel(value) {
  return resources[value] || value || '未知';
}
function statusType(value) { return ({ open: 'danger', acknowledged: 'warning', resolved: 'success' })[value] || 'info'; }
function assigneeLabel(user) { return user?.full_name || user?.username || `用户 #${user?.id || '-'}`; }
async function load() {
  const seq = ++loadSequence;
  rows.value = [];
  loading.value = true;
  error.value = '';
  try {
    const response = await fetchSyncAlertIncidents({
      status: status.value,
      ...(route.query.store_id ? { store_id: route.query.store_id } : {}),
    });
    if (seq !== loadSequence) return;
    capability.value = response?.data?.api_status || (useMock ? 'mock' : response?.success ? 'connected' : 'degraded');
    if (response?.success) rows.value = responseRows(response).filter(row => !route.query.sync_job_id || String(row.sync_job_id) === String(route.query.sync_job_id));
    else { rows.value = []; error.value = response?.message || '读取同步异常失败。'; }
  } catch (requestError) {
    if (seq !== loadSequence) return;
    rows.value = [];
    capability.value = useMock ? 'mock' : 'degraded';
    error.value = requestError?.message || '读取同步异常失败。';
  } finally {
    if (seq === loadSequence) loading.value = false;
  }
}
function applyFilters() { load(); }
function resetFilters() { platform.value = ''; status.value = ''; applyFilters(); }
function clearJobContext() { const query = { ...route.query }; delete query.sync_job_id; router.replace({ path: route.path, query }); }
function openRun(id, job) { if (id && job) router.push({ path: '/integrations/sync-runs', query: { detail: String(id), sync_job_id: String(job) } }); }
watch(() => [route.query.store_id, route.query.sync_job_id], () => { ++previewSequence; drawerOpen.value = false; retryOpen.value = false; load(); });
onBeforeUnmount(() => { ++loadSequence; ++previewSequence; });
async function loadAssignees() {
  if (!canViewUsers.value || assigneeOptions.value.length) return;
  assigneeLoading.value = true;
  try {
    const response = await fetchUsers({ page: 1, page_size: 100, status: 'active' });
    if (!response?.success) throw new Error(response?.message || '租户活跃用户加载失败。');
    assigneeOptions.value = responseRows(response).filter((user) => user?.is_active !== false);
  } catch (loadError) {
    ElMessage.error(loadError?.message || '租户活跃用户加载失败。');
  } finally {
    assigneeLoading.value = false;
  }
}
function openIncident(row) {
  ++previewSequence; latestRetryRun.value = null;
  selected.value = { ...row };
  const candidate = Number(row.assignee);
  assigneeId.value = Number.isInteger(candidate) && candidate > 0 ? candidate : null;
  note.value = '';
  retryPreview.value = null;
  drawerOpen.value = true;
  loadAssignees();
}
async function act(action) {
  if (!selected.value.id || !canManage.value) return;
  if (action === 'assign' && !canAssign.value) return ElMessage.error('当前角色没有加载租户负责人或执行指派的权限。');
  if (action === 'assign' && !assigneeId.value) return ElMessage.warning('请选择当前租户活跃用户作为负责人。');
  if (action === 'note' && !String(note.value || '').trim()) return ElMessage.warning('请输入脱敏处置备注。');
  const assignee = assigneeOptions.value.find((user) => String(user.id) === String(assigneeId.value));
  const actionLabel = action === 'acknowledge'
    ? '确认该异常'
    : action === 'resolve'
      ? '解决该异常'
      : action === 'assign'
        ? `将该异常指派给 ${assigneeLabel(assignee)}`
        : '保存备注';
  try { await ElMessageBox.confirm(`确认${actionLabel}？操作将写入集成审计。`, '确认异常处置', { type: action === 'resolve' ? 'warning' : 'info' }); } catch { return; }
  actionLoading.value = action;
  try {
    const response = await actOnSyncAlertIncident(selected.value.id, {
      action,
      ...(action === 'assign' ? { assignee_id: Number(assigneeId.value) } : {}),
      ...(String(note.value || '').trim() ? { note: String(note.value).trim() } : {})
    });
    if (!response?.success) return ElMessage.error(response?.message || '异常处置失败。');
    ElMessage.success(action === 'assign' ? '负责人已指派。' : '异常处置已记录。');
    selected.value = { ...selected.value, ...(response.data || {}) };
    note.value = '';
    await load();
  } catch (actionError) {
    ElMessage.error(actionError?.message || '异常处置失败。');
  } finally {
    actionLoading.value = '';
  }
}
async function previewRetry() {
  if (!selected.value.id || !canRun.value || retryLoading.value) return;
  const seq = ++previewSequence, incidentId = selected.value.id;
  retryLoading.value = true;
  try {
    const response = await fetchSyncAlertIncidentRetryPreview(incidentId);
    if (seq !== previewSequence || selected.value.id !== incidentId) return;
    if (!response?.success) return ElMessage.error(response?.message || '重试预览失败。');
    retryPreview.value = response.data || null;
    const source = String(response.data?.source_sync_run_id || response.data?.source_run_id || '');
    if (!retryIntent.value || retryIntent.value.incidentId !== incidentId) {
      retryIntent.value = { incidentId, source, key: `ui-incident-${incidentId}-${crypto.randomUUID()}` };
    }
    retryOpen.value = true;
  } catch (requestError) { ElMessage.error(requestError?.message || '重试预览失败。'); }
  finally { retryLoading.value = false; }
}
async function confirmRetry() {
  if (!retryPreview.value?.allowed || !canRun.value || retryLoading.value || !retryIntent.value) return;
  const intent = { ...retryIntent.value }, jobId = selected.value.sync_job_id, epoch = previewSequence;
  retryLoading.value = true;
  try {
    await ElMessageBox.confirm('确认执行受控模拟重试？系统保证不调用生产外部 API。', '确认模拟重试', { type: 'warning', confirmButtonText: '确认重试' });
    if (!canRun.value || selected.value.id !== intent.incidentId || epoch !== previewSequence) return;
    const response = await retrySyncAlertIncident(intent.incidentId, intent.key);
    if (!response?.success) return ElMessage.error(response?.message || '受控重试失败。');
    if (selected.value.id === intent.incidentId) {
      latestRetryRun.value = response.data?.run?.id ? { id: response.data.run.id, sync_job_id: response.data.run.sync_job_id || jobId } : null;
      retryOpen.value = false;
    }
    retryIntent.value = null;
    ElMessage.success('重试请求已受理；请查看新记录确认结果。');
    await load();
  } catch (requestError) {
    if (requestError !== 'cancel' && requestError !== 'close') ElMessage.error(requestError?.message || '受控重试失败；再次确认会复用本次请求编号。');
  } finally { retryLoading.value = false; }
}
onMounted(load);
</script>

<style scoped>
.toolbar { display: flex; gap: 10px; flex-wrap: wrap; margin: 18px 0; }
.toolbar .el-select { width: 170px; }
.page-alert { margin-bottom: 14px; }
.incident-form { margin-top: 20px; }
.form-hint { display: block; margin-top: 6px; color: #8a5a00; line-height: 1.5; }
.incident-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
.retry-summary { margin-top: 18px; }
</style>
