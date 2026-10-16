<template>
  <section class="period-analysis" :aria-busy="loading">
    <div class="intro">
      <div><h2>周期趋势与同比环比</h2><p>按已采集数据比较。未结束周期按相同进度计算，缺失数据保留为空。</p></div>
      <el-tag effect="plain">{{ loading ? '正在计算' : job?.status === 'completed' ? '查询完成' : result ? '已查询' : '尚未查询' }}</el-tag>
    </div>
    <el-form class="query-form" label-position="top" @submit.prevent="run">
      <el-form-item label="分析方式"><el-radio-group v-model="mode">
        <el-radio-button label="monthly">全年月度趋势</el-radio-button><el-radio-button label="weekly">全年周度趋势</el-radio-button><el-radio-button label="period">周期同比环比</el-radio-button>
      </el-radio-group></el-form-item>
      <el-form-item v-if="mode !== 'period'" label="年份"><el-select v-model="year" aria-label="年份">
        <el-option v-for="value in years" :key="value" :label="`${value} 年`" :value="value" />
      </el-select></el-form-item>
      <el-form-item v-else label="自定义周期"><el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" /></el-form-item>
      <el-form-item label="店铺编号"><el-input v-model.trim="filters.store_id" clearable placeholder="全部可见店铺" /></el-form-item>
      <el-form-item v-if="dataset !== 'finance'" label="站点 / 区域"><el-input v-model.trim="filters.region" clearable placeholder="全部站点" /></el-form-item>
      <el-form-item label="币种"><el-input v-model.trim="filters.currency" maxlength="3" clearable placeholder="如 USD" /></el-form-item>
      <el-form-item label="平台"><el-input v-model.trim="filters.platform" clearable placeholder="全部平台" /></el-form-item>
      <el-form-item class="query-actions"><el-button type="primary" native-type="submit" :loading="loading">查询周期</el-button>
        <el-button v-if="(timedOut || error) && activeJobId" :loading="loading" @click="retryStatus">继续检查</el-button>
        <el-button v-if="activeJobId" type="danger" plain @click="cancel">取消任务</el-button></el-form-item>
    </el-form>
    <el-alert v-if="error" type="error" :closable="false" :title="error" />
    <el-alert v-if="result && !canDrill" type="warning" :closable="false" :title="resultNotice" />
    <el-alert v-if="timedOut" type="info" :closable="false" title="任务仍在运行，已保留任务编号；可继续检查状态，或取消任务。" />
    <template v-if="result">
      <div class="result-notes"><span>{{ result.note }}</span><span v-if="result.config?.cutoff">共同已结束日期截至 {{ result.config.cutoff }}</span><span v-if="result.refreshed_at">来源更新时间 {{ formatTimestamp(result.refreshed_at) }}</span><span v-if="result.computed_at">计算时间 {{ formatTimestamp(result.computed_at) }}</span></div>
      <div class="analysis-controls">
        <el-radio-group v-model="currency" aria-label="币种">
          <el-radio-button v-for="item in currencies" :key="item" :label="item">{{ item }}</el-radio-button>
        </el-radio-group>
        <el-select v-model="metric" aria-label="趋势指标" class="metric-select">
          <el-option v-for="item in availableMetrics" :key="item" :label="metricLabel(item)" :value="item" />
        </el-select>
        <el-radio-group v-model="comparison" aria-label="对比口径">
          <el-radio-button label="yoy">同比</el-radio-button><el-radio-button label="previous">环比</el-radio-button>
        </el-radio-group>
      </div>
      <div v-if="activeSeries" class="chart-card">
        <div class="chart-legend"><span class="legend-current">本期</span><span class="legend-prior">{{ comparison === 'yoy' ? '去年同期' : '上期' }}</span><span class="chart-unit">{{ metricLabel(metric) }} · {{ metricUnit }}（{{ currency }} 分组）</span></div>
        <svg class="trend-chart" viewBox="0 0 900 260" role="img" :aria-label="`${currency} ${metricLabel(metric)}周期趋势，实线本期，虚线${comparison === 'yoy' ? '去年同期' : '上期'}`">
          <g class="grid-lines"><line v-for="y in [30, 80, 130, 180, 230]" :key="y" x1="0" :y1="y" x2="900" :y2="y" /></g>
          <template v-for="(segment, segmentIndex) in currentSegments" :key="`c-${segmentIndex}`"><path :d="segmentPath(segment)" class="current-path" /></template>
          <template v-for="(segment, segmentIndex) in compareSegments" :key="`p-${segmentIndex}`"><path :d="segmentPath(segment)" class="prior-path" /></template>
          <g v-for="point in chartPoints" :key="point.label">
            <circle v-if="point.currentValue != null" :cx="point.current.x" :cy="point.current.y" r="4" class="current-dot" tabindex="0" role="button" :aria-label="pointAria(point, 'current')" @click="selectPoint(point, 'current')" @keydown.enter.prevent="selectPoint(point, 'current')" @keydown.space.prevent="selectPoint(point, 'current')"><title>{{ pointTooltip(point) }}</title></circle>
            <circle v-if="point.compareValue != null" :cx="point.compare.x" :cy="point.compare.y" r="3.5" class="prior-dot" tabindex="0" role="button" :aria-label="pointAria(point, comparison)" @click="selectPoint(point, comparison)" @keydown.enter.prevent="selectPoint(point, comparison)" @keydown.space.prevent="selectPoint(point, comparison)"><title>{{ pointTooltip(point) }}</title></circle>
          </g>
          <text v-for="label in chartLabels" :key="label.text" :x="label.x" y="252" text-anchor="middle" class="axis-label">{{ label.text }}</text>
          <text v-for="tick in chartTicks" :key="tick.y" x="4" :y="tick.y" class="axis-label">{{ tick.label }}</text>
        </svg>
        <p class="chart-hint">聚焦或点击任一数据点可打开该周期明细。图中空档表示没有已采集值。</p>
      </div>
      <div v-else class="empty-series">当前筛选条件下暂无可绘制数据。</div>
      <div class="period-table-wrap">
        <el-table :data="pagedPoints" stripe border row-key="label" aria-label="周期比较明细">
          <el-table-column prop="label" label="周期" min-width="95" fixed />
          <el-table-column label="日期范围" min-width="205"><template #default="{ row }">{{ row.start }} 至 {{ row.end }}</template></el-table-column>
          <el-table-column label="状态" width="130"><template #default="{ row }"><el-tag v-if="row.future" type="info" effect="plain">未开始</el-tag><el-tag v-else-if="row.partial" type="warning" effect="plain">进行中</el-tag><el-tag v-else effect="plain">已结束</el-tag></template></el-table-column>
          <el-table-column :label="`本期 · ${metricLabel(metric)}`" min-width="150" align="right"><template #default="{ row }">{{ display(row.current?.metrics?.[metric]) }}</template></el-table-column>
          <el-table-column :label="`${comparison === 'yoy' ? '去年同期' : '上期'} · ${metricLabel(metric)}`" min-width="155" align="right"><template #default="{ row }">{{ display(row[comparison]?.metrics?.[metric]) }}</template></el-table-column>
          <el-table-column :label="metric === 'ctr' ? '差值（百分点）' : '差值'" min-width="140" align="right"><template #default="{ row }">{{ display(periodChange(row, metric, comparison)?.delta) }}</template></el-table-column>
          <el-table-column label="变化率" min-width="120" align="right"><template #default="{ row }">{{ percent(periodChange(row, metric, comparison)?.percent) }}</template></el-table-column>
          <el-table-column label="下钻" width="150" fixed="right"><template #default="{ row }"><el-button link type="primary" :disabled="!canDrill || !row.drill?.current" @click="openDrill(row, 'current')">本期</el-button><el-button link :disabled="!canDrill || !row.drill?.[comparison]" @click="openDrill(row, comparison)">{{ comparison === 'yoy' ? '同比' : '环比' }}</el-button></template></el-table-column>
        </el-table>
        <el-pagination v-if="periodPoints.length > pageSize" v-model:current-page="page" :page-size="pageSize" :total="periodPoints.length" layout="total, prev, pager, next" />
      </div>
    </template>
    <el-empty v-else-if="!loading && !error" description="设置周期和筛选条件后，点击“查询周期”开始计算。" />
    <el-dialog v-model="drillOpen" :title="drillTitle" width="min(1080px, 94vw)" @closed="closeDrill">
      <el-alert v-if="drillError" type="error" :closable="false" :title="drillError" />
      <div v-if="drillLoading" v-loading="drillLoading" class="drill-loading">正在读取所选周期明细…</div>
      <template v-else-if="drillResult">
        <p class="drill-note">根据 {{ drillPeriod }} 的日期和原筛选条件实时查询。最多显示接口返回的分组结果；重新读取的数据可能与周期计算批次有变化。</p>
        <el-alert v-if="drillResult.truncated" type="warning" :closable="false" title="分组结果已截断，以下仅为部分数据。请缩小筛选范围后查看完整结果。" />
        <div class="drill-actions"><el-button v-if="canOpenRawDetails" type="primary" plain @click="openRawDetails">查看原始明细</el-button></div>
        <el-table :data="drillRows" stripe border max-height="460">
          <el-table-column v-for="key in drillDimensions" :key="key" :prop="key" :label="dimensionLabel(key)" min-width="125" show-overflow-tooltip />
          <el-table-column v-for="key in drillMetrics" :key="key" :label="metricLabel(key)" min-width="135" align="right"><template #default="{ row }">{{ display(row[key]) }}</template></el-table-column>
        </el-table>
        <el-empty v-if="!drillRows.length" description="所选区间没有匹配分组。" />
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth';
import { canAccessPath } from '../router/menu';
import { queryReport } from '../api/reporting';
import {
  DATASET_METRICS, METRIC_LABELS, analysisPayload, cancelAnalysisJob, chartDomain, chartSegments, drillReportConfig,
  isAccessFailure, metricNumber, periodChange, pollAnalysisJob, rawDetailRoute, startAnalysisJob
} from '../views/reports/periodAnalysis';

const props = defineProps({ dataset: { type: String, required: true }, initialFilters: { type: Object, default: () => ({}) } });
const router = useRouter(), auth = useAuthStore();
const today = new Date();
const mode = ref('monthly'), year = ref(today.getFullYear()), dateRange = ref([]);
const years = Array.from({ length: Math.max(1, today.getFullYear() - 2024) }, (_, i) => today.getFullYear() - i);
const filters = ref({ store_id: '', region: '', currency: '', platform: '', ...props.initialFilters });
const loading = ref(false), error = ref(''), result = ref(null), job = ref(null), stale = ref(false), timedOut = ref(false), activeJobId = ref('');
const currency = ref(''), metric = ref(DATASET_METRICS[props.dataset]?.[0] || ''), comparison = ref('yoy'), page = ref(1);
const drillOpen = ref(false), drillLoading = ref(false), drillError = ref(''), drillResult = ref(null), drillPeriod = ref(''), drillTitle = ref('');
const drillFilters = ref(null), drillMetric = ref('');
const appliedSnapshot = ref(null), pendingSnapshot = ref(null);
const pageSize = 10;
let sequence = 0, controller = null, drillController = null, drillSequence = 0;
const availableMetrics = computed(() => DATASET_METRICS[props.dataset] || []);
const currentSnapshot = computed(() => analysisPayload({ dataset: props.dataset, mode: mode.value, year: year.value, filters: filters.value, dateFrom: dateRange.value?.[0], dateTo: dateRange.value?.[1] }));
const dirty = computed(() => Boolean(appliedSnapshot.value && JSON.stringify(currentSnapshot.value) !== JSON.stringify(appliedSnapshot.value)));
const canDrill = computed(() => Boolean(result.value && !dirty.value && !loading.value && !error.value && !stale.value));
const resultNotice = computed(() => loading.value ? '当前筛选条件查询进行中；下钻暂时停用。' : dirty.value ? '筛选条件已更改，以下仍是上次成功结果；下钻已停用。' : '当前筛选条件查询失败，以下是上次成功结果；下钻已停用。');
const currencies = computed(() => (result.value?.series || []).map(item => item.currency));
const activeSeries = computed(() => result.value?.series?.find(item => item.currency === currency.value) || result.value?.series?.[0] || null);
const periodPoints = computed(() => activeSeries.value?.points || []);
const pagedPoints = computed(() => periodPoints.value.slice((page.value - 1) * pageSize, page.value * pageSize));
const sharedDomain = computed(() => chartDomain(periodPoints.value, metric.value, ['current', comparison.value]));
const chartTicks = computed(() => sharedDomain.value ? Array.from({length:5},(_,i)=>({y:12+i*55,label:(sharedDomain.value[1]-(sharedDomain.value[1]-sharedDomain.value[0])*i/4).toLocaleString('zh-CN',{maximumFractionDigits:1})})) : []);
const metricUnit = computed(() => metric.value === 'ctr' ? '%' : metric.value.endsWith('roas') ? '倍' : ['gross_sales','signed_amount','expense','direct_gmv','broad_gmv','average_order_value','cpc'].includes(metric.value) ? currency.value : metric.value.includes('order') ? '单' : '条／次');
const currentSegments = computed(() => chartSegments(periodPoints.value, metric.value, 'current', 900, 240, sharedDomain.value));
const compareSegments = computed(() => chartSegments(periodPoints.value, metric.value, comparison.value, 900, 240, sharedDomain.value));
const chartPoints = computed(() => {
  const currentAll = currentSegments.value.flat(), compareAll = compareSegments.value.flat();
  return periodPoints.value.map((point, index) => ({
    ...point,
    currentValue: metricValue(point, 'current'),
    compareValue: metricValue(point, comparison.value),
    current: currentAll.find(item => item.index === index) || null,
    compare: compareAll.find(item => item.index === index) || null
  }));
});
const chartLabels = computed(() => periodPoints.value.map((point, index) => ({ point, index })).filter(({ index }) => periodPoints.value.length < 18 || index % Math.ceil(periodPoints.value.length / 12) === 0).map(({ point, index }) => ({ text: point.label, x: periodPoints.value.length <= 1 ? 450 : index * 900 / (periodPoints.value.length - 1) })));
const drillRows = computed(() => drillResult.value?.rows || []);
const drillDimensions = computed(() => drillResult.value?.config?.dimensions || []);
const drillMetrics = computed(() => drillResult.value?.config?.metrics || []);
const rawRoute = computed(() => drillFilters.value ? rawDetailRoute(props.dataset, drillFilters.value, drillMetric.value) : null);
const canOpenRawDetails = computed(() => Boolean(canDrill.value && rawRoute.value && canAccessPath(auth.currentUser, rawRoute.value.path)));

watch(currencies, items => { if (!items.includes(currency.value)) currency.value = items[0] || ''; });
watch(() => props.dataset, value => { metric.value = DATASET_METRICS[value]?.[0] || ''; result.value = null; appliedSnapshot.value = null; pendingSnapshot.value = null; });
watch([mode, currency, metric, comparison], () => { page.value = 1; });
watch(canDrill, allowed => { if (!allowed && drillOpen.value) closeDrill(); });
watch([currency, metric, comparison], () => { if (drillOpen.value) closeDrill(); });

function metricLabel(key) { return METRIC_LABELS[key] || key; }
function display(value) { return value == null || value === '' ? '—' : String(value); }
function percent(value) { return value == null ? '—' : `${Number(value).toFixed(2)}%`; }
function dimensionLabel(key) { return ({ date: '日期', store_id: '店铺编号', region: '站点', platform: '平台', currency: '币种', fee_category: '流水分类' })[key] || key; }
function formatTimestamp(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }); }
function segmentPath(segment) { return segment.map((point, index) => `${index ? 'L' : 'M'}${point.x},${point.y}`).join(' '); }
function pointTooltip(point) { return `${point.label} · ${point.start} 至 ${point.end}${point.partial ? ' · 进行中' : point.future ? ' · 未开始' : ''} · ${metricLabel(metric.value)}（${currency.value}）· 本期 ${display(point.currentValue)} · ${comparison.value === 'yoy' ? '去年同期' : '上期'} ${display(point.compareValue)}`; }
function pointAria(point, side) { return `${point.label}，${side === 'current' ? '本期' : side === 'yoy' ? '同比' : '环比'}，${metricLabel(metric.value)} ${display(side === 'current' ? point.currentValue : point.compareValue)}，${point.start} 至 ${point.end}，按 Enter 查看周期明细`; }
function selectPoint(point, side) { if (!canDrill.value) return; const row = periodPoints.value.find(item => item.label === point.label); if (row?.drill?.[side]) openDrill(row, side); }
function metricValue(point, comparisonKey) { return metricNumber(point?.[comparisonKey]?.metrics?.[metric.value]); }
function fail(message, response) {
  error.value = message || '周期分析失败，请重试。';
  stale.value = Boolean(result.value);
  if (!activeJobId.value) pendingSnapshot.value = null;
  if (isAccessFailure(response)) { result.value = null; appliedSnapshot.value = null; pendingSnapshot.value = null; activeJobId.value = ''; timedOut.value = false; stale.value = false; }
}

async function run() {
  if (mode.value === 'period' && (!Array.isArray(dateRange.value) || dateRange.value.length !== 2)) { error.value = '请选择周期起止日期。'; return; }
  const current = ++sequence;
  controller?.abort();
  controller = new AbortController();
  loading.value = true; error.value = ''; stale.value = false; timedOut.value = false; job.value = null;
  activeJobId.value = '';
  const payload = JSON.parse(JSON.stringify(currentSnapshot.value));
  pendingSnapshot.value = payload;
  try {
    const created = await startAnalysisJob(payload, controller.signal);
    if (current !== sequence) return;
    if (!created?.success) { fail(created?.message || '无法启动周期分析。', created); return; }
    job.value = created.data;
    activeJobId.value = created.data?.id || '';
    if (created.data?.status === 'completed') { applyResult(created.data.result); activeJobId.value = ''; return; }
    if (!activeJobId.value) { fail('服务器没有返回分析任务编号。'); return; }
    await pollCurrent(activeJobId.value, current);
  } catch (cause) {
    if (current === sequence && cause?.name !== 'AbortError') fail(cause?.message);
  } finally { if (current === sequence) loading.value = false; }
}

async function pollCurrent(id, current) {
  const response = await pollAnalysisJob(id, { signal: controller.signal, onJob: value => { if (current === sequence) job.value = value; } });
  if (current !== sequence) return;
  if (response?.code === 'POLL_TIMEOUT') { timedOut.value = true; return; }
  if (!response?.success) {
    fail(response?.message || '读取分析任务失败。', response);
    if ([404, 410].includes(response?.http_status) || /EXPIRED/i.test(response?.code || '')) activeJobId.value = '';
    return;
  }
  const latest = response.data;
  if (latest.status === 'completed' && latest.result) {
    applyResult(latest.result); activeJobId.value = ''; timedOut.value = false;
  } else if (latest.status === 'failed') {
    fail(latest.error || '周期分析任务失败。'); activeJobId.value = ''; pendingSnapshot.value = null;
  } else if (latest.status === 'cancelled') {
    error.value = '周期分析任务已取消。'; stale.value = Boolean(result.value); activeJobId.value = ''; pendingSnapshot.value = null;
  } else if (latest.status === 'expired') {
    fail(latest.error || '周期分析任务已过期，请重新查询。'); activeJobId.value = ''; pendingSnapshot.value = null;
  }
}

function applyResult(value) {
  result.value = value || null;
  appliedSnapshot.value = pendingSnapshot.value;
  pendingSnapshot.value = null;
  stale.value = false;
}

async function retryStatus() {
  if (!activeJobId.value || loading.value) return;
  const current = ++sequence;
  controller?.abort(); controller = new AbortController();
  loading.value = true; error.value = ''; timedOut.value = false;
  try { await pollCurrent(activeJobId.value, current); }
  catch (cause) { if (current === sequence && cause?.name !== 'AbortError') fail(cause?.message); }
  finally { if (current === sequence) loading.value = false; }
}

async function cancel() {
  const id = activeJobId.value;
  if (!id) return;
  controller?.abort(); sequence++; loading.value = false; timedOut.value = false;
  try {
    const response = await cancelAnalysisJob(id);
    if (!response?.success) { fail(response?.message || '取消任务失败。', response); return; }
    job.value = response.data || { ...job.value, status: 'cancelled' };
    activeJobId.value = ''; pendingSnapshot.value = null;
  } catch (cause) { fail(cause?.message || '取消任务失败。', cause); }
}

async function openDrill(point, key) {
  const periodFilters = point?.drill?.[key];
  if (!periodFilters || !canDrill.value) return;
  const currentDrill = ++drillSequence;
  drillController?.abort(); drillController = new AbortController();
  drillOpen.value = true; drillLoading.value = true; drillError.value = ''; drillResult.value = null;
  drillFilters.value = JSON.parse(JSON.stringify(periodFilters)); drillMetric.value = metric.value;
  drillPeriod.value = `${point.label} · ${key === 'current' ? '本期' : key === 'yoy' ? '去年同期' : '上期'}`;
  drillTitle.value = `${drillPeriod.value}明细`;
  try {
    const config = drillReportConfig(props.dataset, periodFilters);
    if (props.dataset === 'sales' && metric.value === 'cancelled_order_count') config.filters.status = 'cancelled';
    const response = await queryReport(config, drillController.signal);
    if (!drillOpen.value || currentDrill !== drillSequence) return;
    if (!response?.success) {
      drillError.value = response?.message || '所选周期明细读取失败。';
      if (isAccessFailure(response)) { error.value = response?.message || '当前账号无权读取此报表。'; result.value = null; appliedSnapshot.value = null; stale.value = false; }
      return;
    }
    drillResult.value = response.data;
  } catch (cause) { if (currentDrill === drillSequence && cause?.name !== 'AbortError') drillError.value = cause?.message || '所选周期明细读取失败。'; }
  finally { if (currentDrill === drillSequence) drillLoading.value = false; }
}

function closeDrill() { drillSequence++; drillController?.abort(); drillResult.value = null; drillError.value = ''; }
function openRawDetails() {
  if (!canOpenRawDetails.value || !rawRoute.value) return;
  router.push(rawRoute.value);
  drillOpen.value = false;
}
onBeforeUnmount(() => { sequence++; drillSequence++; controller?.abort(); drillController?.abort(); });
</script>

<style scoped>
.period-analysis { display: grid; gap: 16px; padding: 6px 2px 18px; color: #233247; }
.intro, .analysis-controls, .chart-legend, .result-notes { display: flex; justify-content: space-between; align-items: center; gap: 14px; flex-wrap: wrap; }
.intro h2 { margin: 0 0 5px; font-size: 19px; }
.intro p, .chart-hint, .drill-note { margin: 0; color: #66758a; font-size: 13px; line-height: 1.6; }
.query-form { display: flex; align-items: end; gap: 12px; flex-wrap: wrap; padding: 14px; border: 1px solid #e0e7f0; border-radius: 10px; background: #f8fafd; }
.query-form :deep(.el-form-item) { margin: 0; }
.query-form :deep(.el-date-editor), .query-form :deep(.el-select), .query-form :deep(.el-input) { width: 170px; }
.query-actions { margin-left: auto !important; }
.result-notes { align-items: flex-start; color: #66758a; font-size: 12px; }
.analysis-controls { justify-content: flex-start; }
.metric-select { width: 190px; margin-left: auto; }
.chart-card { border: 1px solid #e0e7f0; border-radius: 12px; padding: 14px 18px 10px; background: linear-gradient(180deg, #fff, #fbfcfe); }
.chart-legend { justify-content: flex-start; color: #526177; font-size: 12px; }
.legend-current::before, .legend-prior::before { content: ''; display: inline-block; width: 22px; margin: 0 7px 3px 0; border-top: 3px solid #2878cf; vertical-align: middle; }
.legend-prior::before { border-color: #a1aec1; border-top-style: dashed; }
.chart-unit { margin-left: auto; }
.trend-chart { display: block; width: 100%; height: auto; min-height: 150px; margin-top: 10px; overflow: visible; }
.grid-lines line { stroke: #edf1f6; stroke-width: 1; }
.current-path, .prior-path { fill: none; stroke: #2878cf; stroke-width: 2.6; stroke-linecap: round; stroke-linejoin: round; }
.prior-path { stroke: #9ba9bb; stroke-width: 2; stroke-dasharray: 7 5; }
.current-dot { fill: #fff; stroke: #2878cf; stroke-width: 2; cursor: pointer; }
.prior-dot { fill: #fff; stroke: #8493a8; stroke-width: 2; cursor: pointer; }
.current-dot:focus, .prior-dot:focus { outline: none; stroke: #f08a24; stroke-width: 3.5; }
.axis-label { fill: #77869a; font-size: 11px; }
.chart-hint { margin-top: 2px; }
.period-table-wrap { min-width: 0; }
.period-table-wrap :deep(.el-pagination) { justify-content: flex-end; margin-top: 14px; }
.empty-series { padding: 30px; text-align: center; color: #738198; background: #f7f9fc; border-radius: 10px; }
.drill-loading { height: 180px; }
.drill-note { margin-bottom: 12px; }
.drill-actions { display: flex; justify-content: flex-end; margin: 8px 0; }
@media (max-width: 760px) { .query-form :deep(.el-form-item) { width: 100%; } .query-form :deep(.el-date-editor), .query-form :deep(.el-select), .query-form :deep(.el-input) { width: 100%; } .query-actions { margin-left: 0 !important; } .metric-select { margin-left: 0; } .trend-chart { min-height: 110px; } }
</style>
