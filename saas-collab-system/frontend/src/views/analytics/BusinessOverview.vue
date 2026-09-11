<template>
  <section class="business-overview" :aria-busy="loading">
    <header class="page-heading"><div><h1>经营总览</h1><p>从销售表现、取消与退款到店铺经营，查看当前授权范围内的真实数据。</p></div><el-tag :type="data.api_status === 'connected' ? 'success' : 'info'" effect="plain">{{ data.api_status === 'connected' ? 'API 已连接' : loading ? '加载中' : '暂无实时数据' }}</el-tag></header>
    <el-form class="business-filters" label-position="top" :model="query" @submit.prevent="search">
      <el-form-item label="平台"><el-select v-model="query.platforms" multiple collapse-tags collapse-tags-tooltip clearable placeholder="全部平台" @change="pruneStores"><el-option v-for="value in options.platforms || []" :key="value" :value="value" :label="formatField(value, { format: 'platform' })" /></el-select></el-form-item>
      <el-form-item label="店铺"><el-select v-model="query.store_ids" multiple collapse-tags collapse-tags-tooltip clearable filterable placeholder="全部店铺"><el-option v-for="store in stores" :key="store.id" :value="store.id" :label="store.name || store.code" /></el-select></el-form-item>
      <el-form-item label="币种口径"><el-select v-model="query.currency" clearable placeholder="全部（分币种展示）"><el-option v-for="value in options.currencies || []" :key="value" :value="value" :label="value" /></el-select></el-form-item>
      <el-form-item label="统计日期" class="date-filter"><div class="date-controls"><div class="quick-dates"><button v-for="days in [1, 7, 15, 30]" :key="days" type="button" :aria-pressed="isRange(days)" @click="query.date_range = completedDateRange(days)">{{ days === 1 ? '昨天' : `过去${days}天` }}</button></div><el-date-picker v-model="query.date_range" type="daterange" unlink-panels value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" /></div></el-form-item>
      <div class="filter-actions"><el-button type="primary" native-type="submit" :loading="loading">查询</el-button><el-button :disabled="loading" @click="reset">重置</el-button></div>
    </el-form>
    <p v-if="pendingFilters" class="data-note">筛选条件已修改，点击“查询”更新以下所有数据。</p>
    <el-alert v-if="filterError" :title="filterError" type="warning" :closable="false" show-icon />
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-loading="loading" class="report-content">
      <div class="scope-line"><span>统计范围：{{ applied.date_range?.join(' 至 ') || '全部日期' }} · 金额不跨币种合计</span><span>更新时间（UTC）：{{ formatField(data.quality?.refreshed_at, { format: 'datetime' }) }}</span></div>
      <p class="data-note">订单按店铺时区筛选；金额不含取消订单，销量包含取消订单。成本、毛利与同期对比尚未接入。</p>
      <SalesOverviewPanel v-for="group in groups" :key="group.currency" :data="data" :currency-code="group.currency" report-kind="business" :chart-metrics="metricSections.flatMap(section => section.codes.map(code => ({ ...metric(group, code), code })))">
        <template #metrics="{ selected, toggle, color }"><div class="business-metrics">
          <div class="currency-heading"><h2>经营指标 <span>{{ group.currency || '未提供币种' }}</span></h2><span>当前筛选范围 · 非环比数据</span></div>
          <div class="metric-groups" tabindex="0" aria-label="横向滚动查看经营指标"><section v-for="section in metricSections" :key="section.title" class="metric-group"><h3>{{ section.title }}</h3><div class="metric-list"><button v-for="code in section.codes" :key="code" type="button" :aria-pressed="selected.includes(code)" :style="{ '--series-color': color(code) }" @click="toggle(code)"><span>{{ metric(group, code).label }}</span><strong>{{ metric(group, code).display }} <small>{{ metric(group, code).unit }}</small></strong><p>{{ metric(group, code).definition }}</p><span class="selection-state"><i />{{ selected.includes(code) ? '已显示' : '已隐藏' }}</span></button></div></section></div>
        </div></template>
      </SalesOverviewPanel>
      <el-empty v-if="!loading && !error && !groups.length" description="当前范围暂无真实订单经营数据，请调整筛选或检查订单同步。" />
      <section class="store-report">
        <header><div><h2>店铺监控</h2><p>按店铺、站点与币种核对经营表现；点击表头可排序。</p></div><span>{{ storeRows.length }} / {{ data.count || 0 }} 条</span></header>
        <p v-if="data.count > storeRows.length" class="data-note">接口当前返回前 {{ storeRows.length }} 条店铺记录；上方指标仍为完整筛选范围，请缩小店铺范围查看其他记录。</p>
        <el-table :data="storeRows" stripe empty-text="当前范围暂无店铺经营数据">
          <el-table-column prop="store_name" label="店铺" min-width="210" show-overflow-tooltip sortable />
          <el-table-column prop="platform" label="平台" min-width="125" sortable><template #default="{ row }">{{ formatField(row.platform, { format: 'platform' }) }}</template></el-table-column>
          <el-table-column prop="region" label="站点" min-width="80" sortable />
          <el-table-column prop="currency" label="币种" min-width="80" sortable />
          <el-table-column v-for="column in columns" :key="column.key" :prop="column.key" :label="column.label" min-width="150" align="right" sortable :sort-method="(a,b) => compare(a,b,column.key)"><template #default="{ row }">{{ formatField(row[column.key], { numeric: true, format: column.money ? 'money' : undefined }) }}</template></el-table-column>
        </el-table>
      </section>
      <details class="quality-details"><summary>数据质量与统计边界</summary><p>仅展示当前租户及授权店铺数据；不触发同步、采购、改价或资金动作。趋势按订单业务日期及退款 UTC 申请日期展示，缺失日期不补零。退款金额来自筛选范围内全部售后事实，不等于已到账退款。退款金额占比不是退款订单率。</p><p>质量检查记录：{{ data.quality?.checked_rows ?? '—' }}；问题记录：{{ data.quality?.problem_rows ?? '—' }}；口径版本：{{ data.quality?.metric_version || '—' }}。</p><p>仓库、分类、组合 SKU、成本利润及同期对比未接入本报表，不提供无数据依据的筛选和估算。</p></details>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { fetchBusinessFilters, fetchBusinessOverview } from '../../api/analytics';
import { formatApiError } from '../../api/request';
import SalesOverviewPanel from '../sales-management/SalesOverviewPanel.vue';
import { completedDateRange } from '../sales-management/overviewTrend';
import { formatField, formatMetric } from '../sales-management/display';

const defaults = () => ({ platforms: [], store_ids: [], currency: '', date_range: completedDateRange(30) });
const query = reactive(defaults()), applied = ref(defaults());
const options = ref({}), data = ref({}), loading = ref(false), error = ref(''), filterError = ref('');
let sequence = 0;
const stores = computed(() => (options.value.stores || []).filter(store => !query.platforms.length || query.platforms.includes(store.platform)));
const pendingFilters = computed(() => JSON.stringify({ ...query, date_range: query.date_range || [] }) !== JSON.stringify(applied.value));
const groups = computed(() => data.value.api_status === 'connected' ? data.value.currency_groups || [] : []);
const storeRows = computed(() => data.value.api_status === 'connected' ? (data.value.results || []).filter(row => row.store_id != null) : []);
const metricSections = [
  { title: '销售表现', codes: ['order_count', 'units_sold', 'gross_sales', 'net_sales'] },
  { title: '取消订单', codes: ['cancelled_order_count', 'cancellation_rate'] },
  { title: '退款分析', codes: ['refund_amount', 'refund_rate'] }
];
const columns = [
  { key: 'order_count', label: '订单总量' }, { key: 'units_sold', label: '产品销量' },
  { key: 'gross_sales', label: '非取消订单销售额', money: true }, { key: 'net_sales', label: '净销售额', money: true },
  { key: 'cancelled_order_count', label: '取消订单量' }, { key: 'refund_case_count', label: '售后单量' },
  { key: 'refund_amount', label: '退款金额', money: true }
];
function metric(group, code) {
  const raw = (group.metrics || []).find(item => item.code === code) || { code, value: null };
  if (code === 'cancellation_rate') {
    const count = group.metrics?.find(item => item.code === 'order_count')?.value;
    const cancelled = group.metrics?.find(item => item.code === 'cancelled_order_count')?.value;
    return { label: '取消率', display: formatField(Number(count) > 0 && cancelled != null ? Number(cancelled) / Number(count) : null, { format: 'ratio' }), definition: '取消订单量 ÷ 订单总量' };
  }
  const result = formatMetric(raw);
  if (code === 'refund_rate' && !(Number(group.metrics?.find(item => item.code === 'gross_sales')?.value) > 0)) result.display = '—';
  if (code === 'gross_sales') Object.assign(result, { label: '非取消订单销售额', definition: '订单总金额，不含取消订单' });
  if (code === 'order_count') result.label = '订单总量';
  if (code === 'units_sold') result.definition = '订单商品数量，包含取消订单';
  return result;
}
function compare(a, b, key) {
  const left = a[key], right = b[key];
  if (left == null || right == null) return left == null ? right == null ? 0 : -1 : 1;
  return Number(left) - Number(right);
}
function pruneStores() { query.store_ids = query.store_ids.filter(id => stores.value.some(store => store.id === id)); }
function isRange(days) { return JSON.stringify(query.date_range) === JSON.stringify(completedDateRange(days)); }
function reset() { Object.assign(query, defaults()); search(); }
async function search() {
  const requestSequence = ++sequence;
  const snapshot = { ...query, platforms: [...query.platforms], store_ids: [...query.store_ids], date_range: [...(query.date_range || [])] };
  loading.value = true; error.value = '';
  try {
    const response = await fetchBusinessOverview({ ...snapshot, platforms: snapshot.platforms.join(','), store_ids: snapshot.store_ids.join(',') });
    if (requestSequence !== sequence) return;
    if (!response?.success) throw new Error(formatApiError(response));
    if (response.data?.api_status !== 'connected') throw new Error('经营接口未返回实时数据，请检查接口后重试；本页不使用模拟数据代替真实经营结果。');
    data.value = response.data || {};
    applied.value = snapshot;
  } catch (failure) {
    if (requestSequence !== sequence) return;
    data.value = {};
    error.value = formatApiError(failure?.response || { message: failure.message });
  } finally { if (requestSequence === sequence) loading.value = false; }
}
onMounted(async () => {
  search();
  try {
    const response = await fetchBusinessFilters();
    if (!response?.success) throw new Error(formatApiError(response));
    options.value = response.data || {};
  } catch { filterError.value = '筛选选项加载失败，请刷新页面重试。经营数据仍按当前授权范围展示。'; }
});
</script>

<style scoped>
.business-overview, .report-content { display: grid; gap: 16px; min-width: 0; color: #172033; }
.page-heading, .store-report header, .currency-heading, .scope-line { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
.page-heading h1 { margin: 0; font-size: 24px; }
.page-heading p, .store-report p { margin: 6px 0 0; color: #526177; font-size: 13px; }
.business-filters { display: grid; grid-template-columns: repeat(3, minmax(150px, 1fr)) minmax(360px, 2fr); align-items: end; gap: 12px; padding: 16px; background: #fff; border: 1px solid #dce3ec; border-radius: 6px; }
.business-filters :deep(.el-form-item) { min-width: 0; margin: 0; }
.business-filters :deep(.el-form-item__label) { font-size: 12px; color: #475569; margin-bottom: 6px; }
.business-filters :deep(.el-select), .business-filters :deep(.el-date-editor) { width: 100%; min-width: 0; }
.date-controls { display: grid; width: 100%; gap: 6px; }
.quick-dates { display: flex; }
.quick-dates button { border: 1px solid #dce3ec; background: #fff; color: #334155; padding: 6px 10px; cursor: pointer; }
.quick-dates button + button { margin-left: -1px; }
.quick-dates button[aria-pressed=true] { position: relative; color: #513ab9; border-color: #6952d9; background: #f4f1ff; }
.quick-dates button:focus-visible, .metric-groups:focus-visible { outline: 2px solid #5941c6; outline-offset: 2px; }
.filter-actions { grid-column: 1/-1; display: flex; justify-content: flex-end; }
.scope-line, .data-note, .currency-heading > span, .store-report header > span { font-size: 12px; color: #526177; }
.data-note { margin: 0; line-height: 1.6; }
.business-metrics { margin: 0 18px 12px; }
.currency-heading h2, .store-report h2 { font-size: 15px; margin: 0; }
.currency-heading h2 span { margin-left: 8px; color: #513ab9; }
.metric-groups { display: flex; overflow-x: auto; gap: 24px; padding: 16px 0; }
.metric-group { flex-shrink: 0; }
.metric-group h3 { font-size: 13px; margin: 0 0 10px; }
.metric-list { display: flex; }
.metric-list button { width: 222px; padding: 12px 16px; border: 1px solid #dce3ec; border-top: 3px solid transparent; border-radius: 4px; margin-right: 6px; background: #fff; text-align: left; font: inherit; color: inherit; cursor: pointer; }
.metric-list button[aria-pressed=true] { border-top-color: var(--series-color); background: #f8faff; }
.metric-list button:focus-visible { outline: 2px solid #5941c6; outline-offset: 2px; }
.metric-list button > span { color: #475569; font-size: 12px; }
.metric-list strong { display: block; margin: 10px 0; font-size: 23px; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
.selection-state { display: flex; align-items: center; gap: 6px; margin-top: 9px; }
.selection-state i { width: 8px; height: 8px; background: #94a3b8; }
.metric-list button[aria-pressed=true] .selection-state i { background: var(--series-color); }
.metric-group small { font-size: 11px; font-weight: 400; color: #526177; }
.metric-group p { font-size: 11px; line-height: 1.5; color: #526177; margin: 0; }
.store-report { min-width: 0; padding: 18px; background: #fff; border: 1px solid #dce3ec; border-radius: 6px; }
.store-report header { margin-bottom: 16px; }
.quality-details { color: #475569; font-size: 12px; line-height: 1.7; }
.quality-details summary { cursor: pointer; }
.quality-details p { max-width: 100ch; }
@media (max-width: 1200px) { .business-filters { grid-template-columns: repeat(3, minmax(0, 1fr)); } .date-filter { grid-column: 1/-1; } .date-controls { display: flex; flex-wrap: wrap; } .date-controls :deep(.el-date-editor) { flex: 1; min-width: 260px; } }
@media (max-width: 600px) { .business-filters { grid-template-columns: 1fr; padding: 12px; } .filter-actions :deep(.el-button) { flex: 1; min-height: 40px; } .date-controls :deep(.el-date-editor) { min-width: 0; flex-basis: 100%; } .quick-dates { width: 100%; } .quick-dates button { flex: 1; min-height: 40px; } }
</style>
