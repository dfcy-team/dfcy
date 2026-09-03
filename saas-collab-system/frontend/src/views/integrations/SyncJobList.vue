<template>
  <AppPage
    eyebrow="API DATA INTEGRATION"
    title="同步任务"
    subtitle="查看内部同步调度、任务健康和最近一次运行结果。"
    boundary-note="任务健康来自内部 workspace 汇总；运行模拟任务仅写入 Mock 运行记录，停用任务仅停用内部任务，不连接真实平台。"
    :capability="capability"
  >
    <template #action>
      <el-button plain :loading="loading" @click="load">刷新</el-button>
    </template>

    <AppState v-if="state !== 'ready' && state !== 'empty'" :status="state" :detail="errorMessage" @action="load" />
    <template v-else>
      <section class="sync-summary" aria-label="同步任务健康摘要">
        <article v-for="item in summaryItems" :key="item.key" :class="['summary-card', item.tone]">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </article>
      </section>

      <el-alert
        title="健康状态与调度状态分开统计；失败、重试等待、重试耗尽和陈旧运行均需人工关注。"
        type="warning"
        show-icon
        :closable="false"
      />

      <section class="incident-workbench" aria-label="同步事件工作台">
        <header class="incident-header">
          <div>
            <h2>同步事件工作台</h2>
            <p>集中处理失败事件、负责人和脱敏备注；人工重试只允许 Mock/沙箱模拟运行。</p>
          </div>
          <div class="incident-filters">
            <el-select v-model="incidentStatus" clearable placeholder="全部事件" @change="loadIncidents">
              <el-option label="未处理" value="open" />
              <el-option label="已确认" value="acknowledged" />
              <el-option label="已解决" value="resolved" />
            </el-select>
            <el-button plain :loading="incidentLoading" @click="loadIncidents">刷新事件</el-button>
          </div>
        </header>
        <el-alert v-if="incidentError" :title="incidentError" type="error" show-icon :closable="false" />
        <el-table v-loading="incidentLoading" :data="incidents" border empty-text="暂无同步事件">
          <el-table-column prop="id" label="事件ID" width="90" />
          <el-table-column prop="status" label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="incidentStatusType(row.status)" effect="plain">{{ incidentStatusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="occurrence_count" label="发生次数" width="100" />
          <el-table-column prop="assignee_name" label="负责人" min-width="140">
            <template #default="{ row }">{{ row.assignee_name || '未指派' }}</template>
          </el-table-column>
          <el-table-column prop="last_error_code" label="错误码" min-width="170" />
          <el-table-column prop="masked_message" label="脱敏错误" min-width="240" show-overflow-tooltip />
          <el-table-column prop="resolution_note" label="备注" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">{{ row.resolution_note || '-' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openIncident(row)">查看/处理</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <el-empty v-if="state === 'empty'" description="暂无同步任务" />
      <el-table v-else v-loading="loading" :data="rows" border stripe empty-text="暂无同步任务">
        <el-table-column prop="id" label="任务ID" width="90" />
        <el-table-column prop="platform" label="平台" min-width="110" />
        <el-table-column prop="subject_name" label="业务主体" min-width="150">
          <template #default="{ row }">
            <div>{{ row.subject_name || '未绑定' }}</div>
            <small>{{ row.subject_code || '-' }}</small>
          </template>
        </el-table-column>
        <el-table-column prop="resource_type" label="资源类型" min-width="150" />
        <el-table-column prop="health_state" label="任务健康" min-width="120">
          <template #default="{ row }">
            <el-tag :type="stateTagType(row.health_state)" effect="plain">{{ stateLabel(row.health_state) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="capability_state" label="能力状态" min-width="145">
          <template #default="{ row }">
            <el-tag :type="capabilityTagType(row.capability_state)" effect="plain">{{ capabilityLabel(row.capability_state) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="capability_code" label="能力代码" min-width="130">
          <template #default="{ row }">{{ row.capability_code || '-' }}</template>
        </el-table-column>
        <el-table-column prop="source_priority" label="来源优先级" width="115">
          <template #default="{ row }">{{ row.source_priority ?? '-' }}</template>
        </el-table-column>
        <el-table-column prop="selected_authorization_id" label="选中授权ID" width="120">
          <template #default="{ row }">{{ row.selected_authorization_id ?? '-' }}</template>
        </el-table-column>
        <el-table-column prop="schedule_state" label="调度状态" min-width="130">
          <template #default="{ row }">
            <el-tag :type="stateTagType(row.schedule_state)" effect="plain">{{ scheduleLabel(row.schedule_state) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="blocked_reason" label="阻塞原因" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.blocked_reason || '-' }}</template>
        </el-table-column>
        <el-table-column label="最近错误" min-width="250" show-overflow-tooltip>
          <template #default="{ row }">
            <div>{{ row.latest_error_code || '-' }}</div>
            <small>{{ row.latest_error_message || '无错误' }}</small>
          </template>
        </el-table-column>
        <el-table-column prop="next_run_at" label="下次运行" min-width="180">
          <template #default="{ row }">{{ row.next_run_at || '未安排' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="actionAccess(actionConfigs[0]).visible"
              link
              type="primary"
              :disabled="actionAccess(actionConfigs[0]).disabled"
              :title="actionAccess(actionConfigs[0]).reason"
              :loading="actionLoading === `${actionConfigs[0].label}:${row.id}`"
              @click.stop="runAction(actionConfigs[0], row)"
            >运行模拟任务</el-button>
            <el-button
              v-if="actionAccess(actionConfigs[1]).visible"
              link
              type="danger"
              :disabled="actionAccess(actionConfigs[1]).disabled"
              :title="actionAccess(actionConfigs[1]).reason"
              :loading="actionLoading === `${actionConfigs[1].label}:${row.id}`"
              @click.stop="runAction(actionConfigs[1], row)"
            >停用任务</el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <el-drawer v-model="incidentDrawerOpen" title="同步事件处理" size="min(580px, 94vw)" destroy-on-close>
      <template v-if="selectedIncident.id">
        <section class="incident-detail">
          <el-descriptions :column="1" border>
            <el-descriptions-item label="事件状态">
              <el-tag :type="incidentStatusType(selectedIncident.status)" effect="plain">{{ incidentStatusLabel(selectedIncident.status) }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="同步任务">#{{ selectedIncident.sync_job_id }} · {{ selectedIncident.resource_type }}</el-descriptions-item>
            <el-descriptions-item label="发生次数">{{ selectedIncident.occurrence_count || 0 }}</el-descriptions-item>
            <el-descriptions-item label="负责人">{{ selectedIncident.assignee_name || '未指派' }}</el-descriptions-item>
            <el-descriptions-item label="错误码">{{ selectedIncident.last_error_code || '-' }}</el-descriptions-item>
            <el-descriptions-item label="脱敏错误">{{ selectedIncident.masked_message || '-' }}</el-descriptions-item>
            <el-descriptions-item label="备注">{{ selectedIncident.resolution_note || '-' }}</el-descriptions-item>
          </el-descriptions>

          <el-form label-position="top" class="incident-form">
            <el-form-item label="指派当前 tenant 用户">
              <el-select v-model="assigneeId" clearable filterable :loading="assigneeLoading" placeholder="选择负责人" style="width: 100%">
                <el-option v-for="user in assigneeOptions" :key="user.id" :label="user.username || user.full_name" :value="user.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="备注（脱敏）">
              <el-input v-model="incidentNote" type="textarea" :rows="3" maxlength="500" show-word-limit placeholder="填写排查或解决备注" />
            </el-form-item>
          </el-form>

          <div class="incident-actions">
            <el-button
              v-if="selectedIncident.status === 'open'"
              :disabled="!actionAccess(actionConfigs[1]).allowed"
              :title="actionAccess(actionConfigs[1]).reason"
              :loading="incidentActionLoading === 'acknowledge'"
              @click="submitIncidentAction('acknowledge')"
            >确认事件</el-button>
            <el-button
              :disabled="!actionAccess(actionConfigs[1]).allowed"
              :title="actionAccess(actionConfigs[1]).reason"
              :loading="incidentActionLoading === 'assign'"
              @click="submitIncidentAction('assign')"
            >指派负责人</el-button>
            <el-button
              :disabled="!actionAccess(actionConfigs[1]).allowed"
              :title="actionAccess(actionConfigs[1]).reason"
              :loading="incidentActionLoading === 'note'"
              @click="submitIncidentAction('note')"
            >保存备注</el-button>
            <el-button
              v-if="selectedIncident.status !== 'resolved'"
              type="success"
              :disabled="!actionAccess(actionConfigs[1]).allowed"
              :title="actionAccess(actionConfigs[1]).reason"
              :loading="incidentActionLoading === 'resolve'"
              @click="submitIncidentAction('resolve')"
            >解决事件</el-button>
            <el-button
              v-if="actionAccess(actionConfigs[0]).visible"
              type="warning"
              :disabled="!actionAccess(actionConfigs[0]).allowed || retryLoading"
              :title="actionAccess(actionConfigs[0]).reason"
              @click="loadRetryPreview"
            >受控重试预览</el-button>
          </div>

          <el-alert
            v-if="retryPreview"
            class="retry-preview"
            :type="retryPreview.allowed ? 'info' : 'error'"
            :title="retryPreview.allowed ? '预览允许人工模拟重试' : (retryPreview.blocked_reason || '当前事件不可重试')"
            show-icon
            :closable="false"
          >
            <p>environment: {{ retryPreview.environment || '-' }}；execution_mode: {{ retryPreview.execution_mode || '-' }}</p>
            <p>external_api_called: <strong>false</strong>；requires_confirmation: {{ retryPreview.requires_confirmation ? 'true' : 'false' }}</p>
            <el-input v-model="retryIdempotencyKey" readonly aria-label="幂等键" />
            <el-button
              v-if="retryPreview.allowed"
              type="primary"
              :loading="retrySubmitting"
              @click="confirmRetry"
            >确认人工重试</el-button>
          </el-alert>
        </section>
      </template>
    </el-drawer>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import { useMock } from '../../api/request';
import { fetchUsers } from '../../api/systemAdmin';
import {
  actOnSyncAlertIncident,
  disableSyncJob,
  fetchSyncAlertIncidentRetryPreview,
  fetchSyncAlertIncidents,
  fetchSyncJobs,
  retrySyncAlertIncident,
  runSyncJobMock
} from '../../api/integrations';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';
import { statusFromApiResponse } from '../../utils/uiState';

const actionConfigs = [
  {
    label: 'run-mock',
    permission: 'integrations.run',
    type: 'primary',
    handler: ({ row }) => runSyncJobMock(row?.id || 1)
  },
  {
    label: 'disable',
    permission: 'integrations.manage',
    type: 'danger',
    confirmMessage: '仅禁用阶段2同步任务，不连接真实平台。',
    handler: ({ row }) => disableSyncJob(row?.id || 1)
  }
];

const auth = useAuthStore();
const rows = ref([]);
const summary = ref({});
const state = ref('loading');
const capability = ref(useMock ? 'mock' : 'pending');
const loading = ref(false);
const actionLoading = ref('');
const errorMessage = ref('');
const incidents = ref([]);
const incidentStatus = ref('');
const incidentLoading = ref(false);
const incidentError = ref('');
const incidentDrawerOpen = ref(false);
const selectedIncident = ref({});
const assigneeOptions = ref([]);
const assigneeLoading = ref(false);
const assigneeId = ref(null);
const incidentNote = ref('');
const incidentActionLoading = ref('');
const retryPreview = ref(null);
const retryLoading = ref(false);
const retrySubmitting = ref(false);
const retryIdempotencyKey = ref('');

const summaryItems = computed(() => [
  { key: 'job_count', label: '任务总数', value: summary.value.job_count || 0, tone: '' },
  { key: 'failed_run_count', label: '失败运行', value: summary.value.failed_run_count || 0, tone: 'summary-card--danger' },
  { key: 'retry_waiting_job_count', label: '重试等待', value: summary.value.retry_waiting_job_count || 0, tone: 'summary-card--warning' },
  { key: 'retry_exhausted_job_count', label: '重试耗尽', value: summary.value.retry_exhausted_job_count || 0, tone: 'summary-card--danger' },
  { key: 'stale_running_job_count', label: '陈旧运行', value: summary.value.stale_running_job_count || 0, tone: 'summary-card--warning' },
  { key: 'capability_blocked_job_count', label: '能力阻塞', value: summary.value.capability_blocked_job_count || 0, tone: 'summary-card--danger' },
  { key: 'open_sync_alert_count', label: '未关闭预警', value: summary.value.open_sync_alert_count || 0, tone: 'summary-card--warning' },
  { key: 'open_sync_incident_count', label: '待处理事件', value: summary.value.open_sync_incident_count || 0, tone: 'summary-card--danger' },
  { key: 'acknowledged_sync_incident_count', label: '已确认事件', value: summary.value.acknowledged_sync_incident_count || 0, tone: 'summary-card--warning' },
  { key: 'enabled_job_count', label: '启用任务', value: summary.value.enabled_job_count || 0, tone: 'summary-card--success' }
]);

function actionAccess(action) {
  return getActionAccess(auth, action);
}

function responseRows(data) {
  if (Array.isArray(data?.results)) return data.results;
  if (Array.isArray(data?.items)) return data.items;
  if (Array.isArray(data)) return data;
  return [];
}

function stateLabel(value) {
  return {
    disabled: '已禁用',
    authorization: '授权阻塞',
    configuration: '配置阻塞',
    capability: '能力阻塞',
    running: '运行中',
    failed: '失败',
    due: '待执行',
    healthy: '健康'
  }[value] || value || '-';
}

function incidentStatusLabel(value) {
  return { open: '未处理', acknowledged: '已确认', resolved: '已解决' }[value] || value || '-';
}

function incidentStatusType(value) {
  return { open: 'danger', acknowledged: 'warning', resolved: 'success' }[value] || 'info';
}

function capabilityLabel(value) {
  return {
    not_required: '无需能力',
    ready: '能力就绪',
    authorization: '授权不可用',
    capability_missing: '能力未启用',
    source_not_selected: '未选中来源',
    unsupported: '能力不支持'
  }[value] || value || '-';
}

function scheduleLabel(value) {
  return {
    disabled: '已禁用',
    running: '运行中',
    retry_waiting: '重试等待',
    retry_exhausted: '重试耗尽',
    manual: '手动',
    scheduled: '已排程',
    unscheduled: '未排程',
    due: '待执行'
  }[value] || value || '-';
}

function stateTagType(value) {
  return {
    healthy: 'success',
    running: 'primary',
    due: 'warning',
    retry_waiting: 'warning',
    retry_exhausted: 'danger',
    failed: 'danger',
    authorization: 'warning',
    configuration: 'warning',
    capability: 'warning',
    disabled: 'info'
  }[value] || 'info';
}

function capabilityTagType(value) {
  return {
    ready: 'success',
    not_required: 'info',
    authorization: 'warning',
    capability_missing: 'danger',
    source_not_selected: 'warning',
    unsupported: 'danger'
  }[value] || 'info';
}

async function load() {
  state.value = 'loading';
  loading.value = true;
  errorMessage.value = '';
  try {
    const response = await fetchSyncJobs();
    if (!response?.success) {
      state.value = statusFromApiResponse(response, typeof navigator === 'undefined' ? true : navigator.onLine);
      errorMessage.value = response?.message || '同步任务接口请求失败';
      capability.value = response?.http_status ? 'pending' : 'degraded';
      return;
    }
    const data = response.data || {};
    rows.value = responseRows(data);
    summary.value = data.summary || {};
    const apiStatus = data.api_status || (useMock ? 'mock' : 'pending');
    capability.value = apiStatus === 'fallback' ? 'degraded' : apiStatus;
    state.value = rows.value.length ? 'ready' : 'empty';
  } catch (error) {
    state.value = 'error';
    errorMessage.value = error?.message || '同步任务接口请求失败';
    capability.value = 'degraded';
  } finally {
    loading.value = false;
  }
}

function incidentRows(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.results)) return data.results;
  if (Array.isArray(data?.items)) return data.items;
  return [];
}

async function loadIncidents() {
  incidentLoading.value = true;
  incidentError.value = '';
  try {
    const response = await fetchSyncAlertIncidents(incidentStatus.value);
    if (!response?.success) throw new Error(response?.message || '同步事件加载失败');
    incidents.value = incidentRows(response.data);
  } catch (error) {
    incidentError.value = error?.message || '同步事件加载失败';
  } finally {
    incidentLoading.value = false;
  }
}

async function loadAssignees() {
  if (assigneeOptions.value.length) return;
  assigneeLoading.value = true;
  try {
    const response = await fetchUsers({ page: 1, page_size: 100, status: 'active' });
    if (!response?.success) throw new Error(response?.message || '租户用户加载失败');
    assigneeOptions.value = incidentRows(response.data).filter((user) => user.is_active !== false);
  } catch (error) {
    incidentError.value = error?.message || '租户用户加载失败';
  } finally {
    assigneeLoading.value = false;
  }
}

async function openIncident(incident) {
  selectedIncident.value = { ...incident };
  assigneeId.value = incident.assignee || null;
  incidentNote.value = '';
  retryPreview.value = null;
  retryIdempotencyKey.value = '';
  incidentDrawerOpen.value = true;
  await loadAssignees();
}

function generatedIdempotencyKey() {
  const key = `incident-retry-${selectedIncident.value.id}-${Date.now()}`;
  return key.length >= 8 ? key : `retry-${Date.now()}`;
}

async function submitIncidentAction(action) {
  const access = actionAccess(actionConfigs[1]);
  if (!access.allowed) {
    ElMessage.warning(access.reason);
    return;
  }
  if (action === 'assign' && !assigneeId.value) {
    ElMessage.warning('请选择当前 tenant 用户');
    return;
  }
  if (['note', 'resolve'].includes(action) && incidentNote.value.trim().length < 3) {
    ElMessage.warning('请填写至少 3 个字符的处置备注');
    return;
  }
  if (action === 'resolve') {
    try {
      await ElMessageBox.confirm('确认将此同步事件标记为已解决？', '解决事件确认', { type: 'warning' });
    } catch { return; }
  }
  const payload = { action };
  if (action === 'assign') payload.assignee_id = assigneeId.value;
  if (incidentNote.value.trim()) payload.note = incidentNote.value.trim();
  incidentActionLoading.value = action;
  try {
    const response = await actOnSyncAlertIncident(selectedIncident.value.id, payload);
    if (!response?.success) throw new Error(response?.message || '同步事件操作失败');
    selectedIncident.value = response.data || selectedIncident.value;
    incidentNote.value = '';
    ElMessage.success(response.message || '同步事件已更新');
    await loadIncidents();
  } catch (error) {
    ElMessage.error(error?.message || '同步事件操作失败');
  } finally {
    incidentActionLoading.value = '';
  }
}

async function loadRetryPreview() {
  const access = actionAccess(actionConfigs[0]);
  if (!access.allowed) {
    ElMessage.warning(access.reason);
    return;
  }
  retryLoading.value = true;
  retryPreview.value = null;
  try {
    const response = await fetchSyncAlertIncidentRetryPreview(selectedIncident.value.id);
    if (!response?.success) throw new Error(response?.message || '重试预览加载失败');
    retryPreview.value = response.data || {};
    retryIdempotencyKey.value = generatedIdempotencyKey();
  } catch (error) {
    ElMessage.error(error?.message || '重试预览加载失败');
  } finally {
    retryLoading.value = false;
  }
}

async function confirmRetry() {
  const access = actionAccess(actionConfigs[0]);
  if (!access.allowed) {
    ElMessage.warning(access.reason);
    return;
  }
  if (!retryPreview.value) {
    ElMessage.warning('请先加载重试预览');
    return;
  }
  if (!retryPreview.value.allowed) {
    ElMessage.warning(retryPreview.value.blocked_reason || '当前事件不可重试');
    return;
  }
  const idempotencyKey = retryIdempotencyKey.value.trim();
  if (idempotencyKey.length < 8) {
    ElMessage.warning('幂等键至少需要 8 个字符');
    return;
  }
  try {
    await ElMessageBox.confirm(
      `确认以幂等键 ${idempotencyKey} 执行人工模拟重试？external_api_called=false`,
      '人工重试二次确认',
      { type: 'warning' }
    );
  } catch (error) {
    if (error === 'cancel') return;
    ElMessage.error(error?.message || '重试确认失败');
    return;
  }
  retrySubmitting.value = true;
  try {
    const response = await retrySyncAlertIncident(selectedIncident.value.id, idempotencyKey);
    if (!response?.success) throw new Error(response?.message || '人工重试失败');
    ElMessage.success('人工模拟重试已提交，external_api_called=false');
    retryPreview.value = null;
    retryIdempotencyKey.value = '';
    await loadIncidents();
    await load();
  } catch (error) {
    ElMessage.error(error?.message || '人工重试失败');
  } finally {
    retrySubmitting.value = false;
  }
}

async function runAction(action, row) {
  const access = actionAccess(action);
  if (!access.allowed) {
    ElMessage.warning(access.reason);
    return;
  }
  try {
    if (action.confirmMessage) {
      await ElMessageBox.confirm(
        `确认对同步任务“${row.id}”执行${action.label === 'disable' ? '停用任务' : '运行模拟任务'}？${action.confirmMessage}`,
        '同步任务操作确认',
        { type: 'warning' }
      );
    }
    actionLoading.value = `${action.label}:${row.id}`;
    const response = await action.handler({ row, rows: rows.value });
    if (!response?.success) throw new Error(response?.message || `${action.label} 操作失败`);
    ElMessage.success(response.message || `${action.label} 操作已提交`);
    await load();
  } catch (error) {
    if (error === 'cancel') return;
    ElMessage.error(error?.message || `${action.label} 操作失败`);
  } finally {
    actionLoading.value = '';
  }
}

onMounted(() => {
  load();
  loadIncidents();
});
</script>

<style scoped>
.sync-summary {
  display: grid;
  grid-template-columns: repeat(6, minmax(120px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

.summary-card {
  min-height: 84px;
  padding: 14px 16px;
  border: 1px solid #dbe3ec;
  border-left: 4px solid #64748b;
  border-radius: 8px;
  background: #fff;
}

.summary-card span,
.summary-card strong {
  display: block;
}

.summary-card span { color: #64748b; font-size: 12px; }
.summary-card strong { margin-top: 8px; color: #172033; font-size: 23px; }
.summary-card--danger { border-left-color: #dc2626; }
.summary-card--warning { border-left-color: #d97706; }
.summary-card--success { border-left-color: #059669; }
small { color: #64748b; font-size: 12px; }

.incident-workbench {
  display: grid;
  gap: 12px;
  margin-top: 16px;
}

.incident-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.incident-header h2 { margin: 0; color: #172033; font-size: 18px; }
.incident-header p { margin: 5px 0 0; color: #64748b; font-size: 12px; }
.incident-filters { display: flex; align-items: center; gap: 8px; }
.incident-detail { display: grid; gap: 16px; }
.incident-form { padding-top: 4px; border-top: 1px solid #e5eaf0; }
.incident-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.retry-preview p { margin: 0 0 8px; line-height: 1.5; }
.retry-preview .el-input { margin: 3px 0 10px; }

@media (max-width: 1100px) {
  .sync-summary { grid-template-columns: repeat(4, minmax(120px, 1fr)); }
}

@media (max-width: 680px) {
  .sync-summary { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
  .incident-header { flex-direction: column; }
  .incident-filters { width: 100%; }
  .incident-filters .el-select { flex: 1; }
}
</style>
