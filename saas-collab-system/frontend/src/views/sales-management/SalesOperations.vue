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
    <div class="view-strip"><strong>{{ applied.date_from }} — {{ applied.date_to }}</strong><span>对比前一等长区间 · 店铺当地业务日期</span><button type="button" class="snapshot-state" @click="snapshotOpen = !snapshotOpen">今日09:00同时段：查看快照</button></div>
    <SalesNineSnapshots v-if="snapshotOpen" :scope="applied" @close="snapshotOpen = false" />
    <div class="list-tools" aria-label="列表显示与排序">
      <label>排序<select v-model="sort" :disabled="loading" @change="reloadList"><option value="sales_desc">GMV由高到低</option><option value="change_asc">下降幅度优先</option><option value="loss_desc">下降金额优先</option><option :value="view === 'products' ? 'units_desc' : 'orders_desc'">{{ view === 'products' ? '销量由高到低' : '订单由高到低' }}</option></select></label>
      <label v-if="view === 'products'">记录范围<select v-model="status" :disabled="loading" @change="reloadList"><option value="all">全部商品</option><option value="declines" :disabled="applied.date_from !== applied.date_to">下降超过30%</option><option value="unobserved">本期未观测</option></select></label>
      <details class="column-options"><summary>显示列</summary><div><p>商品身份和本期GMV固定显示；列选择不会发起查询。</p><label v-for="column in availableColumns" :key="column.key"><input v-model="selectedColumns" type="checkbox" :value="column.key" @change="persistColumns">{{ column.label }}</label><button @click="resetColumns">恢复默认</button></div></details>
      <span>按币种分别排序；范围合计不随异常筛选改变。</span>
    </div>
    <template v-if="data">
      <div class="currency-bar"><label>币种<select v-model="currency" @change="changeCurrency"><option value="">按各币种查看</option><option v-for="code in currencies" :key="code" :value="code">{{ code }}</option></select></label><span>不同币种分别合计；ROI = 同范围GMV ÷ 广告花费</span></div>
      <div class="summary-grid"><article v-for="group in visibleGroups" :key="group.currency" class="summary-card"><div><span>{{ view === 'stores' ? '非取消订单GMV' : '商品行GMV' }}</span><b>{{ group.currency }}</b></div><strong>{{ amount(group.sales_amount) }}</strong><p :class="direction(group.change_percent)">{{ percent(group.change_percent) }} <span>较前一等长区间</span></p><dl><div><dt>广告花费</dt><dd>{{ advertisingValue(group, false, true) }}</dd></div><div><dt>{{ group.ad_status === 'provisional' ? '暂估整店ROI' : '整店ROI' }}</dt><dd>{{ advertisingValue(group, true) }} <small>{{ roiChange(group) }}</small></dd></div></dl><p v-if="group.ad_sales_amount != null" class="note">ROI 计算销售额：{{ amount(group.ad_sales_amount) }} {{ group.currency }}</p><p class="note">{{ group.ad_reason || '已入库数据，后续补采可能调整。' }}</p></article></div>
      <div v-for="(notice,index) in data.notices || []" :key="index" class="notice">{{ typeof notice === 'string' ? notice : notice.message }}</div>
      <section class="results">
        <div class="results-head"><div><h2>{{ view === 'stores' ? '店铺经营表现' : `${selectedStoreName} · 商品链接` }}</h2><p>{{ view === 'stores' ? '点击店铺进入商品链接；按GMV降序，单页最多20条。' : '按商品行金额汇总，不含订单层运费税费；点击下降原因查看证据。' }}</p></div><button v-if="returnToDeclines" @click="returnToBoard">← 返回大屏下降排行</button><button v-else-if="view === 'products'" @click="backToStores">← 返回店铺</button></div>
        <div v-if="loading" class="loading" role="status">正在读取当前范围…</div>
        <div v-else-if="!data.rows?.length" class="empty">当前授权范围暂无可展示记录。缺少记录不代表销量为零或没有异常。</div>
        <div v-else class="table-scroll" tabindex="0" aria-label="经营明细表，可横向滚动">
          <table><thead><tr><th>{{ view === 'stores' ? '店铺 / 国家' : '商品 / 平台商品ID' }}</th><th>GMV / 币种</th>
            <th v-if="shown('previous')">前期GMV</th><th v-if="shown('change')">变化率</th><th v-if="shown('loss')">下降金额</th>
            <th v-if="shown('volume')">{{ view === 'stores' ? '有效订单' : '销量' }}</th><th v-if="view === 'stores' && shown('ads')">广告花费</th><th v-if="view === 'stores' && shown('roi')">整店ROI / 差值</th><th v-if="view === 'products' && shown('reason')">下降原因</th>
          </tr></thead><tbody><tr v-for="row in data.rows" :key="`${row.store_id}-${row.product_id || ''}-${row.currency}`">
            <td><button v-if="view === 'stores'" class="text-button" :disabled="!canProducts" :title="canProducts ? '查看商品链接' : '需SKU销售明细权限'" @click="openStore(row)">{{ row.store_name }}</button><strong v-else>{{ row.product_name || '未命名商品' }}</strong><small>{{ view === 'stores' ? row.country : row.product_id }}</small><small v-if="row.observation_status === 'missing_current'">本期未观测，需核查采集</small></td>
            <td>{{ amount(row.sales_amount) }} <small>{{ row.currency }}</small></td>
            <td v-if="shown('previous')">{{ amount(row.previous_sales_amount) }}</td><td v-if="shown('change')" :class="direction(row.change_percent)">{{ percent(row.change_percent) }}</td><td v-if="shown('loss')">{{ amount(row.loss_amount) }} <small>{{ row.currency }} · 前期减本期</small></td>
            <td v-if="shown('volume')">{{ (view === 'stores' ? row.order_count : row.units_sold) ?? '—' }} {{ view === 'stores' ? '单' : '件' }}</td>
            <td v-if="view === 'stores' && shown('ads')">{{ advertisingValue(row) }}</td><td v-if="view === 'stores' && shown('roi')">{{ advertisingValue(row, true) }}<small v-if="row.ad_status === 'provisional'" :title="row.ad_reason">暂估 · 数据待补齐</small><small>{{ roiChange(row) }}</small></td>
            <td v-if="view === 'products' && shown('reason')"><button class="reason-button" :class="{ flagged: row.diagnosis?.status === 'suspected_decline' }" @click="openReason(row)">{{ row.diagnosis?.title || '查看排查依据' }}</button></td>
          </tr></tbody></table>
        </div>
        <div class="pagination"><span>第 {{ page }} 页 · 每页 {{ pageSize }} 条<span v-if="data.truncated"> · 数据超过范围上限，请缩小筛选</span></span><button :disabled="loading || page === 1" @click="goPage(-1)">上一页</button><button :disabled="loading || !data.has_next" @click="goPage(1)">下一页</button></div>
      </section>
      <p class="note">按已入库数据比较，采集完整性未确认；零基准、缺失日期不生成变化率。{{ data.generated_at ? `生成时间：${data.generated_at}` : '' }}</p>
    </template>
    <div v-else-if="loading" class="empty" role="status">正在读取店铺经营汇总…</div>
    <dialog ref="reasonDialog" class="reason-dialog" @close="reason = null" @click="closeBackdrop"><template v-if="reason"><header><div><p class="eyebrow">LX 巡店SOP · 排查依据</p><h2>{{ reason.product_name || reason.product_id }}</h2></div><button aria-label="关闭原因详情" @click="reasonDialog?.close()">关闭</button></header><p>{{ selectedStoreName }} · {{ applied.date_from }} — {{ applied.date_to }} · {{ reason.currency }}</p><div class="reason-layout"><section><h3>触发与对比</h3><dl><div><dt>本期商品GMV</dt><dd>{{ amount(reason.sales_amount) }} {{ reason.currency }}</dd></div><div><dt>前期商品GMV</dt><dd>{{ amount(reason.previous_sales_amount) }} {{ reason.currency }}</dd></div><div><dt>变化率</dt><dd :class="direction(reason.change_percent)">{{ percent(reason.change_percent) }}</dd></div></dl><p class="note">单日GMV较前日下降超过30%时进入LX排查；其他日期范围仅展示变化。</p></section><section><h3>判断路径</h3><ol><li v-for="(step,index) in reason.diagnosis?.steps || []" :key="index"><strong>{{ step.label }}</strong><p>{{ step.value ?? '缺少数据，暂不能判断' }}</p></li></ol><div class="notice"><strong>{{ reason.diagnosis?.title || '原因待核查' }}</strong><p>变化命中不等于已证实原因。买家、访客、转化、缺货等证据未齐时，不推断经营原因。</p></div><p v-if="reason.diagnosis?.missing?.length" class="note">待补数据：{{ reason.diagnosis.missing.join('、') }}</p></section></div></template></dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { canAccessPath } from '../../router/menu';
import { fetchSalesOperations } from '../../api/salesOperations';
import { fetchBoardFilters } from '../../api/realtimeBoard';
const SalesNineSnapshots = defineAsyncComponent(() => import('./SalesNineSnapshots.vue'));
import { amount, percent, delta, dateRange, validRange, hasNumber } from './salesOperations';
import { columnsFor, preferenceKey, readColumns, writeColumns } from './salesColumns';
defineEmits(['legacy']);
type Row = Record<string, any>;
function advertisingValue(row: Row, roi = false, withCurrency = false) {
  const value = roi ? row.roi : row.ad_spend;
  if (hasNumber(value)) return amount(value) + (roi ? ' 倍' : withCurrency ? ` ${row.currency}` : '');
  if (view.value === 'products') return '请查看店铺数据';
  if (row.ad_reason?.includes('权限')) return '暂无广告查看权限';
  if (roi && hasNumber(row.ad_spend) && Number(row.ad_spend) === 0) return '零花费，无法计算';
  return roi ? '暂无法计算（见数据说明）' : '暂无可用广告数据';
}
function roiChange(row: Row) {
  return hasNumber(row.roi_delta) ? `变化 ${delta(row.roi_delta)} 倍` : '暂无可比变化';
}

const router = useRouter(), route = useRoute(), auth = useAuthStore();
const validIsoDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
const draft = reactive({ ...dateRange(1), platform: '', store_id: '', region: '' });
if (route.query.view === 'operations' && typeof route.query.date_from === 'string' && typeof route.query.date_to === 'string') { const dates = { date_from: route.query.date_from, date_to: route.query.date_to }; if (!validRange(dates)) Object.assign(draft, dates); }
const applied = ref({ ...draft }), view = ref('stores'), page = ref(1), pageSize = 20;
const data = ref<Row | null>(null), filters = ref<Row>({}), loading = ref(false), error = ref(''), filterError = ref(''), currency = ref('');
const currencies = ref<string[]>([]);
const snapshotOpen = ref(false);
const sort = ref('sales_desc'), status = ref('all');
const availableColumns = computed(() => columnsFor(view.value));
function columnStorage() { try { return window.localStorage; } catch { return null; } }
const selectedColumns = ref<string[]>(readColumns(columnStorage(), preferenceKey(auth.currentUser), view.value));
const shown = (key: string) => selectedColumns.value.includes(key);
function persistColumns() { writeColumns(columnStorage(), preferenceKey(auth.currentUser), view.value, selectedColumns.value); }
function resetColumns() { selectedColumns.value = columnsFor(view.value).map(c => c.key); persistColumns(); }
watch([view, () => preferenceKey(auth.currentUser)], () => { selectedColumns.value = readColumns(columnStorage(), preferenceKey(auth.currentUser), view.value); });
const parentScope = ref<Row | null>(null);
const exactProductId = ref(''), returnToDeclines = ref(false), autoOpenReason = ref(false);
const returnScope = ref<Row | null>(null), routeScopeInvalid = ref(false);
const selectedStoreName = ref(''), reason = ref<Row | null>(null), reasonDialog = ref<HTMLDialogElement | null>(null);
let alive = true, controller: AbortController | null = null, generation = 0;
const options = (values: any[] = []) => values.map(v => typeof v === 'string' ? { value: v, label: v } : { ...v, value: v.value ?? v.id, label: v.label ?? v.name });
const platforms = computed(() => options(filters.value.platforms));
const stores = computed(() => options(filters.value.stores).filter(v => (!draft.platform || !v.platform || v.platform === draft.platform) && (!draft.region || (v.country_code || v.country || v.region) === draft.region)));
const regions = computed(() => [...new Set(options(filters.value.stores).map(v => v.country_code || v.country || v.region).filter(Boolean))].sort());
const canProducts = computed(() => canAccessPath(auth.currentUser, '/sales-management/skus'));
const dirty = computed(() => Object.keys(draft).some(key => draft[key as keyof typeof draft] !== applied.value[key as keyof typeof draft]));
const visibleGroups = computed(() => (data.value?.currency_groups || []).filter((g: Row) => !currency.value || g.currency === currency.value));
const links = computed(() => [
  { path: '/sales-management/stores', label: '门店销售明细' },
  { path: '/sales-management/skus', label: 'SKU销售明细' },
  { path: '/sales-management/exports', label: '销售明细导出' }
].filter(link => canAccessPath(auth.currentUser, link.path)));
const direction = (value: any) => value == null ? '' : Number(value) < 0 ? 'negative' : Number(value) > 0 ? 'positive' : '';
async function load() {
  if (routeScopeInvalid.value) return;
  const id = ++generation; controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''; data.value = null; reasonDialog.value?.close();
  try {
    const response = await fetchSalesOperations({ ...applied.value, view: view.value, page: page.value, page_size: pageSize, sort: sort.value, status: status.value, ...(currency.value ? { currency: currency.value } : {}), ...(exactProductId.value ? { product_id: exactProductId.value } : {}) }, controller.signal);
    if (!alive || generation !== id) return;
    if (!response?.success) throw new Error(response?.message || '经营数据暂不可用。');
    data.value = response.data;
    const found = (response.data?.currency_groups || []).map((g: Row) => g.currency);
    currencies.value = currency.value ? [...new Set([...currencies.value, ...found])] : found;
    if (autoOpenReason.value && exactProductId.value) {
      reason.value = data.value.rows?.find((row: Row) => String(row.product_id) === exactProductId.value) || null;
      autoOpenReason.value = false;
      const openId = id;
      if (reason.value) await nextTick(() => { if (alive && generation === openId) reasonDialog.value?.showModal(); });
    }
  } catch (failure: any) { if (alive && generation === id) error.value = failure?.message || '经营数据暂不可用，请重试。'; }
  finally { if (alive && generation === id) loading.value = false; }
}
function apply() { const message = validRange(draft); if (message) { error.value = message; return; } routeScopeInvalid.value = false; exactProductId.value = ''; autoOpenReason.value = false; applied.value = { ...draft }; view.value = 'stores'; page.value = 1; currency.value = ''; currencies.value = []; status.value = 'all'; sort.value = 'sales_desc'; load(); }
function quick(days: number) { Object.assign(draft, dateRange(days)); apply(); }
function openStore(row: Row) { if (!canProducts.value) return; parentScope.value = { ...applied.value, currency: currency.value, sort: sort.value }; applied.value = { ...applied.value, store_id: String(row.store_id) }; draft.store_id = String(row.store_id); selectedStoreName.value = row.store_name; view.value = 'products'; exactProductId.value = ''; returnToDeclines.value = false; sort.value = 'change_asc'; status.value = 'all'; currency.value = row.currency; page.value = 1; load(); }
function backToStores() { if (parentScope.value) { const { currency: previousCurrency, sort: previousSort, ...scope } = parentScope.value; applied.value = scope as typeof applied.value; Object.assign(draft, scope); currency.value = previousCurrency; sort.value = previousSort || 'sales_desc'; } view.value = 'stores'; exactProductId.value = ''; returnToDeclines.value = false; status.value = 'all'; page.value = 1; load(); }
function reloadList() { page.value = 1; load(); }
function returnToBoard() {
  const source = returnScope.value || applied.value;
  const query = { date_from: source.date_from, date_to: source.date_to,
    platform: source.platform || '', region: source.region || '', store_id: source.store_id || '', currency: source.currency || currency.value || '', metric: source.metric || 'amount', view: 'declines' };
  router.push({ path: '/sales-management/realtime-board', query });
}
function changeCurrency() { page.value = 1; load(); }
function goPage(step: number) { page.value += step; load(); }
async function openReason(row: Row) { const id = generation; reason.value = row; await nextTick(); if (alive && generation === id && reason.value === row) reasonDialog.value?.showModal(); }
function closeBackdrop(event: MouseEvent) { if (event.target === reasonDialog.value) { const rect = reasonDialog.value!.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) reasonDialog.value?.close(); } }
async function loadFilters() { filterError.value = ''; try { const response = await fetchBoardFilters(); if (!alive) return; if (!response.success || ['mock','degraded'].includes(response.data?.api_status)) throw new Error(); filters.value = response.data; } catch { if (alive) filterError.value = '店铺筛选暂不可用，当前仍按系统授权范围查询。'; } }
function restoreRouteScope() {
  const q = route.query;
  routeScopeInvalid.value = false;
  const hasIntent = q.view !== undefined || q.product_id !== undefined || q.return_view !== undefined;
  if (q.view !== 'operations') {
    if (hasIntent) { routeScopeInvalid.value = true; error.value = '下钻参数无效，请从大屏下降排行重新进入。'; }
    if (Object.keys(q).length) return false;
    const defaults = { ...dateRange(1), platform: '', store_id: '', region: '' };
    Object.assign(draft, defaults); applied.value = { ...defaults };
    view.value = 'stores'; page.value = 1; currency.value = ''; currencies.value = [];
    sort.value = 'sales_desc'; status.value = 'all'; parentScope.value = null;
    exactProductId.value = ''; returnToDeclines.value = false; autoOpenReason.value = false;
    returnScope.value = null; selectedStoreName.value = ''; snapshotOpen.value = false;
    error.value = ''; reason.value = null;
    return true;
  }
  const scalarKeys = ['date_from','date_to','platform','region','store_id','currency','product_id','return_view','return_date_from','return_date_to','return_platform','return_region','return_store_id','return_currency','return_metric'];
  if (scalarKeys.some(key => q[key] !== undefined && typeof q[key] !== 'string')) { routeScopeInvalid.value = true; error.value = '下钻参数无效，请从大屏下降排行重新进入。'; return false; }
  if (typeof q.date_from !== 'string' || typeof q.date_to !== 'string') { routeScopeInvalid.value = true; error.value = '下钻日期无效，请从大屏下降排行重新进入。'; return false; }
  const next = { date_from: q.date_from, date_to: q.date_to,
    platform: typeof q.platform === 'string' ? q.platform : '',
    region: typeof q.region === 'string' ? q.region : '',
    store_id: typeof q.store_id === 'string' ? q.store_id : '' };
  if (!validIsoDate(next.date_from) || !validIsoDate(next.date_to) || validRange(next) || (next.store_id && (!/^\d{1,19}$/.test(next.store_id) || Number(next.store_id) < 1)) || (next.region && !/^[a-z]{2,3}$/i.test(next.region)) || (next.platform && !/^[a-z0-9_-]{1,32}$/i.test(next.platform))) { routeScopeInvalid.value = true; error.value = '下钻筛选无效，请从大屏下降排行重新进入。'; return false; }
  const productId = typeof q.product_id === 'string' && q.product_id.length > 0 && q.product_id.length <= 255 ? q.product_id : '';
  if ((q.product_id !== undefined && !productId) || (productId && (!next.store_id || typeof q.currency !== 'string' || !q.currency))) { routeScopeInvalid.value = true; error.value = '精确商品参数无效，请从大屏下降排行重新进入。'; return false; }
  if (typeof q.currency === 'string' && q.currency && !/^[a-z0-9]{1,8}$/i.test(q.currency)) { routeScopeInvalid.value = true; error.value = '币种参数无效，请从大屏下降排行重新进入。'; return false; }
  Object.assign(draft, next); applied.value = { ...next };
  view.value = productId ? 'products' : 'stores'; exactProductId.value = productId;
  returnToDeclines.value = q.return_view === 'declines';
  returnScope.value = returnToDeclines.value ? {
    date_from: typeof q.return_date_from === 'string' ? q.return_date_from : next.date_from,
    date_to: typeof q.return_date_to === 'string' ? q.return_date_to : next.date_to,
    platform: typeof q.return_platform === 'string' ? q.return_platform : next.platform,
    region: typeof q.return_region === 'string' ? q.return_region : next.region,
    store_id: typeof q.return_store_id === 'string' ? q.return_store_id : '',
    currency: typeof q.return_currency === 'string' ? q.return_currency : (typeof q.currency === 'string' ? q.currency : ''),
    metric: typeof q.return_metric === 'string' ? q.return_metric : 'amount'
  } : null;
  if (returnScope.value) {
    const source = returnScope.value;
    const badDates = !validIsoDate(source.date_from) || !validIsoDate(source.date_to) || source.date_from > source.date_to || source.date_to >= new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()) || (Date.parse(source.date_to) - Date.parse(source.date_from)) / 86400000 >= 31;
    if (badDates || (source.store_id && (!/^\d{1,19}$/.test(source.store_id) || Number(source.store_id) < 1)) || (source.region && !/^[a-z]{2,3}$/i.test(source.region)) || (source.platform && !/^[a-z0-9_-]{1,32}$/i.test(source.platform)) || (source.currency && !/^[a-z0-9]{1,8}$/i.test(source.currency)) || (typeof q.return_metric === 'string' && !['amount','percent'].includes(q.return_metric))) { routeScopeInvalid.value = true; error.value = '返回大屏的筛选参数无效，请重新从大屏进入。'; return false; }
  }
  autoOpenReason.value = Boolean(productId && returnToDeclines.value);
  currency.value = typeof q.currency === 'string' ? q.currency : '';
  selectedStoreName.value = stores.value.find((item: Row) => String(item.value) === next.store_id)?.label || next.store_id;
  page.value = 1;
  return true;
}
onMounted(() => { if (restoreRouteScope() || !routeScopeInvalid.value) load(); loadFilters(); });
watch(() => [route.query.view, route.query.date_from, route.query.date_to, route.query.platform, route.query.region, route.query.store_id, route.query.currency, route.query.product_id, route.query.return_view, route.query.return_date_from, route.query.return_date_to, route.query.return_platform, route.query.return_region, route.query.return_store_id, route.query.return_currency, route.query.return_metric], () => {
  ++generation; controller?.abort(); loading.value = false; data.value = null; reason.value = null; reasonDialog.value?.close();
  if (!restoreRouteScope()) return;
  load();
});
onBeforeUnmount(() => { alive = false; ++generation; controller?.abort(); });
</script>

<style scoped>
.list-tools{display:flex;align-items:center;flex-wrap:wrap;gap:14px;margin:16px 0;color:#63758a;font-size:12px}.list-tools>label{display:flex;align-items:center;gap:8px}.list-tools>span{margin-left:auto}.column-options{position:relative}.column-options>div{position:absolute;right:0;top:100%;z-index:6;min-width:220px;padding:14px;background:white;border:1px solid #dce4ee;border-radius:8px;box-shadow:0 8px 28px #23354d20}.column-options label{display:flex;align-items:center;gap:8px;padding:6px 0}.column-options input{accent-color:#2864b4}.column-options p{line-height:1.6;margin:0 0 8px}.operations{color:#243247;padding:8px 4px;font-size:14px}.operations-head,.results-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.operations-head h1{font-size:26px;margin:6px 0}.operations-head p,.results-head p{color:#65758a;margin:6px 0;line-height:1.6}.eyebrow{font-size:12px;color:#527696!important}.operations button,.operations input,.operations select,.operations summary{font:inherit;border:1px solid #d5dfeb;border-radius:6px;background:white;padding:9px 12px;color:#33465d}.operations button,.operations summary{cursor:pointer}.operations button:disabled{opacity:.5;cursor:default}.operations button:focus-visible,.operations input:focus-visible,.operations select:focus-visible,.operations summary:focus-visible{outline:2px solid #3478d4;outline-offset:3px}.operations .primary{background:#2864b4;color:white;border-color:#2864b4}.more{position:relative;flex-shrink:0}.more nav{position:absolute;right:0;z-index:5;padding:8px;background:white;box-shadow:0 8px 28px #23354d20;border:1px solid #dce4ee;border-radius:8px;min-width:210px}.more nav button{display:block;text-align:left;width:100%;border:0}.more nav button:hover{background:#f0f5fc}.filters{display:flex;align-items:flex-end;gap:12px;flex-wrap:wrap;margin-top:24px;padding:18px;background:#f6f8fc;border:1px solid #e0e7f0;border-radius:10px}.filters label{display:grid;gap:7px;font-size:12px;color:#5f7087}.filters select{max-width:220px;min-width:150px}.quick{display:flex;gap:6px}.view-strip,.currency-bar{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:20px 0;color:#64748b;font-size:12px}.view-strip strong{color:#33465d}.snapshot-state{margin-left:auto;background:#eef2f6;border-radius:4px;padding:6px 9px}.currency-bar{justify-content:space-between}.currency-bar label{display:flex;align-items:center;gap:8px}.summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}.summary-card{padding:22px;border:1px solid #dae4ef;border-radius:10px;background:white}.summary-card>div:first-child{display:flex;justify-content:space-between;color:#63758a;font-size:13px}.summary-card>strong{display:block;font-size:30px;margin:18px 0 12px;font-variant-numeric:tabular-nums}.summary-card dl{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:16px 0 6px}.summary-card dl>div{display:block;padding:0}.summary-card dd{text-align:left;margin-top:8px}.summary-card p span{color:#718096;font-size:12px;margin-left:5px}dl{margin:18px 0}dl>div{display:flex;justify-content:space-between;gap:14px;padding:8px 0}dt{color:#66778c}dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}dd small{display:block;color:#6d7f92;margin-top:5px}.note{font-size:12px;color:#718196;line-height:1.7}.notice{padding:12px 16px;margin:12px 0;background:#fff9ed;color:#805f26;border:1px solid #eeddb6;border-radius:6px;line-height:1.7}.notice button{font-size:12px;padding:5px 9px;margin-left:10px}.notice.error{background:#fff2f2;color:#a64040;border-color:#f3cece}.results{margin-top:24px;border:1px solid #e0e7ef;background:white;border-radius:10px;overflow:hidden}.results-head{padding:20px}.results-head h2{font-size:17px;margin:0}.results-head p{font-size:12px}.table-scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:16px;text-align:right;border-top:1px solid #e8edf4;white-space:nowrap}th{background:#f8fafc;color:#65758b;font-weight:500}th:first-child,td:first-child{text-align:left;min-width:200px;max-width:320px}td:first-child strong{display:block;overflow:hidden;text-overflow:ellipsis;max-width:300px}td small{display:block;color:#718196;font-size:11px;margin-top:5px}.operations .text-button{border:0;background:none;color:#2864b4;padding:0;text-align:left;font-weight:600;max-width:280px;overflow:hidden;text-overflow:ellipsis}.operations .reason-button{font-size:12px;padding:7px 10px}.operations .reason-button.flagged{color:#a34d24;background:#fff5e9;border-color:#f0d2ab}.negative{color:#c64a43}.positive{color:#16856c}.pagination{display:flex;align-items:center;justify-content:flex-end;gap:10px;padding:16px;border-top:1px solid #e8edf4;font-size:12px;color:#687a90}.pagination>span{margin-right:auto}.pagination button{font-size:12px;padding:6px 10px}.empty,.loading{padding:45px 20px;text-align:center;color:#718196}.reason-dialog{width:min(940px,calc(100vw - 40px));max-height:85vh;overflow:auto;border:0;border-radius:12px;padding:26px;color:#243247;box-shadow:0 20px 100px #15284440}.reason-dialog::backdrop{background:#15284466}.reason-dialog header{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.reason-dialog h2{font-size:20px;margin:4px 0}.reason-dialog>p{color:#718196;font-size:12px}.reason-layout{display:grid;grid-template-columns:1fr 1.35fr;gap:24px;margin-top:24px}.reason-layout section{padding:18px;border:1px solid #e0e7ef;border-radius:8px}.reason-layout h3{font-size:14px;margin:0 0 14px}.reason-layout li{padding-bottom:8px;font-size:13px}.reason-layout li p{color:#65758b;line-height:1.6}@media(max-width:760px){.list-tools>span{margin-left:0}.column-options>div{right:auto;left:0;max-width:240px}.list-tools select{max-width:190px}.operations-head{gap:10px}.operations-head h1{font-size:22px}.filters{padding:12px;gap:10px}.filters label{flex:1;min-width:130px}.filters select,.filters input{width:100%;max-width:100%;box-sizing:border-box;min-width:0}.snapshot-state{margin-left:0}.quick{width:100%}.summary-card{padding:16px}.reason-layout{grid-template-columns:1fr}.reason-dialog{padding:18px;box-sizing:border-box}.results-head{padding:14px}.pagination{flex-wrap:wrap}}
</style>
