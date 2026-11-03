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
      <div class="quick" role="group" aria-label="快捷日期"><button v-for="days in [1,7,15,30]" :key="days" type="button" :class="{ active: isRange(days) }" :aria-pressed="isRange(days)" @click="quick(days)">{{ days === 1 ? '昨日' : `近${days}天` }}</button></div>
      <label class="currency-filter">币种（原币）<select v-model="currency" @change="changeCurrency"><option value="">全部币种</option><option v-for="code in currencies" :key="code" :value="code">{{ code }}</option></select></label>
      <button class="primary" :disabled="loading">{{ loading ? '查询中…' : '查询' }}</button>
    </form>
    <p v-if="dirty" class="note">筛选已修改，点击查询后生效；下方仍为上次查询范围。</p>
    <div v-if="filterError" role="status" class="notice">{{ filterError }} <button @click="loadFilters">重试筛选目录</button></div>
    <div v-if="error" role="alert" class="notice error">{{ error }} <button :disabled="loading" @click="load">重试</button></div>
    <div class="view-strip"><strong>{{ applied.date_from }} — {{ applied.date_to }}</strong><span>对比前一等长区间 · 店铺当地业务日期</span><button type="button" class="snapshot-state" @click="snapshotOpen = !snapshotOpen">今日09:00同时段：查看快照</button></div>
    <SalesNineSnapshots v-if="snapshotOpen" :scope="applied" @close="snapshotOpen = false" />
    <template v-if="data">

      <section class="kpi-grid" aria-label="经营汇总">
        <article v-for="item in kpis" :key="item.key" class="kpi-card" :class="`tone-${item.key}`"><span class="kpi-icon" aria-hidden="true"><component :is="metricIcons[item.key]" /></span><div><p>{{ item.label }}</p><strong>{{ item.value }}</strong><small>{{ item.note }}</small></div></article>
      </section>
      <details v-if="data.cny_summary" class="summary-notes"><summary>人民币汇总 · 数据口径</summary><p>原币明细不变 · 销售额按当前筛选范围折算</p><p>ROI 分子：{{ data.cny_summary.roi_sales_scope }}</p><p>参考汇率日期：{{ data.cny_summary.rate_dates.join('、') || '暂无' }}</p></details>
      <p v-if="data.cny_summary?.ad_partial" class="notice">广告数据有在途，后续同步可能更新。</p><p v-if="data.cny_summary?.excluded_currencies?.length" class="notice">未换算币种：{{ data.cny_summary.excluded_currencies.join('、') }}</p>
      <details class="summary-grid"><summary>各币种汇总 <span>展开查看详情 · {{ visibleGroups.length }} 种</span></summary><article v-for="group in visibleGroups" :key="group.currency" class="summary-card"><div><span>{{ view === 'stores' ? '非取消订单GMV' : '商品行GMV' }}</span><b>{{ group.currency }}</b></div><strong>{{ amount(group.sales_amount) }}</strong><p :class="direction(group.change_percent)">{{ percent(group.change_percent) }} <span>较前一等长区间</span></p><dl><div><dt>广告花费</dt><dd>{{ adSpendValue(group.ad_spend, group.ad_reason) }} <span v-if="group.ad_spend != null">{{ group.currency }}</span></dd></div><div><dt>{{ group.ad_status === 'provisional' ? '暂估整店ROI' : '整店ROI' }}</dt><dd>{{ roiDisplay(group.roi, group.ad_spend, group.ad_reason) }} <small v-if="group.roi_delta != null">变化 {{ roiValue(group.roi_delta) }} 倍</small></dd></div></dl><p v-if="group.ad_sales_amount != null" class="note">ROI 计算销售额：{{ amount(group.ad_sales_amount) }} {{ group.currency }}</p><p v-if="group.ad_status === 'provisional' || group.ad_status === 'estimated'" class="note">暂估：有在途数据，后续同步后将更新。</p><p class="note">{{ group.ad_reason || '已入库数据，后续补采可能调整。' }}</p></article></details>
      <div v-for="(notice,index) in data.notices || []" :key="index" class="notice">{{ typeof notice === 'string' ? notice : notice.message }}</div>
      <section class="results">
        <div class="results-head"><div><h2>{{ view === 'stores' ? '店铺经营表现' : `${selectedStoreName} · 商品链接` }}</h2><p>{{ view === 'stores' ? '点击店铺进入商品链接；按GMV降序，单页最多20条。' : '按商品行金额汇总，不含订单层运费税费；点击下降原因查看证据。' }}</p></div><button v-if="returnToDeclines" @click="returnToBoard">← 返回大屏下降排行</button><button v-else-if="view === 'products'" @click="backToStores">← 返回店铺</button>    <div class="list-tools" aria-label="列表显示与排序">
      <label>排序<select v-model="sort" :disabled="loading" @change="reloadList"><option value="sales_desc">GMV由高到低</option><option value="change_asc">下降幅度优先</option><option value="loss_desc">下降金额优先</option><option :value="view === 'products' ? 'units_desc' : 'orders_desc'">{{ view === 'products' ? '销量由高到低' : '订单由高到低' }}</option></select></label>
      <label v-if="view === 'products'">记录范围<select v-model="status" :disabled="loading" @change="reloadList"><option value="all">全部商品</option><option value="declines" :disabled="applied.date_from !== applied.date_to">下降超过30%</option><option value="unobserved">本期未观测</option></select></label>
      <details class="column-options"><summary>显示列</summary><div><p>商品身份和本期GMV固定显示；列选择不会发起查询。</p><label v-for="column in availableColumns" :key="column.key"><input v-model="selectedColumns" type="checkbox" :value="column.key" @change="persistColumns">{{ column.label }}</label><button @click="resetColumns">恢复默认</button></div></details>
      <span>按币种分别排序；范围合计不随异常筛选改变。</span>
    </div></div>

      <div class="currency-bar"><span>币种为原币筛选，不进行汇率转换；ROI = 销售金额 ÷ 广告花费（同店铺、日期、币种范围）</span></div>
        <div v-if="loading" class="loading" role="status">正在读取当前范围…</div>
        <div v-else-if="!data.rows?.length" class="empty">当前授权范围暂无可展示记录。缺少记录不代表销量为零或没有异常。</div>
        <div v-else class="table-scroll" tabindex="0" aria-label="经营明细表，可横向滚动">
          <table><thead><tr><th>{{ view === 'stores' ? '店铺 / 国家' : '商品 / 平台商品ID' }}</th><th>GMV / 币种</th>
            <th v-if="shown('previous')">前期GMV</th><th v-if="shown('change')">变化率</th><th v-if="shown('loss')">下降金额</th>
            <th v-if="shown('volume')">{{ view === 'stores' ? '有效订单' : '销量' }}</th><th v-if="view === 'stores' && shown('ads')">广告花费</th><th v-if="view === 'stores' && shown('roi')">整店ROI / 差值</th><th v-if="view === 'products' && shown('reason')">下降原因</th>
          </tr></thead><tbody><tr v-for="row in data.rows" :key="`${row.store_id}-${row.product_id || ''}-${row.currency}`">
            <td><button v-if="view === 'stores'" class="text-button" :disabled="!canProducts" :title="canProducts ? '查看商品链接' : '需SKU销售明细权限'" @click="openStore(row)">{{ row.store_name }}</button><template v-else><el-image v-if="row.platform_image_url" :src="row.platform_image_url" :preview-src-list="[row.platform_image_url]" preview-teleported fit="contain" class="ops-product-image"><template #error><span>暂无图片</span></template></el-image><span v-else class="ops-image-empty">暂无图片</span><strong>{{ row.product_name || '未命名商品' }}</strong></template><small>{{ view === 'stores' ? row.country : row.product_id }}</small><small v-if="row.observation_status === 'missing_current'">本期未观测，需核查采集</small></td>
            <td>{{ amount(row.sales_amount) }} <small>{{ row.currency }}</small></td>
            <td v-if="shown('previous')">{{ amount(row.previous_sales_amount) }}</td><td v-if="shown('change')" :class="direction(row.change_percent)">{{ percent(row.change_percent) }}</td><td v-if="shown('loss')">{{ amount(row.loss_amount) }} <small>{{ row.currency }} · 前期减本期</small></td>
            <td v-if="shown('volume')">{{ (view === 'stores' ? row.order_count : row.units_sold) ?? '—' }} {{ view === 'stores' ? '单' : '件' }}</td>
            <td v-if="view === 'stores' && shown('ads')">{{ adSpendValue(row.ad_spend, row.ad_reason) }}</td><td v-if="view === 'stores' && shown('roi')">{{ roiDisplay(row.roi, row.ad_spend, row.ad_reason) }}<small v-if="row.ad_status === 'provisional' || row.ad_status === 'estimated'">暂估：有在途数据，后续同步后将更新。</small><small v-if="row.roi_delta != null">变化 {{ roiValue(row.roi_delta) }} 倍</small></td>
            <td v-if="view === 'products' && shown('reason')"><button class="reason-button" :class="{ flagged: row.diagnosis?.status === 'suspected_decline' }" @click="openReason(row)">{{ row.diagnosis?.title || '查看排查依据' }}</button></td>
          </tr></tbody></table>
        </div>
        <div class="pagination"><span>第 {{ page }} 页 · 每页 {{ pageSize }} 条<span v-if="data.truncated"> · 数据超过范围上限，请缩小筛选</span></span><button :disabled="loading || page === 1" @click="goPage(-1)">上一页</button><button :disabled="loading || !data.has_next" @click="goPage(1)">下一页</button></div>
      </section>
      <details class="declines" @toggle="toggleDeclines">
        <summary>需关注商品 · 销售下降 <span>按当前筛选按需读取，最多10项</span></summary>
        <p v-if="!canProducts" class="note">需 SKU 销售明细权限，当前不查询商品数据。</p>
        <p v-else-if="!currency" class="note">请先选择单一币种，再读取销售下降商品。</p>
        <div v-else-if="declinesLoading" class="loading" role="status">正在读取销售下降商品…</div>
        <div v-else-if="declinesError" class="notice error" role="alert">{{ declinesError }} <button @click="loadDeclines">重试</button></div>
        <div v-else-if="declinesLoaded && !declines.length" class="empty">当前筛选范围暂无可比较的下降商品。</div>
        <div v-else-if="declinesLoaded" class="table-scroll"><table><thead><tr><th>商品 / 店铺</th><th>本期 GMV</th><th>前期 GMV</th><th>下降金额</th><th>变化率</th><th>排查</th></tr></thead><tbody><tr v-for="row in declines" :key="`${row.store_id}-${row.product_id}-${row.currency}`"><td><el-image v-if="row.platform_image_url" :src="row.platform_image_url" :preview-src-list="[row.platform_image_url]" preview-teleported fit="contain" class="ops-product-image"/><strong>{{ row.product_name || row.product_id }}</strong><small>{{ row.store_name }} · {{ row.country }} · {{ row.currency }}</small></td><td>{{ amount(row.sales_amount) }}</td><td>{{ amount(row.previous_sales_amount) }}</td><td>{{ amount(row.decline_amount) }} {{ row.currency }}</td><td class="negative">{{ percent(row.change_percent) }}</td><td><button class="reason-button" @click="openDecline(row)">查看详情</button></td></tr></tbody></table></div>
      </details>
      <p class="note">按已入库数据比较，采集完整性未确认；零基准、缺失日期不生成变化率。{{ data.generated_at ? `生成时间：${data.generated_at}` : '' }}</p>
    </template>
    <div v-else-if="loading" class="empty" role="status">正在读取店铺经营汇总…</div>
    <dialog ref="reasonDialog" class="reason-dialog" @close="reason = null" @click="closeBackdrop"><template v-if="reason"><el-image v-if="reason.platform_image_url" :src="reason.platform_image_url" :preview-src-list="[reason.platform_image_url]" :preview-teleported="false" fit="contain" class="ops-product-image"><template #error><span class="ops-image-empty">暂无图片</span></template></el-image><span v-else class="ops-image-empty">暂无图片</span><header><div><p class="eyebrow">LX 巡店SOP · 排查依据</p><h2>{{ reason.product_name || reason.product_id }}</h2></div><button aria-label="关闭原因详情" @click="reasonDialog?.close()">关闭</button></header><p>{{ selectedStoreName }} · {{ applied.date_from }} — {{ applied.date_to }} · {{ reason.currency }}</p><div class="reason-layout"><section><h3>触发与对比</h3><dl><div><dt>本期商品GMV</dt><dd>{{ amount(reason.sales_amount) }} {{ reason.currency }}</dd></div><div><dt>前期商品GMV</dt><dd>{{ amount(reason.previous_sales_amount) }} {{ reason.currency }}</dd></div><div><dt>变化率</dt><dd :class="direction(reason.change_percent)">{{ percent(reason.change_percent) }}</dd></div></dl><p class="note">单日GMV较前日下降超过30%时进入LX排查；其他日期范围仅展示变化。</p></section><section><h3>判断路径</h3><ol><li v-for="(step,index) in reason.diagnosis?.steps || []" :key="index"><strong>{{ step.label }}</strong><p>{{ step.value ?? '缺少数据，暂不能判断' }}</p><small v-if="step.snapshot_at">快照时间：{{ step.snapshot_at }}</small><small v-if="step.status === 'shop_auxiliary'">所属店铺广告辅助数据，不代表该商品</small></li></ol><p v-if="reason.diagnosis?.shop_ad_label" class="note">{{ reason.diagnosis.shop_ad_label }}</p><div class="notice"><strong>{{ reason.diagnosis?.title || '原因待核查' }}</strong><p>变化命中不等于已证实原因。买家、访客、转化、缺货等证据未齐时，不推断经营原因。</p></div><p v-if="reason.diagnosis?.missing?.length" class="note">待补数据：{{ reason.diagnosis.missing.join('、') }}</p></section></div></template></dialog>
  </section>
</template>

<script setup lang="ts">
import { ShoppingBag, Promotion, DataAnalysis, Tickets } from '@element-plus/icons-vue';
const metricIcons = { sales: ShoppingBag, ads: Promotion, roi: DataAnalysis, orders: Tickets };
import { computed, defineAsyncComponent, nextTick, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { canAccessPath } from '../../router/menu';
import { fetchSalesOperations } from '../../api/salesOperations';
import { fetchBoardFilters, fetchBoardDeclines } from '../../api/realtimeBoard';
const SalesNineSnapshots = defineAsyncComponent(() => import('./SalesNineSnapshots.vue'));
import { amount, percent, delta, dateRange, validRange } from './salesOperations';
import { columnsFor, preferenceKey, readColumns, writeColumns } from './salesColumns';
defineEmits(['legacy']);
type Row = Record<string, any>;
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
let declinesController: AbortController | null = null, declinesGeneration = 0;
const declines = ref<Row[]>([]), declinesLoading = ref(false), declinesError = ref(''), declinesLoaded = ref(false);
const declinesOpen = ref(false);
const options = (values: any[] = []) => values.map(v => typeof v === 'string' ? { value: v, label: v } : { ...v, value: v.value ?? v.id, label: v.label ?? v.name });
const platforms = computed(() => options(filters.value.platforms));
const stores = computed(() => options(filters.value.stores).filter(v => (!draft.platform || !v.platform || v.platform === draft.platform) && (!draft.region || (v.country_code || v.country || v.region) === draft.region)));
const regions = computed(() => [...new Set(options(filters.value.stores).map(v => v.country_code || v.country || v.region).filter(Boolean))].sort());
const canProducts = computed(() => canAccessPath(auth.currentUser, '/sales-management/skus'));
const dirty = computed(() => Object.keys(draft).some(key => draft[key as keyof typeof draft] !== applied.value[key as keyof typeof draft]));
const visibleGroups = computed(() => (data.value?.currency_groups || []).filter((g: Row) => !currency.value || g.currency === currency.value));
const kpis = computed(() => {
  const groups = visibleGroups.value;
  const group = groups.length === 1 ? groups[0] : null;
  const currencyLabel = group?.currency || (groups.length > 1 ? '请选择原币' : '暂无汇总');
  return [
    { key: 'sales', label: '销售额', icon: '¥', value: group?.sales_amount == null ? '—' : amount(group.sales_amount), note: currencyLabel },
    { key: 'ads', label: '广告消耗', icon: '↗', value: group?.ad_spend == null ? '—' : amount(group.ad_spend), note: group?.ad_status === 'provisional' || group?.ad_status === 'estimated' ? '暂估，后续同步更新' : currencyLabel },
    { key: 'roi', label: 'ROI', icon: '◎', value: group?.roi == null ? '—' : `${amount(group.roi)} 倍`, note: group?.ad_reason || currencyLabel },
    { key: 'orders', label: '订单数', icon: '▤', value: group?.order_count == null ? '—' : `${group.order_count} 单`, note: group?.order_count == null ? '未提供全范围汇总' : '当前筛选范围' }
  ];
});
const links = computed(() => [
  { path: '/sales-management/stores', label: '门店销售明细' },
  { path: '/sales-management/skus', label: 'SKU销售明细' },
  { path: '/sales-management/exports', label: '销售明细导出' }
].filter(link => canAccessPath(auth.currentUser, link.path)));
const roiValue = (value: any, reason?: string) => value == null ? (reason || '数据拉取不全，暂无法计算') : amount(value);
const adSpendValue = (value: any, reason?: string) => value == null ? `广告花费尚未拉取${reason ? `：${reason}` : ''}` : amount(value);
const roiDisplay = (value: any, spend: any, reason?: string) => value != null ? `${amount(value)} 倍` : spend != null && Number(spend) === 0 ? '广告花费为0，无法计算ROI' : spend == null ? adSpendValue(spend, reason) : (reason || '数据拉取不全，暂无法计算');
const direction = (value: any) => value == null ? '' : Number(value) < 0 ? 'negative' : Number(value) > 0 ? 'positive' : '';
async function load() {
  if (routeScopeInvalid.value) return;
  clearDeclines();
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
    if (declinesOpen.value && view.value === 'stores') loadDeclines();
  } catch (failure: any) { if (alive && generation === id) error.value = failure?.message || '经营数据暂不可用，请重试。'; }
  finally { if (alive && generation === id) loading.value = false; }
}
function clearDeclines() { ++declinesGeneration; declinesController?.abort(); declinesController = null; declines.value = []; declinesLoading.value = false; declinesError.value = ''; declinesLoaded.value = false; }
function toggleDeclines(event: Event) {
  declinesOpen.value = (event.currentTarget as HTMLDetailsElement).open;
  if (declinesOpen.value && canProducts.value && currency.value && !declinesLoaded.value && !declinesLoading.value) loadDeclines();
  else if (!declinesOpen.value) clearDeclines();
}
async function loadDeclines() {
  if (!canProducts.value || !currency.value || !data.value) return;
  const id = ++declinesGeneration; declinesController?.abort(); declinesController = new AbortController(); declinesLoading.value = true; declinesError.value = ''; declines.value = [];
  try {
    const response = await fetchBoardDeclines({ ...applied.value, currency: currency.value, metric: 'amount' }, declinesController.signal);
    if (!alive || id !== declinesGeneration) return;
    if (!response.success || ['mock','degraded'].includes(response.data?.api_status)) throw new Error();
    declines.value = response.data?.rows || []; declinesLoaded.value = true;
  } catch (failure: any) { if (alive && id === declinesGeneration) declinesError.value = failure?.message || '销售下降商品暂不可用。'; }
  finally { if (alive && id === declinesGeneration) declinesLoading.value = false; }
}
function openDecline(row: Row) {
  if (!canProducts.value) return;
  parentScope.value = { ...applied.value, currency: currency.value, sort: sort.value };
  applied.value = { ...applied.value, store_id: String(row.store_id) };
  Object.assign(draft, { store_id: String(row.store_id) });
  selectedStoreName.value = row.store_name;
  view.value = 'products'; exactProductId.value = row.product_id; returnToDeclines.value = false;
  status.value = 'all'; sort.value = 'change_asc'; page.value = 1; load();
}
function apply() { const message = validRange(draft); if (message) { error.value = message; return; } routeScopeInvalid.value = false; exactProductId.value = ''; autoOpenReason.value = false; applied.value = { ...draft }; view.value = 'stores'; page.value = 1; currency.value = ''; currencies.value = []; status.value = 'all'; sort.value = 'sales_desc'; load(); }
function isRange(days: number) { const range = dateRange(days); return applied.value.date_from === range.date_from && applied.value.date_to === range.date_to; }
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
  const q = route.query.view === 'operations' && Object.keys(route.query).length === 1
    ? { ...route.query, ...dateRange(1) } : route.query;
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
.operations{color:#26364b;padding:8px 4px;font-size:14px;max-width:100%;box-sizing:border-box}.operations-head,.results-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.operations-head h1{font-size:24px;margin:4px 0}.operations-head p,.results-head p{color:#65758a;margin:4px 0;line-height:1.5}.eyebrow{font-size:12px;color:#527696!important}.operations button,.operations input,.operations select,.operations summary{font:inherit;border:1px solid #d7e1ed;border-radius:6px;background:white;padding:7px 10px;color:#33465d;box-sizing:border-box}.operations button,.operations summary{cursor:pointer}.operations button:disabled{opacity:.5;cursor:default}.operations button:focus-visible,.operations input:focus-visible,.operations select:focus-visible,.operations summary:focus-visible{outline:2px solid #3478d4;outline-offset:2px}.operations .primary{background:#2864b4;color:white;border-color:#2864b4}.more{position:relative;flex-shrink:0}.more nav{position:absolute;right:0;z-index:5;padding:8px;background:white;box-shadow:0 8px 28px #23354d20;border:1px solid #dce4ee;border-radius:8px;min-width:210px}.more nav button{display:block;text-align:left;width:100%;border:0}.filters{display:grid;grid-template-columns:repeat(5,minmax(120px,1fr)) auto;align-items:end;gap:8px 10px;margin:14px 0 10px;padding:12px;background:#fff;border:1px solid #e1e8f1;border-radius:6px}.filters label{display:grid;gap:4px;font-size:11px;color:#66768b}.filters select,.filters input{min-width:0;width:100%}.filters .quick{grid-column:1/5;display:flex;gap:6px}.filters .currency-filter{grid-column:5;grid-row:2}.filters>.primary{grid-column:6;grid-row:2}.quick button{font-size:12px;padding:6px 12px}.quick button.active{background:#2864b4;color:white;border-color:#2864b4;font-weight:600}.note{font-size:12px;color:#718196;line-height:1.6}.view-strip,.currency-bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:10px 0;color:#64748b;font-size:12px}.view-strip strong{color:#33465d}.snapshot-state{margin-left:auto;background:#f2f6fb!important}.kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:12px 0}.kpi-card{display:flex;align-items:center;gap:12px;padding:14px 16px;background:#fff;border:1px solid #e1e8f1;border-radius:6px;min-width:0}.kpi-icon{width:34px;height:34px;flex:0 0 34px;border-radius:6px;display:grid;place-items:center;font-size:15px;font-weight:700;background:#edf4ff;color:#477bd1}.tone-ads .kpi-icon{background:#f2efff;color:#8065c9}.tone-roi .kpi-icon{background:#eaf7f1;color:#32946e}.tone-orders .kpi-icon{background:#fff4e9;color:#d28b3b}.kpi-card p{font-size:12px;color:#6b7b90;margin:0 0 4px}.kpi-card strong{display:block;font-size:21px;line-height:1.25;color:#253a56;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.kpi-card small{display:block;color:#8a98aa;font-size:10px;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.cny-summary{display:grid;grid-template-columns:1fr 2fr;gap:6px 18px;padding:12px 14px;margin:8px 0;border:1px solid #e1e8f1;border-radius:6px;background:#fff}.cny-summary>div,.cny-summary>strong,.cny-summary>p:not(.note){grid-column:1}.cny-summary>strong{font-size:22px;margin:0}.cny-summary>p:not(.note){font-size:11px;margin:0}.cny-summary dl{grid-column:2;grid-row:1/4;display:flex;gap:20px;margin:0}.cny-summary dl>div{display:block;border-left:1px solid #e8edf4;padding-left:16px}.cny-summary dd{text-align:left;font-size:18px;font-weight:600;margin-top:5px}.cny-summary .note{grid-column:1/-1;border-top:1px solid #edf1f6;padding-top:6px;margin:0}.summary-grid{margin:8px 0}.summary-grid>summary{cursor:pointer;color:#52647b;font-size:12px;padding:8px 10px;border:1px solid #e0e7ef;border-radius:6px;background:#f8fafc}.summary-grid>summary span{color:#718196;margin-left:8px}.summary-grid[open]>summary{margin-bottom:8px}.summary-grid[open]{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:10px}.summary-grid>.summary-card{margin:0}.summary-card{padding:14px 16px;border:1px solid #dae4ef;border-radius:6px;background:white}.summary-card>div:first-child{display:flex;justify-content:space-between;color:#63758a;font-size:12px}.summary-card>strong{display:block;font-size:24px;margin:8px 0;font-variant-numeric:tabular-nums}.summary-card dl{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:8px 0 4px}.summary-card dl>div{display:flex;justify-content:space-between;gap:8px}.summary-card dd{text-align:right;margin:0;font-variant-numeric:tabular-nums}.summary-card p{margin:6px 0}.summary-card p span{color:#718096;font-size:11px;margin-left:5px}dl{margin:14px 0}dl>div{display:flex;justify-content:space-between;gap:12px;padding:6px 0}dt{color:#66778c}dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}dd small{display:block;color:#6d7f92;margin-top:4px}.notice{padding:10px 14px;margin:10px 0;background:#fff9ed;color:#805f26;border:1px solid #eeddb6;border-radius:6px;line-height:1.6}.notice button{font-size:12px;padding:5px 9px;margin-left:8px}.notice.error{background:#fff2f2;color:#a64040;border-color:#f3cece}.results{margin-top:14px;border:1px solid #e0e7ef;background:white;border-radius:6px;overflow:hidden}.results-head{padding:12px 14px}.results-head h2{font-size:16px;margin:0}.results-head p{font-size:11px}.list-tools{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin:8px 14px;color:#63758a;font-size:11px}.list-tools>label{display:flex;align-items:center;gap:6px}.list-tools>span{margin-left:auto}.column-options{position:relative}.column-options>div{position:absolute;right:0;top:100%;z-index:6;min-width:220px;padding:12px;background:white;border:1px solid #dce4ee;border-radius:6px;box-shadow:0 8px 28px #23354d20}.column-options label{display:flex;align-items:center;gap:8px;padding:5px 0}.column-options input{accent-color:#2864b4}.column-options p{line-height:1.5;margin:0 0 8px}.currency-bar{padding:0 14px}.table-scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px}th,td{padding:9px 12px;text-align:right;border-top:1px solid #e8edf4;white-space:nowrap}th{background:#f0f5fb;color:#536a86;font-weight:600}th:first-child,td:first-child{text-align:left;min-width:190px;max-width:320px}td:first-child strong{display:block;overflow:hidden;text-overflow:ellipsis;max-width:300px}td small{display:block;color:#718196;font-size:10px;margin-top:4px}.ops-product-image{width:40px;height:40px;vertical-align:middle;margin-right:8px}.ops-image-empty{font-size:10px;color:#94a6bf;margin-right:8px}.operations .text-button{border:0;background:none;color:#2864b4;padding:0;text-align:left;font-weight:600;max-width:280px;overflow:hidden;text-overflow:ellipsis}.operations .reason-button{font-size:11px;padding:6px 8px}.operations .reason-button.flagged{color:#a34d24;background:#fff5e9;border-color:#f0d2ab}.negative{color:#c64a43}.positive{color:#16856c}.pagination{display:flex;align-items:center;justify-content:flex-end;gap:8px;padding:12px;border-top:1px solid #e8edf4;font-size:11px;color:#687a90}.pagination>span{margin-right:auto}.pagination button{font-size:11px;padding:5px 8px}.empty,.loading{padding:36px 16px;text-align:center;color:#718196}.reason-dialog{width:min(940px,calc(100vw - 32px));max-height:85vh;overflow:auto;border:0;border-radius:10px;padding:22px;color:#243247;box-shadow:0 20px 100px #15284440}.reason-dialog::backdrop{background:#15284466}.reason-dialog header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.reason-dialog h2{font-size:19px;margin:4px 0}.reason-dialog>p{color:#718196;font-size:11px}.reason-layout{display:grid;grid-template-columns:1fr 1.35fr;gap:18px;margin-top:18px}.reason-layout section{padding:14px;border:1px solid #e0e7ef;border-radius:6px}.reason-layout h3{font-size:13px;margin:0 0 12px}.reason-layout li{padding-bottom:7px;font-size:12px}.reason-layout li p{color:#65758b;line-height:1.5}@media(max-width:760px){.operations{padding:4px 0}.operations-head{gap:8px}.operations-head h1{font-size:21px}.filters{grid-template-columns:repeat(2,minmax(0,1fr));padding:10px}.filters .quick{grid-column:1/-1;grid-row:3;flex-wrap:wrap}.filters .currency-filter{grid-column:1;grid-row:4}.filters>.primary{grid-column:2;grid-row:4}.kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.kpi-card{padding:10px;gap:8px}.kpi-card strong{font-size:17px}.cny-summary{grid-template-columns:1fr}.cny-summary>div,.cny-summary>strong,.cny-summary>p:not(.note),.cny-summary dl,.cny-summary .note{grid-column:1;grid-row:auto}.cny-summary dl{flex-wrap:wrap}.snapshot-state{margin-left:0}.list-tools>span{width:100%}.reason-layout{grid-template-columns:1fr}.pagination{flex-wrap:wrap}.summary-grid[open]{grid-template-columns:minmax(0,1fr)}}@media(max-width:360px){.kpi-grid{grid-template-columns:minmax(0,1fr)}.filters{grid-template-columns:minmax(0,1fr)}.filters .quick,.filters .currency-filter,.filters>.primary{grid-column:1;grid-row:auto}}

.operations-head{align-items:center;margin-bottom:12px}.operations-head .eyebrow{display:none}.operations-head>div{display:flex;align-items:center;gap:16px}.operations-head h1{margin:0;font-size:23px}.operations-head p{margin:0;font-size:12px}
.filters{margin-top:0;grid-template-columns:repeat(3,minmax(100px,1fr)) repeat(2,minmax(125px,.9fr)) auto;gap:12px}.filters>label:not(.currency-filter){flex-direction:row;align-items:center;gap:8px}.filters>label select,.filters>label input{min-width:0;width:100%}.filters>.primary{grid-column:6;grid-row:1}.filters .quick{grid-column:1/5;grid-row:2}.filters .currency-filter{grid-column:5/7;grid-row:2;display:flex;flex-direction:row;justify-content:flex-end;align-items:center}.filters .currency-filter select{width:110px}
.kpi-icon svg{width:22px;height:22px}.kpi-card{min-width:0;padding:16px 12px;align-items:flex-start}.kpi-card>div{min-width:0}.kpi-card strong{font-size:22px}.summary-notes{font-size:12px;color:#64748b;margin-top:8px}.summary-notes summary{padding:6px 10px}.summary-notes p{margin:5px 10px}.view-strip{margin:8px 0}.results{margin-top:10px}.results-head>div>p{margin:3px 0}.results .list-tools{margin-top:0}
@media(max-width:900px){.filters{grid-template-columns:repeat(3,minmax(0,1fr))}.filters>.primary{grid-column:3;grid-row:2}.filters .quick{grid-column:1/3;grid-row:3}.filters .currency-filter{grid-column:3;grid-row:3}.operations-head>div{display:block}.kpi-card strong{font-size:19px}}
@media(max-width:600px){.filters{grid-template-columns:repeat(2,minmax(0,1fr))}.filters>.primary,.filters .quick,.filters .currency-filter{grid-column:auto;grid-row:auto}.filters .quick{grid-column:1/-1}.filters>label:not(.currency-filter){flex-direction:column;align-items:stretch}}
.filters>label:not(.currency-filter){display:flex}.results-head{align-items:center;flex-wrap:wrap}.results-head .list-tools{margin:0 0 0 auto}.results-head .list-tools>span{display:none}.results-head>div>p{display:none}.summary-notes,.summary-grid{margin:6px 0}.currency-bar{font-size:11px;margin:0 0 8px}.kpi-card{min-height:90px;box-sizing:border-box}
.filters>label{white-space:nowrap}.filters>label select,.filters>label input{flex:1;width:0}.filters .currency-filter select{flex:none;width:110px}
@media(max-width:600px){.filters>label:not(.currency-filter) select,.filters>label:not(.currency-filter) input{flex:none;width:100%}}
</style>
