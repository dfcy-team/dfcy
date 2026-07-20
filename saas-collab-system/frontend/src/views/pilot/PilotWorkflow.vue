<template>
  <AppPage
    eyebrow="CONTROLLED PILOT"
    :title="release ? '发布记录' : '恢复演练'"
    :subtitle="release ? '规划发布、审批并记录受控环境中的外部执行结果。' : '规划恢复演练、审批并记录受控环境中的外部执行结果。'"
    boundary-note="本页不会执行部署、回滚、备份恢复、SQL、Docker 或远程命令；start、result 和 rollback 仅记录已在受控主机完成的外部操作。"
    :capability="capability"
  >
    <template #action>
      <el-button v-if="canPlan" type="primary" @click="createDemo">创建演示计划</el-button>
    </template>
    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="load" />
    <el-table v-else :data="rows" border @row-click="openDetail">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="environment_id" label="环境" min-width="140" />
      <el-table-column :prop="release ? 'release_channel' : 'name'" :label="release ? '发布通道' : '计划名称'" min-width="170" />
      <el-table-column prop="status" label="状态" width="140" />
      <el-table-column prop="version" label="版本" width="75" />
      <el-table-column prop="audit_ref" label="审计引用" min-width="150" />
      <el-table-column label="受控操作" min-width="520">
        <template #default="{ row }">
          <el-button v-if="canPlan && row.status === 'draft'" size="small" @click.stop="runBasic(row, 'submit-review')">提交审批</el-button>
          <el-button v-if="canReview && row.status === 'review_pending'" size="small" type="success" @click.stop="runBasic(row, 'approve')">批准</el-button>
          <el-button v-if="canReview && row.status === 'review_pending'" size="small" @click.stop="runBasic(row, 'reject')">拒绝</el-button>
          <el-button v-if="canPlan && row.status === 'approved'" size="small" @click.stop="runBasic(row, 'schedule')">排期</el-button>
          <el-button v-if="canRecord && row.status === 'scheduled'" size="small" type="primary" @click.stop="runBasic(row, 'start')">记录开始</el-button>
          <el-button v-if="canRecord && row.status === 'running'" size="small" type="success" @click.stop="recordResult(row, 'success')">记录成功</el-button>
          <el-button v-if="canRecord && row.status === 'running'" size="small" @click.stop="recordResult(row, 'manual_required')">转人工</el-button>
          <el-button v-if="release && canRecord && row.status === 'running'" size="small" type="warning" @click.stop="recordResult(row, 'rollback_required')">记录需回滚</el-button>
          <el-button v-if="canRecord && row.status === 'manual_required' && (!release || row.manual_context === 'release')" size="small" @click.stop="runBasic(row, 'resume')">记录恢复</el-button>
          <el-button v-if="release && canRollback && row.status === 'rollback_required' && !row.rollback_approval_ref" size="small" type="warning" @click.stop="approveRollback(row)">批准回滚记录</el-button>
          <el-button v-if="release && canRollback && row.status === 'rollback_required' && row.rollback_approval_ref" size="small" @click.stop="recordRollback(row, 'rolled_back')">记录回滚完成</el-button>
          <el-button v-if="release && canRollback && row.status === 'rollback_required' && row.rollback_approval_ref" size="small" @click.stop="recordRollback(row, 'manual_required')">回滚转人工</el-button>
          <el-button v-if="release && canRollback && row.status === 'manual_required' && row.manual_context === 'rollback'" size="small" @click.stop="resumeRollback(row)">恢复回滚记录</el-button>
          <el-button v-if="canPlan && cancellable(row)" size="small" type="danger" plain @click.stop="runBasic(row, 'cancel')">取消</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-drawer v-model="drawer" title="计划详情与审计边界" size="min(560px, 92vw)">
      <el-descriptions v-if="selected" :column="1" border>
        <el-descriptions-item v-for="(value, key) in selected" :key="key" :label="key">
          <pre v-if="typeof value === 'object'">{{ JSON.stringify(value, null, 2) }}</pre>
          <span v-else>{{ value }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-drawer>
  </AppPage>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import {
  createRecoveryPlan, createReleasePlan, fetchRecoveryDrills, fetchRecoveryPlans,
  fetchReleasePlans, recordRecoveryResult, runRecoveryAction, runReleaseAction
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
const canRollback = computed(() => release.value && auth.hasPermission('pilot.release.rollback'));
const state = ref('loading');
const capability = ref('pending');
const errorMessage = ref('');
const rows = ref([]);
const drawer = ref(false);
const selected = ref(null);

const futureTime = () => new Date(Date.now() + 5 * 60 * 1000).toISOString();
const cancellable = (row) => ['draft', 'review_pending', 'approved', 'scheduled'].includes(row.status) || (row.status === 'manual_required' && (!release.value || row.manual_context === 'release'));

async function load() {
  state.value = 'loading';
  const response = release.value ? await fetchReleasePlans() : await fetchRecoveryPlans();
  if (!response.success) {
    state.value = statusFromApiResponse(response, navigator.onLine);
    errorMessage.value = response.message;
    return;
  }
  rows.value = response.data.results || [];
  capability.value = response.data.api_status || 'sandbox';
  state.value = rows.value.length ? 'ready' : 'empty';
}

async function createDemo() {
  const response = release.value
    ? await createReleasePlan({ environment_id: 'controlled-pilot', release_channel: 'demo', commit_sha: '1111111111111111111111111111111111111111', tag: 'demo-ui-p7', demo_tenant_refs: ['demo-tenant'], observation_minutes: 30, stop_conditions: ['fixed demo stop condition'], rollback_point: 'demo rollback point', database_compatibility: 'pending', reason: 'fixed demo planning only' })
    : await createRecoveryPlan({ environment_id: 'controlled-pilot', name: 'Demo recovery drill', rpo_minutes: 30, rto_minutes: 60, backup_summary: 'Masked demo backup summary', backup_checksum_masked: 'sha256:demo-***', reason: 'fixed demo planning only' });
  finish(response, '计划已记录，不会自动执行');
}

async function act(row, actionName, payload) {
  const response = release.value
    ? await runReleaseAction(row.id, actionName, payload)
    : await runRecoveryAction(row.id, actionName, payload);
  finish(response, '受控状态与审计记录已更新');
}

function finish(response, message) {
  ElMessage[response.success ? 'success' : 'error'](response.success ? message : response.message);
  if (response.success) load();
}

function runBasic(row, actionName) {
  const base = { version: row.version, reason: `${actionName} fixed demo record` };
  if (['submit-review', 'approve'].includes(actionName)) base.approval_ref = `demo-approval-${row.id}`;
  if (actionName === 'schedule') base.scheduled_at = futureTime();
  if (actionName === 'resume') base.manual_resolution_ref = `demo-resolution-${row.id}`;
  return act(row, actionName, base);
}

async function recordResult(row, resultStatus) {
  if (release.value) {
    return act(row, 'record-result', { version: row.version, reason: 'record controlled release result', result_status: resultStatus, result_summary: 'Demo external execution record only', evidence_refs: ['demo-release-evidence'] });
  }
  const drillsResponse = await fetchRecoveryDrills({ recovery_plan_id: row.id, status: 'running' });
  const drill = drillsResponse.success ? drillsResponse.data.results?.[0] : null;
  if (!drill) return ElMessage.error('未找到可记录结果的运行中演练');
  const response = await recordRecoveryResult(drill.id, {
    version: drill.version,
    reason: 'record controlled recovery result',
    result_status: resultStatus,
    actual_rpo_minutes: resultStatus === 'success' ? 20 : null,
    actual_rto_minutes: resultStatus === 'success' ? 40 : null,
    result_summary: 'Demo external drill record only',
    evidence_refs: ['demo-recovery-evidence']
  });
  finish(response, '恢复演练结果已记录');
}

function approveRollback(row) {
  return act(row, 'approve-rollback', { version: row.version, reason: 'approve controlled rollback record', rollback_approval_ref: `demo-rollback-${row.id}`, approval_expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString() });
}

function recordRollback(row, rollbackStatus) {
  return act(row, 'record-rollback', { version: row.version, reason: 'record controlled rollback result', rollback_approval_ref: row.rollback_approval_ref, rollback_status: rollbackStatus, result_summary: 'Demo external rollback record only', evidence_refs: ['demo-rollback-evidence'] });
}

function resumeRollback(row) {
  return act(row, 'resume-rollback', { version: row.version, reason: 'resume controlled rollback record', rollback_approval_ref: row.rollback_approval_ref, manual_resolution_ref: `demo-rollback-resolution-${row.id}` });
}

function openDetail(row) {
  selected.value = row;
  drawer.value = true;
}

watch(() => props.kind, load);
load();
</script>

<style scoped>
pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.5 ui-monospace, monospace; }
</style>
