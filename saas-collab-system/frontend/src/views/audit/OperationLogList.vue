<template>
  <AppPage
    eyebrow="SYSTEM GOVERNANCE"
    title="日志审计"
    subtitle="按租户和授权数据范围查看不可变操作记录。"
    boundary-note="审计详情只展示脱敏后的变更摘要；密码、Token、Cookie、Session、密钥和连接串不会在页面或导出文件中出现。"
    :capability="capability"
  >
    <template #action>
      <el-button v-if="canExport" type="primary" :loading="exporting" @click="exportRows">导出 CSV</el-button>
    </template>

    <AppState v-if="state === 'loading'" :status="state" :detail="errorMessage" @action="handleStateAction" />
    <template v-else>
      <el-form class="filters" inline @submit.prevent="query">
        <el-form-item label="操作人">
          <el-input v-model="filters.operator" clearable placeholder="用户名或操作人 ID" @keyup.enter="query" />
        </el-form-item>
        <el-form-item label="模块">
          <el-input v-model="filters.module" clearable placeholder="模块编码" @keyup.enter="query" />
        </el-form-item>
        <el-form-item label="动作">
          <el-input v-model="filters.action" clearable placeholder="动作编码" @keyup.enter="query" />
        </el-form-item>
        <el-form-item label="对象 ID">
          <el-input v-model="filters.object_id" clearable placeholder="对象 ID" @keyup.enter="query" />
        </el-form-item>
        <el-form-item label="起始时间">
          <el-input v-model="filters.created_from" clearable placeholder="YYYY-MM-DD" @keyup.enter="query" />
        </el-form-item>
        <el-form-item label="结束时间">
          <el-input v-model="filters.created_to" clearable placeholder="YYYY-MM-DD" @keyup.enter="query" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="query">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>

      <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="handleStateAction" />
      <template v-else>
        <el-alert v-if="exportMessage" class="notice" :title="exportMessage" :type="exportFailed ? 'error' : 'success'" :closable="false" />
        <el-alert v-if="listError" class="notice" :title="listError" type="error" :closable="false" />

        <el-table class="logs-table" :data="rows" border empty-text="当前范围暂无操作日志" @row-click="openDetail">
          <el-table-column prop="id" label="编号" width="84" />
          <el-table-column label="操作人" min-width="160">
            <template #default="{ row }">{{ row.operator_name || row.operator || '系统' }}</template>
          </el-table-column>
          <el-table-column prop="module" label="模块" min-width="130" />
          <el-table-column prop="action" label="动作" min-width="190" show-overflow-tooltip />
          <el-table-column prop="object_type" label="对象类型" min-width="130" />
          <el-table-column prop="object_id" label="对象 ID" min-width="120" />
          <el-table-column prop="ip_address" label="IP" min-width="140" />
          <el-table-column prop="created_at" label="时间" min-width="190" />
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }"><el-button link type="primary" @click.stop="openDetail(row)">详情</el-button></template>
          </el-table-column>
        </el-table>

        <el-pagination
          v-if="total"
          class="pager"
          background
          layout="total, sizes, prev, pager, next"
          :page-sizes="[20, 50, 100]"
          :page-size="pageSize"
          :current-page="page"
          :total="total"
          @current-change="changePage"
          @size-change="changePageSize"
        />

        <el-drawer v-model="detailOpen" title="操作日志详情" size="min(680px, 94vw)" @closed="closeDetail">
          <AppState v-if="detailState" :status="detailState" :detail="detailError" @action="closeDetail" />
          <template v-else-if="detail">
            <el-descriptions :column="1" border>
              <el-descriptions-item label="操作人">{{ detail.operator_name || detail.operator || '系统' }}</el-descriptions-item>
              <el-descriptions-item label="模块 / 动作">{{ detail.module }} / {{ detail.action }}</el-descriptions-item>
              <el-descriptions-item label="对象">{{ detail.object_type || '-' }} / {{ detail.object_id || '-' }}</el-descriptions-item>
              <el-descriptions-item label="IP / 时间">{{ detail.ip_address || '-' }} / {{ detail.created_at }}</el-descriptions-item>
            </el-descriptions>
            <section class="change-section">
              <h3>变更前（脱敏）</h3>
              <pre>{{ stringify(detail.before_data) }}</pre>
            </section>
            <section class="change-section">
              <h3>变更后（脱敏）</h3>
              <pre>{{ stringify(detail.after_data) }}</pre>
            </section>
          </template>
        </el-drawer>
      </template>
    </template>
  </AppPage>
</template>

<script setup>
import { computed, ref } from 'vue';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import { exportOperationLogs, fetchOperationLog, fetchOperationLogs } from '../../api/audit';
import { useAuthStore } from '../../stores/auth';
import { statusFromApiResponse } from '../../utils/uiState';

const auth = useAuthStore();
const canExport = computed(() => auth.hasPermission('audit.operation_logs.export'));
const state = ref('loading');
const capability = ref(import.meta.env.PROD ? 'pending' : 'mock');
const errorMessage = ref('');
const listError = ref('');
const detailError = ref('');
const detailState = ref('');
const exportMessage = ref('');
const exportFailed = ref(false);
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const exporting = ref(false);
const detailOpen = ref(false);
const detail = ref(null);
const filters = ref({
  operator: '',
  module: '',
  action: '',
  object_id: '',
  created_from: '',
  created_to: ''
});
let loadSequence = 0;
let detailSequence = 0;

const online = () => (typeof navigator === 'undefined' ? true : navigator.onLine);
const activeFilters = () => Object.fromEntries(
  Object.entries(filters.value).filter(([, value]) => String(value || '').trim())
);

async function load() {
  const sequence = ++loadSequence;
  state.value = 'loading';
  errorMessage.value = '';
  listError.value = '';
  let response;
  try {
    response = await fetchOperationLogs({ ...activeFilters(), page: page.value, page_size: pageSize.value });
  } catch (error) {
    if (sequence !== loadSequence) return;
    state.value = 'error';
    errorMessage.value = error?.message || '日志审计请求失败，请稍后重试。';
    capability.value = 'degraded';
    return;
  }
  if (sequence !== loadSequence) return;
  if (!response.success) {
    state.value = statusFromApiResponse(response, online());
    errorMessage.value = response.message;
    capability.value = response.http_status ? 'pending' : 'degraded';
    return;
  }
  const data = response.data || {};
  rows.value = Array.isArray(data) ? data : (data.results || data.items || []);
  total.value = Array.isArray(data) ? data.length : Number(data.count || rows.value.length);
  capability.value = data.api_status || data.status || (import.meta.env.PROD ? 'connected' : 'mock');
  state.value = rows.value.length ? 'ready' : 'empty';
}

function query() {
  page.value = 1;
  load();
}

function resetFilters() {
  filters.value = { operator: '', module: '', action: '', object_id: '', created_from: '', created_to: '' };
  query();
}

function handleStateAction() {
  if (state.value === 'empty') resetFilters();
  else load();
}

function changePage(value) {
  page.value = value;
  load();
}

function changePageSize(value) {
  pageSize.value = value;
  page.value = 1;
  load();
}

async function openDetail(row) {
  const sequence = ++detailSequence;
  detail.value = null;
  detailError.value = '';
  detailState.value = '';
  detailOpen.value = true;
  let response;
  try {
    response = await fetchOperationLog(row.id);
  } catch (error) {
    if (sequence !== detailSequence) return;
    detailState.value = 'error';
    detailError.value = error?.message || '日志详情请求失败，请稍后重试。';
    return;
  }
  if (sequence !== detailSequence || !detailOpen.value) return;
  if (!response.success) {
    detailState.value = statusFromApiResponse(response, online());
    detailError.value = response.message;
    return;
  }
  detail.value = response.data;
}

function closeDetail() {
  detailSequence += 1;
  detailOpen.value = false;
  detail.value = null;
  detailState.value = '';
  detailError.value = '';
}

function stringify(value) {
  if (value === undefined || value === null) return '{}';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch (_error) {
    return String(value);
  }
}

async function exportRows() {
  if (!canExport.value || exporting.value) return;
  exporting.value = true;
  exportMessage.value = '';
  exportFailed.value = false;
  try {
    const response = await exportOperationLogs(activeFilters());
    if (response.success) exportMessage.value = response.message || '导出已开始。';
    else {
      exportFailed.value = true;
      exportMessage.value = response.message || '导出失败，请稍后重试。';
    }
  } catch (error) {
    exportFailed.value = true;
    exportMessage.value = error?.message || '导出失败，请稍后重试。';
  } finally {
    exporting.value = false;
  }
}

load();
</script>

<style scoped>
.filters { padding: 14px 16px 4px; border: 1px solid #dbe3ec; border-radius: 8px; background: #fff; }
.filters :deep(.el-form-item) { margin-bottom: 10px; }
.filters :deep(.el-input) { width: 170px; }
.notice { margin: 14px 0; }
.logs-table { margin-top: 14px; cursor: pointer; }
.pager { justify-content: flex-end; margin-top: 16px; }
.change-section { margin-top: 18px; }
.change-section h3 { margin: 0 0 8px; color: #25324b; font-size: 14px; }
pre { max-height: 260px; margin: 0; padding: 12px; overflow: auto; border: 1px solid #e5eaf0; border-radius: 6px; background: #f8fafc; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, monospace; }
@media (max-width: 720px) {
  .filters :deep(.el-input) { width: 100%; }
}
</style>
