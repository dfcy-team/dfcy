<template>
  <section class="snapshots" aria-label="今日09:00同时段快照">
    <header><div><h2>今日09:00同时段</h2><p>只读取已采集的店铺当地时间00:00至09:00订单；样本完整性尚未核验，不计算变化率或异常结论。</p></div><button type="button" @click="$emit('close')">收起</button></header>
    <form class="snapshot-query" @submit.prevent="query">
      <label>业务日期（店铺当地；默认北京时间今日）<input v-model="draftDate" type="date" required></label>
      <button class="primary" :disabled="loading">{{ loading ? '读取中…' : '读取快照' }}</button>
      <span>日期修改后需点击读取；打开面板不会自动请求。</span>
    </form>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="!queried && !loading" class="empty">选择日期后点击“读取快照”。</p>
    <p v-else-if="queried && !loading && !rows.length" class="empty">此范围没有已保存快照；缺少采样不代表 GMV 或订单为零。</p>
    <div v-if="loading" class="empty" role="status">正在读取已保存快照…</div>
    <div v-if="rows.length" class="snapshot-scroll" tabindex="0" aria-label="09:00快照，可横向滚动">
      <article v-for="row in rows" :key="row.store_id" class="store-card">
        <div class="store-head"><div><strong>{{ row.store_name }}</strong><span>{{ row.country || '站点未知' }} · {{ row.timezone || '时区未知' }}</span></div><span class="integrity">{{ row.status === 'missing' ? '未采样' : '完整性未核验' }}</span></div>
        <p class="times">目标时间（店铺时区）：{{ timestamp(row.target_at, row.timezone) }}　采集时间（店铺时区）：{{ timestamp(row.captured_at, row.timezone) }}</p>
        <p class="integrity-reason">{{ row.integrity_reason || '采样完整性未知。' }}</p>
        <div v-if="!row.groups?.length" class="missing">当前日期没有币种快照数据；不补零。</div>
        <div v-for="group in row.groups || []" :key="group.currency" class="currency-group">
          <h3>{{ group.currency }}</h3>
          <dl class="metrics"><div><dt>已观测 GMV</dt><dd>{{ observedAmount(group.sales_amount) }} {{ group.currency }}</dd></div><div><dt>已观测订单</dt><dd>{{ observedCount(group.order_count) }} 单</dd></div></dl>
          <div class="baselines"><div v-for="item in baselineItems(group.baselines)" :key="item.key"><span>{{ item.label }}</span><strong>{{ baselineAmount(item.value, group.currency) }}</strong><small>{{ item.value?.sample_count == null ? '无样本' : `样本 ${item.value.sample_count}` }} · {{ item.value?.status === 'unverified' ? '完整性未核验' : '缺样或时区不兼容' }}</small></div></div>
        </div>
      </article>
    </div>
    <footer v-if="queried" class="pagination"><span>第 {{ page }} 页 · 每页 {{ pageSize }} 家店铺</span><button :disabled="loading || page <= 1" @click="changePage(-1)">上一页</button><button :disabled="loading || !hasNext" @click="changePage(1)">下一页</button></footer>
  </section>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue';
import { fetchSalesNineSnapshots } from '../../api/salesNineSnapshots';

const props = defineProps({ scope: { type: Object, default: () => ({}) } });
defineEmits(['close']);
const pageSize = 20;
const dateInBeijing = () => {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
  const part = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  return `${part.year}-${part.month}-${part.day}`;
};
const draftDate = ref(dateInBeijing()), appliedDate = ref(''), rows = ref([]), loading = ref(false), error = ref(''), page = ref(1), hasNext = ref(false), queried = ref(false);
let generation = 0, controller = null, alive = true;
function query() { page.value = 1; appliedDate.value = draftDate.value; void load(); }
async function load() {
  const id = ++generation;
  controller?.abort(); controller = new AbortController();
  loading.value = true; error.value = ''; rows.value = []; queried.value = true;
  const params = { date: appliedDate.value, page: page.value, page_size: pageSize };
  for (const key of ['store_id', 'platform', 'region']) if (props.scope?.[key]) params[key] = props.scope[key];
  try {
    const response = await fetchSalesNineSnapshots(params, controller.signal);
    if (!alive || id !== generation) return;
    if (!response?.success) throw new Error(response?.message || '快照暂不可用，请重试。');
    rows.value = response.data?.rows || []; hasNext.value = Boolean(response.data?.has_next);
  } catch (failure) { if (alive && id === generation) error.value = failure?.message || '快照暂不可用，请重试。'; }
  finally { if (alive && id === generation) loading.value = false; }
}
function changePage(step) { page.value += step; void load(); }
function timestamp(value, zone) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { timeZone: zone || 'Asia/Shanghai', dateStyle: 'medium', timeStyle: 'medium' }).format(date); }
function observedAmount(value) { return value == null ? '—' : Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function observedCount(value) { return value == null ? '—' : Number(value).toLocaleString('zh-CN'); }
function baselineAmount(value, currency) { return value?.sales_amount == null ? `缺样 · — ${currency}` : `${observedAmount(value.sales_amount)} ${currency}（未核验）`; }
function baselineItems(baselines = {}) { return [
  { key: 'previous_day', label: '前一日09:00同时段', value: baselines.previous_day },
  { key: 'previous_week_same_day', label: '上周同日09:00同时段', value: baselines.previous_week_same_day },
  { key: 'previous_week_average', label: '上个自然周日均09:00同时段', value: baselines.previous_week_average }
]; }
watch(() => [props.scope?.store_id, props.scope?.platform, props.scope?.region], () => {
  ++generation; controller?.abort(); controller = null; loading.value = false; rows.value = []; error.value = ''; hasNext.value = false; queried.value = false; page.value = 1;
});
onBeforeUnmount(() => { alive = false; ++generation; controller?.abort(); });
</script>

<style scoped>
.snapshots{margin:18px 0;padding:18px;border:1px solid #d7e2ee;border-radius:10px;background:#f8fafd;color:#26384e}.snapshots header,.store-head,.pagination{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.snapshots h2{margin:0;font-size:17px}.snapshots p{line-height:1.6;color:#68798d;font-size:12px}.snapshots button,.snapshots input{font:inherit;padding:8px 10px;border:1px solid #d5dfeb;border-radius:6px;background:white;color:#33465d}.snapshots button{cursor:pointer}.snapshots button:disabled{opacity:.5;cursor:default}.snapshots .primary{background:#2864b4;color:#fff;border-color:#2864b4}.snapshot-query{display:flex;align-items:flex-end;gap:12px;flex-wrap:wrap;margin:14px 0}.snapshot-query label{display:grid;gap:6px;font-size:12px}.snapshot-query span{font-size:12px;color:#68798d}.snapshot-scroll{display:grid;gap:12px;max-height:64vh;overflow:auto;padding:2px}.store-card{min-width:0;padding:16px;border:1px solid #e0e7ef;border-radius:8px;background:#fff}.store-head{align-items:center}.store-head strong,.store-head span{display:block}.store-head span,.times,.integrity-reason,.baselines small{font-size:11px;color:#748398}.integrity{padding:5px 8px;background:#fff4df;border-radius:4px;color:#805f26!important;white-space:nowrap}.times{margin:12px 0 4px}.integrity-reason{margin:4px 0 12px}.currency-group{border-top:1px solid #e8edf4;padding:10px 0}.currency-group h3{font-size:13px;margin:0 0 8px}.metrics{display:flex;gap:24px;margin:0 0 10px}.metrics>div{display:flex;gap:8px}.metrics dt,.baselines span{color:#68798d;font-size:12px}.metrics dd{margin:0;font-size:13px;font-variant-numeric:tabular-nums}.baselines{display:grid;grid-template-columns:repeat(3,minmax(180px,1fr));gap:10px;overflow-x:auto}.baselines>div{display:grid;gap:4px;padding:10px;background:#f7f9fc;border-radius:6px;min-width:170px}.baselines strong{font-size:13px;font-variant-numeric:tabular-nums}.empty,.missing{padding:18px;text-align:center;color:#748398;font-size:12px}.error{color:#a64040!important}.pagination{align-items:center;margin-top:12px;font-size:12px;color:#68798d}.pagination>span{margin-right:auto}@media(max-width:700px){.snapshots{padding:12px}.snapshots header{gap:8px}.snapshot-query label{width:100%}.snapshot-query input{box-sizing:border-box;width:100%}.baselines{grid-template-columns:1fr}.metrics{flex-wrap:wrap}}
</style>
