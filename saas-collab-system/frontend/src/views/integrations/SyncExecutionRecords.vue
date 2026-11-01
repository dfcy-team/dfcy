<template>
  <section class="run-records">
    <header><div><h1>同步运行记录</h1><p>核对每次执行的结果；模拟运行不计入真实成功统计。时间统一为 UTC。</p></div><div class="header-actions"><el-button v-if="canCleanup" type="danger" plain :loading="cleaning" @click="cleanup">按日期清理成功记录</el-button><el-button :loading="loading" @click="load">刷新</el-button></div></header>
    <el-dialog v-model="cleanupDialog" title="按日期清理成功记录" width="min(520px, 94vw)">
      <p>范围：当前租户中你有管理权限的同步任务全部记录；不随当前列表筛选变化。仅成功记录，结束时间早于所选 UTC 日期 00:00。默认日期为 90 天前。</p>
      <el-date-picker v-model="cleanupDate" :disabled="cleaning" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" placeholder="选择 UTC 截止日期" />
      <el-alert v-if="cleanupPreview" class="cleanup-preview" type="info" :closable="false" :title="`本次最多删除 ${cleanupPreview.delete_count} 条；${cleanupPreview.has_more ? '还有更多记录，请本次完成后重新预览。' : '没有更多符合条件的记录。'}`">
        符合日期与管理权限范围、可清理的成功记录共 {{ cleanupPreview.candidate_count }} 条；另有 {{ cleanupPreview.protected_count }} 条因关联数据而保留。失败、取消、排队和运行中记录保留。关联原始响应、补采进度、检查点、调度或业务数据的记录也保留。
      </el-alert>
      <template #footer><el-button @click="cleanupDialog = false">取消</el-button><el-button :loading="cleaning" @click="previewCleanup">预览数量</el-button><el-button v-if="cleanupPreview?.delete_count" type="danger" :loading="cleaning" @click="confirmCleanup">确认删除预览记录</el-button></template>
    </el-dialog>
    <el-alert v-if="route.query.subject_key" type="info" :closable="false" :title="`当前主体：${String(route.query.subject_key).replace('store:', '店铺 #').replace('warehouse:', '仓库 #')}`"><el-button link @click="clearSubjectContext">显示全部主体</el-button></el-alert>
    <el-form label-position="top" class="filters" @submit.prevent="search">
      <el-form-item label="执行日期（UTC）" class="filter-dates"><el-date-picker v-model="dates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" range-separator="至" /></el-form-item>
      <el-form-item label="平台" class="platform-filter"><IntegrationPlatformPicker v-model="filters.platform" :options="platformOptions" @change="search" /></el-form-item>
      <el-form-item label="主体"><el-select v-model="filters.subject_key" :disabled="Boolean(route.query.subject_key)" clearable filterable><el-option v-for="v in options.subjects || []" :key="v.value" :value="v.value" :label="v.label" /></el-select></el-form-item>
      <el-form-item label="同步内容"><el-select v-model="filters.resource_type" clearable><el-option v-for="v in options.resource_types || []" :key="v" :value="v" :label="resources[v] || v" /></el-select></el-form-item>
      <el-form-item label="结果"><el-select v-model="filters.status" clearable><el-option v-for="v in options.statuses || []" :key="v" :value="v" :label="runStates[v] || v" /></el-select></el-form-item>
      <el-form-item label="触发方式"><el-select v-model="filters.trigger_type" clearable><el-option label="手动" value="manual" /><el-option label="调度" value="scheduled" /><el-option label="重试" value="retry" /></el-select></el-form-item>
      <el-form-item label="运行编号"><el-input v-model="filters.run_id" clearable placeholder="输入运行编号" /></el-form-item>
      <el-form-item label="所属任务 ID"><el-input v-model="filters.sync_job_id" clearable placeholder="输入任务 ID" /></el-form-item>
      <div class="filter-actions"><el-button type="primary" native-type="submit" :loading="loading">查询</el-button></div>
    </el-form>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-table v-loading="loading" :data="rows" border :empty-text="error ? '读取失败，记录未显示；请刷新重试' : '当前筛选下暂无运行记录'">
      <el-table-column label="触发来源" width="100"><template #default="{ row }">{{ { manual: '手动', scheduled: '定时', retry: '失败重试' }[row.trigger_type] || '—' }}</template></el-table-column>
      <el-table-column label="计划时间（UTC）" min-width="180"><template #default="{ row }">{{ syncTime(row.scheduled_at) }}</template></el-table-column>
      <el-table-column label="开始时间（UTC）" min-width="180"><template #default="{ row }">{{ syncTime(row.started_at) }}</template></el-table-column>
      <el-table-column label="所属任务" min-width="140"><template #default="{ row }"><el-button link type="primary" @click="task(row)">#{{ row.sync_job_id }}</el-button></template></el-table-column>
      <el-table-column prop="subject_name" label="主体" min-width="160" />
      <el-table-column prop="platform" label="平台" width="110" />
      <el-table-column label="同步内容" width="130"><template #default="{ row }">{{ resources[row.resource_type] || row.resource_type }}</template></el-table-column>
      <el-table-column label="真实／模拟" width="110"><template #default="{ row }"><el-tag :type="row.execution_mode === 'live_readonly' ? 'success' : 'warning'">{{ modeLabel(row) }}</el-tag></template></el-table-column>
      <el-table-column label="状态" width="100"><template #default="{ row }">{{ runStates[row.status] || '—' }}</template></el-table-column>
      <el-table-column label="采集通道" width="120"><template #default="{ row }">{{ laneLabel(row) }}</template></el-table-column>
      <el-table-column label="最新运行进度" min-width="240"><template #default="{ row }">{{ syncRuntimePresentation(row.runtime_state) }}</template></el-table-column>
      <el-table-column label="耗时" width="100"><template #default="{ row }">{{ row.duration_seconds == null ? '—' : `${row.duration_seconds} 秒` }}</template></el-table-column>
      <el-table-column label="重试次数" width="100"><template #default="{ row }">{{ syncCount(row.retry_count) }}</template></el-table-column>
      <el-table-column label="读取数" width="100"><template #default="{ row }">{{ syncCount(row.fetched_count) }}</template></el-table-column>
      <el-table-column label="落库数" width="100"><template #default="{ row }">{{ syncCount(written(row)) }}</template></el-table-column>
      <el-table-column label="失败数" width="100"><template #default="{ row }">{{ syncCount(row.failed_count) }}</template></el-table-column>
      <el-table-column label="操作" fixed="right" width="110"><template #default="{ row }"><el-button link type="primary" @click="open(row)">查看详情</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-if="!error" v-model:current-page="page" :page-size="50" :total="total" layout="total, prev, pager, next" @current-change="load" />
    <el-drawer v-model="drawer" title="运行详情" size="min(650px, 95vw)">
      <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
      <el-descriptions v-if="detail" :column="1" border>
        <el-descriptions-item label="运行编号／诊断定位">{{ detail.run_id || '—' }}</el-descriptions-item>
        <el-descriptions-item label="结果">{{ runStates[detail.status] || '—' }} · {{ modeLabel(detail) }}</el-descriptions-item>
        <el-descriptions-item label="开始／结束（UTC）">{{ syncTime(detail.started_at) }} / {{ syncTime(detail.finished_at) }}</el-descriptions-item>
        <el-descriptions-item label="计划执行时间（UTC）">{{ syncTime(detail.scheduled_at) }}</el-descriptions-item>
        <el-descriptions-item label="运行状态／当前等待／最近进度">{{ syncRuntimePresentation(detail.runtime_state) }}</el-descriptions-item>
        <el-descriptions-item label="采集通道">{{ laneLabel(detail) }}；通道分离不等于取数已成功，存量已投递消息不迁移。</el-descriptions-item>
        <el-descriptions-item v-if="detail.masked_log?.sync_policy" label="实际增量策略">{{ detail.masked_log.sync_policy.notice }}</el-descriptions-item>
        <el-descriptions-item label="原始入队时间（UTC）">{{ syncTime(detail.enqueued_at) }}</el-descriptions-item>
        <el-descriptions-item label="首次启动前排队时长（历史）">{{ queueSeconds(detail) }}</el-descriptions-item>
        <el-descriptions-item label="当次历史计划">{{ syncHistoricalPlanSummary(detail.schedule_snapshot) }}</el-descriptions-item>
        <el-descriptions-item label="原始运行关联">{{ detail.retry_of || '—' }}</el-descriptions-item>
        <el-descriptions-item label="触发方式">{{ { manual: '手动', scheduled: '调度', retry: '重试', history: '历史补采' }[detail.trigger_type] || '—' }}</el-descriptions-item>
        <el-descriptions-item label="读取／落库／失败">{{ syncCount(detail.fetched_count) }} / {{ syncCount(written(detail)) }} / {{ syncCount(detail.failed_count) }}</el-descriptions-item>
        <el-descriptions-item label="实际采集范围（北京时间）">{{ syncActualRange(detail.masked_log?.decision_source || {}) }}</el-descriptions-item>
        <el-descriptions-item label="执行参数">{{ detail.execution_mode || '—' }}；重试次数 {{ detail.retry_count ?? '—' }}；检查点 {{ detail.checkpoint_version ?? '—' }}</el-descriptions-item>
        <el-descriptions-item v-if="detail.execution_budget_seconds" label="分段续跑">单段 {{ detail.execution_budget_seconds }} 秒；续跑序号 {{ detail.continuation_count || 0 }}；{{ detail.continuation_pending ? '进度已保存，等待自动续跑' : '本段执行中或已结束' }}</el-descriptions-item>
        <el-descriptions-item label="失败阶段">{{ detail.masked_log?.failure_stage || '—' }}</el-descriptions-item>
        <el-descriptions-item label="错误码">{{ detail.error_code || '—' }}</el-descriptions-item>
        <el-descriptions-item label="原因和建议">{{ syncError(detail.masked_error_message, detail.error_code) }}</el-descriptions-item>
      </el-descriptions>
      <div v-if="detail" class="detail-actions">
        <el-button @click="task(detail)">返回所属任务</el-button>
        <el-button @click="router.push({ path: '/integrations/incidents', query: { sync_job_id: String(detail.sync_job_id) } })">同步异常</el-button>
        <el-button @click="router.push({ path: '/integrations/sync-jobs', query: { sync_job_id: String(detail.sync_job_id) } })">查看任务及授权配置</el-button>
        <el-button v-if="detail.status === 'failed'" :disabled="!!retryReason" :title="retryReason" :loading="retrying" @click="retry">再次模拟执行（新记录）</el-button>
        <p v-if="detail.status === 'failed'">{{ retryReason || '将创建一次新的模拟运行，不覆盖历史记录。' }}</p>
      </div>
    </el-drawer>
  </section>
</template>
<script setup>
import IntegrationPlatformPicker from '../../components/IntegrationPlatformPicker.vue';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { fetchIntegrationWorkspace, retrySyncRun, previewSyncRunDateCleanup, deleteSyncRunsByDate } from '../../api/integrations';
import { useAuthStore } from '../../stores/auth';
import { resources, runStates, syncTime, syncCount, syncError, syncWorkspaceError, syncHistoricalPlanSummary, syncActualRange, syncRuntimePresentation } from '../../utils/syncPresentation';
const route = useRoute(), router = useRouter(), auth = useAuthStore();
const props = defineProps({ detailId: { type: [String, Number], default: '' } });
const rows = ref([]), options = ref({}), loading = ref(false), error = ref(''), page = ref(1), total = ref(0), dates = ref([]);
const drawer = ref(false), detail = ref(null), detailError = ref(''), retrying = ref(false);
const cleaning = ref(false);
const cleanupDialog = ref(false), cleanupDate = ref(''), cleanupPreview = ref(null);
const cleanupDefault = new Date(Date.now() - 90 * 86400000).toISOString().slice(0, 10);
const canCleanup = computed(() => auth.hasPermission('integrations.manage'));
const platformOptions = computed(() => [...new Set([...(options.value.platforms || []), ...rows.value.map(row => row.platform).filter(Boolean)])]);
let workspaceLoadSequence = 0;
const filters = reactive({ platform: '', subject_key: String(route.query.subject_key || ''), resource_type: '', status: '', trigger_type: '', run_id: '', sync_job_id: String(route.query.sync_job_id || '') });
const modeLabel = row => row.is_plan_only ? '未执行' : ({ live_readonly: '真实只读', simulation: '模拟' }[row.execution_mode] || '未记录');
const laneLabel = row => row.runtime_state?.execution_lane === 'history' ? '历史补采' : row.runtime_state?.execution_lane === 'daily' ? '日常采集' : '未确认';
const queueSeconds = row => row.enqueued_at && row.started_at ? `${Math.max(0, Math.round((new Date(row.started_at) - new Date(row.enqueued_at)) / 1000))} 秒` : '—';
const written = row => row.created_count == null || row.updated_count == null ? null : row.created_count + row.updated_count;
const retryReason = computed(() => !auth.hasPermission('integrations.run') ? '没有模拟运行权限。' : !detail.value?.job_enabled ? '所属任务已停用或状态未确认，请返回任务页核对。' : detail.value?.execution_mode !== 'simulation' || detail.value?.environment !== 'mock' || detail.value?.resource_type !== 'mock_record' ? '仅独立 Mock 任务可在此重试；真实运行请返回任务页重新确认。' : detail.value.retry_count >= detail.value.max_retry_count ? '已达到最大重试次数。' : '');
function task(row) { router.push({ path: '/integrations/sync-jobs', query: { sync_job_id: String(row.sync_job_id) } }); }
function open(row) { detail.value = row; detailError.value = ''; drawer.value = true; }
function clearSubjectContext() { const query = { ...route.query }; delete query.subject_key; router.replace({ path: route.path, query }); }
function search() { page.value = 1; load(); }
async function load() {
  const requestSequence = ++workspaceLoadSequence;
  loading.value = true; error.value = '';
  rows.value = []; options.value = {}; total.value = 0;
  try {
    const response = await fetchIntegrationWorkspace('sync-runs', { ...filters, run_pk: props.detailId || route.query.detail || '', started_from: dates.value?.[0] || '', started_to: dates.value?.[1] || '', page: page.value, page_size: 50 });
    if (requestSequence !== workspaceLoadSequence) return;
    if (!response.success) throw new Error(response.message);
    rows.value = response.data.results || []; options.value = response.data.options || {};
    total.value = response.data.pagination?.total || 0; page.value = response.data.pagination?.page || 1;
    if ((props.detailId || route.query.detail) && !drawer.value) {
      const row = rows.value.find(item => String(item.id) === String(props.detailId || route.query.detail));
      if (row) open(row);
    }
  } catch (e) {
    if (requestSequence !== workspaceLoadSequence) return;
    rows.value = []; options.value = {}; total.value = 0;
    error.value = syncWorkspaceError(e.message);
  }
  finally { if (requestSequence === workspaceLoadSequence) loading.value = false; }
}
async function retry() {
  if (retrying.value || retryReason.value) return;
  retrying.value = true;
  try {
    await ElMessageBox.confirm('将创建一条新的模拟运行，不覆盖历史记录；后台仍会校验停用和安全规则。', '确认再次执行');
    const response = await retrySyncRun(detail.value.id);
    if (!response.success) throw new Error(response.message);
    ElMessage.success('已提交，将打开新的运行记录。'); drawer.value = false;
    if (response.data?.id) await router.push({ path: '/integrations/sync-runs', query: { sync_job_id: String(detail.value.sync_job_id), detail: String(response.data.id) } });
    else await load();
  } catch (e) { if (e !== 'cancel' && e !== 'close') detailError.value = syncError(e.message); }
  finally { retrying.value = false; }
}
async function cleanup() {
  if (cleaning.value || !canCleanup.value) return;
  cleanupDate.value = cleanupDefault; cleanupPreview.value = null; cleanupDialog.value = true;
}
async function previewCleanup() {
  if (cleaning.value || !cleanupDate.value) return;
  cleaning.value = true;
  try {
    const scope = { cutoff_date: cleanupDate.value, status: 'success' };
    const preview = await previewSyncRunDateCleanup(scope);
    if (!preview.success) throw new Error(preview.message);
    cleanupPreview.value = preview.data;
    if (!preview.data.delete_count) ElMessage.info('没有符合条件的成功记录。');
  } catch (e) { ElMessage.error(syncError(e.message)); }
  finally { cleaning.value = false; }
}
async function confirmCleanup() {
  if (cleaning.value || !cleanupPreview.value?.delete_count) return;
  cleaning.value = true;
  try {
    await ElMessageBox.confirm(`将删除 ${cleanupPreview.value.delete_count} 条成功运行记录。此操作不可撤销。`, '确认删除记录', { type: 'warning', confirmButtonText: '删除预览记录' });
    const result = await deleteSyncRunsByDate({ cutoff_date: cleanupDate.value, status: 'success', confirmation: cleanupPreview.value.confirmation });
    if (!result.success) throw new Error(result.message);
    ElMessage.success(`已删除 ${result.data.deleted_count} 条记录。`);
    cleanupDialog.value = false;
    await load();
  } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(syncError(e.message)); }
  finally { cleaning.value = false; }
}
watch(cleanupDate, () => { cleanupPreview.value = null; });
watch(() => [route.query.sync_job_id, route.query.subject_key, route.query.detail], ([job, subject]) => { drawer.value = false; filters.sync_job_id = String(job || ''); filters.subject_key = String(subject || ''); search(); });
onMounted(load);
</script>
<style scoped>
.run-records { display:grid; gap:16px; padding:20px; container:run-records / inline-size; } header { display:flex; justify-content:space-between; align-items:start; } .header-actions { display:flex; gap:8px; } h1 { margin:0; font-size:24px; } p { color:#64748b; font-size:13px; } .detail-actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:20px; }
.platform-filter { grid-column:1 / -1; }
.filters { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:16px 12px; align-items:end; }
.filters .el-form-item { margin:0; min-width:0; }
.filter-dates { grid-column:span 2; }
.filters :deep(.el-form-item__label) { margin-bottom:8px; line-height:20px; color:#475569; }
.filters :deep(.el-form-item__content) { min-width:0; }
.filters :deep(.el-select),.filters :deep(.el-input),.filters :deep(.el-date-editor) { width:100%; min-width:0; box-sizing:border-box; }
.filter-actions { grid-column:span 3; display:flex; justify-content:flex-end; align-items:center; min-height:32px; }
.filter-actions .el-button { min-width:80px; }
@container run-records (max-width:1100px) { .filters { grid-template-columns:repeat(4,minmax(0,1fr)); } }
@container run-records (max-width:760px) { .filters { grid-template-columns:repeat(2,minmax(0,1fr)); } .filter-actions { grid-column:span 1; } }
@container run-records (max-width:420px) { .filters { grid-template-columns:minmax(0,1fr); } .filter-dates { grid-column:auto; } .filter-actions .el-button { width:100%; } }
</style>
