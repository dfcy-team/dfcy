<template>
  <section class="overview-analysis" aria-label="销售表现分析">
    <div v-if="showTabs" class="analysis-tabs" role="tablist" aria-label="总览视图">
      <button v-for="item in tabs" :id="`${panelId}-${item.key}`" :key="item.key" role="tab" :aria-selected="view === item.key" :aria-controls="panelId" :tabindex="view === item.key ? 0 : -1" @click="view = item.key" @keydown="changeTab($event, item.key)">{{ item.label }}</button>
    </div>
    <div class="analysis-toolbar">
      <h2 :id="`${panelId}-heading`">{{ storeReport ? '店铺概览' : reportKind === 'skus' ? '商品销量汇总' : reportKind === 'overview' ? '汇总数据' : view === 'trend' ? '时间趋势' : '区间统计' }}<span v-if="reportKind === 'overview'" class="summary-currency">（{{ currency || '暂无币种' }}）</span></h2>
      <div class="analysis-controls">
        <slot name="date-controls" />
        <label v-if="view === 'trend'" class="chart-toggle"><input v-model="showChart" type="checkbox">显示图表</label>
      </div>
    </div>
    <slot name="metrics" :selected="selected" :toggle="toggleSeries" :color="seriesColor"><section class="performance" aria-label="销售表现">
      <div class="performance-heading"><h3 v-if="reportKind !== 'overview'">汇总数据 <span>当前筛选范围 · {{ currency || '暂无币种' }} · 无同期对比</span></h3><div v-if="cards.length > 3" class="metric-navigation"><button aria-label="上一组指标" @click="scrollMetrics(-1)">‹</button><button aria-label="下一组指标" @click="scrollMetrics(1)">›</button></div></div>
      <div v-if="cards.length" ref="metricStrip" class="performance-strip" tabindex="0" aria-label="横向滚动查看销售指标">
        <component :is="cardControls ? 'button' : 'article'" v-for="metric in cards" :key="metric.code" class="performance-metric" :class="{ 'metric-toggle': cardControls }" :type="cardControls ? 'button' : undefined" :aria-pressed="cardControls ? selected.includes(metric.code) : undefined" :style="cardControls ? { '--series-color': seriesColor(metric.code) } : undefined" @click="cardControls && toggleSeries(metric.code)">
          <span>{{ metric.label }}</span><strong>{{ metric.display }} <small>{{ metric.unit }}</small></strong>
          <p>{{ metric.definition || '当前筛选口径' }}</p>
          <span v-if="cardControls" class="metric-selection"><i />{{ selected.includes(metric.code) ? '已显示' : '已隐藏' }}</span>
        </component>
      </div>
      <p v-else class="overview-note">当前范围尚无销售汇总，请调整筛选或检查数据同步。</p>
    </section></slot>
    <div :id="panelId" :role="showTabs ? 'tabpanel' : 'region'" :aria-labelledby="`${panelId}-${showTabs ? view : 'heading'}`">
      <template v-if="view === 'trend' && showChart">
        <div v-if="!cardControls" class="chart-legend" role="group" aria-label="选择趋势指标">
          <button v-for="item in amountSeries" :key="item.key" :aria-pressed="selected.includes(item.key)" @click="toggleSeries(item.key)"><i :style="{ background: item.color }" />{{ item.label }}<span>{{ selected.includes(item.key) ? '已显示' : '已隐藏' }}</span></button>
        </div>
        <p class="axis-caption">{{ ratioMode ? '比例（%）' : `左轴：金额（${currency || '未提供币种'}）` }}<span>{{ countGeometry.hasValues ? `右轴：数量（${countUnits}）` : '点击卡片显示／隐藏曲线' }}</span></p>
        <p class="chart-date-note">日期：YYYY-MM-DD · {{ points.length }} 个有数据日期全部显示，较多时可左右滚动；缺失日期不补零。</p>
        <div v-if="geometry.hasValues" class="line-chart">
          <div class="chart-scroll" tabindex="0" aria-label="左右滚动查看全部日期">
          <svg :viewBox="`0 0 ${chartWidth} 326`" :style="{ minWidth: `${chartWidth}px` }" role="img" :aria-label="`${currency} 销售趋势，${points.length} 个日期；${storeReport ? '各日期数值可通过图表焦点查看' : `完整数值见${reportKind === 'overview' ? '订单汇总明细' : '区间统计'}`}`" @pointerleave="activePoint = null">
            <g v-for="(tick, index) in geometry.ticks" :key="index" class="chart-grid"><line x1="76" :x2="chartWidth - 100" :y1="tick.y" :y2="tick.y" /><text x="64" :y="tick.y + 4" text-anchor="end">{{ axisNumber(tick.value) }}{{ ratioMode ? '%' : '' }}</text></g>
            <g v-if="countGeometry.hasValues" class="chart-grid"><text v-for="(tick, index) in countGeometry.ticks" :key="index" :x="chartWidth - 88" :y="tick.y + 4">{{ tick.value.toLocaleString('en-US', { maximumFractionDigits: 0 }) }}</text></g>
            <g v-for="series in geometry.paths" :key="series.key" :style="{ color: seriesColor(series.key) }">
              <path :d="series.path" fill="none" stroke="currentColor" stroke-width="2.2" />
              <circle v-for="point in series.points" :key="point.date" :cx="point.x" :cy="point.y" :r="points.length < 3 ? 4 : 2.5" fill="currentColor"><title>{{ point.date }} · {{ seriesLabel(series.key) }}：{{ seriesValue(point.value, series.key, true) }}</title></circle>
            </g>
            <g class="chart-dates"><text v-for="tick in dateTicks" :key="tick.date" :x="tick.x" y="300" text-anchor="middle">{{ tick.date }}</text></g>
            <line v-if="activePoint !== null" :x1="geometry.x(activePoint)" :x2="geometry.x(activePoint)" y1="32" y2="270" stroke="#7b8799" stroke-dasharray="4 3" />
            <g v-for="(point, index) in points" :key="`hit-${point.date}`" class="chart-hit" tabindex="0" :aria-label="`${point.date}，查看各指标数值`" @pointerenter="activePoint = index" @focus="activePoint = index" @blur="activePoint = null" @keydown.esc="activePoint = null"><rect :x="geometry.x(index) - hitWidth / 2" y="32" :width="hitWidth" height="238" fill="transparent" /></g>
          </svg>
          </div>
          <div v-if="activeRow" class="chart-tooltip" :class="{ 'tooltip-right': activePoint < points.length / 2 }" role="status"><strong>{{ activeRow.date }}</strong><p v-for="item in amountSeries.filter(series => selected.includes(series.key))" :key="item.key"><i :style="{ background: item.color }" />{{ item.label }}：<b>{{ seriesValue(activeRow[item.key], item.key) }}</b></p></div>
        </div>
      <el-empty v-else :description="!points.length || amountSeries.some(item => selected.includes(item.key)) ? '当前币种暂无趋势数据，请调整筛选或检查同步状态。' : '请选择至少一个趋势指标。'" :image-size="54" />
      </template>
      <p v-else-if="view === 'trend'" class="chart-hidden-note">图表已收起，汇总数据和下方销量明细仍可查看。</p>
      <div v-else class="interval-table">
        <el-table :data="points" stripe empty-text="当前范围暂无趋势明细。">
          <el-table-column prop="date" label="日期" min-width="140" sortable />
          <el-table-column v-for="item in amountSeries" :key="item.key" :prop="item.key" :label="item.label" min-width="160" align="right" sortable><template #default="{ row }">{{ seriesValue(row[item.key], item.key) }}</template></el-table-column>
        </el-table>
      </div>
    </div>
    <details class="overview-definition"><summary>统计口径与数据说明</summary>
      <p v-if="reportKind === 'skus'">商品销售额取订单商品行金额，不等于含运费等项目的订单总金额。非取消指标排除取消订单；全部指标包含取消订单。退款金额、数量取退款商品行，按申请日期统计。店铺 SKU 按来源门店与 SKU 聚合；商品 SKU 仅按已关联的内部 SKU 合并，未关联记录保留门店边界。平均产品价格＝全部商品销售额÷全部商品销量。搜索同时影响汇总、趋势与明细。</p>
      <p v-else-if="reportKind === 'overview'">订单总量、全部订单金额包含取消订单；非取消订单销售额排除取消订单。平均订单金额＝全部订单金额÷订单总量，不是按客户计算的客单价。退款取筛选范围内全部退款事实，售后单数不等于去重订单数。概览显示所选范围最近两个有数据日期，不将缺失日期当成零。</p>
      <p v-else-if="storeReport">销售额不含取消订单；订单总量、产品销量包含取消订单。退款取全部筛选退款事实。平均订单金额＝非取消订单销售额÷订单总量，不等同于按客户计算的客单价。</p>
      <p>快捷日期截至昨天；接口按门店时区筛选。订单趋势取来源业务日期，退款趋势取 UTC 申请日期，边界日期可能不同。币种独立展示，不换算；缺失日期不补零，缺失指标显示“—”。净销售额＝非取消销售额减退款，负值表示退款高于销售额；相同数值的曲线会重合。毛利、客户、包裹及同期对比未接入。</p>
    </details>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { formatField, formatMetric } from './display';
import { aggregateTrend, amountSeries as defaultSeries, chartGeometry } from './overviewTrend';
const props = defineProps({ data: { type: Object, default: () => ({}) }, storeReport: Boolean, reportKind: { type: String, default: '' }, currencyCode: { type: String, default: '' }, chartMetrics: { type: Array, default: null } });
const cardControls = computed(() => props.storeReport || ['skus', 'overview', 'business'].includes(props.reportKind));
const tabs = [{ key: 'trend', label: '时间趋势' }, { key: 'interval', label: '区间统计' }];
const view = ref('trend');
const showTabs = computed(() => props.reportKind !== 'overview' && !props.storeReport);
watch(showTabs, visible => { if (!visible) view.value = 'trend'; }, { immediate: true });
const showChart = ref(true), activePoint = ref(null), metricStrip = ref(null);
const selected = ref(defaultSeries.map(item => item.key));
watch(() => props.reportKind, kind => { selected.value = kind === 'skus' ? ['gross_sales', 'refund_amount'] : defaultSeries.map(item => item.key); }, { immediate: true });
const seriesColors = ['#6952d9', '#008978', '#2563eb', '#bf6500', '#b33670', '#657319', '#8b4b22', '#397886', '#7557a8'];
const amountSeries = computed(() => cardControls.value ? cards.value.map((metric, index) => ({ key: metric.code, label: metric.label, color: seriesColors[index % seriesColors.length], count: ['件', '单'].includes(metric.unit), ratio: ['cancellation_rate', 'refund_rate'].includes(metric.code), unit: metric.unit })) : defaultSeries);
const ratioMode = computed(() => amountSeries.value.some(item => item.ratio && selected.value.includes(item.key)));
const currencies = computed(() => [...new Set([
  props.data.currency, ...(props.data.currency_groups || []).map(group => group.currency),
  ...(props.data.trend || []).flatMap(row => defaultSeries.flatMap(item => Object.keys(row[item.key] || {})))
].filter(Boolean))].sort());
const currency = computed(() => props.currencyCode || props.data.currency || (currencies.value.length === 1 ? currencies.value[0] : ''));
const panelId = computed(() => `overview-panel-${currency.value || 'empty'}`);
const cards = computed(() => {
  if (props.chartMetrics) return props.chartMetrics;
  const group = ((props.reportKind === 'overview' ? props.data.order_currency_groups : null) || props.data.currency_groups || []).find(item => item.currency === currency.value);
  const values = group?.metrics || ((props.data.currency === currency.value || currencies.value.length <= 1) ? props.data.metrics : []) || [];
  if (props.storeReport || ['overview', 'skus'].includes(props.reportKind)) return values.map(metric => ({ ...formatMetric(metric), label: metric.label, definition: metric.definition }));
  const order = ['order_count', 'units_sold', 'gross_sales', 'net_sales', 'refund_amount', 'average_order_value', 'refund_rate', 'valid_order_count', 'cancelled_order_count'];
  return [...values].sort((a, b) => order.indexOf(a.code) - order.indexOf(b.code)).map(formatMetric);
});
const points = computed(() => {
  const daily = props.reportKind === 'overview' ? props.data.order_daily : props.reportKind === 'business' || props.storeReport ? props.data.metric_daily : null;
  if (daily) return daily.filter(row => row.currency === currency.value).map(row => ({ ...row })).sort((a, b) => a.date.localeCompare(b.date));
  return aggregateTrend(props.data.trend, currency.value, amountSeries.value);
});
const numericPoints = computed(() => points.value.map(row => ({ ...row, ...Object.fromEntries(amountSeries.value.map(item => [item.key, row[item.key] == null ? null : Number(row[item.key]) * (item.ratio ? 100 : 1)])) })));
const chartWidth = computed(() => Math.max(1000, (points.value.length - 1) * 110 + 176));
const countUnits = computed(() => [...new Set(amountSeries.value.filter(item => item.count && selected.value.includes(item.key)).map(item => item.unit))].join('／'));
const countGeometry = computed(() => chartGeometry(numericPoints.value, amountSeries.value.filter(item => item.count && selected.value.includes(item.key)).map(item => item.key), { width: chartWidth.value - 56, integer: true }));
const geometry = computed(() => {
  const money = chartGeometry(numericPoints.value, amountSeries.value.filter(item => !item.count && selected.value.includes(item.key)).map(item => item.key), { width: chartWidth.value - 56 });
  return { ...money, paths: [...money.paths, ...countGeometry.value.paths], hasValues: money.hasValues || countGeometry.value.hasValues };
});
const activeRow = computed(() => activePoint.value === null ? null : points.value[activePoint.value]);
const hitWidth = computed(() => Math.min(80, 880 / Math.max(points.value.length, 1)));
watch([points, selected, showChart], () => { activePoint.value = null; });
const dateTicks = computed(() => points.value.map((point, index) => ({ date: point.date, x: geometry.value.x(index) })));
function seriesColor(key) { return amountSeries.value.find(item => item.key === key)?.color; }
function seriesLabel(key) { return amountSeries.value.find(item => item.key === key)?.label; }
function seriesValue(value, key, scaled = false) {
  const item = amountSeries.value.find(item => item.key === key);
  if (item?.ratio) return formatField(value == null ? null : scaled ? value / 100 : value, { format: 'ratio' });
  return `${formatField(value, { numeric: true, format: item?.count ? undefined : 'money' })} ${item?.unit || currency.value}`;
}
function toggleSeries(key) {
  if (selected.value.includes(key)) { selected.value = selected.value.filter(item => item !== key); return; }
  const ratio = !!amountSeries.value.find(item => item.key === key)?.ratio;
  selected.value = [...selected.value.filter(code => !!amountSeries.value.find(item => item.key === code)?.ratio === ratio), key];
}
function scrollMetrics(direction) { metricStrip.value?.scrollBy({ left: direction * metricStrip.value.clientWidth * .8, behavior: 'auto' }); }
function axisNumber(value) {
  const scale = Math.abs(value) >= 1e8 ? 1e8 : Math.abs(value) >= 1e4 ? 1e4 : 1;
  return `${(value / scale).toLocaleString('en-US', { maximumFractionDigits: 2 })}${scale === 1e8 ? '亿' : scale === 1e4 ? '万' : ''}`;
}
function changeTab(event, key) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  view.value = event.key === 'Home' ? 'trend' : event.key === 'End' ? 'interval' : key === 'trend' ? 'interval' : 'trend';
  event.currentTarget.parentElement.querySelector(`#${panelId.value}-${view.value}`)?.focus();
}
</script>

<style scoped>
.overview-analysis { min-width: 0; background: #fff; border: 1px solid #dce3ec; border-radius: 6px; color: #172033; }
.analysis-tabs { display: flex; gap: 28px; padding: 0 18px; border-bottom: 1px solid #e9edf3; }
.analysis-tabs button { padding: 15px 0 13px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: #475569; font: inherit; font-size: 14px; cursor: pointer; }
.analysis-tabs button[aria-selected=true] { border-bottom-color: #5941c6; color: #513ab9; font-weight: 600; }
.analysis-toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px; padding: 16px 18px; }
.analysis-toolbar h2, .performance h3 { margin: 0; font-size: 14px; }
.summary-currency { color: #526177; font-size: 12px; font-weight: 400; }
.analysis-toolbar h2 { flex-shrink: 0; }
.analysis-controls { min-width: 0; }
.performance-heading .metric-navigation { margin-left: auto; }
.analysis-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; font-size: 12px; color: #475569; }
.performance { margin: 0 18px; padding: 10px 0; background: #fff; }
.performance-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.metric-navigation { display: flex; gap: 6px; padding-bottom: 9px; }
.metric-navigation button { width: 26px; height: 26px; border: 1px solid #cbd5e1; border-radius: 50%; background: #fff; color: #475569; font-size: 20px; cursor: pointer; }
.chart-toggle { display: inline-flex; align-items: center; gap: 4px; cursor: pointer; }
.chart-toggle input { accent-color: #5941c6; }
.performance h3 { padding: 0 10px 9px; }
.performance h3 span { margin-left: 12px; color: #526177; font-size: 12px; font-weight: 400; }
.performance-strip { display: flex; gap: 6px; padding: 0 6px 8px; overflow-x: auto; }
.performance-metric { flex: 0 0 205px; padding: 13px 14px 10px; background: #fff; border: 1px solid #d7deea; border-radius: 4px; }
.performance-metric > span { font-size: 13px; color: #475569; }
.performance-metric strong { display: block; margin: 9px 0; font-size: 23px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.performance-metric small { font-size: 11px; font-weight: 400; color: #526177; }
.performance-metric p { margin: 0; font-size: 11px; line-height: 1.5; color: #526177; }
.metric-toggle { text-align: left; font: inherit; cursor: pointer; border-top: 3px solid transparent; }
.metric-toggle[aria-pressed=true] { border-top-color: var(--series-color); background: #f8faff; }
.metric-toggle .metric-selection { display: flex; align-items: center; gap: 6px; margin-top: 9px; font-size: 11px; }
.metric-selection i { width: 8px; height: 8px; background: #94a3b8; }
.metric-toggle[aria-pressed=true] .metric-selection i { background: var(--series-color); }
.chart-legend { display: flex; justify-content: center; flex-wrap: wrap; gap: 10px; padding: 18px 16px 10px; }
.chart-legend button { display: flex; align-items: center; gap: 6px; padding: 6px 9px; border: 1px solid #dce3ec; border-radius: 4px; background: #fff; color: #334155; font-size: 12px; cursor: pointer; }
.chart-legend i { width: 9px; height: 9px; }
.chart-legend span { color: #526177; font-size: 11px; }
.chart-legend button[aria-pressed=false] { background: #f1f3f7; text-decoration: line-through; }
.axis-caption { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; padding: 0 24px; color: #334155; font-size: 14px; font-weight: 500; }
.chart-date-note { margin: 0 24px 12px; color: #475569; font-size: 13px; line-height: 1.6; }
.line-chart { position: relative; padding: 0 12px; min-width: 0; }
.chart-scroll { overflow-x: auto; }
.chart-scroll:focus-visible { outline: 2px solid #5941c6; outline-offset: 2px; }
.chart-hit { outline: none; }
.chart-hit:focus rect { stroke: #6952d9; stroke-width: 1; }
.chart-tooltip { position: absolute; top: 20px; left: 60px; padding: 12px; border: 1px solid #cbd5e1; border-radius: 4px; background: #fff; color: #334155; font-size: 14px; line-height: 1.5; pointer-events: none; max-width: calc(100% - 100px); }
.chart-tooltip.tooltip-right { right: 40px; left: auto; }
.chart-tooltip p { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; margin: 7px 0 0; }
.chart-tooltip i { width: 8px; height: 8px; border-radius: 50%; }
.chart-hidden-note { padding: 20px; font-size: 13px; color: #475569; }
.line-chart svg { display: block; width: 100%; min-width: 620px; }
.chart-grid line { stroke: #dce3ec; stroke-dasharray: 4 3; }
.chart-grid text, .chart-dates text { fill: #526177; font-size: 15px; }
.interval-table { padding: 18px; }
.overview-definition { margin: 12px 18px 18px; font-size: 12px; line-height: 1.7; color: #475569; }
.overview-definition summary { cursor: pointer; width: fit-content; }
.overview-definition p { max-width: 100ch; }
.overview-note { padding: 0 10px; font-size: 13px; color: #475569; }
button:focus-visible, .performance-strip:focus-visible { outline: 2px solid #5941c6; outline-offset: 3px; }
button:hover { filter: brightness(.96); }
@media (max-width: 600px) { .performance h3 span { display: block; margin: 6px 0 0; } .analysis-toolbar { align-items: flex-start; } .performance-metric { flex-basis: 185px; } }
</style>
