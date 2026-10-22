<template>
  <section ref="screen" class="realtime-board" :aria-busy="loading">
    <header class="board-header">
      <div><span class="eyebrow">SALES COMMAND CENTER</span><h1>实时数据大屏</h1></div>
      <div class="header-actions"><span class="period-label">{{ applied.date_from }} — {{ applied.date_to }}</span><button :disabled="loading" @click="load">{{ loading ? '更新中…' : '刷新' }}</button><button @click="toggleFullscreen">{{ fullscreen ? '退出全屏' : '全屏展示' }}</button></div>
    </header>
    <form class="board-filters" @submit.prevent="apply">
      <label>平台<select v-model="draft.platform" @change="draft.store_id = ''"><option value="">全部平台</option><option v-for="item in platforms" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
      <label>店铺<select v-model="draft.store_id"><option value="">全部授权店铺</option><option v-for="item in stores" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
      <label>开始日期<input v-model="draft.date_from" type="date" required></label><label>结束日期<input v-model="draft.date_to" type="date" required></label>
      <button class="primary" :disabled="loading">查看</button>
      <span class="filter-spacer" />
      <label>币种<select v-model="currency"><option v-if="!groups.length" value="">—</option><option v-for="group in groups" :key="group.currency" :value="group.currency">{{ group.currency }}</option></select></label>
    </form>
    <div v-if="error || filterError" role="alert" class="board-notice">{{ error || filterError }}</div>
    <div v-for="(notice, index) in notices" :key="index" class="board-notice">{{ typeof notice === 'string' ? notice : notice.message }}</div>
    <div v-if="!data && loading" class="board-empty">正在读取销售数据…</div>
    <template v-else-if="current">
      <div class="kpi-grid">
        <article v-for="metric in metrics" :key="metric.label" class="kpi" :class="{ accent: metric.accent }"><span>{{ metric.label }}</span><strong>{{ metric.value }}<small v-if="metric.unit">{{ metric.unit }}</small></strong><p>{{ metric.description }}</p></article>
      </div>
      <div class="board-grid">
        <article class="board-panel trend-panel"><div class="panel-heading"><h2>{{ trendMetric === 'sales_amount' ? '销售趋势' : '订单趋势' }}</h2><div class="trend-switch"><button :aria-pressed="trendMetric === 'sales_amount'" @click="trendMetric = 'sales_amount'">销售额</button><button :aria-pressed="trendMetric === 'order_count'" @click="trendMetric = 'order_count'">订单量</button></div><span>{{ trendMetric === 'sales_amount' ? currency : '单' }} · 按日</span></div>
          <div v-if="!trend.length" class="board-empty">所选日期暂无销售趋势</div>
          <div v-else class="trend-chart"><div class="chart-ceiling">{{ trendMetric === 'sales_amount' ? money(trendMax) : number(trendMax) }}</div><svg viewBox="0 0 800 220" role="img" :aria-label="trendMetric === 'sales_amount' ? '按日销售额趋势' : '按日订单量趋势'"><defs><linearGradient id="board-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#55d6be" stop-opacity=".24"/><stop offset="100%" stop-color="#55d6be" stop-opacity="0"/></linearGradient></defs><path d="M 20 20 H 780 M 20 100 H 780 M 20 200 H 780" stroke="#26354b" fill="none" stroke-dasharray="4 6"/><path :d="areaPath" fill="url(#board-area)"/><polyline :points="points" fill="none" stroke="#55d6be" stroke-width="3"/><circle v-for="(point, index) in chartPoints" :key="index" :cx="point.x" :cy="point.y" r="4" fill="#55d6be"><title>{{ trend[index].date }} · {{ trend[index][trendMetric] }} {{ trendMetric === 'sales_amount' ? currency : '单' }}</title></circle></svg><div class="chart-labels"><span>{{ trend[0]?.date }}</span><span>{{ trend.at(-1)?.date }}</span></div></div>
          <div class="trend-footer"><span>{{ trendMetric === 'sales_amount' ? '非取消销售额' : '订单总量（含取消订单）' }}</span><button v-if="canOrders" @click="drillOrders()">查看销售订单 ↗</button></div>
        </article>
        <article class="board-panel"><div class="panel-heading"><h2>广告投入占比</h2><span>广告费率</span></div><div class="ad-focus"><div class="ad-ring"><strong>{{ rate(current.ad_rate) }}</strong></div><p>广告消耗 ÷ 非取消销售额</p><span>{{ current.ad_reason || '广告与销售按同一查询范围计算' }}</span></div><div class="ad-detail"><span>广告消耗</span><strong>{{ money(current.ad_spend) }} {{ currency }}</strong></div><button v-if="canAds && current.ad_store_ids?.length" class="text-action" @click="drillAds">查看广告明细 ↗</button></article>
        <article class="board-panel"><div class="panel-heading"><h2>店铺贡献 TOP 10</h2><span>按销售额</span></div><div v-if="!storeRanking.length" class="board-empty">暂无店铺销售数据</div><ol v-else class="store-ranking"><li v-for="(row, index) in storeRanking" :key="row.store_id"><div class="rank-number">{{ String(index + 1).padStart(2, '0') }}</div><div class="store-detail"><div><button :disabled="!canOrders" @click="drillOrders({ store_id: row.store_id })">{{ row.store_name || '未命名店铺' }}</button><strong>{{ money(row.sales_amount) }}</strong></div><div class="rank-track"><span :style="{ width: rankWidth(row.sales_amount) + '%' }" /></div></div></li></ol></article>
        <article class="board-panel product-panel"><div class="panel-heading"><h2>商品排行 TOP 10</h2><span>按销售额 · 全部商品</span></div><div v-if="!skuRanking.length" class="board-empty">暂无商品销售数据</div><div v-else class="product-table"><table><thead><tr><th>排名／商品</th><th>销量</th><th>销售额 {{ currency }}</th></tr></thead><tbody><tr v-for="(row, index) in skuRanking" :key="row.sku"><td><span class="product-rank">{{ index + 1 }}</span><button :disabled="!canOrders || !row.sku" @click="drillOrders({ sku: row.sku })"><strong>{{ row.name || row.sku || '未关联商品' }}</strong><small>{{ row.sku }}</small></button></td><td>{{ number(row.units_sold) }}</td><td>{{ money(row.sales_amount) }}</td></tr></tbody></table></div></article>
      </div>
    </template>
    <div v-else-if="!loading && !error" class="board-empty">所选范围暂无销售数据，请调整日期或店铺。</div>
    <footer class="board-footnote">销售金额采用非取消订单口径。不同币种分开展示；广告费率不代表利润回报。{{ current?.product_classification_note || data?.product_classification_note || '' }}</footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { fetchRealtimeBoard, fetchBoardFilters } from '../../api/realtimeBoard';
import { useAuthStore } from '../../stores/auth';
import { canAccessPath } from '../../router/menu';

type Row = Record<string, any>;
const auth = useAuthStore(), router = useRouter();
const screen = ref<HTMLElement | null>(null), fullscreen = ref(false);
const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
const draft = reactive({ platform: '', store_id: '', date_from: today(), date_to: today() });
const applied = ref({ ...draft }), data = ref<Row | null>(null), currency = ref('');
const trendMetric = ref('sales_amount');
const loading = ref(false), error = ref(''), filterError = ref(''), filterData = ref<Row>({});
let controller: AbortController | null = null, timer: ReturnType<typeof setTimeout> | null = null, generation = 0, alive = true;
let failedRefreshes = 0;
const groups = computed<Row[]>(() => data.value?.currency_groups || []);
const current = computed(() => groups.value.find(row => row.currency === currency.value));
const notices = computed(() => data.value?.notices || []);
const options = (values: any[]) => (values || []).map(item => typeof item === 'string' ? { value: item, label: item } : { ...item, value: item.value ?? item.id, label: item.label ?? item.name });
const platforms = computed(() => options(filterData.value.platforms));
const stores = computed(() => options(filterData.value.stores).filter(item => !draft.platform || !item.platform || item.platform === draft.platform));
const canOrders = computed(() => canAccessPath(auth.currentUser, '/sales-management/orders'));
const canAds = computed(() => canAccessPath(auth.currentUser, '/analytics/advertising-overview'));
const finite = (value: any) => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
const number = (value: any) => finite(value) ? Number(value).toLocaleString('zh-CN') : '—';
const money = (value: any) => finite(value) ? Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—';
const rate = (value: any) => finite(value) ? `${Number(value).toFixed(2)}%` : '—';
const metrics = computed(() => [
  { label: '非取消销售额', value: money(current.value?.sales_amount), unit: currency.value, description: '含运费、税费等以来源口径为准', accent: true },
  { label: '订单总量', value: number(current.value?.order_count), unit: '单', description: '当前查询范围内订单' },
  { label: '有效订单', value: number(current.value?.valid_order_count), unit: '单', description: '排除取消订单' },
  { label: '商品销量', value: number(current.value?.units_sold), unit: '件', description: '非取消订单商品件数' },
  { label: '广告费率', value: rate(current.value?.ad_rate), description: current.value?.ad_reason || '广告消耗 / 非取消销售额', accent: true }
]);
const trend = computed<Row[]>(() => current.value?.trend || []), storeRanking = computed<Row[]>(() => current.value?.store_ranking || []), skuRanking = computed<Row[]>(() => current.value?.sku_ranking || []);
const trendMax = computed(() => Math.max(1, ...trend.value.map(row => Number(row[trendMetric.value]) || 0)));
const chartPoints = computed(() => trend.value.map((row, index) => ({ x: trend.value.length === 1 ? 400 : 20 + index * 760 / (trend.value.length - 1), y: 200 - Math.max(0, Number(row[trendMetric.value]) || 0) * 180 / trendMax.value })));
const points = computed(() => chartPoints.value.map(p => `${p.x},${p.y}`).join(' '));
const areaPath = computed(() => chartPoints.value.length ? `M ${chartPoints.value[0].x} 200 L ${chartPoints.value.map(p => `${p.x} ${p.y}`).join(' L ')} L ${chartPoints.value.at(-1)?.x} 200 Z` : '');
const rankWidth = (amount: any) => Math.max(0, Number(amount) || 0) / Math.max(1, ...storeRanking.value.map(row => Number(row.sales_amount) || 0)) * 100;
function stopTimer() { if (timer) clearTimeout(timer); timer = null; }
function schedule() { stopTimer(); if (alive && !document.hidden) timer = setTimeout(load, 60000); }
async function load() {
  if (!alive || document.hidden || loading.value) return;
  stopTimer(); const sequence = ++generation;
  controller = new AbortController(); loading.value = true;
  try {
    const response = await fetchRealtimeBoard({ ...applied.value }, controller.signal);
    if (!alive || sequence !== generation) return;
    if (!response?.success) throw new Error(response?.message || '销售数据暂不可用，请稍后重试。');
    data.value = response.data; error.value = ''; failedRefreshes = 0;
    if (!groups.value.some(group => group.currency === currency.value)) currency.value = groups.value[0]?.currency || '';
  } catch (failure: any) {
    if (alive && sequence === generation) {
      failedRefreshes += 1;
      if (failedRefreshes >= 3) data.value = null;
      error.value = data.value ? '更新暂未完成，当前保留上次结果。请稍后重试。' : failure.message;
    }
  } finally { if (alive && sequence === generation) { loading.value = false; schedule(); } }
}
function apply() {
  if (!draft.date_from || !draft.date_to || draft.date_from > draft.date_to) { error.value = '请选择有效的起止日期。'; return; }
  if ((Date.parse(draft.date_to) - Date.parse(draft.date_from)) / 86400000 > 30) { error.value = '单次最多查询31天，请缩小日期范围。'; return; }
  ++generation; controller?.abort(); loading.value = false; data.value = null; error.value = ''; failedRefreshes = 0; applied.value = { ...draft }; load();
}
function drillOrders(extra: Row = {}) { if (canOrders.value) router.push({ path: '/sales-management/orders', query: { ...applied.value, currency: currency.value, ...(Object.keys(extra).length ? { exclude_cancelled: 'true' } : {}), ...(extra.sku ? { sku_exact: 'true' } : {}), ...extra } }); }
function drillAds() { if (canAds.value && current.value?.ad_store_ids?.length) router.push({ path: '/analytics/advertising-overview', query: { ...applied.value, currency: currency.value, platform: 'shopee', store_ids: current.value.ad_store_ids.join(',') } }); }
async function toggleFullscreen() { try { if (document.fullscreenElement) await document.exitFullscreen(); else await screen.value?.requestFullscreen(); } catch { error.value = '当前浏览器暂不支持全屏，请使用浏览器全屏功能。'; } }
function syncFullscreen() { fullscreen.value = document.fullscreenElement === screen.value; }
function visibility() { if (document.hidden) { stopTimer(); ++generation; controller?.abort(); loading.value = false; } else load(); }
onMounted(() => {
  document.addEventListener('visibilitychange', visibility); document.addEventListener('fullscreenchange', syncFullscreen);
  load();
  fetchBoardFilters().then((response: Row) => { if (!alive) return; if (response.success && !['mock', 'degraded'].includes(response.data?.api_status)) filterData.value = response.data; else filterError.value = '店铺筛选暂不可用，当前展示授权范围内的数据。'; }).catch(() => { if (alive) filterError.value = '店铺筛选暂不可用。'; });
});
onBeforeUnmount(() => { alive = false; ++generation; stopTimer(); controller?.abort(); document.removeEventListener('visibilitychange', visibility); document.removeEventListener('fullscreenchange', syncFullscreen); });
</script>

<style scoped>
.trend-switch{display:flex;gap:4px;margin-left:auto}.trend-switch button{font-size:11px;padding:5px 10px;background:transparent}.trend-switch button[aria-pressed="true"]{background:#23463f;border-color:#55d6be;color:#66dfc8}
.realtime-board{--muted:#94a6bf;background:#0d1625;color:#eaf0fa;padding:28px;border-radius:12px;min-height:calc(100vh - 150px);font-family:inherit;color-scheme:dark}.realtime-board:fullscreen{overflow:auto;border-radius:0;min-height:100vh;box-sizing:border-box}.board-header,.header-actions,.board-filters,.panel-heading,.trend-footer,.ad-detail{display:flex;align-items:center;gap:14px}.board-header{justify-content:space-between;margin-bottom:24px}.eyebrow{font-size:10px;letter-spacing:3px;color:#55d6be}h1{font-size:26px;letter-spacing:2px;margin:6px 0 0}h2{font-size:15px;margin:0}.header-actions{font-size:12px;color:var(--muted)}button,select,input{font:inherit}button{cursor:pointer;border:1px solid #344359;background:#1b293d;color:#eaf0fa;border-radius:6px;padding:8px 13px}button:disabled{cursor:default;opacity:.55}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid #55d6be;outline-offset:3px}.board-filters{flex-wrap:wrap;padding:16px 0;border-top:1px solid #26354b;border-bottom:1px solid #26354b;margin-bottom:24px}.board-filters label{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted)}select,input{background:#142136;color:#eaf0fa;border:1px solid #344359;border-radius:5px;padding:8px;min-width:90px;max-width:200px}.primary{background:#55d6be;border-color:#55d6be;color:#0d1625;font-weight:600}.filter-spacer{flex:1}.kpi-grid{display:grid;grid-template-columns:1.5fr repeat(4,1fr);gap:20px;margin:28px 0}.kpi{padding:2px 20px 8px 0;border-right:1px solid #26354b;min-width:0}.kpi:last-child{border:0}.kpi>span{font-size:13px;color:var(--muted)}.kpi strong{display:block;font-size:clamp(24px,2.5vw,40px);font-variant-numeric:tabular-nums;letter-spacing:-1px;margin:14px 0 10px;overflow-wrap:anywhere}.kpi small{font-size:11px;letter-spacing:0;margin-left:6px;color:var(--muted)}.kpi p{font-size:11px;color:var(--muted);line-height:1.5;margin:0}.kpi.accent strong{color:#66dfc8}.board-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) minmax(260px,.8fr);gap:18px}.board-panel{background:#131f31;border:1px solid #243249;border-radius:8px;padding:20px;min-width:0}.trend-panel{grid-column:span 2}.panel-heading{justify-content:space-between;margin-bottom:22px}.panel-heading>span{font-size:11px;color:var(--muted)}.trend-chart svg{display:block;width:100%;height:220px}.chart-ceiling,.chart-labels{font-size:11px;color:var(--muted)}.chart-labels{display:flex;justify-content:space-between}.trend-footer{justify-content:space-between;border-top:1px solid #26354b;margin-top:20px;padding-top:14px;font-size:12px;color:#55d6be}.trend-footer button,.text-action{background:none;border:0;padding:0;color:#9ebcf6;font-size:12px}.ad-focus{text-align:center}.ad-ring{width:142px;height:142px;border-radius:50%;border:9px solid #28384f;box-shadow:inset 0 0 0 1px #3e826f;display:grid;place-items:center;margin:4px auto 18px}.ad-ring strong{font-size:30px;color:#55d6be}.ad-focus p{font-size:12px;color:var(--muted)}.ad-focus>span{display:block;color:#b4c2d6;font-size:11px;line-height:1.6;min-height:36px}.ad-detail{justify-content:space-between;border-top:1px solid #26354b;padding-top:15px;font-size:12px;margin:20px 0 12px}.ad-detail>span{color:var(--muted)}.product-panel{grid-column:span 2}.store-ranking{list-style:none;padding:0;margin:0}.store-ranking li{display:flex;gap:12px;margin:18px 0}.rank-number{font-size:12px;color:#7392b9;padding-top:3px}.store-detail{flex:1;min-width:0}.store-detail>div:first-child{display:flex;justify-content:space-between;gap:12px;font-size:12px}.store-detail button{padding:0;border:0;background:none;text-align:left;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.store-detail button:disabled,.product-table button:disabled{opacity:1}.rank-track{height:4px;background:#243249;border-radius:3px;margin-top:10px}.rank-track span{display:block;height:100%;background:linear-gradient(90deg,#3b78ba,#55d6be);border-radius:3px}.product-table{overflow:auto}table{width:100%;border-collapse:collapse;font-size:12px}th{color:var(--muted);font-weight:400;text-align:left;padding-bottom:14px}td{padding:13px 0;border-top:1px solid #26354b}td:not(:first-child),th:not(:first-child){text-align:right;white-space:nowrap;padding-left:18px}td:first-child{display:flex;gap:12px;align-items:center}.product-rank{color:#7392b9;min-width:16px}.product-table button{padding:0;border:0;background:none;text-align:left;min-width:0}.product-table strong{display:block;font-size:12px;max-width:420px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:500}.product-table small{display:block;color:var(--muted);font-size:10px;margin-top:5px}.board-notice{padding:12px 15px;border:1px solid #726044;background:#332c21;color:#f5d8a1;border-radius:6px;font-size:12px;margin-bottom:14px}.board-empty{padding:60px 20px;text-align:center;color:var(--muted);font-size:13px}.board-footnote{color:#7f94af;font-size:11px;line-height:1.7;margin-top:22px}@media(min-width:1800px){.trend-chart svg{height:290px}}@media(max-width:1100px){.board-grid{grid-template-columns:1fr 1fr}.trend-panel{grid-column:span 2}.product-panel{grid-column:span 2}.kpi-grid{grid-template-columns:repeat(3,1fr)}.header-actions .period-label{display:none}}@media(max-width:700px){.realtime-board{padding:16px}.board-header{align-items:flex-start}h1{font-size:21px}.header-actions{gap:6px}.header-actions button{padding:7px}.kpi-grid{grid-template-columns:1fr 1fr}.board-grid{grid-template-columns:1fr}.trend-panel,.product-panel{grid-column:span 1}.board-filters label{flex:1;justify-content:space-between}.board-filters label input,.board-filters label select{min-width:100px}.product-table strong{max-width:160px}.panel-heading{flex-wrap:wrap}}
</style>
