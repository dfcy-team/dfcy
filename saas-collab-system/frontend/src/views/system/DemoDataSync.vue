<template>
  <AppPage :capability="pageError ? 'error' : !optionsLoaded ? 'loading' : options.enabled ? 'connected' : 'disabled'" eyebrow="SYSTEM MANAGEMENT" title="开发环境数据同步" subtitle="将授权的业务资源同步到隔离的开发环境，由内网同步服务异步执行。">
    <div v-if="pageError" class="sync-alert error" role="alert">
      <strong>开发环境同步状态读取失败</strong><span>{{ pageError }}</span>
      <el-button size="small" @click="loadAll">重试</el-button>
    </div>
    <div v-else-if="!optionsLoaded" class="sync-alert">正在读取部署配置…</div>
    <div v-else-if="!options.enabled" class="sync-alert warning" role="status">
      <strong>部署未配置</strong><span>开发环境数据同步尚未启用。请完成服务端部署配置后再使用。</span>
    </div>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="同步任务" name="tasks">
        <section class="sync-panel">
          <div class="panel-heading"><div><h2>创建同步任务</h2><p>选择开发环境和日期范围生成快照；新任务会重新扫描所选范围，不承诺可靠增量。</p></div></div>
          <el-form :inline="true" @submit.prevent="createBatch">
            <el-form-item label="开发环境"><el-select v-model="batchForm.environment_id" placeholder="选择环境" :disabled="!canRun || !options.enabled" style="width: 220px"><el-option v-for="env in activeEnvironments" :key="env.id" :label="env.name" :value="env.id" /></el-select></el-form-item>
            <el-form-item label="日期窗口"><el-date-picker v-model="batchForm.range" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" :disabled="!canRun || !options.enabled" /></el-form-item>
            <el-form-item><el-button type="primary" :disabled="!canRun || !options.enabled || !batchForm.environment_id || !batchForm.range || submitting" :loading="submitting" @click="createBatch">提交并排队</el-button></el-form-item>
          </el-form>
          <p class="hint">单次日期窗口最多 {{ options.max_window_days || 31 }} 天。系统会补齐必要的订单明细和主数据；平台凭据由服务端管理。</p>
          <p v-if="runAccess.reason" class="hint permission-hint">{{ runAccess.reason }}</p>
          <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
          <p v-if="queuedMessage" class="queued-message" role="status">{{ queuedMessage }}</p>
        </section>

        <section class="sync-panel">
          <div class="panel-heading"><div><h2>最近任务</h2><p>排队和运行中的任务会有限轮询，离开页面后自动停止。</p></div><el-button :loading="loadingBatches" @click="loadBatches">刷新</el-button></div>
          <p v-if="batchError" class="form-error" role="alert">{{ batchError }}</p>
          <el-table :data="batches" border empty-text="暂无同步任务" @row-click="selectBatch">
            <el-table-column prop="id" label="任务 ID" min-width="210" show-overflow-tooltip />
            <el-table-column prop="environment_name" label="开发环境" min-width="130" />
            <el-table-column label="状态" width="150"><template #default="{ row }"><span :title="row.status">{{ batchStatus(row.status) }}</span></template></el-table-column>
            <el-table-column label="日期窗口" min-width="180"><template #default="{ row }">{{ row.date_from }} 至 {{ row.date_to }}</template></el-table-column>
            <el-table-column prop="created_at" label="创建时间" min-width="170" />
            <el-table-column label="操作" width="180" fixed="right"><template #default="{ row }">
              <el-button v-if="row.status === 'ready' && downloadAccess.visible" link :disabled="downloadAccess.disabled || !options.enabled" :title="downloadAccess.reason" @click.stop="download(row)">下载快照</el-button>
              <el-button v-if="canRetryBatch(row) && runAccess.visible" link :disabled="runAccess.disabled || !options.enabled" :title="runAccess.reason" @click.stop="retry(row)">重新排队</el-button>
            </template></el-table-column>
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="数据快照" name="snapshots">
        <section class="sync-panel"><h2>数据快照</h2><p>每个任务都会重新扫描所选环境、授权资源和日期范围，不是可靠增量同步。快照仅在任务状态为 ready 时提供下载。</p>
          <el-table :data="readyBatches" border empty-text="暂无可下载快照"><el-table-column prop="environment_name" label="开发环境" /><el-table-column label="资源"><template #default="{ row }">{{ resourceNames(row.resources) }}</template></el-table-column><el-table-column label="日期窗口"><template #default="{ row }">{{ row.date_from }} 至 {{ row.date_to }}</template></el-table-column><el-table-column prop="finished_at" label="完成时间" /><el-table-column label="操作" width="140"><template #default="{ row }"><el-button v-if="downloadAccess.visible" link :disabled="downloadAccess.disabled || !options.enabled" @click="download(row)">下载 ZIP</el-button></template></el-table-column></el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="开发环境" name="environments">
        <section class="sync-panel">
          <div class="panel-heading"><div><h2>开发环境</h2><p>环境归属当前用户；店铺 ID 与仓库 ID 使用逗号分隔的整数。</p></div><el-button v-if="manageAccess.visible" type="primary" :disabled="manageAccess.disabled || !options.enabled" @click="envDialog = true">新建环境</el-button></div>
          <p v-if="manageAccess.reason" class="hint permission-hint">{{ manageAccess.reason }}</p>
          <p v-if="environmentError" class="form-error" role="alert">{{ environmentError }}</p>
          <el-table :data="environments" border empty-text="暂无开发环境"><el-table-column prop="name" label="名称" min-width="150" /><el-table-column prop="owner_name" label="负责人" min-width="130" /><el-table-column label="资源" min-width="180"><template #default="{ row }">{{ resourceNames(row.resources) }}</template></el-table-column><el-table-column prop="store_ids" label="店铺 ID" min-width="140" /><el-table-column prop="warehouse_ids" label="仓库 ID" min-width="140" /><el-table-column label="状态" width="100"><template #default="{ row }">{{ row.active ? '启用' : '停用' }}</template></el-table-column><el-table-column v-if="manageAccess.visible" label="操作" width="130"><template #default="{ row }"><el-button link :disabled="manageAccess.disabled || !options.enabled" :title="manageAccess.reason" @click="toggleEnvironment(row)">{{ row.active ? '停用环境' : '恢复环境' }}</el-button></template></el-table-column></el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="执行日志" name="logs">
        <section class="sync-panel"><div class="panel-heading"><div><h2>执行日志</h2><p>选择任务查看服务端记录的审计事件和错误信息。</p></div></div>
          <el-select v-model="selectedBatchId" placeholder="选择任务" clearable @change="loadBatchDetail" style="width: 360px"><el-option v-for="row in batches" :key="row.id" :label="`${row.environment_name} · ${batchStatus(row.status)} · ${row.id}`" :value="row.id" /></el-select>
          <p v-if="detailError" class="form-error" role="alert">{{ detailError }}</p>
          <p v-if="selectedDetail?.error_code" class="form-error">错误代码：{{ selectedDetail.error_code }} {{ selectedDetail.summary || '' }}</p>
          <el-table :data="selectedDetail?.audit || []" border empty-text="暂无审计事件"><el-table-column prop="event" label="事件" min-width="220" /><el-table-column prop="created_at" label="时间" min-width="180" /></el-table>
        </section>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="envDialog" title="新建开发环境" width="560px">
      <el-form label-width="100px"><el-form-item label="环境名称"><el-input v-model="envForm.name" maxlength="80" /></el-form-item>
        <el-form-item label="负责人 ID"><el-input v-model="envForm.owner_id" inputmode="numeric" placeholder="留空表示当前用户" /></el-form-item>
        <el-form-item label="同步资源"><el-select v-model="envForm.resources" multiple placeholder="选择资源" style="width: 100%"><el-option v-for="resource in options.resources || []" :key="resource.code" :label="resource.label" :value="resource.code" /></el-select></el-form-item>
        <el-form-item label="店铺 ID"><el-input v-model="envForm.store_ids" placeholder="例如 12, 34" /></el-form-item><el-form-item label="仓库 ID"><el-input v-model="envForm.warehouse_ids" placeholder="例如 5, 8" /></el-form-item>
      </el-form>
      <p v-if="environmentFormError" class="form-error" role="alert">{{ environmentFormError }}</p>
      <template #footer><el-button @click="envDialog = false">取消</el-button><el-button type="primary" :loading="submittingEnvironment" :disabled="!manageAccess.allowed || !options.enabled" @click="createEnvironment">创建</el-button></template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import { createDemoSyncBatch, createDemoSyncEnvironment, downloadDemoSyncBatch, fetchDemoDataSyncOptions, fetchDemoSyncBatch, fetchDemoSyncBatches, fetchDemoSyncEnvironments, retryDemoSyncBatch, updateDemoSyncEnvironmentStatus } from '../../api/demoDataSync';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';

const auth = useAuthStore();
const activeTab = ref('tasks');
const options = ref({ enabled: false, resources: [], max_window_days: 31 });
const optionsLoaded = ref(false);
const pageError = ref('');
const environments = ref([]);
const batches = ref([]);
const loadingBatches = ref(false);
const batchError = ref('');
const environmentError = ref('');
const formError = ref('');
const queuedMessage = ref('');
const submitting = ref(false);
const submittingEnvironment = ref(false);
const envDialog = ref(false);
const environmentFormError = ref('');
const envForm = ref({ name: '', owner_id: '', resources: [], store_ids: '', warehouse_ids: '' });
const batchForm = ref({ environment_id: '', range: null });
const selectedBatchId = ref('');
const selectedDetail = ref(null);
const detailError = ref('');
let pollTimer;
let pollCount = 0;
let disposed = false;
let pollRequestActive = false;
const viewAccess = computed(() => getActionAccess(auth, { permission: 'system.demo_sync.view' }));
const manageAccess = computed(() => getActionAccess(auth, { permission: 'system.demo_sync.manage', unauthorizedBehavior: 'disable' }));
const runAccess = computed(() => getActionAccess(auth, { permission: 'system.demo_sync.run', unauthorizedBehavior: 'disable' }));
const downloadAccess = computed(() => getActionAccess(auth, { permission: 'system.demo_sync.download', unauthorizedBehavior: 'disable' }));
const canRun = computed(() => runAccess.value.allowed);
const readyBatches = computed(() => batches.value.filter((row) => row.status === 'ready'));
const activeEnvironments = computed(() => environments.value.filter((env) => env.active));

function batchStatus(status) {
  return ({ queued: '排队中', pending: '待处理', running: '执行中', ready: '已完成', failed: '失败', canceled: '已取消', cancelled: '已取消' })[String(status || '').toLowerCase()] || '状态未知';
}

function canRetryBatch(row) { return row.status === 'failed' || (row.status === 'running' && row.heartbeat_at && Date.now() - Date.parse(row.heartbeat_at) > 600000); }
function resourceNames(codes) { return (codes || []).map(code => options.value.resources.find(r => r.code === code)?.label || code).join('、'); }
function showError(response) { return response?.message || response?.code || '请求失败'; }
function intList(text, label) {
  if (!String(text).trim()) return [];
  const parts = String(text).split(',').map((part) => part.trim());
  if (parts.some((part) => !/^\d+$/.test(part))) throw new Error(`${label}必须是逗号分隔的整数`);
  return [...new Set(parts.map(Number))];
}
function isBusy() { return batches.value.some((row) => ['queued', 'pending', 'running'].includes(String(row.status).toLowerCase())); }

async function loadAll() {
  pageError.value = '';
  optionsLoaded.value = false;
  const [optionResponse, envResponse, batchResponse] = await Promise.all([fetchDemoDataSyncOptions(), fetchDemoSyncEnvironments(), fetchDemoSyncBatches()]);
  if (disposed) return;
  if (!optionResponse.success) { pageError.value = showError(optionResponse); optionsLoaded.value = true; return; }
  options.value = optionResponse.data;
  optionsLoaded.value = true;
  if (!envResponse.success) environmentError.value = showError(envResponse);
  else { environments.value = envResponse.data?.results || []; environmentError.value = ''; }
  if (!batchResponse.success) batchError.value = showError(batchResponse);
  else { batches.value = batchResponse.data?.results || []; batchError.value = ''; }
  resetPoll();
}
async function loadBatches() {
  if (disposed || pollRequestActive) return;
  pollRequestActive = true;
  loadingBatches.value = true;
  let response;
  try { response = await fetchDemoSyncBatches(); }
  finally { pollRequestActive = false; loadingBatches.value = false; }
  if (disposed) return;
  if (!response.success) { batchError.value = showError(response); return; }
  batchError.value = '';
  batches.value = response.data?.results || [];
  if (!isBusy()) {
    clearTimeout(pollTimer);
    pollTimer = undefined;
  } else {
    schedulePoll();
  }
}
function schedulePoll() {
  if (disposed || pollTimer || pollCount >= 15 || !isBusy()) return;
  pollTimer = setTimeout(async () => {
    pollTimer = undefined;
    if (disposed || pollRequestActive) return;
    pollCount += 1;
    await loadBatches();
  }, 8000);
}
function resetPoll() {
  clearTimeout(pollTimer);
  pollTimer = undefined;
  pollCount = 0;
  schedulePoll();
}
async function createEnvironment() {
  environmentFormError.value = '';
  if (!manageAccess.value.allowed || !options.value.enabled) return;
  let payload;
  try {
    if (!envForm.value.name.trim()) throw new Error('请填写环境名称');
    if (!envForm.value.resources.length) throw new Error('请至少选择一项同步资源');
    payload = { name: envForm.value.name.trim(), resources: [...envForm.value.resources], store_ids: intList(envForm.value.store_ids, '店铺 ID'), warehouse_ids: intList(envForm.value.warehouse_ids, '仓库 ID') };
    if (String(envForm.value.owner_id).trim()) {
      if (!/^\d+$/.test(String(envForm.value.owner_id).trim())) throw new Error('负责人 ID 必须是整数');
      payload.owner_id = Number(envForm.value.owner_id);
    }
  } catch (error) { environmentFormError.value = error.message; return; }
  submittingEnvironment.value = true;
  const response = await createDemoSyncEnvironment(payload);
  submittingEnvironment.value = false;
  if (!response.success) { environmentFormError.value = showError(response); return; }
  envDialog.value = false;
  envForm.value = { name: '', owner_id: '', resources: [], store_ids: '', warehouse_ids: '' };
  ElMessage.success('开发环境已创建');
  const refreshed = await fetchDemoSyncEnvironments();
  if (refreshed.success) environments.value = refreshed.data?.results || [];
  else environmentError.value = showError(refreshed);
}
async function toggleEnvironment(row) {
  if (!manageAccess.value.allowed || !options.value.enabled) return;
  const response = await updateDemoSyncEnvironmentStatus(row.id, !row.active);
  if (!response.success) { environmentError.value = showError(response); return; }
  if (String(batchForm.value.environment_id) === String(row.id) && row.active) batchForm.value.environment_id = '';
  const refreshed = await fetchDemoSyncEnvironments();
  if (refreshed.success) { environments.value = refreshed.data?.results || []; environmentError.value = ''; }
  else environmentError.value = showError(refreshed);
}
async function createBatch() {
  formError.value = '';
  queuedMessage.value = '';
  if (!runAccess.value.allowed || !options.value.enabled) return;
  const [date_from, date_to] = batchForm.value.range || [];
  if (!batchForm.value.environment_id || !date_from || !date_to) { formError.value = '请选择开发环境和日期窗口'; return; }
  const dayCount = (Date.parse(`${date_to}T00:00:00Z`) - Date.parse(`${date_from}T00:00:00Z`)) / 86400000 + 1;
  if (dayCount <= 0 || dayCount > Number(options.value.max_window_days || 31)) { formError.value = `日期窗口不能超过 ${options.value.max_window_days || 31} 天`; return; }
  submitting.value = true;
  const response = await createDemoSyncBatch({ environment_id: batchForm.value.environment_id, date_from, date_to });
  submitting.value = false;
  if (!response.success) { formError.value = showError(response); return; }
  queuedMessage.value = `任务已提交并排队（${response.data?.id || '已受理'}），等待内网同步服务执行。`;
  batchForm.value = { ...batchForm.value, range: null };
  await loadBatches();
}
async function selectBatch(row) { selectedBatchId.value = row.id; await loadBatchDetail(); activeTab.value = 'logs'; }
async function loadBatchDetail() {
  if (!selectedBatchId.value) { selectedDetail.value = null; detailError.value = ''; return; }
  const response = await fetchDemoSyncBatch(selectedBatchId.value);
  if (!response.success) { selectedDetail.value = null; detailError.value = showError(response); return; }
  selectedDetail.value = response.data;
  detailError.value = '';
}
function filenameFor(row) { return `demo-data-snapshot-${String(row.id).slice(0, 8)}.zip`; }
async function download(row) {
  if (!downloadAccess.value.allowed || !options.value.enabled || row.status !== 'ready') return;
  const response = await downloadDemoSyncBatch(row.id, filenameFor(row));
  if (!response.success) ElMessage.error(showError(response));
}
async function retry(row) {
  if (!runAccess.value.allowed || !options.value.enabled) return;
  const response = await retryDemoSyncBatch(row.id);
  if (!response.success) { ElMessage.error(showError(response)); return; }
  queuedMessage.value = `新任务已提交并排队（${response.data?.id || '已受理'}）。`;
  activeTab.value = 'tasks';
  await loadBatches();
}
onMounted(() => { disposed = false; loadAll(); });
onUnmounted(() => { disposed = true; clearTimeout(pollTimer); pollTimer = undefined; });
</script>

<style scoped>
.sync-panel { margin: 16px 0; padding: 20px; border: 1px solid #dce4ed; border-radius: 8px; background: #fff; }
.sync-panel h2 { margin: 0 0 6px; font-size: 17px; }
.sync-panel p { color: #667085; }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.panel-heading p, .hint { margin: 4px 0 12px; color: #667085; font-size: 13px; }
.sync-alert { display: flex; align-items: center; gap: 12px; margin: 12px 0; padding: 14px 16px; border: 1px solid #d6e2ef; border-radius: 8px; background: #f8fafc; }
.sync-alert.warning { color: #825b12; border-color: #f0d89d; background: #fff9e9; }
.sync-alert.error, .form-error { color: #b42318; }
.sync-alert.error { border-color: #f1c1bd; background: #fff6f5; }
.permission-hint { color: #a05a00; }
.queued-message { padding: 10px 12px; border-radius: 6px; color: #176b42 !important; background: #effaf3; }
</style>




