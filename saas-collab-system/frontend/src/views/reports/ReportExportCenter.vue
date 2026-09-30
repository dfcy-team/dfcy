<template>
  <section class="export-center">
    <header><div><h1>报表导出与下载审计</h1><p>查看本人导出任务，可按原筛选条件重新生成文件。</p></div><el-button @click="load">刷新</el-button></header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-form inline @submit.prevent="applyFilters">
      <el-form-item label="报表类型"><el-select v-model="typeFilter" clearable><el-option v-for="item in reportTypes" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
      <el-form-item label="状态"><el-select v-model="statusFilter" clearable><el-option label="已完成" value="completed"/><el-option label="已拒绝" value="rejected"/><el-option label="处理中" value="processing"/></el-select></el-form-item>
      <el-button type="primary" @click="applyFilters">查询</el-button><el-button @click="resetFilters">重置</el-button>
    </el-form>
    <el-table v-loading="loading" :data="rows" border empty-text="暂无导出任务">
      <el-table-column prop="id" label="导出编号" min-width="130"/><el-table-column label="报表类型" min-width="150"><template #default="{row}">{{ reportTypeLabel(row.report_type) }}</template></el-table-column>
      <el-table-column prop="status" label="状态"/><el-table-column prop="row_count" label="行数"/><el-table-column prop="requested_at" label="申请时间" min-width="180"/>
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
import { computed, onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useAuthStore } from '../../stores/auth';
import { createReportExport, downloadReportExport, downloadReportFile, fetchReportExports } from '../../api/reportExports';

const auth = useAuthStore();
const reportTypes = [
  { value: 'sales_details', label: '销售明细' }, { value: 'self_service', label: '自助报表' },
  ...['analytics_summary','inventory_alerts','replenishment','lifecycle','business_alerts','finance_summary'].map(value => ({ value, label: value }))
];
const reportTypeLabel = value => reportTypes.find(item => item.value === value)?.label || value || '-';
const canExport = computed(() => Boolean(auth.currentUser?.is_superuser || auth.hasPermission?.('reports.export') || auth.currentUser?.permissions?.includes('reports.export')));
const canDownload = computed(() => Boolean(auth.currentUser?.is_superuser || auth.hasPermission?.('reports.download') || auth.currentUser?.permissions?.includes('reports.download')));
const rows = ref([]), total = ref(0), page = ref(1), pageSize = ref(20), loading = ref(false), actionKey = ref(''), error = ref('');
const typeFilter = ref(''), statusFilter = ref('');
let sequence = 0;
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
  } catch (cause) { if (current === sequence) { error.value = cause?.message || '导出记录读取失败'; rows.value = []; total.value = 0; } }
  finally { if (current === sequence) loading.value = false; }
}
function applyFilters() { page.value = 1; load(); }
function resetFilters() { typeFilter.value = ''; statusFilter.value = ''; applyFilters(); }
function restart() { page.value = 1; load(); }
async function repeat(row) {
  if (!['sales_details','self_service'].includes(row.report_type)) return;
  actionKey.value = `again:${row.id}`; error.value = '';
  try { const result = await createReportExport({ report_type: row.report_type, filters: row.filters }); if (!result?.success) throw new Error(result?.message || '重新导出失败'); ElMessage.success(result.message || '已提交重新导出'); await load(); }
  catch (cause) { error.value = cause?.message || '重新导出失败'; } finally { actionKey.value = ''; }
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
  } catch (cause) { error.value = cause?.message || '文件下载失败'; } finally { actionKey.value = ''; }
}
onMounted(load);
</script>

<style scoped>
.export-center { display: grid; gap: 16px; }
header { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
h1 { margin:0; font-size:22px; } header p { margin:8px 0 0; color:#64748b; font-size:13px; }
</style>
