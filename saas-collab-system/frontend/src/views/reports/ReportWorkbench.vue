<template>
  <section class="report-workbench" :aria-busy="loading">
    <header>
      <div>
        <h1>{{ title || selected?.name || '自助报表' }}</h1>
        <p>{{ selected?.note || '选择授权数据集，调整维度、指标和展示方式。' }}</p>
      </div>
      <el-tag effect="plain">{{ loading ? '读取中' : result ? '业务数据' : '请选择报表' }}</el-tag>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-form label-position="top" class="report-editor" @submit.prevent="run">
      <el-form-item v-if="!dataset" label="数据集"
        ><el-select v-model="config.dataset" @change="chooseDataset"
          ><el-option
            v-for="item in datasets"
            :key="item.id"
            :label="`${item.module} · ${item.name}`"
            :value="item.id" /></el-select
      ></el-form-item>
      <el-form-item label="分组维度"
        ><el-select v-model="config.dimensions" multiple :multiple-limit="6" collapse-tags collapse-tags-tooltip
          ><el-option
            v-for="item in selected?.dimensions || []"
            :key="item.key"
            :label="item.label"
            :value="item.key" /></el-select
      ></el-form-item>
      <el-form-item label="指标"
        ><el-select v-model="config.metrics" multiple collapse-tags collapse-tags-tooltip
          ><el-option
            v-for="item in selected?.metrics || []"
            :key="item.key"
            :label="item.label"
            :value="item.key" /></el-select
      ></el-form-item>
      <el-form-item label="展示方式"
        ><el-select v-model="config.chart"
          ><el-option label="明细表" value="table" /><el-option label="柱状图" value="bar" /><el-option
            label="折线图"
            value="line" /><el-option label="透视表" value="pivot" /></el-select
      ></el-form-item>
      <el-form-item v-if="config.chart === 'pivot'" label="透视列"
        ><el-select v-model="config.pivot"
          ><el-option v-for="key in config.dimensions" :key="key" :label="label(key)" :value="key" /></el-select
      ></el-form-item>
      <el-form-item v-if="config.chart !== 'table'" label="图表 / 透视指标"
        ><el-select v-model="config.chart_metric"
          ><el-option v-for="key in config.metrics" :key="key" :label="label(key)" :value="key" /></el-select
      ></el-form-item>
      <el-form-item label="结果排序">
        <el-select v-model="config.ordering" clearable placeholder="按默认分组排序">
          <template v-for="key in [...config.dimensions,...config.metrics]" :key="key">
            <el-option :label="`${label(key)} · 升序`" :value="key" />
            <el-option :label="`${label(key)} · 降序`" :value="`-${key}`" />
          </template>
        </el-select>
      </el-form-item>
      <div class="editor-actions">
        <el-button type="primary" native-type="submit" :disabled="!selected" :loading="loading">查询</el-button
        ><el-button v-if="canSave" :disabled="!result || dirty || loading" @click="saveOpen = true">保存视图</el-button
        ><el-button
          v-if="canExport"
          :disabled="!result || dirty || loading || result.truncated"
          :loading="exporting"
          @click="exportResult"
          >导出已查询结果</el-button
        >
      </div>
    </el-form>
    <el-form v-if="selected" class="report-filters" inline>
      <el-form-item v-for="key in availableFilters" :key="key" :label="filterLabels[key]">
        <el-date-picker
          v-if="key.startsWith('date_')"
          v-model="config.filters[key]"
          value-format="YYYY-MM-DD"
          type="date"
          clearable
        />
        <el-input
          v-else
          v-model.trim="config.filters[key]"
          clearable
          :placeholder="key === 'currency' ? '如 PHP、CNY' : '全部'"
        />
      </el-form-item>
      <el-checkbox v-if="config.dataset.startsWith('inventory')" v-model="config.filters.include_virtual"
        >包含虚拟商品</el-checkbox
      >
    </el-form>
    <p v-if="dirty && result" class="note">配置已修改，点击查询后更新结果；保存、导出和穿透使用已查询条件。</p>
    <el-alert
      v-if="result?.truncated"
      :title="`分组结果超过 ${result.limit} 条，仅展示部分结果；请缩小范围后导出。`"
      type="warning"
      :closable="false"
    />
    <div v-if="result" v-loading="loading" class="report-results">
      <div class="result-meta">
        <span
          >{{ result.count }} 个分组 · {{ result.metric_version }} · {{ result.cached ? '缓存结果' : '本次计算' }}（最长
          {{ result.cache_seconds }} 秒）</span
        ><span>来源更新时间：{{ result.refreshed_at || '未提供' }}</span>
      </div>
      <p class="note">{{ result.note }} 点击分组可在有权限的业务页面核对明细。</p>
      <template v-if="applied.chart === 'pivot' && applied.pivot">
        <p class="note">透视表按原币分行，不跨币种汇总；选择一个指标查看。缺失单元格不补零。</p>
        <table class="pivot-table">
          <thead>
            <tr>
              <th>分组</th>
              <th v-for="value in pivot.headings" :key="value">{{ value }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in pivot.rows" :key="row.label">
              <th>{{ row.label }}</th>
              <td v-for="value in pivot.headings" :key="value">{{ formatCell(row.cells[value], displayMetric) }}</td>
            </tr>
          </tbody>
        </table>
      </template>
      <template v-else-if="['bar', 'line'].includes(applied.chart)">
        <p class="note">图表展示前 40 个分组，保留币种标签，缺失值不绘制。完整分组见下方明细表。</p>
        <svg
          v-if="result.rows.length"
          class="report-chart"
          viewBox="0 0 900 280"
          role="img"
          :aria-label="label(displayMetric)"
        >
          <line x1="45" y1="230" x2="890" y2="230" stroke="#cbd5e1" />
          <polyline
            v-for="(series, index) in applied.chart === 'line' ? chartSeries : []"
            :key="index"
            :points="series.map((p) => `${p.x},${p.y}`).join(' ')"
            fill="none"
            stroke="#5941c6"
            stroke-width="2"
          />
          <g v-for="(point, index) in chartPoints" :key="index">
            <rect
              v-if="applied.chart === 'bar'"
              :x="point.x - 7"
              :y="Math.min(point.y, 140)"
              width="14"
              :height="Math.max(1, Math.abs(140 - point.y))"
              fill="#6952d9"
            />
            <circle v-else :cx="point.x" :cy="point.y" r="3" fill="#5941c6" />
            <title>{{ point.label }}：{{ point.value }}</title>
            <text
              v-if="index % Math.ceil(chartPoints.length / 8) === 0"
              :x="point.x"
              y="252"
              text-anchor="middle"
              font-size="10"
            >
              {{ point.label.slice(0, 24) }}
            </text>
          </g>
          <line x1="45" y1="140" x2="890" y2="140" stroke="#94a3b8" stroke-dasharray="3 3" />
          <text x="8" y="144" font-size="11">0</text>
        </svg>
      </template>
      <el-table :data="result.rows" stripe max-height="620" @row-click="drill">
        <el-table-column
          v-for="column in result.columns"
          :key="column.key"
          :prop="column.key"
          :label="column.label"
          min-width="145"
          ><template #default="{ row }">{{ formatCell(row[column.key], column.key) }}</template></el-table-column
        >
      </el-table>
      <el-empty v-if="!result.rows.length" description="当前授权范围和筛选条件下暂无数据。" />
    </div>
    <el-empty v-else-if="!loading && !selected" description="当前角色没有可用数据集，请核对业务权限和数据范围。" />
    <el-dialog v-model="saveOpen" title="保存报表视图" width="min(440px, 92vw)"
      ><el-input v-model.trim="saveName" placeholder="视图名称" maxlength="100" />
      <p><el-checkbox v-model="shareView">共享给当前租户有对应业务权限的用户</el-checkbox></p>
      <p class="note">共享仅保存配置，每次打开按查看者的权限重新查询。</p>
      <template #footer><el-button :loading="saving" @click="save">保存</el-button></template></el-dialog
    >
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { canAccessPath } from '../../router/menu';
import { fetchReportDatasets, queryReport, saveReportView } from '../../api/reporting';
import { createReportExport } from '../../api/reportExports';
import { filterLabels, drillQuery, money, pivotRows, present } from './reportPresentation';
const props = defineProps({
  dataset: { type: String, default: '' },
  title: { type: String, default: '' },
  viewConfig: { type: Object, default: null }
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
const allowed = (code) => auth.currentUser?.is_superuser || auth.hasPermission?.(code);
const canSave = computed(() => allowed('reports.view'));
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
const availableFilters = computed(() => [
  ...(selected.value?.filters || []),
  ...(!config.dataset.startsWith('inventory') ? ['platforms', 'store_ids'] : [])
]);
const label = (key) =>
  [...(selected.value?.dimensions || []), ...(selected.value?.metrics || [])].find((item) => item.key === key)?.label ||
  key;
const formatCell = (value, key) =>
  selected.value?.metrics.find((item) => item.key === key)?.kind === 'money' ? money(value) : present(value);
const displayMetric = computed(() => applied.value?.chart_metric || applied.value?.metrics?.[0] || config.chart_metric);
const pivot = computed(() =>
  pivotRows(result.value?.rows || [], applied.value?.dimensions || [], applied.value?.pivot, displayMetric.value)
);
const chartPoints = computed(() => {
  const rows = (result.value?.rows || []).slice(0, 40);
  const valid = (row) =>
    row[displayMetric.value] != null &&
    row[displayMetric.value] !== '' &&
    Number.isFinite(Number(row[displayMetric.value]));
  const max = Math.max(1, ...rows.filter(valid).map((row) => Math.abs(Number(row[displayMetric.value]))));
  return rows.flatMap((row, i) =>
    valid(row)
      ? [
          {
            index: i,
            currency: row.currency,
            x: 60 + (i * 810) / Math.max(1, rows.length - 1),
            y: 140 - (Number(row[displayMetric.value]) / max) * 100,
            value: row[displayMetric.value],
            label: applied.value.dimensions.map((k) => present(row[k])).join(' · ')
          }
        ]
      : []
  );
});
const chartSeries = computed(() => {
  const series = [];
  for (const point of chartPoints.value) {
    const previous = series.at(-1)?.at(-1);
    if (!previous || previous.currency !== point.currency || previous.index + 1 !== point.index) series.push([]);
    series.at(-1).push(point);
  }
  return series;
});
function chooseDataset() {
  if (!selected.value) return;
  Object.assign(config, {
    dataset: selected.value.id,
    dimensions: [...selected.value.defaults.dimensions],
    metrics: [...selected.value.defaults.metrics],
    filters: {},
    chart: 'table',
    chart_metric: selected.value.defaults.metrics[0],
    pivot: '',
    ordering: ''
  });
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
  try {
    const response = await queryReport(snapshot, controller.signal);
    if (current !== sequence) return;
    if (!response.success) throw new Error(response.message);
    result.value = response.data;
    Object.assign(config, response.data.config);
    applied.value = JSON.parse(JSON.stringify(config));
  } catch (failure) {
    if (current === sequence) {
      result.value = null;
      applied.value = null;
      error.value = failure.message || '读取失败';
    }
  } finally {
    if (current === sequence) loading.value = false;
  }
}
function drill(row) {
  if (!applied.value || loading.value || dirty.value) return;
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
  saving.value = true;
  error.value = '';
  try {
    const response = await saveReportView({ name: saveName.value, config: applied.value, is_shared: shareView.value });
    if (!response.success) throw new Error(response.message);
    saveOpen.value = false;
    emit('saved');
  } catch (failure) {
    error.value = failure.message;
  } finally {
    saving.value = false;
  }
}
async function exportResult() {
  exporting.value = true;
  error.value = '';
  try {
    const response = await createReportExport({ report_type: 'self_service', filters: { config: applied.value } });
    if (!response.success) throw new Error(response.message);
    if (response.data.status === 'rejected') throw new Error('结果超过导出上限，请缩小范围。');
    router.push('/reports/exports');
  } catch (failure) {
    error.value = failure.message;
  } finally {
    exporting.value = false;
  }
}
async function initialize() {
  try {
    const response = await fetchReportDatasets();
    if (!response.success) throw new Error(response.message);
    datasets.value = response.data.datasets || [];
    config.dataset = props.dataset || props.viewConfig?.dataset || route.query.dataset || datasets.value[0]?.id || '';
    chooseDataset();
    if (props.viewConfig) Object.assign(config, JSON.parse(JSON.stringify(props.viewConfig)));
    else for (const key of availableFilters.value) if (route.query[key]) config.filters[key] = String(route.query[key]);
    if (selected.value) await run();
  } catch (failure) {
    error.value = failure.message;
  }
}
watch(
  () => props.viewConfig,
  (value) => {
    if (value) {
      Object.assign(config, JSON.parse(JSON.stringify(value)));
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
defineExpose({ config, run, drill, result });
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
