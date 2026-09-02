<template>
  <AppPage
    eyebrow="PRODUCTION GOVERNANCE"
    :title="isAssistant ? '助手治理目录' : 'API 合同目录'"
    :subtitle="isAssistant ? '选择助手并提交真实评估输入，跟踪异步作业、评分和审计结果。' : '集中核对接口路径、权限、数据范围和版本，并执行固定合同检查（mock）。'"
    :boundary-note="isAssistant ? '评估作业由服务端按当前租户、权限和版本执行；前端不接触模型密钥。' : '合同检查当前为 fixed-demo/mock 静态校验，只验证合同结构，不代表真实运行时联通性。'"
    :capability="capability"
  >
    <template #action>
      <el-button @click="load" :loading="state === 'loading'">刷新</el-button>
      <el-button v-if="canCheck && !isAssistant" type="primary" :loading="checking" @click="runContractCheck">执行固定合同检查（mock）</el-button>
    </template>

    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="handleStateAction" />
    <template v-else>
      <div class="toolbar">
        <el-input v-model="keyword" clearable placeholder="名称、模块或路径" @keyup.enter="load" />
        <el-button @click="load">查询</el-button>
      </div>

      <section v-if="isAssistant" class="evaluation-panel" aria-labelledby="evaluation-title">
        <div class="panel-heading">
          <div>
            <h2 id="evaluation-title">真实助手评估</h2>
            <p>输入将按当前治理策略发送到服务端评估作业；评估结果返回后才会更新状态。</p>
          </div>
          <el-button v-if="evaluationId" :loading="evaluationLoading" @click="refreshEvaluation">刷新作业</el-button>
        </div>
        <el-alert
          class="evaluation-warning"
          type="warning"
          :closable="false"
          show-icon
          title="仅允许合成或公开测试数据（public_demo）"
          description="禁止输入 API key、密码、Cookie、令牌、连接串、生产数据或任何真实业务敏感信息。需要真实业务数据时，先完成脱敏和专项审批。"
        />
        <el-form label-position="top" class="evaluation-form" @submit.prevent="startEvaluation">
          <el-form-item label="助手" required>
            <el-select v-model="evaluationAssistantId" filterable placeholder="选择助手" aria-label="评估助手" :disabled="evaluationLoading || !canCheck">
              <el-option v-for="assistant in rows" :key="assistant.id" :label="`${assistant.name || assistant.code || `助手 ${assistant.id}`}（v${assistant.version || '-'}）`" :value="assistant.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="评估场景" required>
            <el-select v-model="evaluationForm.scenario" aria-label="评估场景" :disabled="evaluationLoading || !canCheck">
              <el-option label="治理目录审查" value="catalog_review" />
              <el-option label="就绪度摘要" value="readiness_summary" />
              <el-option label="风险摘要" value="risk_summary" />
            </el-select>
          </el-form-item>
          <el-form-item label="评估输入" required>
            <el-input v-model="evaluationForm.input" type="textarea" :rows="4" maxlength="10000" show-word-limit placeholder="填写合成或公开测试输入，不要包含真实业务数据" :disabled="evaluationLoading || !canCheck" />
          </el-form-item>
          <el-form-item label="预期结果" required>
            <el-input v-model="evaluationForm.expected_output" type="textarea" :rows="4" maxlength="10000" show-word-limit placeholder="填写可判定的预期输出或验收标准" :disabled="evaluationLoading || !canCheck" />
          </el-form-item>
          <el-form-item label="评估理由" required>
            <el-input v-model="evaluationForm.reason" type="textarea" :rows="3" maxlength="500" show-word-limit placeholder="说明本次评估的生产治理目的" :disabled="evaluationLoading || !canCheck" />
          </el-form-item>
          <div class="form-actions">
            <el-button type="primary" native-type="submit" :loading="evaluationLoading" :disabled="!evaluationAssistantId || !canCheck">发起异步评估</el-button>
            <span v-if="!canCheck" class="permission-hint">当前账号没有助手评估执行权限，仅可查看目录和历史详情。</span>
            <span v-if="evaluationError" class="inline-error" role="alert">{{ evaluationError }}</span>
          </div>
        </el-form>

        <section v-if="evaluation" class="evaluation-result" aria-live="polite">
          <div class="result-heading">
            <h3>评估作业 {{ evaluationId || '—' }}</h3>
            <el-tag :type="evaluationTagType(evaluationStatus)" effect="plain">{{ evaluationStatus || 'unknown' }}</el-tag>
          </div>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="模型">{{ evaluation.model || evaluation.model_name || '—' }}</el-descriptions-item>
            <el-descriptions-item label="通过">{{ evaluation.pass ?? evaluation.passed ?? evaluation.result?.pass ?? evaluation.result?.passed ?? '—' }}</el-descriptions-item>
            <el-descriptions-item label="分数">{{ evaluation.score ?? evaluation.result?.score ?? '—' }}</el-descriptions-item>
            <el-descriptions-item label="助手输出" :span="2"><pre>{{ formatObject(evaluation.assistant_output ?? evaluation.output ?? evaluation.result ?? evaluation.result_summary) }}</pre></el-descriptions-item>
            <el-descriptions-item label="发现" :span="2"><pre>{{ formatObject(evaluation.findings ?? evaluation.result?.findings) }}</pre></el-descriptions-item>
            <el-descriptions-item label="结果摘要" :span="2">{{ evaluation.result_summary || evaluation.result?.summary || '—' }}</el-descriptions-item>
            <el-descriptions-item label="Token usage">{{ formatTokenUsage(evaluation.token_usage || evaluation.usage) }}</el-descriptions-item>
            <el-descriptions-item label="错误">{{ evaluation.error_message || evaluation.error?.message || '—' }}</el-descriptions-item>
            <el-descriptions-item label="审计信息" :span="2"><pre>{{ formatObject(evaluation.audit || evaluation.audit_info || evaluation.audit_ref) }}</pre></el-descriptions-item>
          </el-descriptions>
          <el-alert v-if="evaluation.error_message || evaluation.error" type="error" :closable="false" class="result-alert" :title="evaluation.error_message || evaluation.error?.message" />
        </section>
      </section>

      <el-alert v-if="detailError" class="detail-error" type="error" :closable="false" :title="detailError" />
      <el-table :data="rows" border @row-click="openDetail">
        <el-table-column prop="name" label="名称" min-width="180" />
        <el-table-column v-if="!isAssistant" prop="module" label="模块" width="120" />
        <el-table-column v-if="!isAssistant" prop="method" label="方法" width="90" />
        <el-table-column v-if="!isAssistant" prop="path" label="规范路径" min-width="300" show-overflow-tooltip />
        <el-table-column v-if="!isAssistant" prop="permission" label="权限" min-width="180" />
        <el-table-column v-if="isAssistant" label="数据级别" width="160"><template #default="{ row }">{{ (row.data_classes || row.data_class || []).join?.(', ') || row.data_class || '—' }}</template></el-table-column>
        <el-table-column v-if="isAssistant" prop="human_confirmation_required" label="人工确认" width="100"><template #default="{ row }">{{ row.human_confirmation_required ? '需要' : '不需要' }}</template></el-table-column>
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column v-if="!isAssistant" prop="version" label="版本" width="120" />
      </el-table>
      <el-pagination class="pager" background layout="total, prev, pager, next" :total="total" :page-size="20" :current-page="page" @current-change="changePage" />

      <el-drawer v-model="drawer" title="治理详情" size="min(620px, 92vw)" @closed="closeDetailRoute">
        <el-descriptions v-if="detail" :column="1" border>
          <el-descriptions-item v-for="(value, key) in detail" :key="key" :label="key">
            <pre v-if="typeof value === 'object'">{{ JSON.stringify(value, null, 2) }}</pre>
            <span v-else>{{ value }}</span>
          </el-descriptions-item>
        </el-descriptions>
      </el-drawer>
      <el-alert v-if="checkResult" class="result" :type="checkFailed ? 'error' : 'success'" :closable="false" :title="`固定合同检查（fixed-demo/mock）${checkFailed ? '未通过' : '完成'}`" :description="JSON.stringify(checkResult)" />
    </template>
  </AppPage>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { useRoute, useRouter } from 'vue-router';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import {
  checkApiContract,
  createAssistantEvaluation,
  fetchApiContract,
  fetchApiContracts,
  fetchAssistant,
  fetchAssistantEvaluation,
  fetchAssistants
} from '../../api/governance';
import { useAuthStore } from '../../stores/auth';
import { statusFromApiResponse } from '../../utils/uiState';

const props = defineProps({ resource: { type: String, required: true } });
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const isAssistant = computed(() => props.resource === 'assistants');
const basePath = computed(() => isAssistant.value ? '/governance/assistants' : '/governance/api-contracts');
const canCheck = computed(() => auth.hasPermission(isAssistant.value ? 'governance.assistants.evaluate' : 'governance.api.check'));
const state = ref('loading');
const capability = ref('connected');
const errorMessage = ref('');
const detailError = ref('');
const keyword = ref('');
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const drawer = ref(false);
const detail = ref(null);
const checking = ref(false);
const checkResult = ref(null);
const evaluationAssistantId = ref(null);
const evaluation = ref(null);
const evaluationId = ref('');
const evaluationLoading = ref(false);
const evaluationError = ref('');
const evaluationForm = reactive({ scenario: 'catalog_review', input: '', expected_output: '', reason: '' });
let evaluationPollTimer = null;

const evaluationStatus = computed(() => evaluation.value?.status || evaluation.value?.state || '');
const checkFailed = computed(() => Boolean(checkResult.value?.violations?.length || checkResult.value?.passed === false));
const online = () => typeof navigator === 'undefined' || navigator.onLine;
const terminalEvaluationStates = new Set(['passed', 'failed', 'succeeded', 'success', 'cancelled', 'manual_required', 'error']);

function setFailure(response) {
  state.value = statusFromApiResponse(response, online());
  errorMessage.value = response.message || '请求失败';
}

async function load() {
  state.value = 'loading';
  errorMessage.value = '';
  detailError.value = '';
  const response = isAssistant.value
    ? await fetchAssistants({ page: page.value, page_size: 20, search: keyword.value || undefined })
    : await fetchApiContracts({ page: page.value, page_size: 20, search: keyword.value || undefined });
  if (!response.success) {
    setFailure(response);
    return;
  }
  const payload = response.data || {};
  rows.value = payload.results || [];
  total.value = Number(payload.count || 0);
  capability.value = payload.api_status || 'connected';
  state.value = rows.value.length ? 'ready' : 'empty';
  if (isAssistant.value && !evaluationAssistantId.value && rows.value[0]) evaluationAssistantId.value = rows.value[0].id;
  if (route.params.id) await loadDetail(route.params.id, false);
}

async function loadDetail(id, updateRoute = true) {
  detailError.value = '';
  const response = isAssistant.value ? await fetchAssistant(id) : await fetchApiContract(id);
  if (!response.success) {
    if (!updateRoute && route.params.id) setFailure(response);
    else detailError.value = response.message || '详情加载失败';
    return;
  }
  detail.value = response.data;
  drawer.value = true;
  if (isAssistant.value) evaluationAssistantId.value = response.data.id;
  if (updateRoute && String(route.params.id || '') !== String(id)) await router.push(`${basePath.value}/${id}`);
}

function openDetail(row) { loadDetail(row.id); }
function closeDetailRoute() { detail.value = null; if (route.params.id) router.replace(basePath.value); }
async function handleStateAction() {
  if (state.value === 'not_found' && route.params.id) await router.replace(basePath.value);
  await load();
}

async function runContractCheck() {
  if (isAssistant.value || !rows.value.length) return;
  checking.value = true;
  const response = await checkApiContract({ contract_ids: rows.value.map((item) => item.id).slice(0, 50), sample_case: 'success' });
  checking.value = false;
  if (!response.success) {
    checkResult.value = null;
    ElMessage.error(response.message || '合同检查失败');
    return;
  }
  checkResult.value = response.data;
  ElMessage[checkFailed.value ? 'error' : 'success'](checkFailed.value ? '合同检查发现问题' : '合同检查通过');
}

function evaluationTagType(status) {
  if (['passed', 'succeeded', 'success'].includes(status)) return 'success';
  if (['failed', 'error'].includes(status)) return 'danger';
  if (['queued', 'running'].includes(status)) return 'warning';
  return 'info';
}

function formatObject(value) {
  if (value === undefined || value === null || value === '') return '—';
  return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
}

function formatTokenUsage(value) {
  if (!value) return '—';
  if (typeof value !== 'object') return String(value);
  const input = value.input_tokens ?? value.prompt_tokens;
  const output = value.output_tokens ?? value.completion_tokens;
  const totalUsage = value.total_tokens ?? (input !== undefined && output !== undefined ? input + output : undefined);
  return formatObject({ input_tokens: input, output_tokens: output, total_tokens: totalUsage });
}

function clearEvaluationPoll() {
  if (evaluationPollTimer) clearTimeout(evaluationPollTimer);
  evaluationPollTimer = null;
}

function scheduleEvaluationPoll() {
  clearEvaluationPoll();
  if (!evaluationId.value || terminalEvaluationStates.has(evaluationStatus.value)) return;
  evaluationPollTimer = setTimeout(() => refreshEvaluation(true), 2000);
}

async function refreshEvaluation(isPoll = false) {
  if (!evaluationId.value) return;
  if (!isPoll) evaluationLoading.value = true;
  const response = await fetchAssistantEvaluation(evaluationId.value);
  if (!response.success) {
    clearEvaluationPoll();
    evaluationError.value = response.message || '评估作业状态读取失败';
    evaluationLoading.value = false;
    return;
  }
  evaluation.value = response.data || {};
  evaluationError.value = '';
  evaluationLoading.value = false;
  scheduleEvaluationPoll();
}

async function startEvaluation() {
  evaluationError.value = '';
  const assistant = rows.value.find((item) => String(item.id) === String(evaluationAssistantId.value));
  if (!assistant) { evaluationError.value = '请选择要评估的助手'; return; }
  if (!canCheck.value) { evaluationError.value = '当前账号没有助手评估执行权限'; return; }
  if (!evaluationForm.input.trim() || !evaluationForm.expected_output.trim() || !evaluationForm.reason.trim()) {
    evaluationError.value = '评估输入、预期结果和评估理由均为必填项';
    return;
  }
  if (containsSensitiveValue(evaluationForm.input) || containsSensitiveValue(evaluationForm.expected_output) || containsSensitiveValue(evaluationForm.reason)) {
    evaluationError.value = '评估字段仅允许合成或公开测试数据，禁止凭据及真实业务敏感信息';
    return;
  }
  const version = Number(assistant.version);
  if (!Number.isInteger(version) || version < 1) {
    evaluationError.value = '助手版本缺失或无效，请刷新目录后重试';
    return;
  }
  clearEvaluationPoll();
  evaluationLoading.value = true;
  evaluation.value = null;
  evaluationId.value = '';
  const payload = {
    scenario: evaluationForm.scenario,
    input: evaluationForm.input.trim(),
    expected_output: evaluationForm.expected_output.trim(),
    reason: evaluationForm.reason.trim(),
    version
  };
  const response = await createAssistantEvaluation(assistant.id, payload);
  if (!response.success) {
    evaluationLoading.value = false;
    evaluationError.value = response.message || '评估作业创建失败';
    ElMessage.error(evaluationError.value);
    return;
  }
  evaluation.value = response.data || {};
  evaluationId.value = response.data?.id || response.data?.evaluation_id || response.data?.job_id || '';
  if (!evaluationId.value) {
    evaluationLoading.value = false;
    evaluationError.value = '服务端未返回评估作业编号，无法安全跟踪状态';
    ElMessage.error(evaluationError.value);
    return;
  }
  evaluationLoading.value = false;
  scheduleEvaluationPoll();
  ElMessage.success('评估作业已提交');
}

function containsSensitiveValue(value) {
  return /(?:sk-[A-Za-z0-9_-]{12,}|(?:api[_-]?key|api[_-]?secret|password|passwd|cookie|session|token|authorization)\s*[:=]|(?:mysql|redis|postgres(?:ql)?)\s*:\/\/|(?:\d{1,3}\.){3}\d{1,3})/i.test(value);
}

function changePage(value) { page.value = value; load(); }
watch(() => props.resource, () => {
  page.value = 1;
  drawer.value = false;
  clearEvaluationPoll();
  evaluation.value = null;
  evaluationId.value = '';
  load();
});
watch(() => route.params.id, (id) => { if (id && state.value === 'ready') loadDetail(id, false); });
onBeforeUnmount(clearEvaluationPoll);
load();
</script>

<style scoped>
.toolbar { display: flex; gap: 10px; max-width: 560px; margin-bottom: 14px; }
.pager { margin-top: 16px; justify-content: flex-end; }
.result { margin-top: 16px; overflow-wrap: anywhere; }
.detail-error { margin-bottom: 14px; }
.evaluation-panel { margin-bottom: 20px; padding: 18px; border: 1px solid #dbe3ec; border-radius: 8px; background: #fff; }
.panel-heading, .result-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.panel-heading h2, .result-heading h3 { margin: 0; color: #172033; font-size: 16px; }
.panel-heading p { margin: 6px 0 16px; color: #64748b; line-height: 1.5; }
.evaluation-warning { margin-bottom: 16px; }
.evaluation-form { display: grid; grid-template-columns: repeat(2, minmax(220px, 1fr)); gap: 12px; align-items: start; }
.evaluation-form :deep(.el-form-item:nth-child(3)), .evaluation-form :deep(.el-form-item:nth-child(4)), .evaluation-form :deep(.el-form-item:nth-child(5)) { grid-column: 1 / -1; }
.evaluation-form :deep(.el-select), .evaluation-form :deep(.el-input) { width: 100%; }
.form-actions { grid-column: 1 / -1; display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.permission-hint { color: #64748b; font-size: 13px; }
.inline-error { color: #c45656; font-size: 13px; }
.evaluation-result { margin-top: 18px; padding-top: 18px; border-top: 1px solid #e8edf3; }
.evaluation-result :deep(.el-descriptions) { margin-top: 12px; }
.result-alert { margin-top: 12px; }
pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.5 ui-monospace, monospace; }
@media (max-width: 900px) { .evaluation-form { grid-template-columns: 1fr; } .form-actions { grid-column: auto; } }
@media (max-width: 560px) { .toolbar, .panel-heading, .result-heading { flex-direction: column; align-items: stretch; } }
</style>
