<template>
  <AppPage
    eyebrow="API DATA INTEGRATION"
    title="同步异常"
    subtitle="筛选、确认、记录和解决同步异常，并在受控条件下预览人工重试。"
    boundary-note="事件处置会写入集成审计。人工重试只允许后端判定为 Mock/沙箱模拟运行，必须先预览并人工确认，绝不调用生产外部 API。"
    :capability="capability"
  >
    <template #action><el-button :loading="loading" @click="load">刷新</el-button></template>

    <section class="toolbar" aria-label="同步异常筛选">
      <el-select v-model="status" clearable placeholder="全部状态" @change="applyFilters">
        <el-option label="未确认" value="open" />
        <el-option label="已确认" value="acknowledged" />
        <el-option label="已解决" value="resolved" />
      </el-select>
      <el-button type="primary" @click="applyFilters">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </section>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="page-alert" />
    <el-table v-loading="loading" :data="rows" border stripe empty-text="暂无同步异常">
      <el-table-column prop="id" label="事件 ID" width="90" />
      <el-table-column prop="sync_job_id" label="任务 ID" width="90" />
      <el-table-column prop="platform" label="平台" width="110" />
      <el-table-column prop="resource_type" label="资源" min-width="150" />
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
          <el-descriptions-item label="平台/资源">{{ selected.platform || '-' }} · {{ selected.resource_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="发生次数">{{ selected.occurrence_count || 0 }}</el-descriptions-item>
          <el-descriptions-item label="当前负责人">{{ selected.assignee_name || '未指派' }}</el-descriptions-item>
          <el-descriptions-item label="错误码">{{ selected.last_error_code || '-' }}</el-descriptions-item>
          <el-descriptions-item label="脱敏错误">{{ selected.masked_message || '-' }}</el-descriptions-item>
          <el-descriptions-item label="当前备注">{{ selected.resolution_note || '暂无' }}</el-descriptions-item>
        </el-descriptions>

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
import { computed, onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import { fetchUsers } from '../../api/systemAdmin';
import { useAuthStore } from '../../stores/auth';
import { useMock } from '../../api/request';
import { actOnSyncAlertIncident, fetchSyncAlertIncidentRetryPreview, fetchSyncAlertIncidents, retrySyncAlertIncident } from '../../api/integrations';

const auth = useAuthStore();
const capability = ref(useMock ? 'mock' : 'pending');
const loading = ref(false);
const error = ref('');
const rows = ref([]);
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
function statusType(value) { return ({ open: 'danger', acknowledged: 'warning', resolved: 'success' })[value] || 'info'; }
function assigneeLabel(user) { return user?.full_name || user?.username || `用户 #${user?.id || '-'}`; }
async function load() {
  loading.value = true;
  error.value = '';
  try {
    const response = await fetchSyncAlertIncidents({ status: status.value });
    capability.value = response?.data?.api_status || (useMock ? 'mock' : response?.success ? 'connected' : 'degraded');
    if (response?.success) rows.value = responseRows(response);
    else { rows.value = []; error.value = response?.message || '读取同步异常失败。'; }
  } catch (requestError) {
    rows.value = [];
    capability.value = useMock ? 'mock' : 'degraded';
    error.value = requestError?.message || '读取同步异常失败。';
  } finally {
    loading.value = false;
  }
}
function applyFilters() { load(); }
function resetFilters() { status.value = ''; applyFilters(); }
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
  if (!selected.value.id || !canRun.value) return;
  retryLoading.value = true;
  try {
    const response = await fetchSyncAlertIncidentRetryPreview(selected.value.id);
    if (!response?.success) return ElMessage.error(response?.message || '重试预览失败。');
    retryPreview.value = response.data || null;
    retryOpen.value = true;
  } catch (requestError) {
    ElMessage.error(requestError?.message || '重试预览失败。');
  } finally {
    retryLoading.value = false;
  }
}
async function confirmRetry() {
  if (!retryPreview.value?.allowed || !canRun.value) return;
  try { await ElMessageBox.confirm('确认执行受控模拟重试？系统保证不调用生产外部 API。', '确认模拟重试', { type: 'warning', confirmButtonText: '确认重试' }); } catch { return; }
  retryLoading.value = true;
  try {
    const idempotencyKey = `ui-incident-${selected.value.id}-${Date.now()}`;
    const response = await retrySyncAlertIncident(selected.value.id, idempotencyKey);
    if (!response?.success) return ElMessage.error(response?.message || '受控重试失败。');
    retryOpen.value = false;
    ElMessage.success('受控模拟重试已提交。');
    await load();
  } catch (requestError) {
    ElMessage.error(requestError?.message || '受控重试失败。');
  } finally {
    retryLoading.value = false;
  }
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
