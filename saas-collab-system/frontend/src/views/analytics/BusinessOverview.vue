<template>
  <section class="business-overview" :aria-busy="loading">
    <header>
      <div>
        <h1>经营总览</h1>
        <p>查看核心摘要和数据缺口，点击指标进入对应业务模块。</p>
      </div>
      <BusinessDashboardLink module="经营分析" /><el-tag effect="plain">{{ loading ? '读取中' : '业务数据摘要' }}</el-tag>
    </header>
    <el-form inline @submit.prevent="search">
      <el-form-item label="平台"
        ><el-select v-model="query.platforms" multiple clearable @change="pruneStores"
          ><el-option
            v-for="platform in options.platforms || []"
            :key="platform"
            :value="platform"
            :label="platform" /></el-select
      ></el-form-item>
      <el-form-item label="店铺"
        ><el-select v-model="query.store_ids" multiple clearable filterable
          ><el-option
            v-for="store in stores"
            :key="store.id"
            :value="store.id"
            :label="store.name || store.code" /></el-select
      ></el-form-item>
      <el-form-item label="币种"
        ><el-select v-model="query.currency" clearable
          ><el-option
            v-for="currency in options.currencies || []"
            :key="currency"
            :value="currency"
            :label="currency" /></el-select
      ></el-form-item>
      <el-form-item label="销售日期"
        ><el-date-picker
          v-model="query.date_range"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至" /></el-form-item
      ><el-button type="primary" native-type="submit" :loading="loading">查询</el-button>
    </el-form>
    <p v-if="pendingFilters" class="note">筛选已修改，请查询后更新摘要。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <section v-for="group in groups" :key="group.currency" :data-currency="group.currency">
      <h2>销售摘要 · {{ group.currency || '币种未提供' }}</h2>
      <div class="cards">
        <button
          v-for="code in codes"
          :key="code"
          @click="openSales()"
          :disabled="!canAccessPath(auth.currentUser, '/analytics/sales')"
        >
          <span>{{ metric(group, code).label }}</span
          ><strong>{{ metric(group, code).display }}</strong
          ><small>{{ metric(group, code).definition }}</small>
        </button>
      </div>
    </section>
    <div class="cards">
      <button
        v-for="card in stockCards"
        :key="card.label"
        @click="openStock"
        :disabled="!canAccessPath(auth.currentUser, '/analytics/inventory')"
      >
        <span>{{ card.label }}</span
        ><strong>{{ card.value }}</strong
        ><small>授权仓库范围 · 截止 {{ applied.date_range?.[1] || '当前时点' }}</small>
      </button>
    </div>
    <section class="exceptions">
      <h2>重点缺口与数据时效</h2>
      <p>
        销售来源更新时间：{{ data.quality?.refreshed_at || '未提供' }}；库存来源更新时间：{{
          stock?.refreshed_at || '未提供'
        }}。
      </p>
      <p>
        未关联库存：{{ stockMissing ?? '未评估' }} 个仓库 SKU；订单 / 售后质量问题：{{
          data.quality?.problem_rows ?? '未评估'
        }}
        条。
      </p>
      <div class="links">
        <el-button
          v-for="link in links.filter((item) => canAccessPath(auth.currentUser, item.path))"
          :key="link.path"
          @click="router.push(link.path)"
          >{{ link.label }}</el-button
        >
      </div>
    </section>
    <el-empty v-if="!loading && !groups.length" description="当前筛选范围暂无订单数据。" />
    <details class="note">
      <summary>统计口径</summary>
      <p>
        销售金额和商品销量排除取消订单；净销售额扣除已完成退款，退款申请不等于已完成退款。金额按来源币种分组。库存按授权仓库的截止快照统计，与销售店铺筛选分别展示；默认排除已知虚拟商品。费用、估值和对账明细在财务中心查看。
      </p>
    </details>
  </section>
</template>
<script setup>
import BusinessDashboardLink from '../reports/BusinessDashboardLink.vue';
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { canAccessPath } from '../../router/menu';
import { fetchBusinessFilters, fetchBusinessOverview } from '../../api/analytics';
import { queryReport } from '../../api/reporting';
import { reportError } from '../reports/reportDisplay';
import { completedDateRange } from '../sales-management/overviewTrend';
import { formatField, formatMetric } from '../sales-management/display';
const router = useRouter(),
  auth = useAuthStore();
const defaults = () => ({ platforms: [], store_ids: [], currency: '', date_range: completedDateRange(30) });
const query = reactive(defaults()),
  applied = ref(defaults()),
  options = ref({}),
  data = ref({}),
  stock = ref(null),
  loading = ref(false),
  error = ref('');
let sequence = 0;
const stores = computed(() =>
  (options.value.stores || []).filter((store) => !query.platforms.length || query.platforms.includes(store.platform))
);
const pendingFilters = computed(() => JSON.stringify(query) !== JSON.stringify(applied.value));
const groups = computed(() => (data.value.api_status === 'connected' ? data.value.currency_groups || [] : []));
const codes = ['order_count', 'gross_sales', 'net_sales', 'cancellation_rate', 'units_sold', 'refund_amount'];
const stockTotal = (key) => stock.value?.rows?.reduce((sum, row) => sum + Number(row[key] || 0), 0);
const stockMissing = computed(() => stockTotal('unmapped_count'));
const stockCards = computed(() => [
  { label: '可用库存', value: stock.value ? formatField(stockTotal('available'), { numeric: true }) : '未评估' },
  { label: '缺货仓库 SKU 数', value: stock.value ? formatField(stockTotal('out_count'), { numeric: true }) : '未评估' }
]);
const links = [
  { path: '/sales-management/data-quality', label: '销售数据质量' },
  { path: '/sales-management/stores', label: '门店销售明细' },
  { path: '/inventory/workbench', label: '库存工作台' },
  { path: '/finance/analytics', label: '财务费用与估值' },
  { path: '/reports/basic', label: '自助报表' }
];
function metric(group, code) {
  if (code === 'cancellation_rate') {
    const order = group.metrics?.find((v) => v.code === 'order_count')?.value,
      cancel = group.metrics?.find((v) => v.code === 'cancelled_order_count')?.value;
    return {
      label: '取消率',
      display: formatField(Number(order) > 0 && cancel != null ? Number(cancel) / Number(order) : null, {
        format: 'ratio'
      }),
      definition: '取消订单量 ÷ 订单总量'
    };
  }
  return formatMetric(group.metrics?.find((v) => v.code === code) || { code, value: null });
}
function pruneStores() {
  query.store_ids = query.store_ids.filter((id) => stores.value.some((store) => store.id === id));
}
function saleFilters() {
  return {
    platforms: applied.value.platforms.join(','),
    store_ids: applied.value.store_ids.join(','),
    currency: applied.value.currency,
    date_from: applied.value.date_range?.[0],
    date_to: applied.value.date_range?.[1]
  };
}
function openSales() {
  router.push({ path: '/analytics/sales', query: saleFilters() });
}
function openStock() {
  router.push({ path: '/analytics/inventory', query: { as_of: 'true', date_to: applied.value.date_range?.[1] } });
}
async function search() {
  const current = ++sequence;
  loading.value = true;
  error.value = '';
  const snapshot = JSON.parse(JSON.stringify(query));
  try {
    const response = await fetchBusinessOverview({
      ...snapshot,
      compact: 'true',
      platforms: snapshot.platforms.join(','),
      store_ids: snapshot.store_ids.join(',')
    });
    if (current !== sequence) return;
    if (!response.success || response.data?.api_status !== 'connected')
      throw new Error('经营数据读取失败；不使用模拟数据代替业务结果。');
    data.value = response.data;
    applied.value = snapshot;
    try {
      const stockResponse = await queryReport({
        dataset: 'inventory',
        dimensions: ['warehouse_id', 'site_code'],
        metrics: ['available', 'out_count', 'unmapped_count'],
        filters: snapshot.date_range?.[1] ? { date_to: snapshot.date_range[1] } : {}
      });
      if (current === sequence) stock.value = stockResponse.success ? stockResponse.data : null;
    } catch {
      if (current === sequence) stock.value = null;
    }
  } catch (failure) {
    if (current === sequence) {
      data.value = {};
      stock.value = null;
      error.value = reportError(failure.message, '经营数据读取失败，请重试或检查数据接入状态。');
    }
  } finally {
    if (current === sequence) loading.value = false;
  }
}
onMounted(async () => {
  search();
  const response = await fetchBusinessFilters();
  if (response.success) options.value = response.data || {};
});
</script>
<style scoped>
.business-overview {
  display: grid;
  gap: 16px;
  min-width: 0;
  color: #172033;
}
header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}
h1 {
  margin: 0;
  font-size: 24px;
}
h2 {
  font-size: 15px;
}
.note,
header p,
.exceptions p {
  font-size: 12px;
  color: #526177;
  line-height: 1.7;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}
.cards button {
  display: grid;
  gap: 10px;
  text-align: left;
  background: white;
  border: 1px solid #dce3ec;
  border-radius: 6px;
  padding: 16px;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.cards button:disabled {
  cursor: default;
  opacity: 1;
}
.cards strong {
  font-size: 24px;
  font-variant-numeric: tabular-nums;
}
.cards small {
  color: #526177;
  font-size: 11px;
}
.exceptions {
  padding: 16px;
  background: #fff;
  border: 1px solid #dce3ec;
}
.links {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.business-overview :deep(.el-select) {
  min-width: 160px;
}
</style>
