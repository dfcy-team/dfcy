<template>
  <section class="report-workbench" :aria-busy="loading">
    <header><div><h1>{{ title || selected?.name || '自助报表' }}</h1><p>先设置查询条件，再查看结果；需要自定义时调整字段和图表。</p></div>
      <el-tag effect="plain">{{ loading ? '读取中' : error ? '本次读取失败' : result ? '已查询' : '请选择报表' }}</el-tag>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-form class="query-panel" label-position="top" @submit.prevent="run">
      <div class="query-heading"><el-form-item v-if="!dataset" label="选择报表"><el-select v-model="config.dataset" @change="chooseDataset"><el-option v-for="item in datasets" :key="item.id" :label="`${item.module} · ${item.name}`" :value="item.id" /></el-select></el-form-item>
        <div class="query-summary"><span>分组：{{ config.dimensions.map(label).join('、') || '待选择' }}</span><span>指标：{{ config.metrics.map(label).join('、') || '待选择' }}</span></div>
        <el-button v-if="!businessMode" :disabled="!selected" :aria-expanded="designOpen" @click="designOpen = !designOpen">{{ designOpen ? '收起字段和图表' : '调整字段和图表' }}</el-button>
        <el-button v-else-if="canAccessPath(auth.currentUser, '/reports/basic')" :disabled="!selected" @click="openAnalysis">进入自助分析</el-button>
      </div>
      <div v-if="selected" class="report-filters">
        <el-form-item v-for="key in commonFilters" :key="key" :label="filterLabels[key] || '查询条件'"><ReportFilterControl v-model="config.filters[key]" :filter-key="key" :options="filterOptions(key)" /></el-form-item>
      </div>
      <details v-if="advancedFilters.length || visibleFilters.includes('include_virtual')" class="advanced-filters">
        <summary>更多筛选<span v-if="advancedActive"> · 已启用 {{ advancedActive }} 项</span></summary>
        <div class="report-filters"><el-form-item v-for="key in advancedFilters" :key="key" :label="filterLabels[key] || '查询条件'"><ReportFilterControl v-model="config.filters[key]" :filter-key="key" /></el-form-item>
          <el-checkbox v-if="visibleFilters.includes('include_virtual')" v-model="config.filters.include_virtual">包含虚拟商品</el-checkbox></div>
      </details>
      <div class="editor-actions"><el-button type="primary" native-type="submit" :disabled="!selected" :loading="loading">查询</el-button>
        <el-button :disabled="!selected || loading" @click="resetFilters">重置筛选</el-button>
        <el-button v-if="canSave" :disabled="!result || dirty || loading || !!error" @click="saveOpen = true">保存视图</el-button>
        <el-button v-if="canSave && savedView?.is_owner" :disabled="!result || dirty || loading || !!error" :loading="saving" @click="updateSavedView">更新当前视图版本</el-button>
        <el-button v-if="canExport" :disabled="!result || dirty || loading || !!error || result.truncated" :loading="exporting" @click="exportResult">导出已查询结果</el-button>
      </div>
    </el-form>
<div class="analysis-workspace" :class="{ 'is-editing': designOpen && selected }">
      <div v-if="designOpen && selected" class="analysis-designer" aria-label="字段与图表设置">
        <p class="note">拖动字段或使用添加按钮。点击查询后应用，收起侧栏会保留配置。</p>
        <ReportFieldDesigner :dataset="selected" :config="config" @change="applyFields" />
        <el-form class="report-editor" label-position="top">
          <el-form-item label="展示方式"><el-select v-model="config.chart"><el-option label="明细表" value="table" /><el-option label="柱状图" value="bar" /><el-option label="折线图" value="line" /><el-option label="透视表" value="pivot" /></el-select></el-form-item>
          <el-form-item v-if="config.chart === 'pivot' && !config.field_layout?.columns?.length" label="透视列"><el-select v-model="config.pivot"><el-option v-for="key in config.dimensions" :key="key" :label="label(key)" :value="key" /></el-select></el-form-item>
          <el-form-item v-if="config.chart !== 'table'" label="图表指标"><el-select v-model="config.chart_metric"><el-option v-for="key in config.metrics" :key="key" :label="label(key)" :value="key" /></el-select></el-form-item>
          <el-form-item label="结果排序"><el-select v-model="config.ordering" clearable placeholder="按默认分组排序"><template v-for="key in [...config.dimensions,...config.metrics]" :key="key"><el-option :label="`${label(key)} · 升序`" :value="key" /><el-option :label="`${label(key)} · 降序`" :value="`-${key}`" /></template></el-select></el-form-item>
        </el-form>
      </div>
<div class="analysis-canvas">
    <p v-if="dirty && result" role="status" class="dirty-note">条件已修改，点击查询后更新结果。保存、导出和穿透使用已查询条件。</p>
    <p v-if="error && result" role="status" class="dirty-note">保留上次成功结果及原查询范围。本次失败不能判断有无记录；请重试，当前不可保存、导出或穿透。</p>
    <div v-if="applied && result" class="applied-scope" aria-label="已查询范围"><strong>已查询范围</strong><span v-for="part in queryScope(applied)" :key="part">{{ part }}</span><small>{{ applied.dataset?.startsWith('inventory') ? '快照日期按协调世界时；不是收发存流水。' : ['sales','sales_skus','refunds'].includes(applied.dataset) ? '按门店当地业务日期；退款按申请日期归日。' : '流水日期按协调世界时；净流水不是利润。' }} 来源更新时间不代表完整采集。</small></div>
    <div v-if="qualityCards.length" class="quality-cards" aria-label="数据质量摘要"><button v-for="card in qualityCards" :key="card.label" type="button" :disabled="!card.filter || loading || dirty || !!error" @click="inspectQuality(card.filter)"><span>{{ card.label }}</span><strong>{{ card.value }}</strong><small>{{ card.note }}</small></button></div>
    <el-alert v-if="result?.truncated" :title="`分组结果超过 ${result.limit} 条，仅展示部分结果；请缩小范围后导出。`" type="warning" :closable="false" />
    <div v-if="result" v-loading="loading" class="report-results">
      <div class="result-meta"><h2>查询结果 <small>{{ result.count }} 个分组</small></h2><span>{{ result.cached ? '复用已授权结果' : '已更新' }} · 来源时间 {{ reportTimestamp(result.refreshed_at) }}（协调世界时）</span></div>
      <p class="note">点击分组查看有权限的业务明细。{{ selected?.note }}</p>
      <ReportResult :result="result" :config="applied" :dataset="selected" :can-investigate="canInvestigate && !dirty && !error && !loading" @drill="drill" @investigate="openInvestigation" />
    </div>
    <el-empty v-else-if="!loading && !error" :description="selected ? '设置条件后点击查询。' : '当前角色没有可用报表，请核对业务权限和数据范围。'" />
</div></div>
    <ReportExceptionAction v-if="canInvestigate && applied" v-model="exceptionOpen" :config="applied" :group="exceptionGroup" />
    <el-dialog v-model="saveOpen" title="保存报表视图" width="min(440px, 92vw)"><el-input v-model.trim="saveName" data-testid="report-view-name" placeholder="视图名称" maxlength="100" />
      <p><el-checkbox v-model="shareView">共享给当前租户有对应业务权限的用户</el-checkbox></p><p class="note">共享仅保存配置，每次打开按查看者的权限重新查询。</p>
      <template #footer><el-button :loading="saving" @click="save">保存</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { canAccessPath } from '../../router/menu';
import { fetchReportDatasets, queryReport, saveReportView } from '../../api/reporting';
import { createReportExport } from '../../api/reportExports';
import { filterLabels, drillQuery } from './reportPresentation';
import { datasetFilters, fieldLayout } from './biLayout';
import ReportFieldDesigner from './ReportFieldDesigner.vue';
import ReportResult from './ReportResult.vue';
import ReportFilterControl from './ReportFilterControl.vue';
import ReportExceptionAction from './ReportExceptionAction.vue';
import { reportError, reportTimestamp } from './reportDisplay';
import { reportResponseError, accessFailure, defaultReportFilters, queryScope, reportQuality } from './reportContext';
const props = defineProps({
  dataset: { type: String, default: '' },
  title: { type: String, default: '' },
  viewConfig: { type: Object, default: null },
  catalog: { type: Array, default: null },
  businessMode: { type: Boolean, default: false },
  savedView: { type: Object, default: null }
});
const emit = defineEmits(['saved']);
const auth = useAuthStore(),
  route = useRoute(),
  router = useRouter();
const config = reactive({
  dataset: props.dataset,
  dimensions: [],
  metrics: [],
  filters: {},
  chart: 'table',
  chart_metric: '',
  pivot: '',
  ordering: ''
});
const designOpen = ref(false);
const savedVersion = ref(props.savedView?.version);
watch(() => props.savedView, value => { savedVersion.value = value?.version; });
const datasets = ref([]),
  result = ref(null),
  applied = ref(null),
  loading = ref(false),
  error = ref(''),
  exporting = ref(false),
  saveOpen = ref(false),
  saveName = ref(''),
  shareView = ref(false),
  saving = ref(false);
let sequence = 0,
  controller;
const selected = computed(() => datasets.value.find((item) => item.id === config.dataset));
const qualityCards = computed(() => reportQuality(result.value, applied.value?.dataset));
const allowed = (code) => auth.currentUser?.is_superuser || auth.hasPermission?.(code);
const canSave = computed(() => allowed('reports.view'));
const canInvestigate = computed(() => allowed('workflow.exceptions.manage') && canAccessPath(auth.currentUser, '/workflow/exceptions'));
const exceptionOpen = ref(false), exceptionGroup = ref(null);
function openInvestigation(row) {
  if (!canInvestigate.value || dirty.value || loading.value || error.value) return;
  exceptionGroup.value = row; exceptionOpen.value = true;
}
const canExport = computed(
  () =>
    allowed('reports.export') &&
    (config.dataset.startsWith('finance') || config.dataset === 'inventory_value'
      ? allowed('finance.export')
      : config.dataset.startsWith('sales') || config.dataset === 'refunds'
        ? allowed('sales_management.export')
        : true)
);
const dirty = computed(() => applied.value && JSON.stringify(config) !== JSON.stringify(applied.value));
const availableFilters = computed(() => datasetFilters(selected.value));
const visibleFilters = computed(() => config.field_layout?.filters || availableFilters.value);
const primaryKeys = ['date_from', 'date_to', 'sku', 'sku_mode', 'store_id', 'warehouse_id', 'site_code', 'currency'];
const commonFilters = computed(() => primaryKeys.filter(key => visibleFilters.value.includes(key)));
const advancedFilters = computed(() => visibleFilters.value.filter(key => !primaryKeys.includes(key) && key !== 'include_virtual'));
const advancedActive = computed(() => [...advancedFilters.value, 'include_virtual'].filter(key => config.filters[key] !== '' && config.filters[key] != null && config.filters[key] !== false).length);
const filterOptions = key => Object.entries(result.value?.dimension_labels?.[key] || {}).map(([value, name]) => ({ value, label: `${name}（${value}）` }));
function resetFilters() { config.filters = defaultReportFilters(selected.value); }
const label = (key) =>
  [...(selected.value?.dimensions || []), ...(selected.value?.metrics || [])].find((item) => item.key === key)?.label ||
  key;
function applyFields(next) { Object.assign(config, next); }
function openAnalysis() {
  if (!selected.value || !canAccessPath(auth.currentUser, '/reports/basic')) return;
  const filters = applied.value?.dataset === config.dataset ? applied.value.filters : config.filters;
  router.push({ path: '/reports/basic', query: { tab: 'analysis', dataset: config.dataset, ...filters } });
}
async function updateSavedView() {
  if (!props.savedView?.is_owner || !canSave.value || !result.value || dirty.value || loading.value || error.value) return;
  saving.value = true;
  try {
    const response = await saveReportView({ name: props.savedView.name, config: applied.value, is_shared: props.savedView.is_shared, expected_version: savedVersion.value }, props.savedView.id);
    if (!response.success) throw reportResponseError(response);
    savedVersion.value = response.data.version;
    emit('saved');
  } catch (failure) { error.value = reportError(failure.message); }
  finally { saving.value = false; }
}
function chooseDataset() {
  sequence++;
  controller?.abort();
  loading.value = false;
  if (!selected.value) return;
  Object.assign(config, {
    dataset: selected.value.id,
    dimensions: [...selected.value.defaults.dimensions],
    metrics: [...selected.value.defaults.metrics],
    filters: defaultReportFilters(selected.value),
    chart: 'table',
    chart_metric: selected.value.defaults.metrics[0],
    pivot: '',
    ordering: ''
  });
  config.field_layout = fieldLayout({ ...config, field_layout: undefined }, selected.value);
  result.value = null;
  applied.value = null;
}
async function run() {
  const current = ++sequence;
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  error.value = '';
  if (!config.metrics.includes(config.chart_metric)) config.chart_metric = config.metrics[0];
  const snapshot = JSON.parse(JSON.stringify(config));
  snapshot.filters = Object.fromEntries(Object.entries(snapshot.filters).filter(([, v]) => v !== '' && v != null));
  if (snapshot.chart === 'pivot' && snapshot.pivot && !snapshot.field_layout.columns.length) {
    snapshot.field_layout.columns = [snapshot.pivot];
    snapshot.field_layout.rows = snapshot.dimensions.filter(key => key !== snapshot.pivot);
  }
  try {
    const response = await queryReport(snapshot, controller.signal);
    if (current !== sequence) return;
    if (!response.success) throw reportResponseError(response);
    result.value = response.data;
    Object.assign(config, response.data.config);
    applied.value = JSON.parse(JSON.stringify(config));
  } catch (failure) {
    if (current === sequence) {
      if (accessFailure(failure)) { result.value = null; applied.value = null; }
      error.value = reportError(failure.message);
    }
  } finally {
    if (current === sequence) loading.value = false;
  }
}
function drill(row) {
  if (!applied.value || loading.value || dirty.value || error.value) return;
  if (config.dataset === 'inventory_value' && !applied.value.dimensions.includes('sku')) {
    const filters = { ...applied.value.filters };
    for (const key of ['warehouse_id', 'site_code', 'currency']) if (row[key] != null) filters[key] = row[key];
    if (applied.value.dimensions.includes('currency') && row.currency == null) filters.cost_status = 'missing';
    Object.assign(config, {
      dimensions: ['warehouse_id', 'sku', 'currency'],
      metrics: ['on_hand', 'valued_count', 'missing_cost_count', 'inventory_value'],
      filters,
      chart: 'table',
      chart_metric: 'inventory_value',
      pivot: ''
    });
    config.field_layout = fieldLayout({ ...config, field_layout: undefined }, selected.value);
    run();
    return;
  }
  const path = selected.value.path;
  const query = drillQuery(config.dataset, row, applied.value);
  if (config.dataset.startsWith('inventory')) {
    query.as_of = 'true';
    query.warehouse = query.warehouse_id;
    if (config.dataset === 'inventory_value')
      query.valuation_at = query.date_to ? `${query.date_to}T23:59:59.999999Z` : result.value.computed_at;
  }
  if (canAccessPath(auth.currentUser, path)) router.push({ path, query });
}
async function save() {
  if (!result.value || dirty.value || loading.value || error.value) return;
  saving.value = true;
  error.value = '';
  try {
    const response = await saveReportView({ name: saveName.value, config: applied.value, is_shared: shareView.value });
    if (!response.success) throw reportResponseError(response);
    saveOpen.value = false;
    emit('saved');
  } catch (failure) {
    error.value = reportError(failure.message);
  } finally {
    saving.value = false;
  }
}
async function exportResult() {
  if (!result.value || dirty.value || loading.value || error.value || result.value.truncated) return;
  exporting.value = true;
  error.value = '';
  try {
    const response = await createReportExport({ report_type: 'self_service', filters: { config: applied.value } });
    if (!response.success) throw reportResponseError(response);
    if (response.data.status === 'rejected') throw new Error('结果超过导出上限，请缩小范围。');
    router.push('/reports/exports');
  } catch (failure) {
    error.value = reportError(failure.message);
  } finally {
    exporting.value = false;
  }
}
function inspectQuality(filters) {
  if (!filters || !applied.value || error.value || loading.value || dirty.value) return;
  config.filters = { ...applied.value.filters, ...filters };
  if (applied.value.dataset === 'finance') {
    config.dimensions = ['store_id', 'fee_category', 'fee_name', 'match_status', 'currency'];
    config.chart = 'table'; config.pivot = '';
    config.field_layout = fieldLayout({ ...config, field_layout: undefined }, selected.value);
  }
  run();
}
async function initialize() {
  try {
    const response = props.catalog ? { success: true, data: { datasets: props.catalog } } : await fetchReportDatasets();
    if (!response.success) throw reportResponseError(response);
    datasets.value = response.data.datasets || [];
    config.dataset = props.dataset || props.viewConfig?.dataset || route.query.dataset || datasets.value[0]?.id || '';
    chooseDataset();
    if (props.viewConfig) {
      Object.assign(config, JSON.parse(JSON.stringify(props.viewConfig)));
      config.field_layout = fieldLayout(props.viewConfig, selected.value);
    }
    else for (const key of availableFilters.value) if (route.query[key]) config.filters[key] = String(route.query[key]);
    if (selected.value) await run();
  } catch (failure) {
    error.value = reportError(failure.message);
  }
}
watch(
  () => props.viewConfig,
  (value) => {
    if (value) {
      Object.assign(config, JSON.parse(JSON.stringify(value)));
      config.field_layout = fieldLayout(value, selected.value);
      run();
    }
  }
);
watch(
  () => props.dataset,
  (value) => {
    config.dataset = value;
    chooseDataset();
    if (selected.value) run();
  }
);
watch(
  () => route.query,
  () => {
    if (!props.viewConfig && selected.value) {
      config.filters = {};
      for (const key of availableFilters.value) if (route.query[key]) config.filters[key] = String(route.query[key]);
      run();
    }
  }
);
onMounted(initialize);
watch(()=>[...config.dimensions,...config.metrics], fields=>{
  if(config.ordering && !fields.includes(config.ordering.replace(/^-/,'')))config.ordering='';
  if(config.pivot && !config.dimensions.includes(config.pivot))config.pivot='';
  if(!config.metrics.includes(config.chart_metric))config.chart_metric=config.metrics[0];
});
onBeforeUnmount(() => {
  sequence++;
  controller?.abort();
});
defineExpose({ config, run, drill, result, chooseDataset, resetFilters });
</script>
<style scoped>
.report-workbench {
  display: grid;
  gap: 16px;
  min-width: 0;
  color: #172033;
}
header,
.result-meta,
.editor-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
h1 {
  margin: 0;
  font-size: 24px;
}
header p,
.note,
.result-meta {
  font-size: 12px;
  color: #526177;
  line-height: 1.7;
}
.report-editor {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  background: white;
  padding: 16px;
  border: 1px solid #dce3ec;
  border-radius: 6px;
}
.report-editor :deep(.el-select) {
  width: 100%;
}
.editor-actions {
  grid-column: 1/-1;
  justify-content: flex-end;
}
.report-filters {
  padding: 12px;
  background: #f8fafc;
}
.report-filters :deep(.el-input) {
  max-width: 200px;
}
.report-filters :deep(.el-select) {
  width: 200px;
  max-width: 100%;
}
.report-results {
  display: grid;
  gap: 10px;
}
.report-chart {
  width: 100%;
  max-height: 340px;
  background: white;
}
.pivot-table {
  border-collapse: collapse;
  font-size: 12px;
  display: block;
  overflow: auto;
}
.pivot-table th,
.pivot-table td {
  border: 1px solid #dce3ec;
  padding: 10px;
  white-space: nowrap;
}
.pivot-table th {
  background: #f1f5f9;
}
.report-results :deep(.el-table__row) {
  cursor: pointer;
}
.report-editor,
.report-results {
  min-width: 0;
}
.note,
.result-meta {
  overflow-wrap: anywhere;
}
.editor-actions :deep(.el-button) {
  margin-left: 0;
}
@media (max-width: 600px) {
  .report-editor {
    grid-template-columns: minmax(0, 1fr);
  }
  .editor-actions {
    justify-content: flex-start;
  }
  .report-filters {
    display: grid;
    gap: 8px;
  }
  .report-filters :deep(.el-form-item) {
    display: block;
    margin-right: 0;
  }
  .report-filters :deep(.el-form-item__label) {
    display: block;
    text-align: left;
    height: auto;
  }
  .report-filters :deep(.el-input),
  .report-filters :deep(.el-date-editor) {
    width: 100%;
    max-width: 100%;
  }
}
</style>

<style scoped>
.query-panel { background: #fff; border: 1px solid #dce3ec; border-radius: 8px; padding: 18px; min-width: 0; }
.query-heading { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; border-bottom: 1px solid #edf0f5; margin-bottom: 16px; }
.query-heading :deep(.el-form-item) { min-width: 250px; }
.query-heading :deep(.el-select) { width: 100%; }
.query-summary { flex: 1; display: grid; gap: 5px; color: #627086; font-size: 12px; margin-bottom: 14px; }
.query-heading > :deep(.el-button) { margin-bottom: 14px; }
.report-filters { display: grid; grid-template-columns: repeat(auto-fit, minmax(185px, 1fr)); gap: 0 16px; padding: 0; background: transparent; }
.report-filters :deep(.el-form-item) { margin: 0 0 14px; min-width: 0; }
.report-filters :deep(.el-select), .report-filters :deep(.el-input), .report-filters :deep(.el-date-editor) { width: 100%; max-width: 100%; }
.advanced-filters { border-top: 1px solid #edf0f5; padding: 10px 0; margin-bottom: 8px; }
.advanced-filters summary { cursor: pointer; color: #526177; font-size: 13px; }
.advanced-filters[open] .report-filters { margin-top: 16px; }
.editor-actions { justify-content: flex-start; border-top: 1px solid #edf0f5; padding-top: 14px; }
.analysis-designer { padding: 16px 0; border-top: 1px solid #edf0f5; }
.report-results { background: #fff; border: 1px solid #dce3ec; border-radius: 8px; padding: 18px; }
.result-meta h2 { font-size: 17px; margin: 0; color: #172033; }
.result-meta small { font-size: 12px; color: #627086; margin-left: 8px; font-weight: 400; }
.dirty-note { background: #fff7e8; color: #8a570c; padding: 10px 14px; border-radius: 6px; margin: 0; font-size: 13px; }
@media (max-width: 600px) { .query-panel, .report-results { padding: 14px; } .query-heading { display: grid; } .query-heading :deep(.el-form-item) { min-width: 0; } .report-filters { grid-template-columns: minmax(0, 1fr); } }
</style>

<style scoped>
.analysis-workspace { display: grid; gap: 16px; min-width: 0; align-items: start; }
.analysis-workspace.is-editing { grid-template-columns: minmax(360px, 34%) minmax(0, 1fr); }
.analysis-canvas { display: grid; gap: 12px; min-width: 0; }
.analysis-designer { min-width: 0; max-height: 70vh; overflow: auto; padding: 14px; background: #fff; border: 1px solid #dce3ec; border-radius: 8px; }
.analysis-designer .report-editor { grid-template-columns: minmax(0, 1fr); padding: 8px 0; border: 0; }
.query-panel { padding: 12px 16px; }
.query-heading { margin-bottom: 10px; }
.report-filters { grid-template-columns: repeat(auto-fit, minmax(min(150px, 100%), 1fr)); gap: 0 12px; }
.report-filters :deep(.el-form-item) { margin-bottom: 10px; }
.applied-scope { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; padding: 12px 14px; border: 1px solid #dce3ec; background: #f8fafc; border-radius: 8px; font-size: 12px; color: #526177; overflow-wrap: anywhere; }
.applied-scope small { flex-basis: 100%; line-height: 1.6; }
.quality-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(160px, 100%), 1fr)); gap: 12px; }
.quality-cards button { display: grid; gap: 8px; padding: 14px; border: 1px solid #dce3ec; border-radius: 8px; text-align: left; background: #fff; color: #172033; font: inherit; cursor: pointer; }
.quality-cards button:disabled { opacity: 1; cursor: default; }
.quality-cards strong { font-size: 23px; font-variant-numeric: tabular-nums; }
.quality-cards small { font-size: 12px; color: #526177; }
@media(max-width: 700px) { .analysis-workspace.is-editing { grid-template-columns: minmax(0, 1fr); } .analysis-designer { max-height: 60vh; } .query-heading :deep(.el-form-item) { min-width: 0; width: 100%; } }
</style>

<style scoped>
.analysis-designer :deep(.field-designer) { grid-template-columns: minmax(140px, .85fr) minmax(175px, 1fr); gap: 10px; }
.analysis-designer :deep(.field-library) { max-height: 520px; }
.analysis-designer :deep(.field-zones) { width: 100%; }
</style>

<style scoped>@media (max-width: 700px) { .analysis-designer :deep(.field-designer) { grid-template-columns: minmax(0, 1fr); } .analysis-designer :deep(.field-library) { max-height: 240px; } }</style>
