<template>
  <section class="analytics-page" :aria-busy="loading">
    <header class="analytics-header">
      <div>
        <p class="analytics-eyebrow">{{ eyebrow }}</p>
        <h1>{{ title }}</h1>
        <p class="analytics-subtitle">{{ subtitle }}</p>
      </div>
      <el-tag :type="statusTagType" effect="plain">{{ apiStatusLabel }}</el-tag>
    </header>

    <el-alert v-if="boundaryNote" :title="boundaryNote" type="warning" show-icon :closable="false" />

    <el-form class="analytics-filters" :model="query" inline @submit.prevent="loadData">
      <el-form-item v-for="filter in filters" :key="filter.key" :label="filter.label">
        <el-date-picker
          v-if="filter.type === 'daterange'"
          v-model="query[filter.key]"
          type="daterange"
          unlink-panels
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
        />
        <el-select v-else v-model="query[filter.key]" :placeholder="filter.placeholder || '全部'" clearable>
          <el-option v-for="option in filter.options || []" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </el-form-item>
    </el-form>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

    <div v-loading="loading" class="analytics-content">
      <section class="quality-rail" aria-label="数据可信度">
        <div>
          <span>数据可信度</span>
          <strong>{{ quality.score ?? '--' }}<small v-if="quality.score !== undefined">%</small></strong>
        </div>
        <el-progress :percentage="quality.score || 0" :stroke-width="8" :show-text="false" :status="qualityProgressStatus" />
        <dl>
          <div><dt>质量状态</dt><dd>{{ quality.status || 'unknown' }}</dd></div>
          <div><dt>口径版本</dt><dd>{{ quality.metric_version || '--' }}</dd></div>
          <div><dt>刷新时间</dt><dd>{{ quality.refreshed_at || '--' }}</dd></div>
        </dl>
      </section>

      <section v-if="metrics.length" class="metric-grid" aria-label="核心经营指标">
        <article v-for="metric in metrics" :key="metric.code" class="metric-card">
          <div class="metric-heading">
            <span>{{ metric.label }}</span>
            <el-tag size="small" effect="plain">{{ metric.code }}</el-tag>
          </div>
          <strong>{{ metric.value ?? 'N/A' }}<small>{{ metric.unit || '' }}</small></strong>
          <p :class="['metric-change', metric.change_direction]">
            {{ metric.change || '暂无对比数据' }}
          </p>
        </article>
      </section>

      <section v-if="trend.length" class="analytics-panel trend-panel">
        <div class="panel-heading">
          <div><h2>{{ trendTitle }}</h2><p>{{ trendNote }}</p></div>
          <span>{{ trendUnit }}</span>
        </div>
        <div class="bar-chart" role="img" :aria-label="trendTitle">
          <div v-for="point in trend" :key="point.label" class="bar-column">
            <span class="bar-value">{{ point.value }}</span>
            <div class="bar-track"><i :style="{ height: barHeight(point.value) }" /></div>
            <span>{{ point.label }}</span>
          </div>
        </div>
      </section>

      <section class="analytics-panel table-panel">
        <div class="panel-heading">
          <div><h2>{{ tableTitle }}</h2><p>{{ tableNote }}</p></div>
          <el-tag effect="plain">{{ items.length }} 条</el-tag>
        </div>
        <el-table :data="items" :empty-text="emptyText" stripe>
          <el-table-column
            v-for="column in columns"
            :key="column.prop"
            :prop="column.prop"
            :label="column.label"
            :min-width="column.width || 120"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              <el-tag v-if="column.type === 'status'" :type="statusType(row[column.prop])" effect="light">
                {{ row[column.prop] || '--' }}
              </el-tag>
              <span v-else>{{ formatValue(row[column.prop]) }}</span>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!loading && !errorMessage && !items.length" :description="emptyText" />
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { formatApiError } from '../api/request';

const props = defineProps({
  eyebrow: { type: String, default: 'Phase 3' },
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  boundaryNote: { type: String, default: '' },
  loader: { type: Function, required: true },
  filters: { type: Array, default: () => [] },
  columns: { type: Array, default: () => [] },
  trendTitle: { type: String, default: '趋势' },
  trendNote: { type: String, default: '' },
  trendUnit: { type: String, default: '' },
  tableTitle: { type: String, default: '明细' },
  tableNote: { type: String, default: '' },
  emptyText: { type: String, default: '当前筛选条件下暂无数据' }
});

const query = reactive({});
const loading = ref(false);
const errorMessage = ref('');
const apiStatus = ref('mock');
const quality = ref({});
const metrics = ref([]);
const trend = ref([]);
const items = ref([]);

const apiStatusLabel = computed(() => ({
  connected: 'API 已连接',
  fallback: 'API 异常 · Mock 回退',
  pending: 'API 待联调',
  mock: 'Mock 数据'
}[apiStatus.value] || apiStatus.value));
const statusTagType = computed(() => ({ connected: 'success', fallback: 'warning', pending: 'info', mock: 'info' }[apiStatus.value] || 'info'));
const qualityProgressStatus = computed(() => {
  if ((quality.value.score || 0) >= 95) return 'success';
  if ((quality.value.score || 0) < 80) return 'exception';
  return undefined;
});
const maxTrendValue = computed(() => Math.max(...trend.value.map((point) => Number(point.value) || 0), 1));

function initializeFilters() {
  props.filters.forEach((filter) => {
    query[filter.key] = filter.defaultValue ?? (filter.type === 'daterange' ? [] : '');
  });
}

function resetFilters() {
  initializeFilters();
  loadData();
}

function barHeight(value) {
  return `${Math.max(8, ((Number(value) || 0) / maxTrendValue.value) * 100)}%`;
}

function formatValue(value) {
  if (Array.isArray(value)) return value.join('、');
  if (value === true) return '是';
  if (value === false) return '否';
  return value ?? '--';
}

function statusType(value) {
  return {
    healthy: 'success',
    good: 'success',
    resolved: 'success',
    high: 'danger',
    critical: 'danger',
    failed: 'danger',
    medium: 'warning',
    warning: 'warning',
    pending: 'warning',
    low: 'info',
    unknown: 'info'
  }[value] || 'info';
}

async function loadData() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const response = await props.loader({ ...query });
    if (!response?.success) {
      apiStatus.value = 'pending';
      errorMessage.value = formatApiError(response);
      quality.value = {};
      metrics.value = [];
      trend.value = [];
      items.value = [];
      return;
    }
    const data = response.data || {};
    apiStatus.value = data.api_status || data.status || 'mock';
    quality.value = data.quality || {};
    metrics.value = Array.isArray(data.metrics) ? data.metrics : [];
    trend.value = Array.isArray(data.trend) ? data.trend : [];
    items.value = Array.isArray(data.results) ? data.results : (Array.isArray(data.items) ? data.items : []);
    if (data.api_status === 'fallback') errorMessage.value = response.message || data.api_error || '接口异常，已显示 Mock 数据';
  } catch (error) {
    apiStatus.value = 'pending';
    errorMessage.value = formatApiError(error?.response || { message: error?.message });
    quality.value = {};
    metrics.value = [];
    trend.value = [];
    items.value = [];
  } finally {
    loading.value = false;
  }
}

initializeFilters();
onMounted(loadData);
</script>

<style scoped>
.analytics-page { display: grid; gap: 16px; }
.analytics-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.analytics-eyebrow { margin: 0 0 6px; color: #64748b; font-size: 12px; font-weight: 700; text-transform: uppercase; }
.analytics-header h1 { margin: 0; color: #172033; font-size: 24px; letter-spacing: 0; }
.analytics-subtitle { margin: 7px 0 0; color: #64748b; font-size: 14px; }
.analytics-filters { padding: 12px 14px 0; border: 1px solid #dce3ec; border-radius: 8px; background: #fff; }
.analytics-filters :deep(.el-select) { width: 150px; }
.analytics-content { display: grid; gap: 16px; min-height: 220px; }
.quality-rail { display: grid; grid-template-columns: 150px minmax(180px, 1fr) minmax(420px, 1.6fr); align-items: center; gap: 20px; padding: 14px 16px; border: 1px solid #cfd9e6; border-left: 4px solid #0f766e; border-radius: 6px; background: #fff; }
.quality-rail > div:first-child { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; color: #475569; font-size: 13px; }
.quality-rail strong { color: #0f766e; font-size: 22px; }
.quality-rail small { font-size: 12px; }
.quality-rail dl { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 0; }
.quality-rail dl div { min-width: 0; }
.quality-rail dt { color: #7b8798; font-size: 12px; }
.quality-rail dd { margin: 3px 0 0; overflow: hidden; color: #273449; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.metric-card { min-width: 0; padding: 15px 16px; border: 1px solid #dce3ec; border-radius: 6px; background: #fff; }
.metric-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: #5f6f82; font-size: 13px; }
.metric-heading :deep(.el-tag) { max-width: 110px; overflow: hidden; text-overflow: ellipsis; }
.metric-card > strong { display: block; margin-top: 16px; color: #172033; font-size: 27px; font-variant-numeric: tabular-nums; }
.metric-card strong small { margin-left: 4px; color: #64748b; font-size: 13px; font-weight: 500; }
.metric-change { margin: 8px 0 0; color: #64748b; font-size: 12px; }
.metric-change.up { color: #047857; }
.metric-change.down { color: #b45309; }
.analytics-panel { padding: 16px; border: 1px solid #dce3ec; border-radius: 6px; background: #fff; }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.panel-heading h2 { margin: 0; color: #273449; font-size: 16px; }
.panel-heading p { margin: 5px 0 0; color: #7b8798; font-size: 12px; }
.panel-heading > span { color: #7b8798; font-size: 12px; }
.bar-chart { display: grid; grid-template-columns: repeat(auto-fit, minmax(48px, 1fr)); align-items: end; gap: 10px; min-height: 210px; padding-top: 22px; }
.bar-column { display: grid; grid-template-rows: 20px 150px 20px; gap: 5px; min-width: 0; color: #64748b; font-size: 11px; text-align: center; }
.bar-value { overflow: hidden; color: #334155; font-variant-numeric: tabular-nums; text-overflow: ellipsis; }
.bar-track { position: relative; overflow: hidden; border-radius: 3px 3px 0 0; background: #eef2f6; }
.bar-track i { position: absolute; right: 0; bottom: 0; left: 0; border-radius: 3px 3px 0 0; background: #2563eb; }
.table-panel :deep(.el-table) { width: 100%; }
.table-panel :deep(.el-empty) { display: none; }
@media (max-width: 1050px) {
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .quality-rail { grid-template-columns: 130px 1fr; }
  .quality-rail dl { grid-column: 1 / -1; }
}
@media (max-width: 720px) {
  .analytics-header { align-items: stretch; flex-direction: column; }
  .analytics-header :deep(.el-tag) { align-self: flex-start; }
  .analytics-filters { display: grid; }
  .analytics-filters :deep(.el-form-item) { margin-right: 0; }
  .analytics-filters :deep(.el-select), .analytics-filters :deep(.el-date-editor) { width: 100%; }
  .quality-rail, .metric-grid { grid-template-columns: 1fr; }
  .quality-rail dl { grid-template-columns: 1fr; }
}
</style>
