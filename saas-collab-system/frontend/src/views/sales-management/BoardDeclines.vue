<template>
  <section class="declines" :aria-busy="loading">
    <div class="heading"><h2>商品链接下降 TOP 10</h2><label>排序<select v-model="metric" aria-label="下降排序"><option value="amount">下降金额</option><option value="percent">下降比例</option></select></label><button :disabled="loading || !eligible" @click="load">刷新下降排行</button></div>
    <p class="note">按店铺与平台商品链接比较，金额为非取消订单商品行金额。仅比较两期都有记录且基准大于零的商品；未观测数据不按下降100%处理。</p>
    <p v-if="!eligible" role="status">请选择已结束的日期范围和单一币种；今日数据不与历史全天比较。</p>
    <p v-else-if="error" role="alert">{{ error }}</p>
    <p v-else-if="loading">正在读取下降排行…</p>
    <template v-else-if="data">
      <p class="note">观察期 {{ data.filters?.date_from }} — {{ data.filters?.date_to }} · 对比期 {{ data.filters?.previous_from }} — {{ data.filters?.previous_to }} · {{ filters.currency }}</p>
      <p v-for="notice in data.notices || []" :key="notice" class="note">{{ notice }}</p>
      <p v-if="!data.rows?.length">暂无满足比较条件的下降商品。</p>
      <div v-else class="table-scroll"><table><thead><tr><th>店铺／商品链接</th><th>本期金额</th><th>前期金额</th><th>下降金额</th><th>变化比例</th><th>原因详情</th></tr></thead><tbody>
        <tr v-for="row in data.rows" :key="`${row.store_id}:${row.currency}:${row.product_id}`"><td><strong>{{ row.product_name || row.product_id }}</strong><small>{{ row.store_name }} · {{ row.country }} · {{ row.product_id }}</small></td><td>{{ money(row.sales_amount) }}</td><td>{{ money(row.previous_sales_amount) }}</td><td>{{ money(row.decline_amount) }}</td><td>{{ money(row.change_percent) }}%</td><td><button @click="openSelected(row)">查看依据</button><button v-if="canDrill" @click="drill(row)">工作台精确核查</button></td></tr>
      </tbody></table></div>
      <section v-if="selected" class="reason" aria-label="下降原因详情"><div class="heading"><h3>{{ selected.product_name || selected.product_id }}</h3><button @click="selected = null">关闭详情</button></div>
        <p>{{ selected.store_name }} · {{ selected.country }} · {{ filters.currency }} · {{ data.filters?.date_from }} — {{ data.filters?.date_to }}</p>
        <p v-if="selected.diagnosis">{{ selected.diagnosis.title }}</p><p v-else>当前仅展示周期下降事实，未触发昨日单日下降超过30%的诊断规则。</p>
        <p>本期 {{ money(selected.sales_amount) }}，前期 {{ money(selected.previous_sales_amount) }}，变化 {{ money(selected.change_percent) }}%。</p>
        <p>原因待核查；销售下降不直接证明缺货、流量或广告问题。</p>
        <p>待补证据：{{ (selected.diagnosis?.missing || ['买家数', '访客数', '转化率', '历史库存', '促销及价格变化']).join('、') }}</p>
      </section>
    </template>
  </section>
</template>
<script setup lang="ts">
import { computed, nextTick, ref, watch, onBeforeUnmount } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { canAccessPath } from '../../router/menu';
import { fetchBoardDeclines } from '../../api/realtimeBoard';
type Row = Record<string, any>;
const props = defineProps<{ filters: Row }>();
const router = useRouter(), auth = useAuthStore();
const canDrill = computed(() => canAccessPath(auth.currentUser, '/sales-management/skus') && canAccessPath(auth.currentUser, '/sales-management/overview'));
const metric = ref(props.filters.metric === 'percent' ? 'percent' : 'amount'), data = ref<Row | null>(null), selected = ref<Row | null>(null), loading = ref(false), error = ref('');
let generation = 0, alive = true, controller: AbortController | null = null;
const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
const eligible = computed(() => Boolean(props.filters.currency && props.filters.date_from && props.filters.date_to && props.filters.date_to < today()));
const money = (value: any) => value == null || value === '' || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
function drill(row: Row) {
  if (!canDrill.value || !row.store_id || !row.product_id || !row.currency) return;
  router.push({ path: '/sales-management/overview', query: {
    view: 'operations', date_from: props.filters.date_from, date_to: props.filters.date_to,
    platform: props.filters.platform || '', region: props.filters.region || '', store_id: String(row.store_id),
    currency: row.currency, product_id: String(row.product_id), return_view: 'declines',
    return_date_from: props.filters.date_from, return_date_to: props.filters.date_to,
    return_platform: props.filters.platform || '', return_region: props.filters.region || '',
    return_store_id: props.filters.store_id || '', return_currency: props.filters.currency || '', return_metric: metric.value
  } });
}
async function openSelected(row: Row) { selected.value = row; await nextTick(); }
async function load() {
  const id = ++generation; controller?.abort(); data.value = null; selected.value = null; error.value = ''; loading.value = false;
  if (!eligible.value || !alive) return;
  controller = new AbortController(); loading.value = true;
  try {
    const response = await fetchBoardDeclines({ ...props.filters, metric: metric.value }, controller.signal);
    if (!alive || id !== generation) return;
    if (!response?.success) throw new Error(response?.message || '下降排行暂不可用');
    data.value = response.data;
  } catch (failure: any) { if (alive && id === generation) error.value = failure?.message || '下降排行暂不可用'; }
  finally { if (alive && id === generation) loading.value = false; }
}
watch(() => JSON.stringify([props.filters, metric.value]), load, { immediate: true });
watch(() => props.filters.metric, value => { if (value === 'amount' || value === 'percent') metric.value = value; });
onBeforeUnmount(() => { alive = false; ++generation; controller?.abort(); });
</script>
<style scoped>
.declines{grid-column:1 / -1;border:1px solid #344359;border-radius:8px;background:#131f31;padding:20px;min-width:0}.heading{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.heading h2,.heading h3{margin:0;margin-right:auto;font-size:16px}.heading label{display:flex;gap:8px;align-items:center;font-size:12px}button,select{background:#1b293d;color:#eaf0fa;border:1px solid #344359;border-radius:5px;padding:7px 10px;cursor:pointer}button:disabled{opacity:.5;cursor:default}button:focus-visible,select:focus-visible{outline:2px solid #55d6be;outline-offset:3px}.note,small{font-size:11px;color:#a8bedb;line-height:1.7}.table-scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:12px}th,td{padding:12px;border-top:1px solid #344359;text-align:right;white-space:nowrap}td:first-child,th:first-child{text-align:left}strong{display:block;max-width:320px;overflow:hidden;text-overflow:ellipsis}small{display:block}th{font-weight:400;color:#a8bedb}.reason{padding:18px;margin-top:18px;border:1px solid #506277;border-radius:6px;font-size:13px;line-height:1.7}@media(max-width:700px){.declines{padding:14px}strong{max-width:180px}}
</style>
