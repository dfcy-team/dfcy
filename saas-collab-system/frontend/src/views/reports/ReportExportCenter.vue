<template>
  <section class="export-center">
    <header><div><h1>报表导出与下载审计</h1><p>查看本人导出任务，可按原筛选条件重新生成文件。</p></div><el-button @click="load">刷新</el-button></header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-card v-if="exportJobs.length" class="job-panel" shadow="never">
      <template #header><div class="job-heading"><strong>后台导出任务</strong><el-button link @click="refreshJobs">刷新状态</el-button></div></template>
      <div v-for="job in exportJobs" :key="job.id" class="job-row">
        <span>任务 #{{ job.id }} · {{ reportTypeLabel(job.report_type) }} · {{ statusLabel(job.status) }}</span>
        <span v-if="job.error" class="job-error">{{ job.error }}</span>
        <span v-else-if="job.export?.status === 'rejected'" class="job-error">导出结果超过现有行数上限，已拒绝。</span>
        <span class="job-actions">
          <el-button link type="primary" :loading="jobAction === `refresh:${job.id}`" @click="refreshJob(job)">查询状态</el-button>
          <el-button v-if="['queued','running'].includes(job.status)" link type="danger" :loading="jobAction === `cancel:${job.id}`" @click="cancelJob(job)">取消</el-button>
        </span>
      </div>
    </el-card>
    <el-form inline @submit.prevent="applyFilters">
      <el-form-item label="报表类型"><el-select v-model="typeFilter" clearable><el-option v-for="item in reportTypes" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
      <el-form-item label="状态"><el-select v-model="statusFilter" clearable><el-option label="已完成" value="completed"/><el-option label="已拒绝" value="rejected"/><el-option label="处理中" value="processing"/></el-select></el-form-item>
      <el-button type="primary" @click="applyFilters">查询</el-button><el-button @click="resetFilters">重置</el-button>
    </el-form>
    <el-table v-loading="loading" :data="rows" border empty-text="暂无导出任务">
      <el-table-column prop="id" label="导出编号" min-width="130"/><el-table-column label="报表类型" min-width="150"><template #default="{row}">{{ reportTypeLabel(row.report_type) }}</template></el-table-column>
      <el-table-column label="状态"><template #default="{row}">{{ statusLabel(row.status) }}</template></el-table-column><el-table-column prop="row_count" label="行数"/><el-table-column label="申请时间" min-width="180"><template #default="{row}">{{ formatDate(row.requested_at) }}</template></el-table-column>
      <el-table-column label="文件" min-width="120"><template #default="{row}">{{ row.has_file ? (row.filename || '可下载') : '历史记录（无文件）' }}</template></el-table-column>
      <el-table-column label="操作" fixed="right" min-width="180"><template #default="{row}">
        <el-button v-if="canExport" link type="primary" :disabled="!['sales_details','self_service'].includes(row.report_type)" :loading="actionKey === `again:${row.id}`" @click="repeat(row)">再次导出</el-button>
        <el-button v-if="canDownload" link type="primary" :disabled="!row.has_file || row.status !== 'completed'" :loading="actionKey === `download:${row.id}`" @click="download(row)">下载文件</el-button>
      </template></el-table-column>
    </el-table>
    <el-pagination v-if="total" v-model:current-page="page" v-model:page-size="pageSize" :total="total" layout="total, sizes, prev, pager, next" :page-sizes="[10,20,50]" @current-change="load" @size-change="restart" />
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useAuthStore } from '../../stores/auth';
import { cancelReportExportJob, createReportExportJob, downloadReportExport, downloadReportFile, fetchReportExportJob, fetchReportExportJobs, fetchReportExports } from '../../api/reportExports';
import { reportError, reportTimestamp } from './reportDisplay';

const auth = useAuthStore();
const reportTypes = [
  { value: 'sales_details', label: '销售明细' }, { value: 'self_service', label: '自助报表' },
  { value: 'analytics_summary', label: '经营分析汇总' }, { value: 'inventory_alerts', label: '库存预警' },
  { value: 'replenishment', label: '补货建议' }, { value: 'lifecycle', label: '商品生命周期' },
  { value: 'business_alerts', label: '经营预警' }, { value: 'finance_summary', label: '财务汇总' }
];
const reportTypeLabel = value => reportTypes.find(item => item.value === value)?.label || (value ? '其他报表' : '未注明');
const statusLabels = { completed: '已完成', rejected: '已拒绝', processing: '处理中', pending: '排队中', queued: '排队中', running: '处理中', expired: '已过期', failed: '失败', cancelled: '已取消' };
const statusLabel = value => statusLabels[value] || (value ? '其他状态' : '未知状态');
const formatDate = reportTimestamp;
const canExport = computed(() => Boolean(auth.currentUser?.is_superuser || auth.hasPermission?.('reports.export') || auth.currentUser?.permissions?.includes('reports.export')));
const canDownload = computed(() => Boolean(auth.currentUser?.is_superuser || auth.hasPermission?.('reports.download') || auth.currentUser?.permissions?.includes('reports.download')));
const rows = ref([]), total = ref(0), page = ref(1), pageSize = ref(20), loading = ref(false), actionKey = ref(''), error = ref('');
const exportJobs = ref([]), jobAction = ref('');
const typeFilter = ref(''), statusFilter = ref('');
let sequence = 0;
let pollTimer;
let jobsRefreshing = false, disposed = false;
const POLL_INTERVAL_MS=4000, MAX_POLL_MS=300000, MAX_POLL_FAILURES=3;
let pollStartedAt=null, pollFailures=0, pollStopped=false;
const jobRequests=new Set();
function stopPolling(message){if(pollTimer)clearTimeout(pollTimer);pollTimer=null;pollStopped=true;if(message&&!disposed)error.value=message;}
function resumePolling(){if(pollTimer)clearTimeout(pollTimer);pollTimer=null;pollStartedAt=Date.now();pollFailures=0;pollStopped=false;}
function schedulePoll(){
  if(disposed||pollStopped||pollTimer||jobsRefreshing)return;
  if(!exportJobs.value.some(item=>['queued','running'].includes(item.status))){pollStartedAt=null;pollFailures=0;return;}
  if(pollStartedAt===null)pollStartedAt=Date.now();
  const remaining=MAX_POLL_MS-(Date.now()-pollStartedAt);
  if(remaining<=0){stopPolling('自动检查已暂停，请点击“查询状态”手动恢复。');return;}
  pollTimer=setTimeout(()=>{pollTimer=null;refreshJobs(false);},Math.min(POLL_INTERVAL_MS,remaining));
}
function accessFailure(value){return [401,403].includes(value?.http_status??value?.response?.status)||['PERMISSION_DENIED','AUTH_REQUIRED','FORBIDDEN'].includes(value?.code);}
async function load() {
  const current = ++sequence; loading.value = true; error.value = '';
  const params = { page: page.value, page_size: pageSize.value };
  if (typeFilter.value) params.report_type = typeFilter.value;
  if (statusFilter.value) params.status = statusFilter.value;
  try {
    const response = await fetchReportExports(params);
    if (current !== sequence) return;
    if (!response?.success) throw new Error(response?.message || '导出记录读取失败');
    rows.value = Array.isArray(response.data?.results) ? response.data.results : [];
    total.value = Number(response.data?.count ?? rows.value.length);
  } catch (cause) { if (current === sequence) { error.value = reportError(cause?.message, '导出记录读取失败，请稍后重试。'); rows.value = []; total.value = 0; } }
  finally { if (current === sequence) loading.value = false; }
}
function applyFilters() { page.value = 1; load(); }
function resetFilters() { typeFilter.value = ''; statusFilter.value = ''; applyFilters(); }
function restart() { page.value = 1; load(); }
async function repeat(row) {
  if (!['sales_details','self_service'].includes(row.report_type)) return;
  actionKey.value = `again:${row.id}`; error.value = '';
  try {
    const result = await createReportExportJob({ report_type: row.report_type, filters: row.filters });
    if (!result?.success) throw new Error(result?.message || '重新导出失败');
    resumePolling();upsertJob({ ...result.data, report_type: row.report_type });
    ElMessage.success('已提交后台导出任务');
  }
  catch (cause) { error.value = reportError(cause?.message, '重新导出失败，请稍后重试。'); } finally { actionKey.value = ''; }
}
function upsertJob(job) {
  if (disposed) return;
  const index = exportJobs.value.findIndex(item => String(item.id) === String(job.id));
  if (index < 0) exportJobs.value.unshift(job); else exportJobs.value[index] = { ...exportJobs.value[index], ...job };
  if (!exportJobs.value.some(item => ['queued','running'].includes(item.status)) && pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  schedulePoll();
}
async function refreshJob(job, automatic=false) {
  if(disposed||jobRequests.has(String(job.id)))return true;
  if(!automatic)resumePolling();
  jobRequests.add(String(job.id));
  jobAction.value = `refresh:${job.id}`;
  try {
    const response = await fetchReportExportJob(job.id);
    if (disposed) return;
    if (!response?.success) {if(accessFailure(response))stopPolling('授权已变化，自动检查已停止；请确认权限后手动查询。');throw new Error(response?.message || '任务状态读取失败');}
    upsertJob({ ...response.data, report_type: job.report_type });
    if (['completed','failed','cancelled','expired'].includes(response.data?.status)) await load();
    return true;
  } catch (cause) {if(accessFailure(cause))stopPolling('授权已变化，自动检查已停止；请确认权限后手动查询。');if(!disposed&&!pollStopped)error.value = reportError(cause?.message, '任务状态读取失败，请稍后重试。');return false;}
  finally {jobRequests.delete(String(job.id));jobAction.value = '';if(!automatic)schedulePoll();}
}
async function refreshJobs(manual=true) {
  if (jobsRefreshing || disposed) return;
  if(manual!==false)resumePolling();
  if(pollStopped)return;
  if(pollStartedAt!==null&&Date.now()-pollStartedAt>=MAX_POLL_MS){stopPolling('自动检查已暂停，请点击“查询状态”手动恢复。');return;}
  jobsRefreshing = true;
  let successful=true;
  try {for(const job of exportJobs.value.filter(item=>['queued','running'].includes(item.status))){if(disposed||pollStopped)break;if(!await refreshJob(job,true))successful=false;}
    pollFailures=successful?0:pollFailures+1;
    if(pollFailures>=MAX_POLL_FAILURES)stopPolling('连续读取失败，自动检查已暂停；可点击“查询状态”手动恢复。');
  }finally{jobsRefreshing=false;schedulePoll();}
}
async function cancelJob(job) {
  jobAction.value = `cancel:${job.id}`;
  try {
    const response = await cancelReportExportJob(job.id);
    if (!response?.success) throw new Error(response?.message || '取消任务失败');
    upsertJob({ ...response.data, report_type: job.report_type });
    ElMessage.success('后台导出任务已取消');
    await load();
  } catch (cause) { error.value = reportError(cause?.message, '取消任务失败，请稍后重试。'); }
  finally { jobAction.value = ''; }
}
async function download(row) {
  if (!row.has_file || row.status !== 'completed') return;
  actionKey.value = `download:${row.id}`; error.value = '';
  try {
    const result = await downloadReportExport(row.id);
    if (!result?.success) throw new Error(result?.message || '下载授权失败');
    const reference = result.data?.download_reference;
    if (typeof reference !== 'string' || !reference.startsWith('/api/report/exports/')) throw new Error('服务端返回了无效的下载引用');
    const saved = await downloadReportFile(reference, row.filename || 'report-export.csv');
    if (!saved?.success) throw new Error(saved?.message || '文件下载失败');
  } catch (cause) { error.value = reportError(cause?.message, '文件下载失败，请稍后重试。'); } finally { actionKey.value = ''; }
}
onMounted(async () => {
  load();
  if (!canExport.value) return;
  try { const response = await fetchReportExportJobs(); if (!disposed && response.success) for (const job of response.data || []) upsertJob(job); }
  catch (cause) { if (!disposed) error.value = reportError(cause.message); }
});
onUnmounted(() => { disposed = true; sequence++; if (pollTimer) clearTimeout(pollTimer); });
</script>

<style scoped>
.export-center { display: grid; gap: 16px; }
.job-panel { border-color: #dbeafe; }
.job-heading, .job-row, .job-actions { display: flex; align-items: center; gap: 12px; }
.job-heading, .job-row { justify-content: space-between; }
.job-row { flex-wrap: wrap; padding: 8px 0; border-bottom: 1px solid #eef2f7; font-size: 13px; }
.job-row:last-child { border-bottom: 0; }
.job-error { color: #b91c1c; }
.export-center :deep(.el-select) { width: 210px; max-width: 100%; }
@media (max-width: 640px) { .export-center :deep(.el-form--inline .el-form-item) { display: flex; margin-right: 0; }.export-center :deep(.el-form-item__content) { min-width: 0; flex: 1; }.export-center :deep(.el-select) { width: 100%; } }
header { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
h1 { margin:0; font-size:22px; } header p { margin:8px 0 0; color:#64748b; font-size:13px; }
</style>
