<template>
  <AppPage
    eyebrow="UI-P8 / SECURITY GATE"
    :title="config.title"
    :subtitle="config.subtitle"
    boundary-note="本工作台只记录计划、人工评审和外部完成的脱敏结果，不连接真实平台，不执行部署、压力测试、恢复、RPA 或资金动作。"
    :capability="capability"
  >
    <template #action>
      <el-button v-if="canPlan" type="primary" @click="createDemo">创建演示草稿</el-button>
    </template>

    <div v-if="!route.params.id" class="filters">
      <el-select v-model="filters.environment" clearable placeholder="环境" aria-label="环境筛选">
        <el-option label="pilot" value="pilot" />
        <el-option label="sandbox" value="sandbox" />
      </el-select>
      <el-select v-model="filters.status" clearable placeholder="状态" aria-label="状态筛选">
        <el-option v-for="item in config.statuses" :key="item" :label="item" :value="item" />
      </el-select>
      <el-button type="primary" @click="applyFilters">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </div>

    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="load" />
    <template v-else>
      <el-table :data="rows" border @row-click="openDetail">
        <el-table-column prop="code" label="编号" min-width="155" />
        <el-table-column prop="environment" label="环境" width="100" />
        <el-table-column :prop="config.primaryField" :label="config.primaryLabel" min-width="190" />
        <el-table-column prop="status" label="状态" width="135" />
        <el-table-column prop="version" label="版本" width="75" />
        <el-table-column label="人工受控操作" min-width="470">
          <template #default="{ row }">
            <el-button v-if="canPlan && row.status === 'draft'" size="small" @click.stop="openEdit(row)">编辑草稿</el-button>
            <el-button v-if="canPlan && row.status === 'draft'" size="small" @click.stop="act(row, 'submit')">提交评审</el-button>
            <el-button v-if="canReview && row.status === 'submitted'" size="small" type="success" @click.stop="act(row, 'approve')">人工批准</el-button>
            <el-button v-if="canReview && config.canReject && row.status === 'submitted'" size="small" @click.stop="act(row, 'reject')">人工拒绝</el-button>
            <el-button v-if="canRecord && row.status === 'approved'" size="small" type="primary" @click.stop="record(row)">记录脱敏结果</el-button>
            <el-button v-if="canCancel && ['draft', 'submitted', 'approved'].includes(row.status)" size="small" type="danger" plain @click.stop="act(row, 'cancel')">取消计划</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-if="!route.params.id"
        class="pagination"
        background
        layout="total, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page="page"
        @current-change="changePage"
      />
    </template>

    <el-drawer v-model="drawer" :title="`${config.title}详情`" size="min(600px, 94vw)">
      <el-alert title="详情仅展示脱敏、Mock 或受控证据引用。" type="warning" :closable="false" show-icon />
      <el-descriptions v-if="selected" :column="1" border class="detail-list">
        <el-descriptions-item v-for="(value, key) in selected" :key="key" :label="key">
          <pre v-if="typeof value === 'object'">{{ JSON.stringify(value, null, 2) }}</pre>
          <span v-else>{{ value }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-drawer>

    <el-dialog v-model="editVisible" title="编辑受控草稿" width="min(560px, 94vw)">
      <el-form label-position="top">
        <el-form-item :label="config.editLabel">
          <el-input v-model="editForm.value" :maxlength="config.editMaxLength" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="savePatch">保存草稿</el-button>
      </template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import { createP8Resource, fetchP8Resource, fetchP8Resources, patchP8Resource, runP8Action } from '../../api/pilot';
import { useAuthStore } from '../../stores/auth';
import { statusFromApiResponse } from '../../utils/uiState';

const props = defineProps({ kind: { type: String, required: true } });
const route = useRoute();
const auth = useAuthStore();
const commonStatuses = ['draft', 'submitted', 'approved', 'rejected', 'expired'];
const runStatuses = ['draft', 'submitted', 'approved', 'passed', 'failed', 'manual_required', 'cancelled'];
const definitions = {
  security: { title: '专项安全评审', subtitle: '冻结风险范围、脱敏证据与双人评审结果。', permission: 'security_review', primaryField: 'review_type', primaryLabel: '评审类型', canReject: true, statuses: commonStatuses, editField: 'scope_summary', editLabel: '范围说明', editMaxLength: 1000 },
  verification: { title: '受控验证运行', subtitle: '规划验证窗口并记录外部完成的脱敏证据。', permission: 'verification', primaryField: 'category', primaryLabel: '验证类别', canReject: false, statuses: runStatuses, editField: 'target_alias', editLabel: '受控目标别名', editMaxLength: 64 },
  performance: { title: '性能验证运行', subtitle: '定义合成负载阈值并记录外部测量结果。', permission: 'performance', primaryField: 'scenario', primaryLabel: '场景', canReject: false, statuses: runStatuses, editField: 'scenario', editLabel: '合成场景', editMaxLength: 200 },
  entry: { title: '生产试点准入决策', subtitle: '基于不可变证据快照形成 go/no-go 人工结论。', permission: 'entry', primaryField: 'decision', primaryLabel: '建议结论', canReject: true, statuses: commonStatuses, editField: 'scope_summary', editLabel: '准入范围', editMaxLength: 1000 }
};
const config = computed(() => definitions[props.kind]);
const canPlan = computed(() => auth.hasPermission(`pilot.${config.value.permission}.plan`));
const canReview = computed(() => auth.hasPermission(`pilot.${config.value.permission}.review`));
const canRecord = computed(() => ['verification', 'performance'].includes(props.kind) && auth.hasPermission(`pilot.${config.value.permission}.record`));
const canCancel = computed(() => ['verification', 'performance'].includes(props.kind) && auth.hasPermission(`pilot.${config.value.permission}.cancel`));
const state = ref('loading');
const capability = ref('pending');
const errorMessage = ref('');
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const filters = reactive({ environment: '', status: '' });
const drawer = ref(false);
const selected = ref(null);
const editVisible = ref(false);
const editForm = reactive({ id: null, version: 0, value: '' });
const daysFromNow = (days) => new Date(Date.now() + days * 86400000).toISOString();

function showFailure(response) {
  state.value = statusFromApiResponse(response, navigator.onLine);
  errorMessage.value = response.message;
}

async function load() {
  state.value = 'loading';
  errorMessage.value = '';
  const response = route.params.id
    ? await fetchP8Resource(props.kind, route.params.id)
    : await fetchP8Resources(props.kind, {
      page: page.value,
      page_size: pageSize,
      environment: filters.environment || undefined,
      status: filters.status || undefined
    });
  if (!response.success) {
    showFailure(response);
    return;
  }
  rows.value = route.params.id ? [response.data] : (response.data.results || []);
  total.value = route.params.id ? 1 : Number(response.data.count || 0);
  capability.value = response.data.api_status || 'pending';
  state.value = rows.value.length ? 'ready' : 'empty';
  if (route.params.id && rows.value[0]) openDetail(rows.value[0]);
}

function demoPayload() {
  if (props.kind === 'security') return { review_type: 'network_boundary', environment: 'pilot', scope_summary: 'Demo masked network boundary review', risk_level: 'medium', finance_scope: null, evidence_refs: ['demo-security-evidence'], expires_at: daysFromNow(30) };
  if (props.kind === 'verification') return { category: 'browser_e2e', environment: 'pilot', target_alias: 'demo-app', data_class: 'synthetic', planned_start_at: daysFromNow(1), planned_end_at: daysFromNow(2), success_criteria: ['Demo login flow renders'], evidence_refs: ['demo-verification-evidence'] };
  if (props.kind === 'performance') return { scenario: 'Synthetic dashboard read workload', environment: 'pilot', workload_profile: 'synthetic', max_rps: 20, concurrency: 5, duration_seconds: 60, thresholds: { p95_ms_max: 800, error_rate_max: 0.01, cpu_percent_max: 80, memory_percent_max: 80 }, evidence_refs: ['demo-performance-evidence'] };
  return { environment: 'pilot', decision: 'no_go', scope_summary: 'Demo pilot entry decision only', security_review_ids: [1], verification_run_ids: [1], performance_run_ids: [1], recovery_plan_ids: [1], release_plan_ids: [1], expires_at: daysFromNow(14) };
}

async function createDemo() {
  const response = await createP8Resource(props.kind, demoPayload());
  ElMessage[response.success ? 'success' : 'error'](response.success ? '演示草稿已记录，不会触发外部动作' : response.message);
  if (response.success) await load(); else showFailure(response);
}

async function act(row, actionName) {
  const payload = actionName === 'submit'
    ? { version: row.version, reason: 'Submit controlled demo evidence for human review' }
    : actionName === 'cancel'
      ? { version: row.version, cancel_reason: 'Cancel controlled demo plan' }
      : { version: row.version, review_reason: `${actionName} controlled demo evidence` };
  const response = await runP8Action(props.kind, row.id, actionName, payload);
  ElMessage[response.success ? 'success' : 'error'](response.success ? '状态与审计记录已更新' : response.message);
  if (response.success) await load(); else showFailure(response);
}

async function record(row) {
  const payload = props.kind === 'verification'
    ? { version: row.version, reason: 'Record externally completed demo verification', result: 'passed', result_summary: 'Synthetic verification passed', evidence_refs: ['demo-verification-result'], started_at: daysFromNow(-1), finished_at: new Date().toISOString(), error_code: null, error_message: null }
    : { version: row.version, reason: 'Record externally completed synthetic measurement', result_mode: 'measured', p50_ms: 180, p95_ms: 420, error_rate: 0.001, cpu_percent: 42, memory_percent: 58, result_summary: 'Synthetic workload stayed within thresholds', evidence_refs: ['demo-performance-result'] };
  const response = await runP8Action(props.kind, row.id, 'record-result', payload);
  ElMessage[response.success ? 'success' : 'error'](response.success ? '脱敏结果已记录' : response.message);
  if (response.success) await load(); else showFailure(response);
}

async function openEdit(row) {
  const response = await fetchP8Resource(props.kind, row.id);
  if (!response.success) {
    showFailure(response);
    return;
  }
  editForm.id = response.data.id;
  editForm.version = response.data.version;
  editForm.value = response.data[config.value.editField] || '';
  editVisible.value = true;
}

async function savePatch() {
  const response = await patchP8Resource(props.kind, editForm.id, {
    version: editForm.version,
    [config.value.editField]: editForm.value
  });
  ElMessage[response.success ? 'success' : 'error'](response.success ? '草稿已更新' : response.message);
  if (response.success) {
    editVisible.value = false;
    await load();
  } else {
    editVisible.value = false;
    showFailure(response);
  }
}

function applyFilters() { page.value = 1; load(); }
function resetFilters() { filters.environment = ''; filters.status = ''; page.value = 1; load(); }
function changePage(value) { page.value = value; load(); }
function openDetail(row) { selected.value = row; drawer.value = true; }
watch([() => props.kind, () => route.params.id], () => { page.value = 1; load(); });
load();
</script>

<style scoped>
.filters { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
.filters :deep(.el-select) { width: 180px; }
.pagination { justify-content: flex-end; margin-top: 16px; }
.detail-list { margin-top: 16px; }
pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.5 ui-monospace, monospace; }
</style>
