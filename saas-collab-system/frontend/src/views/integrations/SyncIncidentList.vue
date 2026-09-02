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
      <el-select v-model="status" clearable placeholder="全部状态" @change="load">
        <el-option label="未确认" value="open" />
        <el-option label="已确认" value="acknowledged" />
        <el-option label="已解决" value="resolved" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
      <el-button @click="status = ''; load()">重置</el-button>
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
          <el-descriptions-item label="错误码">{{ selected.last_error_code || '-' }}</el-descriptions-item>
          <el-descriptions-item label="脱敏错误">{{ selected.masked_message || '-' }}</el-descriptions-item>
          <el-descriptions-item label="当前备注">{{ selected.resolution_note || '暂无' }}</el-descriptions-item>
        </el-descriptions>

        <el-form label-position="top" class="incident-form">
          <el-form-item label="处置备注（脱敏）"><el-input v-model="note" type="textarea" :rows="4" maxlength="500" show-word-limit placeholder="填写排查、确认或解决说明" /></el-form-item>
        </el-form>
        <div class="incident-actions">
          <el-button v-if="selected.status === 'open' && canManage" :loading="actionLoading === 'acknowledge'" @click="act('acknowledge')">确认事件</el-button>
          <el-button v-if="canManage" :loading="actionLoading === 'note'" @click="act('note')">保存备注</el-button>
          <el-button v-if="selected.status !== 'resolved' && canManage" type="success" :loading="actionLoading === 'resolve'" @click="act('resolve')">解决事件</el-button>
          <el-button v-if="canRun" type="warning" :loading="retryLoading" @click="previewRetry">受控重试预览</el-button>
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
const retryLoading = ref(false);
const retryOpen = ref(false);
const retryPreview = ref(null);
const canManage = computed(() => auth.hasPermission('integrations.manage'));
const canRun = computed(() => auth.hasPermission('integrations.run'));

function responseRows(response) {
  const data = response?.data;
  return Array.isArray(data) ? data : (data?.results || data?.items || []);
}
function statusLabel(value) { return ({ open: '未确认', acknowledged: '已确认', resolved: '已解决' })[value] || value || '未知'; }
function statusType(value) { return ({ open: 'danger', acknowledged: 'warning', resolved: 'success' })[value] || 'info'; }
async function load() {
  loading.value = true;
  error.value = '';
  const response = await fetchSyncAlertIncidents({ status: status.value });
  capability.value = response?.data?.api_status || (useMock ? 'mock' : response?.success ? 'connected' : 'degraded');
  if (response?.success) rows.value = responseRows(response);
  else { rows.value = []; error.value = response?.message || '读取同步异常失败。'; }
  loading.value = false;
}
function openIncident(row) { selected.value = { ...row }; note.value = ''; retryPreview.value = null; drawerOpen.value = true; }
async function act(action) {
  if (!selected.value.id || !canManage.value) return;
  if (action === 'note' && !String(note.value || '').trim()) return ElMessage.warning('请输入脱敏处置备注。');
  try { await ElMessageBox.confirm(`确认${action === 'acknowledge' ? '确认该异常' : action === 'resolve' ? '解决该异常' : '保存备注'}？操作将写入集成审计。`, '确认异常处置', { type: action === 'resolve' ? 'warning' : 'info' }); } catch { return; }
  actionLoading.value = action;
  const response = await actOnSyncAlertIncident(selected.value.id, { action, ...(String(note.value || '').trim() ? { note: String(note.value).trim() } : {}) });
  actionLoading.value = '';
  if (!response?.success) return ElMessage.error(response?.message || '异常处置失败。');
  ElMessage.success('异常处置已记录。');
  selected.value = { ...response.data };
  note.value = '';
  await load();
}
async function previewRetry() {
  if (!selected.value.id || !canRun.value) return;
  retryLoading.value = true;
  const response = await fetchSyncAlertIncidentRetryPreview(selected.value.id);
  retryLoading.value = false;
  if (!response?.success) return ElMessage.error(response?.message || '重试预览失败。');
  retryPreview.value = response.data || null;
  retryOpen.value = true;
}
async function confirmRetry() {
  if (!retryPreview.value?.allowed || !canRun.value) return;
  try { await ElMessageBox.confirm('确认执行受控模拟重试？系统保证不调用生产外部 API。', '确认模拟重试', { type: 'warning', confirmButtonText: '确认重试' }); } catch { return; }
  retryLoading.value = true;
  const idempotencyKey = `ui-incident-${selected.value.id}-${Date.now()}`;
  const response = await retrySyncAlertIncident(selected.value.id, idempotencyKey);
  retryLoading.value = false;
  if (!response?.success) return ElMessage.error(response?.message || '受控重试失败。');
  retryOpen.value = false;
  ElMessage.success('受控模拟重试已提交。');
  await load();
}
onMounted(load);
</script>

<style scoped>
.toolbar { display: flex; gap: 10px; flex-wrap: wrap; margin: 18px 0; }
.toolbar .el-select { width: 170px; }
.page-alert { margin-bottom: 14px; }
.incident-form { margin-top: 20px; }
.incident-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
.retry-summary { margin-top: 18px; }
</style>
