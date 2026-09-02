<template>
  <AppPage
    eyebrow="PRODUCTION PILOT"
    :title="release ? '生产部署' : '生产恢复'"
    :subtitle="release ? '创建发布计划、完成双人审批，并执行部署或回滚作业。' : '创建恢复计划、完成双人审批，并执行受控恢复作业。'"
    boundary-note="部署、恢复和回滚都会产生真实生产影响；每次操作必须通过服务端权限、版本、审批分离和审计校验。"
    :capability="capability"
  >
    <template #action>
      <el-button v-if="canPlan" type="primary" @click="openCreate">{{ release ? '创建部署计划' : '创建恢复计划' }}</el-button>
      <el-button @click="load" :loading="state === 'loading'">刷新</el-button>
    </template>

    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="load" />
    <template v-else>
      <el-table :data="rows" border @row-click="openDetail">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="environment_id" label="环境" min-width="140" />
        <el-table-column :prop="release ? 'release_channel' : 'name'" :label="release ? '发布通道' : '计划名称'" min-width="170" />
        <el-table-column prop="status" label="状态" width="140" />
        <el-table-column label="执行窗口" min-width="180">
          <template #default="{ row }">
            <span v-if="row.scheduled_at">{{ formatDateTime(row.scheduled_at) }}</span>
            <small v-if="row.status === 'scheduled' && row.scheduled_at && !isExecutionWindowOpen(row)" class="execution-window-hint">尚未到可执行时间</small>
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="75" />
        <el-table-column label="执行作业" min-width="190">
          <template #default="{ row }"><span>{{ executionIdFor(row) || '—' }}</span><small v-if="executionStatusFor(row)" class="execution-status">{{ executionStatusFor(row) }}</small><small v-if="executionErrors[row.id]" class="execution-error" role="alert">{{ executionErrors[row.id] }}</small></template>
        </el-table-column>
        <el-table-column prop="audit_ref" label="审计引用" min-width="150" />
        <el-table-column label="生产操作" min-width="560">
          <template #default="{ row }">
            <el-button v-if="canPlan && row.status === 'draft'" size="small" @click.stop="beginAction(row, 'submit-review')">提交审批</el-button>
            <el-button v-if="canReview && row.status === 'review_pending'" size="small" type="success" @click.stop="beginAction(row, 'approve')">批准</el-button>
            <el-button v-if="canReview && row.status === 'review_pending'" size="small" @click.stop="beginAction(row, 'reject')">拒绝</el-button>
            <el-button v-if="canPlan && row.status === 'approved'" size="small" @click.stop="openSchedule(row)">设置执行窗口</el-button>
            <el-button v-if="canExecute && row.status === 'scheduled'" size="small" type="danger" :disabled="!isExecutionWindowOpen(row)" @click.stop="confirmExecution(row)">{{ isExecutionWindowOpen(row) ? (release ? '执行部署' : '执行恢复') : '等待执行窗口' }}</el-button>
            <el-button v-if="canExecute && ['queued', 'running'].includes(row.status)" size="small" @click.stop="refreshExecution(row)">刷新作业</el-button>
            <el-button v-if="canPlan && cancellable(row)" size="small" type="danger" plain @click.stop="beginAction(row, 'cancel')">取消计划</el-button>
            <template v-if="release && canRollback && row.status === 'rollback_required'">
              <el-button v-if="!row.rollback_approval_ref" size="small" type="warning" @click.stop="openRollbackApproval(row)">申请回滚批准</el-button>
              <el-button v-else size="small" type="danger" @click.stop="confirmRollback(row)">执行回滚</el-button>
            </template>
            <el-button v-if="canRecord && row.status === 'manual_required'" size="small" @click.stop="beginAction(row, 'resume')">人工处理后继续</el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <el-drawer v-model="drawer" title="计划详情与执行审计" size="min(680px, 92vw)">
      <el-descriptions v-if="selected" :column="1" border>
        <el-descriptions-item v-for="(value, key) in selected" :key="key" :label="key"><pre v-if="typeof value === 'object'">{{ JSON.stringify(value, null, 2) }}</pre><span v-else>{{ value }}</span></el-descriptions-item>
      </el-descriptions>
      <section v-if="selectedExecution" class="execution-detail" aria-live="polite">
        <h3>执行作业 {{ selectedExecution.id || selectedExecution.execution_id || '—' }}</h3>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="状态">{{ selectedExecution.status || selectedExecution.state || '—' }}</el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ selectedExecution.started_at || '—' }}</el-descriptions-item>
          <el-descriptions-item label="结束时间">{{ selectedExecution.finished_at || '—' }}</el-descriptions-item>
          <el-descriptions-item label="结果"><pre>{{ JSON.stringify(selectedExecution.result_metrics || selectedExecution.result || selectedExecution.metrics || {}, null, 2) }}</pre></el-descriptions-item>
          <el-descriptions-item label="失败信息">{{ selectedExecution.error_message || selectedExecution.error?.message || '—' }}</el-descriptions-item>
          <el-descriptions-item label="证据与审计"><pre>{{ JSON.stringify(selectedExecution.evidence || selectedExecution.audit || selectedExecution.audit_ref || {}, null, 2) }}</pre></el-descriptions-item>
        </el-descriptions>
      </section>
      <el-alert v-if="selected && executionErrors[selected.id]" class="execution-error-alert" type="error" :closable="false" :title="executionErrors[selected.id]" />
    </el-drawer>

    <el-dialog v-model="createVisible" :title="release ? '创建部署计划' : '创建恢复计划'" width="min(650px, 94vw)">
      <el-form label-position="top" class="create-form">
        <el-form-item label="环境" required><el-input v-model="createForm.environment_id" maxlength="64" placeholder="controlled-pilot" /></el-form-item>
        <template v-if="release">
          <el-form-item label="发布通道" required><el-select v-model="createForm.release_channel"><el-option label="受控试点" value="controlled_pilot" /></el-select></el-form-item>
          <el-form-item label="版本 Commit SHA" required><el-input v-model="createForm.commit_sha" maxlength="64" placeholder="输入待发布版本的完整 SHA" /></el-form-item>
          <el-form-item label="发布标签"><el-input v-model="createForm.tag" maxlength="120" /></el-form-item>
          <el-form-item label="目标租户引用" required><el-input v-model="createForm.tenant_refs_text" placeholder="逗号分隔的受控租户引用" /></el-form-item>
          <el-form-item label="观察时长（分钟）" required><el-input-number v-model="createForm.observation_minutes" :min="15" :max="1440" controls-position="right" /></el-form-item>
          <el-form-item label="停止条件" required><el-input v-model="createForm.stop_conditions_text" type="textarea" placeholder="每行一条停止条件" /></el-form-item>
          <el-form-item label="回滚点" required><el-input v-model="createForm.rollback_point" maxlength="200" /></el-form-item>
          <el-form-item label="数据库兼容性" required><el-select v-model="createForm.database_compatibility"><el-option label="已验证" value="verified" /><el-option label="不涉及" value="not_required" /></el-select></el-form-item>
        </template>
        <template v-else>
          <el-form-item label="计划名称" required><el-input v-model="createForm.name" maxlength="120" /></el-form-item>
          <el-form-item label="RPO（分钟）" required><el-input-number v-model="createForm.rpo_minutes" :min="0" :max="100000" controls-position="right" /></el-form-item>
          <el-form-item label="RTO（分钟）" required><el-input-number v-model="createForm.rto_minutes" :min="0" :max="100000" controls-position="right" /></el-form-item>
          <el-form-item label="备份摘要" required><el-input v-model="createForm.backup_summary" type="textarea" maxlength="500" /></el-form-item>
          <el-form-item label="备份校验和（掩码）" required><el-input v-model="createForm.backup_checksum_masked" maxlength="128" placeholder="仅填写掩码后的校验和" /></el-form-item>
        </template>
        <el-form-item label="操作理由" required><el-input v-model="createForm.reason" type="textarea" maxlength="500" /></el-form-item>
        <span v-if="createError" class="inline-error" role="alert">{{ createError }}</span>
      </el-form>
      <template #footer><el-button @click="createVisible = false">取消</el-button><el-button type="primary" :loading="creating" @click="createPlan">创建计划</el-button></template>
    </el-dialog>

    <el-dialog v-model="scheduleVisible" :title="release ? '设置部署执行窗口' : '设置恢复执行窗口'" width="min(520px, 94vw)">
      <el-alert title="排期只会进入已批准的执行窗口；到达时间前执行按钮保持禁用。" type="info" :closable="false" show-icon />
      <el-form label-position="top" class="action-form">
        <el-form-item label="计划开始时间" required>
          <el-date-picker v-model="scheduleForm.scheduled_at" type="datetime" :clearable="false" :editable="false" :disabled-date="disablePastDate" placeholder="选择执行窗口开始时间" />
          <small class="form-hint">默认建议为当前时间后 5 分钟，仅作起始值；请确认该窗口已完成值班、审批和依赖准备。</small>
        </el-form-item>
        <el-form-item label="排期理由" required><el-input v-model="scheduleForm.reason" type="textarea" maxlength="500" placeholder="说明为何在该窗口执行" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="scheduleVisible = false">取消</el-button><el-button type="primary" :loading="scheduleLoading" @click="confirmSchedule">确认排期</el-button></template>
    </el-dialog>

    <el-dialog v-model="actionVisible" title="工作流操作确认" width="min(540px, 94vw)">
      <el-alert :title="`目标 ${pendingAction?.row?.id || '—'}：${actionLabel(pendingAction?.name)}，服务端将校验版本和双人审批。`" type="warning" :closable="false" show-icon />
      <el-form label-position="top" class="action-form">
        <el-form-item label="操作理由" required><el-input v-model="actionForm.reason" type="textarea" maxlength="500" /></el-form-item>
        <el-form-item v-if="['submit-review', 'approve'].includes(pendingAction?.name)" label="审批引用" required><el-input v-model="actionForm.approval_ref" maxlength="160" placeholder="输入外部审批单或工单引用" /></el-form-item>
        <el-form-item v-if="pendingAction?.name === 'resume'" label="人工处理引用" required><el-input v-model="actionForm.manual_resolution_ref" maxlength="160" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="actionVisible = false">取消</el-button><el-button type="primary" :loading="actionLoading" @click="confirmAction">确认</el-button></template>
    </el-dialog>

    <el-dialog v-model="rollbackApprovalVisible" title="回滚批准" width="min(520px, 94vw)">
      <el-alert title="回滚批准必须由独立于创建人和发布批准人的人员完成，并设置有效期。" type="warning" :closable="false" show-icon />
      <el-form label-position="top" class="action-form">
        <el-form-item label="回滚批准引用" required><el-input v-model="rollbackForm.rollback_approval_ref" maxlength="160" /></el-form-item>
        <el-form-item label="批准理由" required><el-input v-model="rollbackForm.reason" type="textarea" maxlength="500" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="rollbackApprovalVisible = false">取消</el-button><el-button type="warning" :loading="rollbackLoading" @click="approveRollback">批准回滚</el-button></template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import {
  createRecoveryPlan,
  createReleasePlan,
  executeRecoveryPlan,
  executeReleasePlan,
  executeReleaseRollback,
  fetchExecution,
  fetchExecutions,
  fetchRecoveryPlans,
  fetchReleasePlans,
  runRecoveryAction,
  runReleaseAction
} from '../../api/pilot';
import { useAuthStore } from '../../stores/auth';
import { statusFromApiResponse } from '../../utils/uiState';

const props = defineProps({ kind: { type: String, required: true } });
const auth = useAuthStore();
const release = computed(() => props.kind === 'release');
const prefix = computed(() => release.value ? 'pilot.release' : 'pilot.recovery');
const canPlan = computed(() => auth.hasPermission(`${prefix.value}.plan`));
const canReview = computed(() => auth.hasPermission(`${prefix.value}.review`));
const canRecord = computed(() => auth.hasPermission(`${prefix.value}.record`));
const executePermission = computed(() => release.value ? 'pilot.release.execute' : 'pilot.recovery.execute');
const canExecute = computed(() => auth.hasPermission(executePermission.value));
const canRollback = computed(() => release.value && auth.hasPermission('pilot.release.rollback.execute'));
const state = ref('loading');
const capability = ref('connected');
const errorMessage = ref('');
const rows = ref([]);
const drawer = ref(false);
const selected = ref(null);
const selectedExecution = ref(null);
const executionCache = reactive({});
const executionErrors = reactive({});
const createVisible = ref(false);
const creating = ref(false);
const createError = ref('');
const actionVisible = ref(false);
const actionLoading = ref(false);
const pendingAction = ref(null);
const actionForm = reactive({ reason: '', approval_ref: '', manual_resolution_ref: '' });
const scheduleVisible = ref(false);
const scheduleLoading = ref(false);
const scheduleRow = ref(null);
const scheduleForm = reactive({ scheduled_at: null, reason: '' });
const rollbackApprovalVisible = ref(false);
const rollbackLoading = ref(false);
const rollbackRow = ref(null);
const rollbackForm = reactive({ rollback_approval_ref: '', reason: '' });
const createForm = reactive({
  environment_id: 'controlled-pilot', release_channel: 'controlled_pilot', commit_sha: '', tag: '', tenant_refs_text: '', observation_minutes: 30, stop_conditions_text: '', rollback_point: '', database_compatibility: 'verified',
  name: '', rpo_minutes: 30, rto_minutes: 60, backup_summary: '', backup_checksum_masked: '', reason: ''
});
let executionPollTimer = null;

const activeExecutionStates = new Set(['queued', 'running', 'pending', 'in_progress']);
const splitValues = (value) => String(value || '').split(/[\n,]/).map((item) => item.trim()).filter(Boolean);
const cancellable = (row) => ['draft', 'review_pending', 'approved', 'scheduled'].includes(row.status);
const formatDateTime = (value) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '无效时间' : date.toLocaleString('zh-CN', { hour12: false });
};
const isExecutionWindowOpen = (row) => {
  if (!row?.scheduled_at) return false;
  const timestamp = Date.parse(row.scheduled_at);
  return Number.isFinite(timestamp) && timestamp <= Date.now();
};
const disablePastDate = (date) => date.getTime() < Date.now() - 60 * 1000;

function showFailure(response) { state.value = statusFromApiResponse(response, typeof navigator === 'undefined' || navigator.onLine); errorMessage.value = response.message || '请求失败'; }
async function load() {
  state.value = 'loading'; errorMessage.value = '';
  const response = release.value ? await fetchReleasePlans() : await fetchRecoveryPlans();
  if (!response.success) { showFailure(response); return; }
  const payload = response.data || {};
  rows.value = payload.results || [];
  capability.value = payload.api_status || 'connected';
  state.value = rows.value.length ? 'ready' : 'empty';
}

function executionIdFor(row) { return row.execution_id || row.execution?.id || row.execution?.execution_id || executionCache[row.id]?.id || executionCache[row.id]?.execution_id || ''; }
function executionStatusFor(row) { const execution = executionCache[row.id] || row.execution; return execution?.status || execution?.state || ''; }
function openDetail(row) { selected.value = row; selectedExecution.value = executionCache[row.id] || row.execution || null; drawer.value = true; if (executionIdFor(row)) refreshExecution(row); }
function findExecution(payload, id) {
  const candidates = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.results)
      ? payload.results
      : payload && typeof payload === 'object'
        ? [payload]
        : [];
  return candidates.find((item) => String(item?.id ?? item?.execution_id ?? '') === String(id)) || null;
}
async function refreshExecution(row) {
  const id = executionIdFor(row); if (!id) return;
  executionErrors[row.id] = '';
  const response = await fetchExecution(id);
  let execution = response.success ? response.data : null;
  if (response.success && !execution) {
    executionErrors[row.id] = '服务端未返回执行作业详情，无法安全更新状态';
  } else if (!response.success) {
    // The collection endpoint does not accept execution_id. Fetch a bounded
    // page and match the requested job explicitly to prevent an unrelated job
    // from being displayed for this plan.
    const list = await fetchExecutions({ page: 1, page_size: 100 });
    if (!list.success) executionErrors[row.id] = list.message || '执行状态读取失败';
    else {
      execution = findExecution(list.data, id);
      if (!execution) executionErrors[row.id] = `执行作业 ${id} 未在服务端返回，无法安全更新状态`;
    }
  }
  if (!execution) {
    ElMessage.error(executionErrors[row.id] || '执行状态读取失败');
    return;
  }
  executionCache[row.id] = execution;
  if (selected.value?.id === row.id) selectedExecution.value = executionCache[row.id];
  if (activeExecutionStates.has(executionStatusFor(row))) {
    if (executionPollTimer) clearTimeout(executionPollTimer);
    executionPollTimer = setTimeout(() => refreshExecution(row), 2000);
  }
}

function resetCreateForm() { Object.assign(createForm, { environment_id: 'controlled-pilot', release_channel: 'controlled_pilot', commit_sha: '', tag: '', tenant_refs_text: '', observation_minutes: 30, stop_conditions_text: '', rollback_point: '', database_compatibility: 'verified', name: '', rpo_minutes: 30, rto_minutes: 60, backup_summary: '', backup_checksum_masked: '', reason: '' }); }
function openCreate() { resetCreateForm(); createError.value = ''; createVisible.value = true; }
function createPayload() {
  if (release.value) return { environment_id: createForm.environment_id.trim(), release_channel: createForm.release_channel, commit_sha: createForm.commit_sha.trim(), tag: createForm.tag.trim(), tenant_refs: splitValues(createForm.tenant_refs_text), observation_minutes: createForm.observation_minutes, stop_conditions: splitValues(createForm.stop_conditions_text), rollback_point: createForm.rollback_point.trim(), database_compatibility: createForm.database_compatibility, reason: createForm.reason.trim() };
  return { environment_id: createForm.environment_id.trim(), name: createForm.name.trim(), rpo_minutes: createForm.rpo_minutes, rto_minutes: createForm.rto_minutes, backup_summary: createForm.backup_summary.trim(), backup_checksum_masked: createForm.backup_checksum_masked.trim(), reason: createForm.reason.trim() };
}
async function createPlan() {
  createError.value = '';
  const payload = createPayload();
  const required = release.value ? [payload.environment_id, payload.commit_sha, payload.tenant_refs.length, payload.stop_conditions.length, payload.rollback_point, payload.reason] : [payload.environment_id, payload.name, payload.backup_summary, payload.backup_checksum_masked, payload.reason];
  if (required.some((value) => !value)) { createError.value = '请填写所有必填字段'; return; }
  creating.value = true;
  const response = release.value ? await createReleasePlan(payload) : await createRecoveryPlan(payload);
  creating.value = false;
  if (!response.success) { createError.value = response.message || '计划创建失败'; return; }
  createVisible.value = false; ElMessage.success('生产计划已创建，等待双人审批'); await load();
}

function actionLabel(name) { return { 'submit-review': '提交审批', approve: '批准', reject: '拒绝', cancel: '取消计划', resume: '人工处理后继续' }[name] || name || ''; }
function beginAction(row, name) { pendingAction.value = { row, name }; Object.assign(actionForm, { reason: '', approval_ref: '', manual_resolution_ref: '' }); actionVisible.value = true; }
async function confirmAction() {
  const action = pendingAction.value; if (!action || !actionForm.reason.trim()) return ElMessage.warning('请填写操作理由');
  if (['submit-review', 'approve'].includes(action.name) && !actionForm.approval_ref.trim()) return ElMessage.warning('请填写审批引用');
  if (action.name === 'resume' && !actionForm.manual_resolution_ref.trim()) return ElMessage.warning('请填写人工处理引用');
  const payload = { version: action.row.version, reason: actionForm.reason.trim() };
  if (['submit-review', 'approve'].includes(action.name)) payload.approval_ref = actionForm.approval_ref.trim();
  if (action.name === 'resume') payload.manual_resolution_ref = actionForm.manual_resolution_ref.trim();
  actionLoading.value = true;
  const response = release.value ? await runReleaseAction(action.row.id, action.name, payload) : await runRecoveryAction(action.row.id, action.name, payload);
  actionLoading.value = false;
  if (!response.success) { ElMessage.error(response.message || '工作流操作失败'); showFailure(response); return; }
  actionVisible.value = false; ElMessage.success('工作流状态已更新并记录审计'); await load();
}
function openSchedule(row) {
  scheduleRow.value = row;
  scheduleForm.scheduled_at = new Date(Math.ceil((Date.now() + 5 * 60 * 1000) / 60000) * 60000);
  scheduleForm.reason = '';
  scheduleVisible.value = true;
}
async function confirmSchedule() {
  const row = scheduleRow.value;
  const scheduledAt = scheduleForm.scheduled_at instanceof Date ? scheduleForm.scheduled_at : new Date(scheduleForm.scheduled_at);
  if (!row || !scheduleForm.reason.trim()) return ElMessage.warning('请填写排期理由');
  if (Number.isNaN(scheduledAt.getTime()) || scheduledAt <= new Date()) return ElMessage.warning('计划开始时间必须晚于当前时间');
  const payload = { version: row.version, reason: scheduleForm.reason.trim(), scheduled_at: scheduledAt.toISOString() };
  scheduleLoading.value = true;
  const response = release.value ? await runReleaseAction(row.id, 'schedule', payload) : await runRecoveryAction(row.id, 'schedule', payload);
  scheduleLoading.value = false;
  if (!response.success) { ElMessage.error(response.message || '排期失败'); return; }
  scheduleVisible.value = false;
  ElMessage.success(`作业已排期：${formatDateTime(payload.scheduled_at)}`); await load();
}
async function confirmExecution(row) {
  if (!isExecutionWindowOpen(row)) { ElMessage.warning(`尚未到执行窗口：${formatDateTime(row.scheduled_at)}`); return; }
  try { await ElMessageBox.confirm(`确认对环境“${row.environment_id}”执行${release.value ? '部署' : '恢复'}？该操作会产生真实生产影响。`, `${release.value ? '执行部署' : '执行恢复'}确认`, { type: 'warning', confirmButtonText: '确认执行', cancelButtonText: '取消' }); } catch (error) { if (error === 'cancel' || error === 'close') return; ElMessage.error(error?.message || '执行确认失败'); return; }
  const payload = { version: row.version, reason: `Execute approved production ${release.value ? 'release' : 'recovery'} operation` };
  const response = release.value ? await executeReleasePlan(row.id, payload) : await executeRecoveryPlan(row.id, payload);
  if (!response.success) { ElMessage.error(response.message || '执行作业提交失败'); return; }
  executionCache[row.id] = response.data || {};
  ElMessage.success(`执行作业已提交：${executionIdFor(row) || '服务端已受理'}`); await load(); scheduleExecutionPoll(row);
}
function scheduleExecutionPoll(row) { if (executionPollTimer) clearTimeout(executionPollTimer); if (!executionIdFor(row)) return; executionPollTimer = setTimeout(() => refreshExecution(row), 2000); }
function openRollbackApproval(row) { rollbackRow.value = row; Object.assign(rollbackForm, { rollback_approval_ref: '', reason: '' }); rollbackApprovalVisible.value = true; }
async function approveRollback() {
  if (!rollbackRow.value || !rollbackForm.rollback_approval_ref.trim() || !rollbackForm.reason.trim()) return ElMessage.warning('请填写回滚批准引用和理由');
  rollbackLoading.value = true;
  const response = await runReleaseAction(rollbackRow.value.id, 'approve-rollback', { version: rollbackRow.value.version, reason: rollbackForm.reason.trim(), rollback_approval_ref: rollbackForm.rollback_approval_ref.trim(), approval_expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString() });
  rollbackLoading.value = false;
  if (!response.success) { ElMessage.error(response.message || '回滚批准失败'); return; }
  rollbackApprovalVisible.value = false; ElMessage.success('回滚批准已记录'); await load();
}
async function confirmRollback(row) {
  try { await ElMessageBox.confirm(`确认对发布计划 ${row.id} 执行回滚？这会恢复至已批准回滚点并产生生产影响。`, '执行回滚确认', { type: 'warning', confirmButtonText: '确认回滚', cancelButtonText: '取消' }); } catch (error) { if (error === 'cancel' || error === 'close') return; ElMessage.error(error?.message || '回滚确认失败'); return; }
  const response = await executeReleaseRollback(row.id, { version: row.version, reason: 'Execute approved production rollback', rollback_approval_ref: row.rollback_approval_ref });
  if (!response.success) { ElMessage.error(response.message || '回滚作业提交失败'); return; }
  executionCache[row.id] = response.data || {}; ElMessage.success(`回滚作业已提交：${executionIdFor(row) || '服务端已受理'}`); await load(); scheduleExecutionPoll(row);
}

watch(() => props.kind, load);
onBeforeUnmount(() => { if (executionPollTimer) clearTimeout(executionPollTimer); });
load();
</script>

<style scoped>
.execution-status { display: block; color: #64748b; font-size: 11px; }
.execution-error { display: block; color: #c45656; font-size: 11px; line-height: 1.35; }
.execution-window-hint { display: block; color: #a56a00; font-size: 11px; line-height: 1.35; }
.execution-detail { margin-top: 20px; padding-top: 18px; border-top: 1px solid #e8edf3; }
.execution-error-alert { margin-top: 16px; }
.execution-detail h3 { margin: 0 0 12px; font-size: 15px; }
.create-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 14px; }
.create-form :deep(.el-textarea), .create-form :deep(.el-form-item:last-of-type) { grid-column: 1 / -1; }
.create-form :deep(.el-input), .create-form :deep(.el-select), .create-form :deep(.el-input-number) { width: 100%; }
.action-form { margin-top: 16px; }
.form-hint { display: block; margin-top: 6px; color: #64748b; font-size: 12px; line-height: 1.4; }
.inline-error { display: block; color: #c45656; font-size: 13px; }
pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.5 ui-monospace, monospace; }
@media (max-width: 720px) { .create-form { grid-template-columns: 1fr; } }
</style>
