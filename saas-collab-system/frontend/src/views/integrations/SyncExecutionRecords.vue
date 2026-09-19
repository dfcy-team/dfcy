<template>
  <section class="run-records">
    <header><div><h1>同步运行记录</h1><p>核对每次执行的结果；模拟运行不计入真实成功统计。时间统一为 UTC。</p></div><el-button :loading="loading" @click="load">刷新</el-button></header>
    <el-form label-position="top" class="filters" @submit.prevent="search">
      <el-form-item label="执行日期（UTC）" class="filter-dates"><el-date-picker v-model="dates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" range-separator="至" /></el-form-item>
      <el-form-item label="平台"><el-select v-model="filters.platform" clearable><el-option v-for="v in options.platforms || []" :key="v" :value="v" :label="v" /></el-select></el-form-item>
      <el-form-item label="主体"><el-select v-model="filters.subject_key" clearable filterable><el-option v-for="v in options.subjects || []" :key="v.value" :value="v.value" :label="v.label" /></el-select></el-form-item>
      <el-form-item label="同步内容"><el-select v-model="filters.resource_type" clearable><el-option v-for="v in options.resource_types || []" :key="v" :value="v" :label="resources[v] || v" /></el-select></el-form-item>
      <el-form-item label="结果"><el-select v-model="filters.status" clearable><el-option v-for="v in options.statuses || []" :key="v" :value="v" :label="runStates[v] || v" /></el-select></el-form-item>
      <el-form-item label="触发方式"><el-select v-model="filters.trigger_type" clearable><el-option label="手动" value="manual" /><el-option label="调度" value="scheduled" /><el-option label="重试" value="retry" /></el-select></el-form-item>
      <el-form-item label="运行编号"><el-input v-model="filters.run_id" clearable placeholder="输入运行编号" /></el-form-item>
      <el-form-item label="所属任务 ID"><el-input v-model="filters.sync_job_id" clearable placeholder="输入任务 ID" /></el-form-item>
      <div class="filter-actions"><el-button type="primary" native-type="submit" :loading="loading">查询</el-button></div>
    </el-form>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-table v-loading="loading" :data="rows" border empty-text="当前筛选下暂无运行记录">
      <el-table-column label="触发来源" width="100"><template #default="{ row }">{{ { manual: '手动', scheduled: '定时', retry: '失败重试' }[row.trigger_type] || '—' }}</template></el-table-column>
      <el-table-column label="计划时间（UTC）" min-width="180"><template #default="{ row }">{{ syncTime(row.scheduled_at) }}</template></el-table-column>
      <el-table-column label="开始时间（UTC）" min-width="180"><template #default="{ row }">{{ syncTime(row.started_at) }}</template></el-table-column>
      <el-table-column label="所属任务" min-width="140"><template #default="{ row }"><el-button link type="primary" @click="task(row)">#{{ row.sync_job_id }}</el-button></template></el-table-column>
      <el-table-column prop="subject_name" label="主体" min-width="160" />
      <el-table-column prop="platform" label="平台" width="110" />
      <el-table-column label="同步内容" width="130"><template #default="{ row }">{{ resources[row.resource_type] || row.resource_type }}</template></el-table-column>
      <el-table-column label="真实／模拟" width="110"><template #default="{ row }"><el-tag :type="row.execution_mode === 'live_readonly' ? 'success' : 'warning'">{{ modeLabel(row) }}</el-tag></template></el-table-column>
      <el-table-column label="状态" width="100"><template #default="{ row }">{{ runStates[row.status] || '—' }}</template></el-table-column>
      <el-table-column label="耗时" width="100"><template #default="{ row }">{{ row.duration_seconds == null ? '—' : `${row.duration_seconds} 秒` }}</template></el-table-column>
      <el-table-column label="重试次数" width="100"><template #default="{ row }">{{ syncCount(row.retry_count) }}</template></el-table-column>
      <el-table-column label="读取数" width="100"><template #default="{ row }">{{ syncCount(row.fetched_count) }}</template></el-table-column>
      <el-table-column label="落库数" width="100"><template #default="{ row }">{{ syncCount(written(row)) }}</template></el-table-column>
      <el-table-column label="失败数" width="100"><template #default="{ row }">{{ syncCount(row.failed_count) }}</template></el-table-column>
      <el-table-column label="操作" fixed="right" width="110"><template #default="{ row }"><el-button link type="primary" @click="open(row)">查看详情</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" :page-size="50" :total="total" layout="total, prev, pager, next" @current-change="load" />
    <el-drawer v-model="drawer" title="运行详情" size="min(650px, 95vw)">
      <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
      <el-descriptions v-if="detail" :column="1" border>
        <el-descriptions-item label="运行编号／诊断定位">{{ detail.run_id || '—' }}</el-descriptions-item>
        <el-descriptions-item label="结果">{{ runStates[detail.status] || '—' }} · {{ modeLabel(detail) }}</el-descriptions-item>
        <el-descriptions-item label="开始／结束（UTC）">{{ syncTime(detail.started_at) }} / {{ syncTime(detail.finished_at) }}</el-descriptions-item>
        <el-descriptions-item label="计划执行时间（UTC）">{{ syncTime(detail.scheduled_at) }}</el-descriptions-item>
        <el-descriptions-item label="排队时长">{{ queueSeconds(detail) }}</el-descriptions-item>
        <el-descriptions-item label="当次计划">{{ detail.schedule_snapshot ? `${schedules[detail.schedule_snapshot.schedule_type] || '—'} · ${detail.schedule_snapshot.timezone || 'Asia/Shanghai'} · ${detail.schedule_snapshot.local_time || '—'} · 间隔 ${detail.schedule_snapshot.interval_minutes ?? '—'} 分钟 · 星期 ${(detail.schedule_snapshot.weekdays || []).join('、') || '—'}` : '—' }}</el-descriptions-item>
        <el-descriptions-item label="原始运行关联">{{ detail.retry_of || '—' }}</el-descriptions-item>
        <el-descriptions-item label="触发方式">{{ { manual: '手动', scheduled: '调度', retry: '重试' }[detail.trigger_type] || '—' }}</el-descriptions-item>
        <el-descriptions-item label="读取／落库／失败">{{ syncCount(detail.fetched_count) }} / {{ syncCount(written(detail)) }} / {{ syncCount(detail.failed_count) }}</el-descriptions-item>
        <el-descriptions-item label="采集日期（北京时间）">{{ syncCollectionDate(detail.masked_log?.decision_source?.time_from) }} 至 {{ syncCollectionDate(detail.masked_log?.decision_source?.time_to) }}</el-descriptions-item>
        <el-descriptions-item label="执行参数">{{ detail.execution_mode || '—' }}；重试次数 {{ detail.retry_count ?? '—' }}；检查点 {{ detail.checkpoint_version ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="失败阶段">{{ detail.masked_log?.failure_stage || '—' }}</el-descriptions-item>
        <el-descriptions-item label="错误码">{{ detail.error_code || '—' }}</el-descriptions-item>
        <el-descriptions-item label="原因和建议">{{ syncError(detail.masked_error_message, detail.error_code) }}</el-descriptions-item>
      </el-descriptions>
      <div v-if="detail" class="detail-actions">
        <el-button @click="task(detail)">返回所属任务</el-button>
        <el-button @click="router.push('/integrations/incidents')">同步异常</el-button>
        <el-button @click="router.push({ path: '/integrations/sync-jobs', query: { sync_job_id: String(detail.sync_job_id) } })">查看任务及授权配置</el-button>
        <el-button v-if="detail.status === 'failed'" :disabled="!!retryReason" :title="retryReason" :loading="retrying" @click="retry">再次模拟执行（新记录）</el-button>
        <p v-if="detail.status === 'failed'">{{ retryReason || '将创建一次新的模拟运行，不覆盖历史记录。' }}</p>
      </div>
    </el-drawer>
  </section>
</template>
<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { fetchIntegrationWorkspace, retrySyncRun } from '../../api/integrations';
import { useAuthStore } from '../../stores/auth';
import { resources, runStates, schedules, syncTime, syncCount, syncError, syncCollectionDate } from '../../utils/syncPresentation';
const route = useRoute(), router = useRouter(), auth = useAuthStore();
const props = defineProps({ detailId: { type: [String, Number], default: '' } });
const rows = ref([]), options = ref({}), loading = ref(false), error = ref(''), page = ref(1), total = ref(0), dates = ref([]);
const drawer = ref(false), detail = ref(null), detailError = ref(''), retrying = ref(false);
const filters = reactive({ platform: '', subject_key: '', resource_type: '', status: '', trigger_type: '', run_id: '', sync_job_id: String(route.query.sync_job_id || '') });
const modeLabel = row => row.is_plan_only ? '未执行' : ({ live_readonly: '真实只读', simulation: '模拟' }[row.execution_mode] || '未记录');
const queueSeconds = row => row.enqueued_at && row.started_at ? `${Math.max(0, Math.round((new Date(row.started_at) - new Date(row.enqueued_at)) / 1000))} 秒` : '—';
const written = row => row.created_count == null || row.updated_count == null ? null : row.created_count + row.updated_count;
const retryReason = computed(() => !auth.hasPermission('integrations.run') ? '没有模拟运行权限。' : !detail.value?.job_enabled ? '所属任务已停用或状态未确认，请返回任务页核对。' : detail.value?.execution_mode !== 'simulation' || detail.value?.environment !== 'mock' || detail.value?.resource_type !== 'mock_record' ? '仅独立 Mock 任务可在此重试；真实运行请返回任务页重新确认。' : detail.value.retry_count >= detail.value.max_retry_count ? '已达到最大重试次数。' : '');
function task(row) { router.push({ path: '/integrations/sync-jobs', query: { sync_job_id: String(row.sync_job_id) } }); }
function open(row) { detail.value = row; detailError.value = ''; drawer.value = true; }
function search() { page.value = 1; load(); }
async function load() {
  if (loading.value) return;
  loading.value = true; error.value = '';
  try {
    const response = await fetchIntegrationWorkspace('sync-runs', { ...filters, run_pk: props.detailId || '', started_from: dates.value?.[0] || '', started_to: dates.value?.[1] || '', page: page.value, page_size: 50 });
    if (!response.success) throw new Error(response.message);
    rows.value = response.data.results || []; options.value = response.data.options || {};
    total.value = response.data.pagination?.total || 0; page.value = response.data.pagination?.page || 1;
    if ((props.detailId || route.query.detail) && !drawer.value) {
      const row = rows.value.find(item => String(item.id) === String(props.detailId || route.query.detail));
      if (row) open(row);
    }
  } catch (e) { error.value = syncError(e.message); }
  finally { loading.value = false; }
}
async function retry() {
  if (retrying.value || retryReason.value) return;
  retrying.value = true;
  try {
    await ElMessageBox.confirm('将创建一条新的模拟运行，不覆盖历史记录；后台仍会校验停用和安全规则。', '确认再次执行');
    const response = await retrySyncRun(detail.value.id);
    if (!response.success) throw new Error(response.message);
    ElMessage.success('已提交，请刷新核对新运行结果。'); drawer.value = false; await load();
  } catch (e) { if (e !== 'cancel' && e !== 'close') detailError.value = syncError(e.message); }
  finally { retrying.value = false; }
}
watch(() => route.query.sync_job_id, value => { filters.sync_job_id = String(value || ''); search(); });
onMounted(load);
</script>
<style scoped>
.run-records { display:grid; gap:16px; padding:20px; container:run-records / inline-size; } header { display:flex; justify-content:space-between; align-items:start; } h1 { margin:0; font-size:24px; } p { color:#64748b; font-size:13px; } .detail-actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:20px; }
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
