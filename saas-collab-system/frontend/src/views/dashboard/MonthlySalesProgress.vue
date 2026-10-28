<template>
  <section class="monthly-sales" aria-labelledby="monthly-sales-title">
    <header class="monthly-sales-header">
      <div>
        <p class="eyebrow">销售进度</p>
        <h2 id="monthly-sales-title">本月每日销售增长率</h2>
        <p class="description">按当前账号权限范围内可管理店铺统计非取消订单；销售额和销量均与前一日比较，不展示具体金额或件数。</p>
      </div>
      <button v-if="canRead && !loading" class="refresh-button" type="button" @click="load">刷新</button>
    </header>

    <div v-if="canRead" class="store-picker">
      <label for="monthly-sales-store">店铺</label>
      <select id="monthly-sales-store" :value="selectedStoreId ?? ''" :disabled="!stores.length"
        @change="changeStore">
        <option value="">全部可管理店铺</option>
        <option v-for="store in stores" :key="store.id" :value="String(store.id)">
          {{ store.name || store.platform_store_name || store.code }}
          <template v-if="store.name && store.platform_store_name">（{{ store.platform_store_name }}）</template>
          <template v-if="!store.name && store.code && store.platform_store_name">（{{ store.code }}）</template>
        </option>
      </select>
      <span v-if="!loading && storesLoaded && !stores.length" class="empty-stores">权限范围内暂无可管理店铺</span>
    </div>

    <div v-if="!canRead" class="chart-state">当前账号暂无销售数据查看权限。</div>
    <div v-else-if="loading" class="chart-state" role="status">正在读取本月销售数据…</div>
    <div v-else-if="error" class="chart-state" role="alert">
      {{ error }}
      <button type="button" class="retry-button" @click="load">重试</button>
    </div>
    <div v-else-if="!currencies.length" class="chart-state">本月可见范围内暂无销售订单。</div>
    <template v-else>
      <div class="chart-toolbar">
        <div class="month-caption">
          <strong>{{ monthLabel }}</strong>
          <span>每日环比 · {{ selectedCurrency }}</span>
        </div>
        <div v-if="currencies.length > 1" class="currency-tabs" role="group" aria-label="选择销售币种">
          <button v-for="item in currencies" :key="item.currency" type="button"
            :class="{ active: selectedCurrency === item.currency }"
            :aria-pressed="selectedCurrency === item.currency"
            @click="selectedCurrency = item.currency">{{ item.currency }}</button>
        </div>
      </div>

      <div class="latest-grid" aria-label="最新一天的增长率">
        <article v-for="metric in latestMetrics" :key="metric.key" class="latest-card">
          <span>{{ metric.name }} · {{ data.through }}</span>
          <strong :class="metric.growth.direction">
            <span class="trend-icon" aria-hidden="true">{{ metric.growth.icon }}</span>
            {{ metric.growth.label }}
          </strong>
          <small>较前一日{{ metric.growth.description }}</small>
        </article>
      </div>

      <div class="calendar-scroll">
        <div class="calendar" role="group" :aria-label="`${monthLabel}${selectedCurrency}每日销售额和销量增长率`">
          <div v-for="weekday in weekdays" :key="weekday" class="weekday">{{ weekday }}</div>
          <div v-for="index in leadingDays" :key="`pad-${index}`" class="calendar-pad" aria-hidden="true" />
          <article v-for="day in days" :key="day.date" class="day-card" :class="{ today: day.date === data.through }">
            <h3>{{ Number(day.date.slice(-2)) }}日 <span v-if="day.date === data.through">今天</span></h3>
            <p :class="day.sales.direction" :aria-label="`销售额较前一日${day.sales.description}`">
              <span>销售额</span><strong><span class="trend-icon" aria-hidden="true">{{ day.sales.icon }}</span>{{ day.sales.label }}</strong>
            </p>
            <p :class="day.quantity.direction" :aria-label="`销量较前一日${day.quantity.description}`">
              <span>销量</span><strong><span class="trend-icon" aria-hidden="true">{{ day.quantity.icon }}</span>{{ day.quantity.label }}</strong>
            </p>
          </article>
        </div>
      </div>
      <p class="footnote">月初与上月最后一天比较；前一日为零且当日有销售时显示“新增”。今天的数据仍在同步，环比会继续变化。不同币种分别查看。</p>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { fetchMonthlySalesProgress } from '../../api/salesManagement';
import { useAuthStore } from '../../stores/auth';

const auth = useAuthStore();
const canRead = computed(() => auth.currentUser?.user_type === 'internal'
  && auth.hasActionPermission('sales_management.view'));
const data = ref(null);
const loading = ref(false);
const error = ref('');
const selectedCurrency = ref('');
const selectedStoreId = ref(null);
const stores = ref([]);
const storesLoaded = ref(false);
const currencies = computed(() => data.value?.currencies || []);
const monthLabel = computed(() => data.value?.month ? `${data.value.month.slice(0, 4)}年${Number(data.value.month.slice(5))}月` : '本月');
const weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
let requestSequence = 0;

async function load() {
  const sequence = ++requestSequence;
  if (!canRead.value) {
    loading.value = false;
    error.value = '';
    return;
  }
  loading.value = true;
  error.value = '';
  data.value = null;
  try {
    const response = await fetchMonthlySalesProgress(selectedStoreId.value);
    if (sequence !== requestSequence) return;
    if (!response?.success) {
      error.value = response?.http_status === 403
        ? '当前账号没有销售数据查看权限或可用的数据范围。'
        : '销售数据暂时无法读取，请稍后重试。';
      return;
    }
    data.value = response.data;
    stores.value = Array.isArray(response.data?.stores) ? response.data.stores : [];
    storesLoaded.value = true;
    selectedStoreId.value = response.data?.selected_store_id ?? null;
    if (!currencies.value.some((item) => item.currency === selectedCurrency.value)) {
      selectedCurrency.value = currencies.value[0]?.currency || '';
    }
  } catch (_failure) {
    if (sequence === requestSequence) error.value = '销售数据暂时无法读取，请稍后重试。';
  } finally {
    if (sequence === requestSequence) loading.value = false;
  }
}

function changeStore(event) {
  const value = event.target.value;
  selectedStoreId.value = value === '' ? null : Number(value);
  data.value = null;
  selectedCurrency.value = '';
  load();
}

onMounted(load);
watch(() => auth.currentUser, () => {
  data.value = null;
  selectedCurrency.value = '';
  selectedStoreId.value = null;
  stores.value = [];
  storesLoaded.value = false;
  load();
});

const selected = computed(() => currencies.value.find((item) => item.currency === selectedCurrency.value));
const leadingDays = computed(() => {
  if (!data.value?.month) return 0;
  return (new Date(`${data.value.month}-01T00:00:00Z`).getUTCDay() + 6) % 7;
});

function growth(current, previous) {
  if (previous === 0 && current > 0) return { direction: 'up', icon: '↑', label: '新增', description: '新增' };
  if (previous === 0) return { direction: 'flat', icon: '→', label: '—', description: '均无销售' };
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
  const result = [];
  for (; cursor <= end; cursor.setUTCDate(cursor.getUTCDate() + 1)) {
    const date = cursor.toISOString().slice(0, 10);
    const row = daily.get(date);
    const amount = Number(row?.amount) || 0;
    const quantity = Number(row?.quantity) || 0;
    result.push({ date, sales: growth(amount, previousAmount), quantity: growth(quantity, previousQuantity) });
    previousAmount = amount;
    previousQuantity = quantity;
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
</script>

<style scoped>
.monthly-sales { padding: 20px 24px; border: 1px solid #dbe3ec; border-radius: 10px; background: #fff; }
.monthly-sales-header, .chart-toolbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.eyebrow { margin: 0 0 4px; color: #315c87; font-size: 12px; font-weight: 700; }
.monthly-sales h2 { margin: 0; color: #172033; font-size: 20px; }
.description { margin: 8px 0 0; color: #65758c; font-size: 13px; }
.refresh-button, .retry-button { flex-shrink: 0; white-space: nowrap; padding: 6px 12px; color: #1f63b5; border: 1px solid #bfd1e8; border-radius: 6px; background: #fff; cursor: pointer; }
.store-picker { display: flex; align-items: center; gap: 9px; margin-top: 16px; color: #42526a; font-size: 13px; }
.store-picker select { max-width: min(420px, 70vw); padding: 6px 30px 6px 9px; color: #26364b; border: 1px solid #cbd7e5; border-radius: 6px; background: #fff; }
.store-picker select:disabled { color: #65758c; background: #f5f7fa; }
.empty-stores { color: #77859a; }
.chart-state { display: flex; align-items: center; justify-content: center; gap: 16px; min-height: 244px; color: #65758c; }
.chart-toolbar { align-items: center; margin: 24px 0 14px; }
.month-caption { display: flex; align-items: baseline; gap: 10px; color: #65758c; font-size: 13px; }
.month-caption strong { color: #172033; font-size: 16px; }
.currency-tabs { display: flex; flex-wrap: wrap; gap: 6px; }
.currency-tabs button { padding: 6px 11px; color: #42526a; border: 1px solid #dbe3ec; border-radius: 6px; background: #fff; cursor: pointer; }
.currency-tabs button.active { color: #1558ae; border-color: #8eb6ee; background: #edf5ff; font-weight: 700; }
.latest-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
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
.day-card p { display: flex; justify-content: space-between; gap: 4px; margin: 4px 0 0; font-size: 11px; }
.day-card p > span { color: #6d7c90; }
.day-card strong { white-space: nowrap; font-size: 12px; font-variant-numeric: tabular-nums; }
.calendar-pad { visibility: hidden; }
.footnote { margin: 12px 0 0; color: #77859a; font-size: 12px; }
@media (max-width: 700px) {
  .monthly-sales { padding: 16px; }
  .chart-toolbar { flex-direction: column; align-items: flex-start; }
  .latest-grid { grid-template-columns: 1fr; }
}
</style>
