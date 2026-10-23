<template>
  <section class="operations" :aria-busy="loading">
    <header class="operations-head">
      <div><p class="eyebrow">日常经营 · 授权店铺</p><h1>销售工作台</h1><p>先看店铺表现，再定位下降商品及排查依据。</p></div>
      <details class="more"><summary>更多分析</summary><nav aria-label="更多销售分析"><button v-for="link in links" :key="link.path" @click="router.push(link.path)">{{ link.label }} ↗</button><button @click="$emit('legacy')">明细查询与周期分析</button></nav></details>
    </header>
    <form class="filters" @submit.prevent="apply">
      <label>平台<select v-model="draft.platform" @change="draft.store_id = ''"><option value="">全部授权平台</option><option v-for="option in platforms" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
      <label>站点<select v-model="draft.region" @change="draft.store_id = ''"><option value="">全部站点</option><option v-for="site in regions" :key="site" :value="site">{{ site }}</option></select></label>
      <label>店铺<select v-model="draft.store_id"><option value="">全部授权店铺</option><option v-for="option in stores" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
      <label>开始日期<input v-model="draft.date_from" type="date" required></label><label>结束日期<input v-model="draft.date_to" type="date" required></label>
      <button class="primary" :disabled="loading">{{ loading ? '查询中…' : '查询' }}</button>
      <div class="quick" role="group" aria-label="快捷日期"><button v-for="days in [1,7,30]" :key="days" type="button" @click="quick(days)">{{ days === 1 ? '昨日' : `近${days}天` }}</button></div>
    </form>
    <p v-if="dirty" class="note">筛选已修改，点击查询后生效；下方仍为上次查询范围。</p>
    <div v-if="filterError" role="status" class="notice">{{ filterError }} <button @click="loadFilters">重试筛选目录</button></div>
    <div v-if="error" role="alert" class="notice error">{{ error }} <button :disabled="loading" @click="load">重试</button></div>
    <div class="view-strip"><strong>{{ applied.date_from }} — {{ applied.date_to }}</strong><span>对比前一等长区间 · 店铺当地业务日期</span><span class="snapshot-state">今日09:00同时段：待接入快照</span></div>
    <template v-if="data">
      <div class="currency-bar"><label>币种<select v-model="currency" @change="changeCurrency"><option value="">按各币种查看</option><option v-for="group in data.currency_groups" :key="group.currency" :value="group.currency">{{ group.currency }}</option></select></label><span>不同币种分别合计；ROI = 同范围GMV ÷ 广告花费</span></div>
      <div class="summary-grid"><article v-for="group in visibleGroups" :key="group.currency" class="summary-card"><div><span>{{ view === 'stores' ? '非取消订单GMV' : '商品行GMV' }}</span><b>{{ group.currency }}</b></div><strong>{{ amount(group.sales_amount) }}</strong><p :class="direction(group.change_percent)">{{ percent(group.change_percent) }} <span>较前一等长区间</span></p><dl><div><dt>广告花费</dt><dd>{{ amount(group.ad_spend) }} {{ group.currency }}</dd></div><div><dt>整店ROI</dt><dd>{{ amount(group.roi) }} 倍 <small>变化 {{ delta(group.roi_delta) }} 倍</small></dd></div></dl><p class="note">{{ group.ad_reason || '已入库数据，后续补采可能调整。' }}</p></article></div>
      <div v-for="(notice,index) in data.notices || []" :key="index" class="notice">{{ typeof notice === 'string' ? notice : notice.message }}</div>
      <section class="results">
        <div class="results-head"><div><h2>{{ view === 'stores' ? '店铺经营表现' : `${selectedStoreName} · 商品链接` }}</h2><p>{{ view === 'stores' ? '点击店铺进入商品链接；按GMV降序，单页最多20条。' : '按商品行金额汇总，不含订单层运费税费；点击下降原因查看证据。' }}</p></div><button v-if="view === 'products'" @click="backToStores">← 返回店铺</button></div>
        <div v-if="loading" class="loading" role="status">正在读取当前范围…</div>
        <div v-else-if="!data.rows?.length" class="empty">当前授权范围暂无可展示记录。缺少记录不代表销量为零或没有异常。</div>
        <div v-else class="table-scroll" tabindex="0" aria-label="经营明细表，可横向滚动"><table><thead><tr><th>{{ view === 'stores' ? '店铺 / 国家' : '商品 / 平台商品ID' }}</th><th>GMV / 币种</th><th>前期GMV</th><th>变化</th><th>{{ view === 'stores' ? '订单' : '销量' }}</th><th v-if="view === 'stores'">广告花费</th><th v-if="view === 'stores'">整店ROI / 差值</th><th v-else>下降原因</th></tr></thead><tbody><tr v-for="row in data.rows" :key="`${row.store_id}-${row.product_id || ''}-${row.currency}`"><td><button v-if="view === 'stores'" class="text-button" :disabled="!canProducts" :title="canProducts ? '查看商品链接' : '需SKU销售明细权限'" @click="openStore(row)">{{ row.store_name }}</button><strong v-else>{{ row.product_name || '未命名商品' }}</strong><small>{{ view === 'stores' ? row.country : row.product_id }}</small><small v-if="row.observation_status === 'missing_current'">本期未观测，需核查采集</small></td><td>{{ amount(row.sales_amount) }} <small>{{ row.currency }}</small></td><td>{{ amount(row.previous_sales_amount) }}</td><td :class="direction(row.change_percent)">{{ percent(row.change_percent) }}</td><td>{{ (view === 'stores' ? row.order_count : row.units_sold) ?? '—' }} {{ view === 'stores' ? '单' : '件' }}</td><td v-if="view === 'stores'">{{ amount(row.ad_spend) }}</td><td v-if="view === 'stores'">{{ amount(row.roi) }} 倍<small>{{ delta(row.roi_delta) }} 倍</small></td><td v-else><button class="reason-button" :class="{ flagged: row.diagnosis?.status === 'suspected_decline' }" @click="openReason(row)">{{ row.diagnosis?.title || '查看排查依据' }}</button></td></tr></tbody></table></div>
        <div class="pagination"><span>第 {{ page }} 页 · 每页 {{ pageSize }} 条<span v-if="data.truncated"> · 数据超过范围上限，请缩小筛选</span></span><button :disabled="loading || page === 1" @click="goPage(-1)">上一页</button><button :disabled="loading || !data.has_next" @click="goPage(1)">下一页</button></div>
      </section>
      <p class="note">按已入库数据比较，采集完整性未确认；零基准、缺失日期不生成变化率。{{ data.generated_at ? `生成时间：${data.generated_at}` : '' }}</p>
    </template>
    <div v-else-if="loading" class="empty" role="status">正在读取店铺经营汇总…</div>
    <dialog ref="reasonDialog" class="reason-dialog" @close="reason = null" @click="closeBackdrop"><template v-if="reason"><header><div><p class="eyebrow">LX 巡店SOP · 排查依据</p><h2>{{ reason.product_name || reason.product_id }}</h2></div><button aria-label="关闭原因详情" @click="reasonDialog?.close()">关闭</button></header><p>{{ selectedStoreName }} · {{ applied.date_from }} — {{ applied.date_to }} · {{ reason.currency }}</p><div class="reason-layout"><section><h3>触发与对比</h3><dl><div><dt>本期商品GMV</dt><dd>{{ amount(reason.sales_amount) }} {{ reason.currency }}</dd></div><div><dt>前期商品GMV</dt><dd>{{ amount(reason.previous_sales_amount) }} {{ reason.currency }}</dd></div><div><dt>变化率</dt><dd :class="direction(reason.change_percent)">{{ percent(reason.change_percent) }}</dd></div></dl><p class="note">单日GMV较前日下降超过30%时进入LX排查；其他日期范围仅展示变化。</p></section><section><h3>判断路径</h3><ol><li v-for="(step,index) in reason.diagnosis?.steps || []" :key="index"><strong>{{ step.label }}</strong><p>{{ step.value ?? '缺少数据，暂不能判断' }}</p></li></ol><div class="notice"><strong>{{ reason.diagnosis?.title || '原因待核查' }}</strong><p>变化命中不等于已证实原因。买家、访客、转化、缺货等证据未齐时，不推断经营原因。</p></div><p v-if="reason.diagnosis?.missing?.length" class="note">待补数据：{{ reason.diagnosis.missing.join('、') }}</p></section></div></template></dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { canAccessPath } from '../../router/menu';
import { fetchSalesOperations } from '../../api/salesOperations';
import { fetchBoardFilters } from '../../api/realtimeBoard';
import { amount, percent, delta, dateRange, validRange } from './salesOperations';
defineEmits(['legacy']);
type Row = Record<string, any>;
const router = useRouter(), route = useRoute(), auth = useAuthStore();
const draft = reactive({ ...dateRange(1), platform: '', store_id: '', region: '' });
if (route.query.view === 'operations' && typeof route.query.date_from === 'string' && typeof route.query.date_to === 'string') { const dates = { date_from: route.query.date_from, date_to: route.query.date_to }; if (!validRange(dates)) Object.assign(draft, dates); }
const applied = ref({ ...draft }), view = ref('stores'), page = ref(1), pageSize = 20;
const data = ref<Row | null>(null), filters = ref<Row>({}), loading = ref(false), error = ref(''), filterError = ref(''), currency = ref('');
const parentScope = ref<Row | null>(null);
const selectedStoreName = ref(''), reason = ref<Row | null>(null), reasonDialog = ref<HTMLDialogElement | null>(null);
let alive = true, controller: AbortController | null = null, generation = 0;
const options = (values: any[] = []) => values.map(v => typeof v === 'string' ? { value: v, label: v } : { ...v, value: v.value ?? v.id, label: v.label ?? v.name });
const platforms = computed(() => options(filters.value.platforms));
const stores = computed(() => options(filters.value.stores).filter(v => (!draft.platform || !v.platform || v.platform === draft.platform) && (!draft.region || (v.country_code || v.country || v.region) === draft.region)));
const regions = computed(() => [...new Set(options(filters.value.stores).map(v => v.country_code || v.country || v.region).filter(Boolean))].sort());
const canProducts = computed(() => canAccessPath(auth.currentUser, '/sales-management/skus'));
const dirty = computed(() => JSON.stringify(draft) !== JSON.stringify(applied.value));
const visibleGroups = computed(() => (data.value?.currency_groups || []).filter((g: Row) => !currency.value || g.currency === currency.value));
const links = computed(() => [
  { path: '/sales-management/realtime-board', label: '实时数据大屏' },
  { path: '/sales-management/stores', label: '门店销售明细' },
  { path: '/sales-management/skus', label: 'SKU销售明细' },
  { path: '/sales-management/exports', label: '销售明细导出' }
].filter(link => canAccessPath(auth.currentUser, link.path)));
const direction = (value: any) => value == null ? '' : Number(value) < 0 ? 'negative' : Number(value) > 0 ? 'positive' : '';
async function load() {
  const id = ++generation; controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''; data.value = null; reasonDialog.value?.close();
  try {
    const response = await fetchSalesOperations({ ...applied.value, view: view.value, page: page.value, page_size: pageSize, ...(currency.value ? { currency: currency.value } : {}) }, controller.signal);
    if (!alive || generation !== id) return;
    if (!response?.success) throw new Error(response?.message || '经营数据暂不可用。');
    data.value = response.data;
  } catch (failure: any) { if (alive && generation === id) error.value = failure?.message || '经营数据暂不可用，请重试。'; }
  finally { if (alive && generation === id) loading.value = false; }
}
function apply() { const message = validRange(draft); if (message) { error.value = message; return; } applied.value = { ...draft }; view.value = 'stores'; page.value = 1; currency.value = ''; load(); }
function quick(days: number) { Object.assign(draft, dateRange(days)); apply(); }
function openStore(row: Row) { if (!canProducts.value) return; parentScope.value = { ...applied.value, currency: currency.value }; applied.value = { ...applied.value, store_id: String(row.store_id) }; draft.store_id = String(row.store_id); selectedStoreName.value = row.store_name; view.value = 'products'; currency.value = row.currency; page.value = 1; load(); }
function backToStores() { if (parentScope.value) { const { currency: previousCurrency, ...scope } = parentScope.value; applied.value = scope as typeof applied.value; Object.assign(draft, scope); currency.value = previousCurrency; } view.value = 'stores'; page.value = 1; load(); }
function changeCurrency() { page.value = 1; load(); }
function goPage(step: number) { page.value += step; load(); }
function openReason(row: Row) { reason.value = row; reasonDialog.value?.showModal(); }
function closeBackdrop(event: MouseEvent) { if (event.target === reasonDialog.value) { const rect = reasonDialog.value!.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) reasonDialog.value?.close(); } }
async function loadFilters() { filterError.value = ''; try { const response = await fetchBoardFilters(); if (!alive) return; if (!response.success || ['mock','degraded'].includes(response.data?.api_status)) throw new Error(); filters.value = response.data; } catch { if (alive) filterError.value = '店铺筛选暂不可用，当前仍按系统授权范围查询。'; } }
onMounted(() => { load(); loadFilters(); });
watch(() => [route.query.view, route.query.date_from, route.query.date_to], ([mode, from, to]) => {
  if (mode !== 'operations' || typeof from !== 'string' || typeof to !== 'string') return;
  const dates = { date_from: from, date_to: to };
  if (validRange(dates) || from === applied.value.date_from && to === applied.value.date_to) return;
  Object.assign(draft, dates); apply();
});
onBeforeUnmount(() => { alive = false; ++generation; controller?.abort(); });
</script>

<style scoped>
.operations{color:#243247;padding:8px 4px;font-size:14px}.operations-head,.results-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.operations-head h1{font-size:26px;margin:6px 0}.operations-head p,.results-head p{color:#65758a;margin:6px 0;line-height:1.6}.eyebrow{font-size:12px;color:#527696!important}.operations button,.operations input,.operations select,.operations summary{font:inherit;border:1px solid #d5dfeb;border-radius:6px;background:white;padding:9px 12px;color:#33465d}.operations button,.operations summary{cursor:pointer}.operations button:disabled{opacity:.5;cursor:default}.operations button:focus-visible,.operations input:focus-visible,.operations select:focus-visible,.operations summary:focus-visible{outline:2px solid #3478d4;outline-offset:3px}.operations .primary{background:#2864b4;color:white;border-color:#2864b4}.more{position:relative;flex-shrink:0}.more nav{position:absolute;right:0;z-index:5;padding:8px;background:white;box-shadow:0 8px 28px #23354d20;border:1px solid #dce4ee;border-radius:8px;min-width:210px}.more nav button{display:block;text-align:left;width:100%;border:0}.more nav button:hover{background:#f0f5fc}.filters{display:flex;align-items:flex-end;gap:12px;flex-wrap:wrap;margin-top:24px;padding:18px;background:#f6f8fc;border:1px solid #e0e7f0;border-radius:10px}.filters label{display:grid;gap:7px;font-size:12px;color:#5f7087}.filters select{max-width:220px;min-width:150px}.quick{display:flex;gap:6px}.view-strip,.currency-bar{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:20px 0;color:#64748b;font-size:12px}.view-strip strong{color:#33465d}.snapshot-state{margin-left:auto;background:#eef2f6;border-radius:4px;padding:6px 9px}.currency-bar{justify-content:space-between}.currency-bar label{display:flex;align-items:center;gap:8px}.summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}.summary-card{padding:22px;border:1px solid #dae4ef;border-radius:10px;background:white}.summary-card>div:first-child{display:flex;justify-content:space-between;color:#63758a;font-size:13px}.summary-card>strong{display:block;font-size:30px;margin:18px 0 12px;font-variant-numeric:tabular-nums}.summary-card dl{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:16px 0 6px}.summary-card dl>div{display:block;padding:0}.summary-card dd{text-align:left;margin-top:8px}.summary-card p span{color:#718096;font-size:12px;margin-left:5px}dl{margin:18px 0}dl>div{display:flex;justify-content:space-between;gap:14px;padding:8px 0}dt{color:#66778c}dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}dd small{display:block;color:#6d7f92;margin-top:5px}.note{font-size:12px;color:#718196;line-height:1.7}.notice{padding:12px 16px;margin:12px 0;background:#fff9ed;color:#805f26;border:1px solid #eeddb6;border-radius:6px;line-height:1.7}.notice button{font-size:12px;padding:5px 9px;margin-left:10px}.notice.error{background:#fff2f2;color:#a64040;border-color:#f3cece}.results{margin-top:24px;border:1px solid #e0e7ef;background:white;border-radius:10px;overflow:hidden}.results-head{padding:20px}.results-head h2{font-size:17px;margin:0}.results-head p{font-size:12px}.table-scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:16px;text-align:right;border-top:1px solid #e8edf4;white-space:nowrap}th{background:#f8fafc;color:#65758b;font-weight:500}th:first-child,td:first-child{text-align:left;min-width:200px;max-width:320px}td:first-child strong{display:block;overflow:hidden;text-overflow:ellipsis;max-width:300px}td small{display:block;color:#718196;font-size:11px;margin-top:5px}.operations .text-button{border:0;background:none;color:#2864b4;padding:0;text-align:left;font-weight:600;max-width:280px;overflow:hidden;text-overflow:ellipsis}.operations .reason-button{font-size:12px;padding:7px 10px}.operations .reason-button.flagged{color:#a34d24;background:#fff5e9;border-color:#f0d2ab}.negative{color:#c64a43}.positive{color:#16856c}.pagination{display:flex;align-items:center;justify-content:flex-end;gap:10px;padding:16px;border-top:1px solid #e8edf4;font-size:12px;color:#687a90}.pagination>span{margin-right:auto}.pagination button{font-size:12px;padding:6px 10px}.empty,.loading{padding:45px 20px;text-align:center;color:#718196}.reason-dialog{width:min(940px,calc(100vw - 40px));max-height:85vh;overflow:auto;border:0;border-radius:12px;padding:26px;color:#243247;box-shadow:0 20px 100px #15284440}.reason-dialog::backdrop{background:#15284466}.reason-dialog header{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.reason-dialog h2{font-size:20px;margin:4px 0}.reason-dialog>p{color:#718196;font-size:12px}.reason-layout{display:grid;grid-template-columns:1fr 1.35fr;gap:24px;margin-top:24px}.reason-layout section{padding:18px;border:1px solid #e0e7ef;border-radius:8px}.reason-layout h3{font-size:14px;margin:0 0 14px}.reason-layout li{padding-bottom:8px;font-size:13px}.reason-layout li p{color:#65758b;line-height:1.6}@media(max-width:760px){.operations-head{gap:10px}.operations-head h1{font-size:22px}.filters{padding:12px;gap:10px}.filters label{flex:1;min-width:130px}.filters select,.filters input{width:100%;max-width:100%;box-sizing:border-box;min-width:0}.snapshot-state{margin-left:0}.quick{width:100%}.summary-card{padding:16px}.reason-layout{grid-template-columns:1fr}.reason-dialog{padding:18px;box-sizing:border-box}.results-head{padding:14px}.pagination{flex-wrap:wrap}}
</style>
