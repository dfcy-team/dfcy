<template>
  <section :class="['analytics-page', { 'is-operating': presentation === 'operating' }]" :aria-busy="loading">
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
      <el-form-item v-for="filter in resolvedFilters" :key="filter.key" :label="filter.label">
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
        <el-date-picker
          v-else-if="filter.type === 'date'"
          v-model="query[filter.key]"
          type="date"
          :placeholder="filter.placeholder || filter.label"
          value-format="YYYY-MM-DD"
        />
        <el-select
          v-else
          v-model="query[filter.key]"
          :placeholder="filter.placeholder || '全部'"
          clearable
          @change="handleFilterChange(filter)"
        >
          <el-option v-for="option in visibleOptions(filter)" :key="option.value" :label="option.label" :value="option.value" />
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
          <div><dt>质量状态</dt><dd>{{ presentation === 'operating' ? qualityStatusLabel : (quality.status || 'unknown') }}</dd></div>
          <div><dt>{{ qualityMiddleLabel }}</dt><dd>{{ qualityMiddleValue || quality.metric_version || qualityMiddleFallback }}</dd></div>
          <div><dt>刷新时间</dt><dd>{{ presentation === 'operating' ? formatDateTime(quality.refreshed_at) : (quality.refreshed_at || '--') }}</dd></div>
        </dl>
      </section>

      <section v-if="metrics.length" class="metric-grid" :style="{ '--metric-columns': metricColumns }" aria-label="核心经营指标">
        <article v-for="metric in metrics" :key="metric.code" class="metric-card">
          <div class="metric-heading">
            <span>{{ metric.label }}</span>
            <el-tag v-if="showMetricCode" size="small" effect="plain">{{ metric.code }}</el-tag>
          </div>
          <strong>{{ presentation === 'operating' ? formatMetricValue(metric) : (metric.value ?? 'N/A') }}<small>{{ metric.unit || '' }}</small></strong>
          <p :class="['metric-change', metric.change_direction]">
            {{ metric.change || '暂无对比数据' }}
          </p>
        </article>
      </section>

      <section v-if="trend.length" class="analytics-panel trend-panel">
        <div class="panel-heading">
          <div><h2>{{ trendTitle }}</h2><p>{{ trendNote }}</p></div>
          <span>{{ trendCountText }}</span>
        </div>
        <div class="bar-chart" role="img" :aria-label="trendTitle">
          <div v-for="point in trend" :key="point.label" class="bar-column">
            <span class="bar-value">{{ presentation === 'operating' ? formatNumber(point.value) : point.value }}</span>
            <div class="bar-track"><i :style="{ height: barHeight(point.value) }" /></div>
            <span>{{ presentation === 'operating' ? formatTrendLabel(point.label) : point.label }}</span>
          </div>
        </div>
      </section>

      <section class="analytics-panel table-panel">
        <div class="panel-heading">
          <div><h2>{{ tableTitle }}</h2><p>{{ tableNote }}</p></div>
          <el-tag effect="plain">{{ presentation === 'operating' ? total : items.length }} 条</el-tag>
        </div>
        <el-table :data="items" :empty-text="emptyText" :max-height="tableMaxHeight || undefined" stripe>
          <el-table-column
            v-for="column in columns"
            :key="column.prop"
            :prop="column.prop"
            :label="column.label"
            :min-width="column.width || 120"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              <div v-if="column.type === 'primary'" class="cell-primary">
                <strong>{{ formatValue(row[column.prop]) }}</strong>
                <small>{{ row[column.secondaryProp] || column.secondaryFallback || '--' }}</small>
              </div>
              <div v-else-if="column.type === 'dual'" class="cell-primary">
                <span>{{ formatValue(row[column.prop]) }}</span>
                <small>{{ row[column.secondaryProp] || column.secondaryFallback || '--' }}</small>
              </div>
              <el-tag v-else-if="column.type === 'status'" :type="statusType(row[column.statusProp || column.prop])" effect="light">
                {{ presentation === 'operating' ? statusLabel(row[column.prop]) : (row[column.prop] || '--') }}
              </el-tag>
              <strong v-else-if="column.emphasis">{{ formatCell(row, column) }}</strong>
              <span v-else>{{ formatCell(row, column) }}</span>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-if="total > pageSize"
          class="analytics-pagination"
          background
          layout="prev, pager, next, total"
          :current-page="currentPage"
          :page-size="pageSize"
          :total="total"
          @current-change="changePage"
        />
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
  optionsLoader: { type: Function, default: null },
  filters: { type: Array, default: () => [] },
  columns: { type: Array, default: () => [] },
  trendTitle: { type: String, default: '趋势' },
  trendNote: { type: String, default: '' },
  trendUnit: { type: String, default: '' },
  tableTitle: { type: String, default: '明细' },
  tableNote: { type: String, default: '' },
  emptyText: { type: String, default: '当前筛选条件下暂无数据' },
  presentation: { type: String, default: 'generic' },
  metricsKey: { type: String, default: 'metrics' },
  metricColumns: { type: Number, default: 4 },
  pageSize: { type: Number, default: 20 },
  tableMaxHeight: { type: Number, default: 0 },
  trendValueKey: { type: String, default: '' },
  trendLabelKey: { type: String, default: '' },
  trendLabelSeparator: { type: String, default: '-' },
  trendCountUnit: { type: String, default: '个数据点' },
  qualityMiddleLabel: { type: String, default: '口径版本' },
  qualityMiddleValue: { type: String, default: '' },
  qualityMiddleFallback: { type: String, default: '--' },
  showMetricCode: { type: Boolean, default: true }
});

const query = reactive({});
const loading = ref(false);
const errorMessage = ref('');
const apiStatus = ref('mock');
const quality = ref({});
const metrics = ref([]);
const trend = ref([]);
const items = ref([]);
const total = ref(0);
const currentPage = ref(1);
const filterOptions = ref({});
const resolvedFilters = computed(() => props.filters.map((filter) => ({
  ...filter,
  options: filter.options?.length ? filter.options : optionsFor(filter.optionSource)
})));
const qualityStatusLabel = computed(() => statusLabel(quality.value.status));
const trendCountText = computed(() => props.presentation === 'operating'
  ? `${trend.value.length} ${props.trendCountUnit}`
  : props.trendUnit);

const apiStatusLabel = computed(() => ({
  connected: 'API 已连接',
  fallback: 'API 异常 · Mock 回退',
  degraded: 'API 异常 · 降级数据',
  pending: 'API 待联调',
  mock: 'Mock 数据'
}[apiStatus.value] || apiStatus.value));
const statusTagType = computed(() => ({ connected: 'success', degraded: 'warning', fallback: 'warning', pending: 'info', mock: 'info' }[apiStatus.value] || 'info'));
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
  currentPage.value = 1;
}

function optionsFor(source) {
  if (source === 'countries') {
    return [...new Set((filterOptions.value.stores || []).map((item) => item.region).filter(Boolean))]
      .map((item) => ({ label: item, value: item }));
  }
  const values = filterOptions.value[source] || [];
  if (source === 'stores') return values.map((item) => ({ label: `${item.name} · ${item.region}`, value: item.id, platform: item.platform }));
  if (source === 'warehouses') return values.map((item) => ({ label: `${item.name} · ${item.site}`, value: item.id, site: item.site }));
  if (source === 'sites') return values.map((item) => ({ label: item.code || item, value: item.code || item }));
  if (source === 'currencies') return values.map((item) => ({ label: item, value: item }));
  const labels = { shopee: 'Shopee', tiktok: 'TikTok Shop', jifeng_wms: '极风 WMS' };
  return values.map((item) => ({ label: labels[item.code || item] || item.name || item, value: item.code || item }));
}

function visibleOptions(filter) {
  const options = filter.options || [];
  if (!filter.dependsOn || !query[filter.dependsOn]) return options;
  return options.filter((option) => option[filter.optionField] === query[filter.dependsOn]);
}

function handleFilterChange(filter) {
  if (!filter.clears) return;
  for (const key of filter.clears) query[key] = '';
}

async function loadOptions() {
  if (!props.optionsLoader) return;
  const response = await props.optionsLoader();
  if (response?.success) filterOptions.value = response.data || {};
}

function resetFilters() {
  initializeFilters();
  loadData();
}

function changePage(page) {
  currentPage.value = page;
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

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return value ?? 'N/A';
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(number);
}

function formatMoneyMap(value) {
  const entries = Object.entries(value || {});
  if (!entries.length) return 'N/A';
  return entries.map(([currency, amount]) => `${currency} ${formatNumber(amount)}`).join(' · ');
}

function formatMetricValue(metric) {
  if (metric.money) return formatMoneyMap(metric.money);
  if (typeof metric.value === 'number' || /^-?\d+(\.\d+)?$/.test(String(metric.value ?? ''))) {
    return formatNumber(metric.value);
  }
  return metric.value ?? 'N/A';
}

function formatDateTime(value) {
  if (!value) return '--';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false });
}

function formatTrendLabel(value) {
  const text = String(value || '');
  return /^\d{4}-\d{2}-\d{2}$/.test(text)
    ? text.slice(5).replace('-', props.trendLabelSeparator)
    : text;
}

function formatCell(row, column) {
  const value = row[column.prop];
  if (column.type === 'platform') return ({ tiktok: 'TikTok Shop', shopee: 'Shopee' }[value] || value || '--');
  if (column.type === 'datetime') return formatDateTime(value);
  if (column.type === 'money') return value === null || value === undefined || value === ''
    ? 'N/A'
    : `${row[column.currencyProp || 'currency'] || ''} ${formatNumber(value)}`.trim();
  if (column.type === 'number') return formatNumber(value);
  if (column.type === 'percent') return value === null || value === undefined ? 'N/A' : `${formatNumber(Number(value) * 100)}%`;
  return formatValue(value);
}

function statusLabel(value) {
  return {
    healthy: '健康', good: '健康', ready: '健康', warning: '需关注', pending: '待更新',
    out: '缺货', low: '低库存', locked: '锁定偏高', normal: '正常', unknown: '未知'
  }[value] || value || '未知';
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
    normal: 'success',
    out: 'danger',
    locked: 'warning',
    unknown: 'info'
  }[value] || 'info';
}

async function loadData() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const response = await props.loader({ ...query, page: currentPage.value, page_size: props.pageSize });
    if (!response?.success) {
      apiStatus.value = 'pending';
      errorMessage.value = formatApiError(response);
      quality.value = {};
      metrics.value = [];
      trend.value = [];
      items.value = [];
      total.value = 0;
      return;
    }
    const data = response.data || {};
    apiStatus.value = data.api_status || data.status || 'mock';
    quality.value = data.quality || {
      status: data.source_status || 'pending',
      metric_version: data.definition?.metric_version || '事实表实时口径',
      refreshed_at: data.refreshed_at || data.currency_groups?.[0]?.refreshed_at
    };
    metrics.value = data[props.metricsKey]?.length
      ? data[props.metricsKey]
      : data.metrics?.length
        ? data.metrics
      : (data.currency_groups || []).flatMap((group) => (group.metrics || []).map((metric) => ({
          ...metric, code: `${group.currency}-${metric.code}`, label: `${group.currency} · ${metric.label}`
        })));
    trend.value = (data.trend || []).map((point) => ({
      ...point,
      label: point[props.trendLabelKey] || point.label || point.date,
      value: point[props.trendValueKey] ?? point.value ?? point.order_count ?? point.net_sales ?? point.available_qty
    }));
    items.value = Array.isArray(data.results) ? data.results : (Array.isArray(data.items) ? data.items : []);
    total.value = Number(data.count ?? items.value.length);
    if (['fallback', 'degraded'].includes(data.api_status)) errorMessage.value = response.message || data.api_error || '接口异常，已显示降级数据';
  } catch (error) {
    apiStatus.value = 'pending';
    errorMessage.value = formatApiError(error?.response || { message: error?.message });
    quality.value = {};
    metrics.value = [];
    trend.value = [];
    items.value = [];
    total.value = 0;
  } finally {
    loading.value = false;
  }
}

initializeFilters();
onMounted(async () => { await loadOptions(); await loadData(); });
</script>

<style scoped>
.analytics-page { display: grid; gap: 16px; }
.analytics-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.analytics-eyebrow { margin: 0 0 6px; color: #64748b; font-size: 12px; font-weight: 700; text-transform: uppercase; }
.analytics-header h1 { margin: 0; color: #172033; font-size: 24px; letter-spacing: 0; }
.analytics-subtitle { margin: 7px 0 0; color: #64748b; font-size: 14px; }
.analytics-filters { padding: 12px 14px 0; border: 1px solid #dce3ec; border-radius: 8px; background: #fff; }
.analytics-filters :deep(.el-select) { width: 150px; }
.analytics-page.is-operating .analytics-filters { display: grid; grid-template-columns: repeat(5, minmax(150px, 1fr)) auto; gap: 12px; padding: 12px 14px; }
.analytics-page.is-operating .analytics-filters :deep(.el-form-item) { display: block; margin: 0; }
.analytics-page.is-operating .analytics-filters :deep(.el-form-item__label) { display: block; height: auto; margin-bottom: 6px; color: #475569; line-height: 20px; }
.analytics-page.is-operating .analytics-filters :deep(.el-select),
.analytics-page.is-operating .analytics-filters :deep(.el-date-editor) { width: 100%; }
.analytics-page.is-operating .analytics-filters :deep(.el-form-item:last-child) { display: flex; align-items: flex-end; padding-bottom: 1px; }
.analytics-content { display: grid; gap: 16px; min-height: 220px; }
.quality-rail { display: grid; grid-template-columns: 150px minmax(180px, 1fr) minmax(420px, 1.6fr); align-items: center; gap: 20px; padding: 14px 16px; border: 1px solid #cfd9e6; border-left: 4px solid #0f766e; border-radius: 6px; background: #fff; }
.analytics-page.is-operating .quality-rail { border-left-width: 1px; }
.quality-rail > div:first-child { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; color: #475569; font-size: 13px; }
.quality-rail strong { color: #0f766e; font-size: 22px; }
.quality-rail small { font-size: 12px; }
.quality-rail dl { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 0; }
.quality-rail dl div { min-width: 0; }
.quality-rail dt { color: #7b8798; font-size: 12px; }
.quality-rail dd { margin: 3px 0 0; overflow: hidden; color: #273449; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.metric-grid { display: grid; grid-template-columns: repeat(var(--metric-columns, 4), minmax(0, 1fr)); gap: 12px; }
.metric-card { min-width: 0; padding: 15px 16px; border: 1px solid #dce3ec; border-radius: 6px; background: #fff; }
.metric-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: #5f6f82; font-size: 13px; }
.metric-heading :deep(.el-tag) { max-width: 110px; overflow: hidden; text-overflow: ellipsis; }
.metric-card > strong { display: block; margin-top: 16px; color: #172033; font-size: 27px; font-variant-numeric: tabular-nums; }
.analytics-page.is-operating .metric-card > strong { min-height: 64px; overflow-wrap: anywhere; }
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
.analytics-page.is-operating .table-panel :deep(.el-table th.el-table__cell) { background: #f5f7fa; color: #475569; }
.cell-primary { display: grid; gap: 3px; min-width: 0; }
.cell-primary strong, .cell-primary span { overflow: hidden; color: #172033; text-overflow: ellipsis; white-space: nowrap; }
.cell-primary small { overflow: hidden; color: #7b8798; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.table-panel :deep(.el-empty) { display: none; }
.analytics-pagination { justify-content: flex-end; margin-top: 16px; }
@media (max-width: 1050px) {
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .analytics-page.is-operating .analytics-filters { grid-template-columns: repeat(3, minmax(150px, 1fr)); }
  .quality-rail { grid-template-columns: 130px 1fr; }
  .quality-rail dl { grid-column: 1 / -1; }
}
@media (max-width: 720px) {
  .analytics-header { align-items: stretch; flex-direction: column; }
  .analytics-header :deep(.el-tag) { align-self: flex-start; }
  .analytics-filters { display: grid; }
  .analytics-page.is-operating .analytics-filters { grid-template-columns: 1fr; }
  .analytics-filters :deep(.el-form-item) { margin-right: 0; }
  .analytics-filters :deep(.el-select), .analytics-filters :deep(.el-date-editor) { width: 100%; }
  .quality-rail, .metric-grid { grid-template-columns: 1fr; }
  .quality-rail dl { grid-template-columns: 1fr; }
}
</style>
