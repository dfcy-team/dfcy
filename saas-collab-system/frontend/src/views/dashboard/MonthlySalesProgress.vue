<template>
  <section class="monthly-sales" aria-labelledby="monthly-sales-title">
    <header class="monthly-sales-header">
      <div>
        <p class="eyebrow">销售进度</p>
        <h2 id="monthly-sales-title">每日销售增长率</h2>
        <p class="description">按当前账号权限范围内的平台和店铺统计非取消订单及广告花费；显示每日环比。TikTok 广告按已采集来源估算：有已验证 GMV Max 的广告账户优先使用 GMV Max，其余使用竞价广告；跨币种按已保存参考汇率折算。</p>
      </div>
      <button v-if="canRead && !loading" class="refresh-button" type="button" @click="load">刷新</button>
    </header>

    <div v-if="canRead" class="store-picker">
      <label for="monthly-sales-platform">平台</label>
      <select id="monthly-sales-platform" :value="selectedPlatformId ?? ''" :disabled="!platforms.length"
        @change="changePlatform">
        <option value="">全部平台</option>
        <option v-for="platform in platforms" :key="platform.id" :value="String(platform.id)">
          {{ platform.name || platform.code }}
        </option>
      </select>
      <label for="monthly-sales-store">店铺</label>
      <el-select id="monthly-sales-store" class="store-multiselect" aria-label="店铺"
        :model-value="selectedStoreIds" :disabled="!stores.length" multiple collapse-tags clearable filterable
        placeholder="全部可管理店铺" @change="changeStore">
        <el-option :value="allStoresOption" label="全部可管理店铺" />
        <el-option v-for="store in stores" :key="store.id" :value="store.id"
          :label="storeLabel(store)" />
      </el-select>
      <label for="monthly-sales-month">月份</label>
      <input id="monthly-sales-month" type="month" v-model="selectedMonth" :max="todayMonth" @change="changeMonth">
      <span v-if="!loading && storesLoaded && !stores.length" class="empty-stores">权限范围内暂无可管理店铺</span>
    </div>

    <div v-if="!canRead" class="chart-state">当前账号暂无销售数据查看权限。</div>
    <div v-else-if="loading && !data" class="chart-state" role="status">正在读取所选月份销售数据…</div>
    <div v-else-if="error && !data" class="chart-state" role="alert">
      {{ error }}
      <button type="button" class="retry-button" @click="load">重试</button>
    </div>
    <div v-else-if="!displayCurrencies.length && data" class="chart-state">
      <span>所选月份可见范围内暂无销售及广告数据。广告花费：{{ data.advertising_status === 'forbidden' ? '无权限' : '暂无数据' }}。</span>
    </div>
    <template v-else>
      <p v-if="loading || error" class="footnote" :role="error ? 'alert' : 'status'">
        {{ error || '正在更新销售数据，当前显示上次读取结果…' }}
      </p>
      <div class="chart-toolbar">
        <div class="month-caption">
          <strong>{{ monthLabel }}</strong>
          <span>每日环比 · {{ selectedCurrency === 'CNY_TOTAL' ? 'CNY合计' : selectedCurrency }}</span>
        </div>
        <div v-if="displayCurrencies.length > 1" class="currency-tabs" role="group" aria-label="选择销售币种">
          <button v-for="item in displayCurrencies" :key="item.currency" type="button"
            :class="{ active: selectedCurrency === item.currency }"
            :aria-pressed="selectedCurrency === item.currency"
            @click="selectedCurrency = item.currency">{{ item.currency === 'CNY_TOTAL' ? 'CNY合计' : item.currency }}</button>
        </div>
      </div>

      <p v-if="selectedCurrency === 'CNY_TOTAL' && selected?.conversion?.status === 'missing_rates'" class="footnote" role="alert">
        CNY合计汇率缺失，无法计算：{{ selected.conversion.missing_currencies.join('、') }}。原币种数据仍可查看。
      </p>
      <p v-else-if="selectedCurrency === 'CNY_TOTAL'" class="footnote">
        {{ selected?.conversion?.rate_basis }}；参考汇率日期：{{ [...new Set(Object.values(selected?.conversion?.rates || {}).map(rate => rate.date).filter(Boolean))].join('、') || 'CNY按1计算' }}。
      </p>

      <div v-if="!(selectedCurrency === 'CNY_TOTAL' && selected?.conversion?.status === 'missing_rates')" class="latest-grid" aria-label="最新一天的增长率">
        <article v-for="metric in latestMetrics" :key="metric.key" class="latest-card">
          <span>{{ metric.name }} · {{ data.through }}</span>
          <strong :class="metric.growth.direction">
            <span class="trend-icon" aria-hidden="true">{{ metric.growth.icon }}</span>
            {{ metric.growth.label }}
          </strong>
          <small>较前一日{{ metric.growth.description }}</small>
        </article>
        <article class="latest-card advertising-card" aria-label="最新一天的广告花费环比">
          <span>广告花费日环比 · {{ data.through }}</span>
          <strong v-if="data.advertising_status === 'forbidden'" class="flat">无权限</strong>
          <strong v-else-if="!latestAdGrowth" class="flat">暂无数据</strong>
          <strong v-else :class="latestAdGrowth.direction">
            <span class="trend-icon" aria-hidden="true">{{ latestAdGrowth.icon }}</span>{{ latestAdGrowth.label }}
          </strong>
          <small v-if="data.advertising_status === 'forbidden'">当前账号无权查看广告花费</small>
          <small v-else-if="latestAdGrowth?.coveredStores">暂估 · 可比{{ latestAdGrowth.coveredStores }}/{{ latestAdGrowth.totalStores }}店 · {{ currencyLabel }}</small>
          <small v-else-if="hasComparisonForLatest">暂无共同完整店铺可比 · {{ currencyLabel }}</small>
          <small v-else-if="!latestAdGrowth">前一日或当日广告花费缺少数据</small>
          <small v-else>较前一日{{ latestAdGrowth.description }} · {{ currencyLabel }}</small>
        </article>
      </div>

      <div v-if="!(selectedCurrency === 'CNY_TOTAL' && selected?.conversion?.status === 'missing_rates')" class="calendar-scroll">
        <div class="calendar" role="group" :aria-label="`${monthLabel}${currencyLabel}每日销售额和销量增长率`">
          <div v-for="weekday in weekdays" :key="weekday" class="weekday">{{ weekday }}</div>
          <div v-for="index in leadingDays" :key="`pad-${index}`" class="calendar-pad" aria-hidden="true" />
          <article v-for="day in days" :key="day.date" class="day-card" :class="{ today: day.date === data.today }">
            <h3>{{ Number(day.date.slice(-2)) }}日 <span v-if="day.date === data.today">今天</span></h3>
            <p :class="day.sales.direction" :aria-label="`销售额较前一日${day.sales.description}`">
              <span>销售额</span><strong><span class="trend-icon" aria-hidden="true">{{ day.sales.icon }}</span>{{ day.sales.label }}</strong>
            </p>
            <p :class="day.quantity.direction" :aria-label="`销量较前一日${day.quantity.description}`">
              <span>销量</span><strong><span class="trend-icon" aria-hidden="true">{{ day.quantity.icon }}</span>{{ day.quantity.label }}</strong>
            </p>
            <p v-if="data.advertising_status === 'forbidden'" class="flat">
              <span>广告花费</span><strong>无权限</strong>
            </p>
            <p v-else :class="day.advertising?.direction || 'flat'" :aria-label="day.advertising ? `广告花费较前一日${day.advertising.description}` : '广告花费暂无数据'">
              <span>广告花费</span><strong v-if="day.advertising"><span class="trend-icon" aria-hidden="true">{{ day.advertising.icon }}</span>{{ day.advertising.label }}</strong>
              <strong v-else>{{ day.hasComparison ? '暂无可比数据' : '暂无数据' }}</strong>
              <small v-if="day.advertising?.coveredStores">暂估 · 可比{{ day.advertising.coveredStores }}/{{ day.advertising.totalStores }}店</small>
            </p>
          </article>
        </div>
      </div>
      <p class="footnote">月初与上月最后一天比较；前一日为零且当日有值时显示“新增”，前一日有值且当日为零显示下降100%。广告环比按前后两日都有完整花费数据的共同店铺估算，并标明可比店铺数；没有共同店铺时显示“暂无可比数据”。今天的数据仍在同步，环比会继续变化。原币种可分别查看，也可查看CNY合计。</p>
    </template>
  </section>
</template>

<script setup>
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue';
import { fetchMonthlySalesProgress } from '../../api/salesManagement';
import { useAuthStore } from '../../stores/auth';

const auth = useAuthStore();
const canRead = computed(() => auth.currentUser?.user_type === 'internal'
  && auth.hasActionPermission('sales_management.view'));
const data = ref(null);
const loading = ref(true);
const error = ref('');
const selectedCurrency = ref('');
const allStoresOption = "all";
const selectedStoreIds = ref([]);
const selectedPlatformId = ref(null);
const platforms = ref([]);
const stores = ref([]);
const storesLoaded = ref(false);
const todayMonth = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit" }).format(new Date());
const selectedMonth = ref(todayMonth);
const currencies = computed(() => data.value?.currencies || []);
const displayCurrencies = computed(() => [
  ...(data.value?.cny_summary ? [data.value.cny_summary] : []), ...currencies.value,
]);
const monthLabel = computed(() => data.value?.month ? `${data.value.month.slice(0, 4)}年${Number(data.value.month.slice(5))}月` : '本月');
const weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
let requestSequence = 0;
let activeController = null;
let filterTimer = null;
let active = false;

function cancelRequest() {
  requestSequence += 1;
  activeController?.abort();
  activeController = null;
  loading.value = false;
}

function scheduleFilterLoad() {
  cancelRequest();
  clearTimeout(filterTimer);
  data.value = null;
  selectedCurrency.value = '';
  loading.value = true;
  error.value = '';
  filterTimer = setTimeout(() => { filterTimer = null; load(); }, 250);
}

async function load() {
  if (!active) return;
  clearTimeout(filterTimer);
  filterTimer = null;
  activeController?.abort();
  const sequence = ++requestSequence;
  if (!canRead.value) {
    loading.value = false;
    error.value = '';
    return;
  }
  loading.value = true;
  error.value = '';
  const controller = new AbortController();
  activeController = controller;
  try {
    const response = await fetchMonthlySalesProgress(selectedStoreIds.value, selectedPlatformId.value, selectedMonth.value, { signal: controller.signal });
    if (sequence !== requestSequence || controller.signal.aborted) return;
    if (!response?.success) {
      if (response?.http_status === 403) { data.value = null; selectedCurrency.value = ''; }
      error.value = response?.http_status === 403
        ? '当前账号没有销售数据查看权限或可用的数据范围。'
        : '销售数据暂时无法读取，请稍后重试。';
      return;
    }
    data.value = response.data;
    stores.value = Array.isArray(response.data?.stores) ? response.data.stores : [];
    platforms.value = Array.isArray(response.data?.platforms) ? response.data.platforms : [];
    storesLoaded.value = true;
    selectedStoreIds.value = response.data?.selected_store_ids ?? (response.data?.selected_store_id == null ? [] : [response.data.selected_store_id]);
    selectedPlatformId.value = response.data?.selected_platform_id ?? null;
    if (!displayCurrencies.value.some((item) => item.currency === selectedCurrency.value)) {
      selectedCurrency.value = displayCurrencies.value[0]?.currency || '';
    }
  } catch (_failure) {
    if (sequence === requestSequence && !controller.signal.aborted) error.value = '销售数据暂时无法读取，请稍后重试。';
  } finally {
    if (sequence === requestSequence) { loading.value = false; activeController = null; }
  }
}

function storeLabel(store) {
  const name = store.name || store.platform_store_name || store.code;
  const detail = store.name ? store.platform_store_name : store.platform_store_name && store.code;
  return detail ? `${name}（${detail}）` : name;
}

function changeStore(values) {
  selectedStoreIds.value = values.includes(allStoresOption) ? [] : values;
  selectedCurrency.value = '';
  scheduleFilterLoad();
}

function changeMonth() {
  if (!selectedMonth.value || selectedMonth.value > todayMonth) selectedMonth.value = todayMonth;
  selectedCurrency.value = '';
  scheduleFilterLoad();
}

function changePlatform(event) {
  const value = event.target.value;
  selectedPlatformId.value = value === '' ? null : Number(value);
  selectedStoreIds.value = [];
  stores.value = [];
  storesLoaded.value = false;
  selectedCurrency.value = '';
  scheduleFilterLoad();
}

onMounted(() => { active = true; load(); });
onActivated(() => { if (!active) { active = true; load(); } });
onDeactivated(() => { active = false; clearTimeout(filterTimer); filterTimer = null; cancelRequest(); });
onUnmounted(() => { active = false; clearTimeout(filterTimer); filterTimer = null; cancelRequest(); });
watch(() => auth.currentUser, () => {
  cancelRequest();
  clearTimeout(filterTimer);
  filterTimer = null;
  data.value = null;
  selectedCurrency.value = '';
  selectedStoreIds.value = [];
  selectedPlatformId.value = null;
  platforms.value = [];
  stores.value = [];
  storesLoaded.value = false;
  load();
});
watch(canRead, (allowed) => {
  if (!allowed) {
    cancelRequest();
    clearTimeout(filterTimer);
    filterTimer = null;
    data.value = null;
    selectedCurrency.value = '';
    error.value = '';
  } else if (active) load();
});

const selected = computed(() => displayCurrencies.value.find((item) => item.currency === selectedCurrency.value));
const currencyLabel = computed(() => selectedCurrency.value === 'CNY_TOTAL' ? 'CNY合计' : selectedCurrency.value);
const leadingDays = computed(() => {
  if (!data.value?.month) return 0;
  return (new Date(`${data.value.month}-01T00:00:00Z`).getUTCDay() + 6) % 7;
});

function growth(current, previous, advertising = false) {
  if (previous === 0 && current > 0) return { direction: 'up', icon: '↑', label: '新增', description: '新增' };
  if (previous === 0) return { direction: 'flat', icon: '→', label: advertising ? '持平' : '—', description: advertising ? '持平' : '均无销售' };
  const percentage = (current - previous) / previous * 100;
  const direction = percentage > 0 ? 'up' : percentage < 0 ? 'down' : 'flat';
  const icon = direction === 'up' ? '↑' : direction === 'down' ? '↓' : '→';
  const label = `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(Math.abs(percentage))}%`;
  const description = direction === 'up' ? `增长${label}` : direction === 'down' ? `下降${label}` : '持平';
  return { direction, icon, label, description };
}

const days = computed(() => {
  if (!selected.value || !data.value?.month || !data.value?.through) return [];
  const daily = new Map((selected.value.daily || []).map((item) => [item.date, item]));
  const end = new Date(`${data.value.through}T00:00:00Z`);
  const cursor = new Date(`${data.value.month}-01T00:00:00Z`);
  let previousAmount = Number(selected.value.previous?.amount) || 0;
  let previousQuantity = Number(selected.value.previous?.quantity) || 0;
  let previousAdSpend = selected.value.previous?.ad_spend == null ? null : Number(selected.value.previous.ad_spend);
  const result = [];
  for (; cursor <= end; cursor.setUTCDate(cursor.getUTCDate() + 1)) {
    const date = cursor.toISOString().slice(0, 10);
    const row = daily.get(date);
    const amount = Number(row?.amount) || 0;
    const quantity = Number(row?.quantity) || 0;
    const adSpend = row?.ad_spend == null ? null : Number(row.ad_spend);
    const hasComparison = row && Object.hasOwn(row, 'ad_comparison');
    const comparison = row?.ad_comparison;
    const cmpCurrent = comparison?.current == null ? null : Number(comparison.current);
    const cmpPrevious = comparison?.previous == null ? null : Number(comparison.previous);
    const baseGrowth = hasComparison
      ? (comparison && Number.isFinite(cmpCurrent) && Number.isFinite(cmpPrevious) ? growth(cmpCurrent, cmpPrevious, true) : null)
      : (adSpend === null || previousAdSpend === null || !Number.isFinite(adSpend) || !Number.isFinite(previousAdSpend) ? null : growth(adSpend, previousAdSpend, true));
    const advertising = baseGrowth && comparison
      ? { ...baseGrowth, coveredStores: comparison.covered_stores, totalStores: comparison.total_stores }
      : baseGrowth;
    result.push({ date, sales: growth(amount, previousAmount), quantity: growth(quantity, previousQuantity), advertising, hasComparison });
    previousAmount = amount;
    previousQuantity = quantity;
    previousAdSpend = adSpend;
  }
  return result;
});
const latestMetrics = computed(() => {
  const latest = days.value.at(-1);
  return latest ? [
    { key: 'sales', name: '销售额日环比', growth: latest.sales },
    { key: 'quantity', name: '销量日环比', growth: latest.quantity },
  ] : [];
});
const latestAdGrowth = computed(() => data.value?.advertising_status === 'forbidden' ? null : days.value.at(-1)?.advertising || null);
const hasComparisonForLatest = computed(() => days.value.at(-1)?.hasComparison || false);
</script>

<style scoped>
.monthly-sales { padding: 20px 24px; border: 1px solid #dbe3ec; border-radius: 10px; background: #fff; }
.monthly-sales-header, .chart-toolbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.eyebrow { margin: 0 0 4px; color: #315c87; font-size: 12px; font-weight: 700; }
.monthly-sales h2 { margin: 0; color: #172033; font-size: 20px; }
.description { margin: 8px 0 0; color: #65758c; font-size: 13px; }
.refresh-button, .retry-button { flex-shrink: 0; white-space: nowrap; padding: 6px 12px; color: #1f63b5; border: 1px solid #bfd1e8; border-radius: 6px; background: #fff; cursor: pointer; }
.store-picker { display: flex; flex-wrap: wrap; align-items: center; gap: 9px; margin-top: 16px; color: #42526a; font-size: 13px; }
.store-picker select, .store-picker input { max-width: min(420px, 70vw); padding: 6px 30px 6px 9px; color: #26364b; border: 1px solid #cbd7e5; border-radius: 6px; background: #fff; }
.store-picker select, .store-picker input {
  box-sizing: border-box;
  height: 34px;
  min-height: 34px;
  font: inherit;
}
.store-picker select {
  appearance: none;
  -webkit-appearance: none;
  background: #fff url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 8'%3E%3Cpath d='m1 1 5 5 5-5' fill='none' stroke='%2342526a' stroke-width='1.5'/%3E%3C/svg%3E") no-repeat right 10px center / 10px;
}
.store-picker input[type="month"] { appearance: none; -webkit-appearance: none; padding-right: 9px; }
.store-multiselect { width: 320px; max-width: min(420px, 70vw); }
.store-multiselect :deep(.el-select__wrapper) { box-sizing: border-box; height: 34px; min-height: 34px; }
.store-picker select:disabled { color: #65758c; background-color: #f5f7fa; }
.empty-stores { color: #77859a; }
.chart-state { display: flex; align-items: center; justify-content: center; gap: 16px; min-height: 244px; color: #65758c; }
.chart-toolbar { align-items: center; margin: 24px 0 14px; }
.month-caption { display: flex; align-items: baseline; gap: 10px; color: #65758c; font-size: 13px; }
.month-caption strong { color: #172033; font-size: 16px; }
.currency-tabs { display: flex; flex-wrap: wrap; gap: 6px; }
.currency-tabs button { padding: 6px 11px; color: #42526a; border: 1px solid #dbe3ec; border-radius: 6px; background: #fff; cursor: pointer; }
.currency-tabs button.active { color: #1558ae; border-color: #8eb6ee; background: #edf5ff; font-weight: 700; }
.latest-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.latest-card { display: flex; flex-direction: column; gap: 6px; padding: 14px 16px; border: 1px solid #e1eaf4; border-radius: 8px; background: #f8fbff; }
.latest-card > span, .latest-card small { color: #65758c; font-size: 12px; }
.latest-card strong { font-size: 23px; font-variant-numeric: tabular-nums; }
.trend-icon { display: inline-flex; align-items: center; justify-content: center; width: 1.1em; height: 1.1em; margin-right: 4px; border-radius: 50%; font-size: .9em; font-weight: 800; }
.up { color: #16805d; }
.down { color: #c44747; }
.flat { color: #64748b; }
.up .trend-icon { background: #e3f7ed; }
.down .trend-icon { background: #ffebeb; }
.flat .trend-icon { background: #eaf0f5; }
.calendar-scroll { overflow-x: auto; }
.calendar { display: grid; grid-template-columns: repeat(7, minmax(92px, 1fr)); gap: 7px; min-width: 720px; }
.weekday { padding: 6px 2px; color: #64748b; font-size: 12px; text-align: center; }
.day-card { min-height: 89px; padding: 8px 9px; border: 1px solid #e3eaf2; border-radius: 7px; background: #fff; }
.day-card.today { border-color: #87b4eb; background: #f4f9ff; }
.day-card h3 { margin: 0 0 6px; color: #34455b; font-size: 12px; }
.day-card h3 span { margin-left: 4px; color: #1e65b8; font-size: 11px; }
.day-card p { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px; margin: 4px 0 0; font-size: 11px; }
.day-card p > span { color: #6d7c90; }
.day-card p > small { flex-basis: 100%; text-align: right; }
.day-card strong { white-space: nowrap; font-size: 12px; font-variant-numeric: tabular-nums; }
.calendar-pad { visibility: hidden; }
.footnote { margin: 12px 0 0; color: #77859a; font-size: 12px; }
@media (max-width: 700px) {
  .monthly-sales { padding: 16px; }
  .chart-toolbar { flex-direction: column; align-items: flex-start; }
  .latest-grid { grid-template-columns: 1fr; }
}
</style>
