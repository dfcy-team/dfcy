<template>
  <AppPage
    eyebrow="PRODUCTION PILOT"
    :title="config.title"
    :subtitle="config.subtitle"
    boundary-note="所有计划、审批、执行和结果都由服务端状态机校验并写入审计链；前端不保存凭据或绕过权限。"
    :capability="capability"
  >
    <template #action>
      <el-button v-if="canPlan" type="primary" @click="openCreate">{{ config.createLabel }}</el-button>
      <el-button @click="load" :loading="state === 'loading'">刷新</el-button>
    </template>

    <div v-if="!route.params.id" class="filters">
      <el-select v-model="filters.environment" clearable placeholder="环境" aria-label="环境筛选">
        <el-option label="pilot" value="pilot" />
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
        <el-table-column label="执行作业" min-width="180">
          <template #default="{ row }">
            <span>{{ executionIdFor(row) || '—' }}</span>
            <small v-if="executionStatusFor(row)" class="execution-status">{{ executionStatusFor(row) }}</small>
            <small v-if="executionErrors[row.id]" class="execution-error" role="alert">{{ executionErrors[row.id] }}</small>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="470">
          <template #default="{ row }">
            <el-button v-if="canPlan && row.status === 'draft'" size="small" @click.stop="openEdit(row)">编辑草稿</el-button>
            <el-button v-if="canPlan && row.status === 'draft'" size="small" @click.stop="beginAction(row, 'submit')">提交评审</el-button>
            <el-button v-if="canReview && row.status === 'submitted'" size="small" type="success" @click.stop="beginAction(row, 'approve')">人工批准</el-button>
            <el-button v-if="canReview && config.canReject && row.status === 'submitted'" size="small" @click.stop="beginAction(row, 'reject')">人工拒绝</el-button>
            <el-button v-if="isPerformance && canExecute && row.status === 'approved'" size="small" type="primary" @click.stop="confirmPerformanceExecution(row)">执行性能验证</el-button>
            <el-button v-if="isVerification && canRecord && row.status === 'approved'" size="small" type="primary" @click.stop="openResult(row)">提交验证结果</el-button>
            <el-button v-if="canCancel && ['draft', 'submitted', 'approved'].includes(row.status)" size="small" type="danger" plain @click.stop="beginAction(row, 'cancel')">取消计划</el-button>
            <el-button v-if="executionIdFor(row) && isExecutionActive(row)" size="small" @click.stop="refreshExecution(row)">刷新作业</el-button>
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

    <el-drawer v-model="drawer" :title="`${config.title}详情`" size="min(680px, 94vw)">
      <el-descriptions v-if="selected" :column="1" border class="detail-list">
        <el-descriptions-item v-for="(value, key) in selected" :key="key" :label="key">
          <pre v-if="typeof value === 'object'">{{ JSON.stringify(value, null, 2) }}</pre>
          <span v-else>{{ value }}</span>
        </el-descriptions-item>
      </el-descriptions>
      <section v-if="selectedExecution" class="execution-detail" aria-live="polite">
        <h3>执行作业 {{ selectedExecution.id || selectedExecution.execution_id || '—' }}</h3>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="状态">{{ selectedExecution.status || selectedExecution.state || '—' }}</el-descriptions-item>
          <el-descriptions-item label="指标"><pre>{{ JSON.stringify(selectedExecution.result_metrics || selectedExecution.metrics || selectedExecution.result || {}, null, 2) }}</pre></el-descriptions-item>
          <el-descriptions-item label="阈值"><pre>{{ JSON.stringify(selectedExecution.thresholds || selected?.thresholds || {}, null, 2) }}</pre></el-descriptions-item>
          <el-descriptions-item label="证据"><pre>{{ JSON.stringify(selectedExecution.evidence || selectedExecution.evidence_refs || [], null, 2) }}</pre></el-descriptions-item>
          <el-descriptions-item label="错误">{{ selectedExecution.error_message || selectedExecution.error?.message || '—' }}</el-descriptions-item>
          <el-descriptions-item label="审计信息"><pre>{{ JSON.stringify(selectedExecution.audit || selectedExecution.audit_info || selectedExecution.audit_ref || {}, null, 2) }}</pre></el-descriptions-item>
        </el-descriptions>
      </section>
      <el-alert v-if="selected && executionErrors[selected.id]" class="execution-error-alert" type="error" :closable="false" :title="executionErrors[selected.id]" />
    </el-drawer>

    <el-dialog v-model="createVisible" :title="config.createLabel" width="min(660px, 94vw)">
      <el-form label-position="top" class="create-form" @submit.prevent="createResource">
        <el-form-item label="环境" required><el-select v-model="createForm.environment" aria-label="创建环境"><el-option label="pilot" value="pilot" /></el-select></el-form-item>
        <template v-if="kind === 'security'">
          <el-form-item label="评审类型" required><el-select v-model="createForm.review_type"><el-option v-for="item in reviewTypes" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
          <el-form-item label="风险等级" required><el-select v-model="createForm.risk_level"><el-option v-for="item in riskLevels" :key="item" :label="item" :value="item" /></el-select></el-form-item>
          <el-form-item label="范围说明" required><el-input v-model="createForm.scope_summary" type="textarea" maxlength="1000" /></el-form-item>
        </template>
        <template v-else-if="kind === 'verification'">
          <el-form-item label="验证类别" required><el-select v-model="createForm.category"><el-option v-for="item in verificationCategories" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
          <el-form-item label="受控目标别名" required><el-input v-model="createForm.target_alias" maxlength="64" placeholder="例如 controlled-app" /></el-form-item>
          <el-form-item label="数据级别" required><el-select v-model="createForm.data_class"><el-option label="合成" value="synthetic" /><el-option label="脱敏" value="masked" /></el-select></el-form-item>
          <el-form-item label="成功标准" required><el-input v-model="createForm.success_criteria_text" type="textarea" placeholder="每行一条可验证标准" /></el-form-item>
        </template>
        <template v-else-if="kind === 'performance'">
          <el-form-item label="受控目标别名" required><el-input v-model="createForm.target_alias" maxlength="64" placeholder="例如 controlled-api" /></el-form-item>
          <el-form-item label="场景" required><el-input v-model="createForm.scenario" maxlength="200" /></el-form-item>
          <el-form-item label="负载配置" required><div class="load-grid"><el-input-number v-model="createForm.max_rps" :min="1" :max="500" controls-position="right" /><el-input-number v-model="createForm.concurrency" :min="1" :max="100" controls-position="right" /><el-input-number v-model="createForm.duration_seconds" :min="1" :max="3600" controls-position="right" /></div><small class="form-hint">最大 RPS / 并发数 / 持续秒数</small></el-form-item>
          <el-form-item label="阈值" required><div class="load-grid"><el-input-number v-model="createForm.thresholds.p95_ms_max" :min="1" :max="3600000" controls-position="right" /><el-input-number v-model="createForm.thresholds.error_rate_max" :min="0" :max="100" :step="0.01" controls-position="right" /><el-input-number v-model="createForm.thresholds.cpu_percent_max" :min="1" :max="100" controls-position="right" /><el-input-number v-model="createForm.thresholds.memory_percent_max" :min="1" :max="100" controls-position="right" /></div><small class="form-hint">P95 ms / 错误率上限（%） / CPU% / 内存%</small></el-form-item>
        </template>
        <template v-else>
          <el-form-item label="准入结论" required><el-select v-model="createForm.decision"><el-option label="Go" value="go" /><el-option label="No-go" value="no_go" /></el-select></el-form-item>
          <el-form-item label="准入范围" required><el-input v-model="createForm.scope_summary" type="textarea" maxlength="1000" /></el-form-item>
          <el-form-item label="安全评审 ID" required><el-input v-model="createForm.security_review_ids_text" placeholder="逗号分隔" /></el-form-item>
          <el-form-item label="验证运行 ID" required><el-input v-model="createForm.verification_run_ids_text" placeholder="逗号分隔" /></el-form-item>
          <el-form-item label="性能运行 ID" required><el-input v-model="createForm.performance_run_ids_text" placeholder="逗号分隔" /></el-form-item>
          <el-form-item label="恢复计划 ID" required><el-input v-model="createForm.recovery_plan_ids_text" placeholder="逗号分隔" /></el-form-item>
          <el-form-item label="发布计划 ID" required><el-input v-model="createForm.release_plan_ids_text" placeholder="逗号分隔" /></el-form-item>
        </template>
        <el-form-item label="证据引用" required><el-input v-model="createForm.evidence_refs_text" placeholder="每行或逗号分隔；必须引用真实审计证据" /></el-form-item>
        <span v-if="createError" class="inline-error" role="alert">{{ createError }}</span>
      </el-form>
      <template #footer><el-button @click="createVisible = false">取消</el-button><el-button type="primary" :loading="creating" @click="createResource">创建</el-button></template>
    </el-dialog>

    <el-dialog v-model="actionVisible" title="确认工作流操作" width="min(520px, 94vw)">
      <el-alert :title="`正在对 ${pendingAction?.row?.code || '目标'} 执行“${actionLabel(pendingAction?.name)}”，服务端将校验版本、权限和双人审批。`" type="warning" :closable="false" show-icon />
      <el-form label-position="top" class="action-form">
        <el-form-item label="操作理由" required><el-input v-model="actionForm.reason" type="textarea" maxlength="1000" placeholder="填写本次操作的真实原因" /></el-form-item>
        <el-form-item v-if="['approve', 'reject'].includes(pendingAction?.name)" label="评审意见" required><el-input v-model="actionForm.review_reason" type="textarea" maxlength="1000" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="actionVisible = false">取消</el-button><el-button type="primary" :loading="actionLoading" @click="confirmAction">确认提交</el-button></template>
    </el-dialog>

    <el-dialog v-model="resultVisible" title="提交验证结果" width="min(580px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="结果" required><el-select v-model="resultForm.result"><el-option label="通过" value="passed" /><el-option label="失败" value="failed" /><el-option label="需人工介入" value="manual_required" /></el-select></el-form-item>
        <el-form-item label="结果摘要" required><el-input v-model="resultForm.result_summary" type="textarea" maxlength="1000" /></el-form-item>
        <el-form-item label="证据引用" required><el-input v-model="resultForm.evidence_refs_text" placeholder="每行或逗号分隔" /></el-form-item>
        <el-form-item v-if="resultForm.result !== 'passed'" label="错误码"><el-input v-model="resultForm.error_code" maxlength="80" /></el-form-item>
        <el-form-item v-if="resultForm.result !== 'passed'" label="错误说明"><el-input v-model="resultForm.error_message" type="textarea" maxlength="1000" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="resultVisible = false">取消</el-button><el-button type="primary" :loading="resultLoading" @click="submitResult">提交结果</el-button></template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useRoute } from 'vue-router';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import {
  createP8Resource,
  executePerformanceRun,
  fetchExecution,
  fetchExecutions,
  fetchP8Resource,
  fetchP8Resources,
  patchP8Resource,
  runP8Action
} from '../../api/pilot';
import { useAuthStore } from '../../stores/auth';
import { statusFromApiResponse } from '../../utils/uiState';

const props = defineProps({ kind: { type: String, required: true } });
const route = useRoute();
const auth = useAuthStore();
const commonStatuses = ['draft', 'submitted', 'approved', 'rejected', 'expired'];
const runStatuses = ['draft', 'submitted', 'approved', 'queued', 'running', 'passed', 'failed', 'manual_required', 'cancelled'];
const definitions = {
  security: { title: '专项安全评审', subtitle: '冻结风险范围、生产数据边界和双人评审结果。', permission: 'security_review', primaryField: 'review_type', primaryLabel: '评审类型', createLabel: '创建安全评审', canReject: true, statuses: commonStatuses, editField: 'scope_summary', editLabel: '范围说明', editMaxLength: 1000 },
  verification: { title: '受控验证运行', subtitle: '规划受控目标和验收标准，提交真实验证结果。', permission: 'verification', primaryField: 'category', primaryLabel: '验证类别', createLabel: '创建验证运行', canReject: false, statuses: runStatuses, editField: 'target_alias', editLabel: '受控目标别名', editMaxLength: 64 },
  performance: { title: '性能验证运行', subtitle: '配置受控目标和负载阈值，审批后发起自动性能作业。', permission: 'performance', primaryField: 'scenario', primaryLabel: '场景', createLabel: '创建性能运行', canReject: false, statuses: runStatuses, editField: 'scenario', editLabel: '场景', editMaxLength: 200 },
  entry: { title: '生产试点准入决策', subtitle: '基于不可变证据快照形成 go/no-go 人工结论。', permission: 'entry', primaryField: 'decision', primaryLabel: '建议结论', createLabel: '创建准入决策', canReject: true, statuses: commonStatuses, editField: 'scope_summary', editLabel: '准入范围', editMaxLength: 1000 }
};
const config = computed(() => definitions[props.kind]);
const kind = computed(() => props.kind);
const isPerformance = computed(() => props.kind === 'performance');
const isVerification = computed(() => props.kind === 'verification');
const canPlan = computed(() => auth.hasPermission(`pilot.${config.value.permission}.plan`));
const canReview = computed(() => auth.hasPermission(`pilot.${config.value.permission}.review`));
const canRecord = computed(() => isVerification.value && auth.hasPermission('pilot.verification.record'));
const canExecute = computed(() => isPerformance.value && auth.hasPermission('pilot.performance.execute'));
const canCancel = computed(() => ['verification', 'performance'].includes(props.kind) && auth.hasPermission(`pilot.${config.value.permission}.cancel`));
const state = ref('loading');
const capability = ref('connected');
const errorMessage = ref('');
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const filters = reactive({ environment: '', status: '' });
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
const actionForm = reactive({ reason: '', review_reason: '' });
const resultVisible = ref(false);
const resultLoading = ref(false);
const resultRow = ref(null);
const resultForm = reactive({ result: 'passed', result_summary: '', evidence_refs_text: '', error_code: '', error_message: '' });
const editVisible = ref(false);
const editForm = reactive({ id: null, version: 0, value: '' });
const createForm = reactive({
  environment: 'pilot', review_type: 'network_boundary', risk_level: 'medium', scope_summary: '',
  category: 'browser_e2e', target_alias: '', data_class: 'synthetic', success_criteria_text: '',
  scenario: '', workload_profile: 'synthetic', max_rps: 20, concurrency: 5, duration_seconds: 60,
  thresholds: { p95_ms_max: 800, error_rate_max: 1, cpu_percent_max: 80, memory_percent_max: 80 },
  decision: 'no_go', security_review_ids_text: '', verification_run_ids_text: '', performance_run_ids_text: '', recovery_plan_ids_text: '', release_plan_ids_text: '', evidence_refs_text: ''
});
const reviewTypes = [
  { value: 'platform_access', label: '平台访问' }, { value: 'credential_custody', label: '凭据托管' },
  { value: 'network_boundary', label: '网络边界' }, { value: 'data_privacy', label: '数据隐私' },
  { value: 'runner_security', label: '执行器安全' }, { value: 'finance_boundary', label: '财务边界' }
];
const riskLevels = ['low', 'medium', 'high', 'critical'];
const verificationCategories = [
  { value: 'authentication', label: '身份认证' }, { value: 'authorization', label: '授权' },
  { value: 'browser_e2e', label: '浏览器端到端' }, { value: 'backup_restore', label: '备份恢复' },
  { value: 'failover', label: '故障切换' }, { value: 'network_isolation', label: '网络隔离' }, { value: 'security_scan', label: '安全扫描' }
];
let executionPollTimer = null;

const online = () => typeof navigator === 'undefined' || navigator.onLine;
const activeExecutionStates = new Set(['queued', 'running', 'pending', 'in_progress']);
const splitValues = (value) => String(value || '').split(/[\n,]/).map((item) => item.trim()).filter(Boolean);
const numericIds = (value) => splitValues(value).map(Number).filter((item) => Number.isInteger(item) && item > 0);

function showFailure(response) {
  state.value = statusFromApiResponse(response, online());
  errorMessage.value = response.message || '请求失败';
}

async function load() {
  state.value = 'loading';
  errorMessage.value = '';
  const response = route.params.id
    ? await fetchP8Resource(props.kind, route.params.id)
    : await fetchP8Resources(props.kind, { page: page.value, page_size: pageSize, environment: filters.environment || undefined, status: filters.status || undefined });
  if (!response.success) { showFailure(response); return; }
  const payload = response.data || {};
  rows.value = route.params.id ? [payload] : (payload.results || []);
  total.value = route.params.id ? 1 : Number(payload.count || 0);
  capability.value = payload.api_status || 'connected';
  state.value = rows.value.length ? 'ready' : 'empty';
  if (route.params.id && rows.value[0]) openDetail(rows.value[0]);
}

function executionIdFor(row) {
  return row.execution_id || row.execution?.id || row.execution?.execution_id || executionCache[row.id]?.id || executionCache[row.id]?.execution_id || '';
}
function executionStatusFor(row) {
  const execution = executionCache[row.id] || row.execution;
  return execution?.status || execution?.state || '';
}
function isExecutionActive(row) { return activeExecutionStates.has(executionStatusFor(row)); }

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
  const id = executionIdFor(row);
  if (!id) return;
  executionErrors[row.id] = '';
  const response = await fetchExecution(id);
  let execution = response.success ? response.data : null;
  if (response.success && !execution) {
    executionErrors[row.id] = '服务端未返回执行作业详情，无法安全更新状态';
  } else if (!response.success) {
    // The collection endpoint is a supported read path, but it does not
    // accept execution_id. Fetch a bounded page and match the requested job
    // explicitly so an unrelated execution can never be shown as this one.
    const listResponse = await fetchExecutions({ page: 1, page_size: 100 });
    if (!listResponse.success) {
      executionErrors[row.id] = listResponse.message || '执行作业状态读取失败';
    } else {
      execution = findExecution(listResponse.data, id);
      if (!execution) executionErrors[row.id] = `执行作业 ${id} 未在服务端返回，无法安全更新状态`;
    }
  }
  if (!execution) {
    ElMessage.error(executionErrors[row.id] || '执行作业状态读取失败');
    return;
  }
  executionCache[row.id] = execution;
  if (selected.value?.id === row.id) selectedExecution.value = executionCache[row.id];
  scheduleExecutionPoll(row);
}

function scheduleExecutionPoll(row) {
  if (executionPollTimer) clearTimeout(executionPollTimer);
  if (!isExecutionActive(row)) { executionPollTimer = null; return; }
  executionPollTimer = setTimeout(() => refreshExecution(row), 2000);
}

function openDetail(row) {
  selected.value = row;
  drawer.value = true;
  selectedExecution.value = executionCache[row.id] || row.execution || null;
  if (executionIdFor(row)) refreshExecution(row);
}

function resetCreateForm() {
  Object.assign(createForm, {
    environment: 'pilot', review_type: 'network_boundary', risk_level: 'medium', scope_summary: '', category: 'browser_e2e', target_alias: '', data_class: 'synthetic', success_criteria_text: '', scenario: '', workload_profile: 'synthetic', max_rps: 20, concurrency: 5, duration_seconds: 60, decision: 'no_go', security_review_ids_text: '', verification_run_ids_text: '', performance_run_ids_text: '', recovery_plan_ids_text: '', release_plan_ids_text: '', evidence_refs_text: ''
  });
   Object.assign(createForm.thresholds, { p95_ms_max: 800, error_rate_max: 1, cpu_percent_max: 80, memory_percent_max: 80 });
}

function openCreate() { resetCreateForm(); createError.value = ''; createVisible.value = true; }

function createPayload() {
  const evidence_refs = splitValues(createForm.evidence_refs_text);
  if (!evidence_refs.length) throw new Error('至少填写一条真实证据引用');
  const common = { environment: createForm.environment, evidence_refs };
  if (props.kind === 'security') return { ...common, review_type: createForm.review_type, scope_summary: createForm.scope_summary.trim(), risk_level: createForm.risk_level, finance_scope: null, expires_at: new Date(Date.now() + 30 * 86400000).toISOString() };
  if (props.kind === 'verification') return { ...common, category: createForm.category, target_alias: createForm.target_alias.trim(), data_class: createForm.data_class, planned_start_at: new Date().toISOString(), planned_end_at: new Date(Date.now() + 3600000).toISOString(), success_criteria: splitValues(createForm.success_criteria_text) };
  if (props.kind === 'performance') return { ...common, scenario: createForm.scenario.trim(), target_alias: createForm.target_alias.trim(), workload_profile: createForm.workload_profile, max_rps: createForm.max_rps, concurrency: createForm.concurrency, duration_seconds: createForm.duration_seconds, thresholds: { ...createForm.thresholds } };
  return { ...common, decision: createForm.decision, scope_summary: createForm.scope_summary.trim(), security_review_ids: numericIds(createForm.security_review_ids_text), verification_run_ids: numericIds(createForm.verification_run_ids_text), performance_run_ids: numericIds(createForm.performance_run_ids_text), recovery_plan_ids: numericIds(createForm.recovery_plan_ids_text), release_plan_ids: numericIds(createForm.release_plan_ids_text), expires_at: new Date(Date.now() + 14 * 86400000).toISOString() };
}

async function createResource() {
  createError.value = '';
  try {
    const payload = createPayload();
    const required = props.kind === 'performance' ? [payload.scenario, payload.target_alias] : props.kind === 'verification' ? [payload.target_alias, payload.success_criteria.length] : [payload.scope_summary];
    if (required.some((value) => !value)) throw new Error('请填写所有必填字段');
    if (props.kind === 'entry' && Object.values(payload).some((value) => Array.isArray(value) && !value.length)) throw new Error('准入决策必须关联完整证据运行');
    creating.value = true;
    const response = await createP8Resource(props.kind, payload);
    creating.value = false;
    if (!response.success) { createError.value = response.message || '创建失败'; return; }
    createVisible.value = false;
    ElMessage.success('生产计划已创建，等待后续审批');
    await load();
  } catch (error) {
    creating.value = false;
    createError.value = error.message || '表单校验失败';
  }
}

function actionLabel(name) { return { submit: '提交评审', approve: '人工批准', reject: '人工拒绝', cancel: '取消计划' }[name] || name || ''; }
function beginAction(row, actionName) { pendingAction.value = { row, name: actionName }; actionForm.reason = ''; actionForm.review_reason = ''; actionVisible.value = true; }

async function confirmAction() {
  if (!pendingAction.value || !actionForm.reason.trim() || (['approve', 'reject'].includes(pendingAction.value.name) && !actionForm.review_reason.trim())) return ElMessage.warning('请填写操作理由和评审意见');
  actionLoading.value = true;
  const { row, name } = pendingAction.value;
  const payload = { version: row.version };
  if (name === 'approve' || name === 'reject') {
    // ReviewSerializer accepts only review_reason. Preserve the operator's
    // stated reason inside that audited field instead of sending an unknown
    // `reason` key that the strict backend contract rejects.
    payload.review_reason = `${actionForm.reason.trim()} — ${actionForm.review_reason.trim()}`;
  } else if (name === 'cancel') {
    payload.cancel_reason = actionForm.reason.trim();
  } else {
    payload.reason = actionForm.reason.trim();
  }
  const response = await runP8Action(props.kind, row.id, name, payload);
  actionLoading.value = false;
  if (!response.success) { ElMessage.error(response.message || '操作失败'); showFailure(response); return; }
  actionVisible.value = false;
  ElMessage.success('工作流状态已更新并记录审计');
  await load();
}

async function confirmPerformanceExecution(row) {
  try {
    await ElMessageBox.confirm(`确认对受控目标“${row.target_alias || row.scenario}”发起性能作业？这会产生真实负载并影响试点环境。`, '执行性能验证确认', { type: 'warning', confirmButtonText: '确认执行', cancelButtonText: '取消' });
  } catch (error) { if (error === 'cancel' || error === 'close') return; ElMessage.error(error?.message || '执行确认失败'); return; }
  const response = await executePerformanceRun(row.id, { version: row.version, reason: 'Approved production pilot performance execution' });
  if (!response.success) { ElMessage.error(response.message || '性能作业提交失败'); return; }
  const execution = response.data || {};
  executionCache[row.id] = execution;
  if (selected.value?.id === row.id) selectedExecution.value = execution;
  ElMessage.success(`性能作业已提交：${execution.id || execution.execution_id || '服务端已受理'}`);
  await load();
  scheduleExecutionPoll(row);
}

function openResult(row) { resultRow.value = row; Object.assign(resultForm, { result: 'passed', result_summary: '', evidence_refs_text: '', error_code: '', error_message: '' }); resultVisible.value = true; }
async function submitResult() {
  if (!resultRow.value || !resultForm.result_summary.trim() || !splitValues(resultForm.evidence_refs_text).length) return ElMessage.warning('请填写结果摘要和真实证据引用');
  resultLoading.value = true;
  const response = await runP8Action('verification', resultRow.value.id, 'record-result', { version: resultRow.value.version, reason: 'Submit production verification result', result: resultForm.result, result_summary: resultForm.result_summary.trim(), evidence_refs: splitValues(resultForm.evidence_refs_text), started_at: resultRow.value.started_at || new Date().toISOString(), finished_at: new Date().toISOString(), error_code: resultForm.result === 'passed' ? null : (resultForm.error_code.trim() || null), error_message: resultForm.result === 'passed' ? null : (resultForm.error_message.trim() || null) });
  resultLoading.value = false;
  if (!response.success) { ElMessage.error(response.message || '验证结果提交失败'); return; }
  resultVisible.value = false;
  ElMessage.success('验证结果已提交并记录审计');
  await load();
}

async function openEdit(row) {
  const response = await fetchP8Resource(props.kind, row.id);
  if (!response.success) { showFailure(response); return; }
  editForm.id = response.data.id; editForm.version = response.data.version; editForm.value = response.data[config.value.editField] || '';
  editVisible.value = true;
}

async function savePatch() {
  const response = await patchP8Resource(props.kind, editForm.id, { version: editForm.version, [config.value.editField]: editForm.value });
  if (!response.success) { ElMessage.error(response.message || '草稿更新失败'); showFailure(response); return; }
  editVisible.value = false;
  ElMessage.success('草稿已更新');
  await load();
}

function applyFilters() { page.value = 1; load(); }
function resetFilters() { filters.environment = ''; filters.status = ''; page.value = 1; load(); }
function changePage(value) { page.value = value; load(); }
watch([() => props.kind, () => route.params.id], () => { page.value = 1; load(); });
onBeforeUnmount(() => { if (executionPollTimer) clearTimeout(executionPollTimer); });
load();
</script>

<style scoped>
.filters { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
.filters :deep(.el-select) { width: 180px; }
.pagination { justify-content: flex-end; margin-top: 16px; }
.detail-list { margin-top: 16px; }
.execution-status { display: block; color: #64748b; font-size: 11px; }
.execution-error { display: block; color: #c45656; font-size: 11px; line-height: 1.35; }
.execution-detail { margin-top: 20px; padding-top: 18px; border-top: 1px solid #e8edf3; }
.execution-error-alert { margin-top: 16px; }
.execution-detail h3 { margin: 0 0 12px; font-size: 15px; }
.create-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 14px; }
.create-form :deep(.el-form-item):has(.el-textarea), .create-form :deep(.el-form-item:last-of-type) { grid-column: 1 / -1; }
.create-form :deep(.el-select), .create-form :deep(.el-input), .create-form :deep(.el-input-number) { width: 100%; }
.load-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; width: 100%; }
.form-hint { display: block; margin-top: 6px; color: #64748b; font-size: 12px; }
.inline-error { display: block; color: #c45656; font-size: 13px; }
pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.5 ui-monospace, monospace; }
@media (max-width: 720px) { .create-form { grid-template-columns: 1fr; } .load-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
