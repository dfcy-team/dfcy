<template>
  <section class="decision-page" :aria-busy="loading">
    <header class="decision-header">
      <div><p>{{ eyebrow }}</p><h1>{{ title }}</h1><span>{{ subtitle }}</span></div>
      <el-tag effect="plain" :type="apiStatus === 'connected' ? 'success' : apiStatus === 'fallback' ? 'warning' : 'info'">
        {{ statusLabel }}
      </el-tag>
    </header>

    <el-alert :title="boundaryNote" type="warning" show-icon :closable="false" />

    <el-form class="decision-filters" inline @submit.prevent="loadData">
      <el-form-item v-for="filter in filters" :key="filter.key" :label="filter.label">
        <el-select v-model="query[filter.key]" clearable placeholder="全部">
          <el-option v-for="option in filter.options" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </el-form-item>
    </el-form>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

    <section class="decision-summary">
      <div v-for="item in summary" :key="item.label"><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div>
    </section>

    <section class="decision-table">
      <div class="table-heading"><div><h2>{{ tableTitle }}</h2><p>{{ tableNote }}</p></div><span>{{ items.length }} 条</span></div>
      <el-table v-loading="loading" :data="items" stripe :empty-text="emptyText">
        <el-table-column v-for="column in columns" :key="column.prop" :prop="column.prop" :label="column.label" :min-width="column.width || 120" show-overflow-tooltip>
          <template #default="{ row }">
            <el-progress v-if="column.type === 'confidence'" :percentage="Math.round((row[column.prop] || 0) * 100)" :stroke-width="7" />
            <el-tag v-else-if="column.type === 'status'" :type="tagType(row[column.prop])">{{ row[column.prop] || '--' }}</el-tag>
            <span v-else>{{ formatValue(row[column.prop]) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="rowActions.length" label="操作" :width="Math.max(150, rowActions.length * 92)" fixed="right">
          <template #default="{ row }">
            <el-button v-for="action in rowActions" :key="action.label" link :type="action.type || 'primary'" @click="handleAction(action, row)">
              {{ action.label }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !errorMessage && !items.length" :description="emptyText" />
    </section>

    <el-drawer v-model="drawerVisible" title="证据与审计信息" size="440px">
      <el-descriptions :column="1" border>
        <el-descriptions-item v-for="field in detailFields" :key="field.prop" :label="field.label">
          <pre v-if="field.type === 'json'">{{ JSON.stringify(selectedRow[field.prop] || {}, null, 2) }}</pre>
          <span v-else>{{ formatValue(selectedRow[field.prop]) }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-drawer>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';

const props = defineProps({
  eyebrow: { type: String, default: 'Phase 3' }, title: { type: String, required: true }, subtitle: { type: String, default: '' },
  boundaryNote: { type: String, required: true }, loader: { type: Function, required: true }, filters: { type: Array, default: () => [] },
  columns: { type: Array, default: () => [] }, rowActions: { type: Array, default: () => [] }, detailFields: { type: Array, default: () => [] },
  tableTitle: { type: String, default: '处理列表' }, tableNote: { type: String, default: '' }, emptyText: { type: String, default: '当前没有待处理数据' }
});

const query = reactive({});
const loading = ref(false);
const errorMessage = ref('');
const apiStatus = ref('mock');
const summary = ref([]);
const items = ref([]);
const selectedRow = ref({});
const drawerVisible = ref(false);
const statusLabel = computed(() => ({ connected: 'API 已连接', fallback: 'API 异常 · Mock 回退', pending: 'API 待联调', mock: 'Mock 数据' }[apiStatus.value] || apiStatus.value));

function initializeFilters() { props.filters.forEach((filter) => { query[filter.key] = ''; }); }
function resetFilters() { initializeFilters(); loadData(); }
function formatValue(value) { return Array.isArray(value) ? value.join('、') : value ?? '--'; }
function tagType(value) {
  return { high: 'danger', critical: 'danger', open: 'danger', medium: 'warning', pending: 'warning', in_progress: 'warning', low: 'info', acknowledged: 'info', resolved: 'success', confirmed: 'success', good: 'success' }[value] || 'info';
}

async function handleAction(action, row) {
  selectedRow.value = row;
  if (action.mode === 'detail') { drawerVisible.value = true; return; }
  if (action.confirmMessage) {
    try { await ElMessageBox.confirm(action.confirmMessage, action.confirmTitle || '人工确认提示', { type: 'warning' }); }
    catch (error) { if (error === 'cancel' || error === 'close') return; }
  }
  ElMessage.info(action.message || '该操作为阶段3占位，不会触发真实业务执行。');
}

async function loadData() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const response = await props.loader({ ...query });
    if (!response?.success) throw new Error(response?.message || '加载失败');
    const data = response.data || {};
    apiStatus.value = data.api_status || data.status || 'mock';
    summary.value = Array.isArray(data.summary) ? data.summary : [];
    items.value = Array.isArray(data.items) ? data.items : [];
    if (data.api_status === 'fallback') errorMessage.value = response.message || data.api_error || '接口异常，已显示 Mock 数据';
  } catch (error) {
    apiStatus.value = 'pending'; summary.value = []; items.value = []; errorMessage.value = error?.message || '加载失败';
  } finally { loading.value = false; }
}

initializeFilters();
onMounted(loadData);
</script>

<style scoped>
.decision-page { display: grid; gap: 16px; }
.decision-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.decision-header p { margin: 0 0 6px; color: #64748b; font-size: 12px; font-weight: 700; text-transform: uppercase; }
.decision-header h1 { margin: 0; color: #172033; font-size: 24px; letter-spacing: 0; }
.decision-header span { display: block; margin-top: 7px; color: #64748b; font-size: 14px; }
.decision-filters { padding: 12px 14px 0; border: 1px solid #dce3ec; border-radius: 8px; background: #fff; }
.decision-filters :deep(.el-select) { width: 160px; }
.decision-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); border: 1px solid #dce3ec; border-radius: 6px; background: #fff; }
.decision-summary div { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; padding: 14px 16px; border-right: 1px solid #e7ecf2; }
.decision-summary div:last-child { border-right: 0; }
.decision-summary span { color: #64748b; font-size: 13px; }
.decision-summary strong { color: #172033; font-size: 22px; }
.decision-table { padding: 16px; border: 1px solid #dce3ec; border-radius: 6px; background: #fff; }
.table-heading { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.table-heading h2 { margin: 0; color: #273449; font-size: 16px; }
.table-heading p, .table-heading > span { margin: 5px 0 0; color: #7b8798; font-size: 12px; }
.decision-table :deep(.el-empty) { display: none; }
pre { max-height: 300px; margin: 0; overflow: auto; font-size: 12px; white-space: pre-wrap; }
@media (max-width: 720px) {
  .decision-header { flex-direction: column; }
  .decision-filters { display: grid; }
  .decision-filters :deep(.el-form-item) { margin-right: 0; }
  .decision-filters :deep(.el-select) { width: 100%; }
  .decision-summary { grid-template-columns: 1fr 1fr; }
}
</style>
