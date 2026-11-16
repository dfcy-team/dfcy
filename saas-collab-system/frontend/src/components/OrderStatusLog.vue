<template>
  <section v-if="auth.hasPermission('sales_management.orders.view')" class="order-log" aria-label="订单状态日志">
    <header><h3>订单日志 <small>{{ data.count ?? data.events.length }} 条</small></h3><span>最新在前 · 北京时间</span></header>
    <p v-if="loading" role="status">正在读取订单日志…</p>
    <p v-else-if="error" role="alert">{{ error }} <button @click="load">重试</button></p>
    <template v-else>
      <p v-if="!data.events.length" class="empty">暂无已保存的状态推送，历史完成和取消时间暂无记录。</p>
      <ol v-else>
        <li v-for="event in shown" :key="event.id"><time>{{ displayTime(event.event_at) }}</time><div><strong>{{ eventTitle(event) }}</strong><p>{{ event.source || '平台状态推送' }}<span v-if="event.status"> · {{ event.status }}</span></p><details v-if="plainTitle(event.title) && eventTitle(event) !== plainTitle(event.title)"><summary>查看平台原文</summary><p class="original">{{ plainTitle(event.title) }}</p></details></div></li>
      </ol>
      <button v-if="data.events.length > 6" class="toggle" @click="expanded = !expanded">{{ expanded ? '收起较早记录 ↑' : `展开其余 ${data.events.length - 6} 条记录 ↓` }}</button>
      <button v-if="expanded && data.has_more" :disabled="loadingMore" @click="loadMore">{{ loadingMore ? '读取中…' : '加载更早日志' }}</button>
      <p v-if="moreError" role="alert">{{ moreError }}</p>
      <p class="note">{{ data.message }}</p>
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useAuthStore } from '../stores/auth';
import { fetchOrderEvents } from '../api/salesManagement';

const props = defineProps({ orderId: { type: [Number, String], required: true } });
const auth = useAuthStore();
const data = ref({ events: [] }), error = ref(''), loading = ref(false), expanded = ref(false);
const loadingMore = ref(false), moreError = ref('');
let generation = 0;
const shown = computed(() => expanded.value ? data.value.events : data.value.events.slice(0, 6));
const title = event => event.status === 'COMPLETED'
  ? (event.completed_scenario === 'NORMAL' ? '订单完成' : event.completed_scenario === 'RRAOC' ? '完成后售后流程结束' : '平台状态更新：已完成')
  : ({ IN_CANCEL: '申请取消', CANCELLED: '订单取消', UNPAID: '待付款', READY_TO_SHIP: '待发货', PROCESSED: '处理中', SHIPPED: '已发货' }[event.status] || '平台状态更新');
// Keep provider text as escaped text; links and markup are never rendered.
const plainTitle = value => String(value || '')
  .replace(/&lt;/gi, '<').replace(/&gt;/gi, '>').replace(/&quot;/gi, '"').replace(/&#39;|&apos;/gi, "'").replace(/&amp;/gi, '&')
  .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, '')
  .replace(/<[^>]*>/g, ' ').replace(/&nbsp;/gi, ' ').replace(/\s+/g, ' ').trim();
const logisticsTitles = [
  [/^Your (?:package|parcel) has been delivered(?:!| to buyer|\.|$)/i, '包裹已妥投'],
  [/^Your package is currently out for delivery\b/i, '包裹正在派送'],
  [/^Your package has departed from the last mile hub for delivery\b/i, '包裹已离开末端配送站'],
  [/^Your package has arrived at the last mile hub before delivery\b/i, '包裹已到达末端配送站'],
  [/^Your package has departed from the sortation facility\b/i, '包裹已离开分拣中心'],
  [/^Your package has arrived at the sortation facility\b/i, '包裹已到达分拣中心'],
  [/^Your package has been picked up by\b/i, '物流商已揽收'],
  [/^Your parcel has been handed over to\b/i, '包裹已交接物流商'],
  [/^Your package is packed and will be handed over to our logistics partner\b/i, '包裹已打包，待交接物流商']
];
function eventTitle(event) {
  const original = plainTitle(event.title);
  if (event.source === '平台物流') return logisticsTitles.find(([pattern]) => pattern.test(original))?.[1] || (/\p{Script=Han}/u.test(original) ? original : '物流节点更新');
  return original || title(event);
}
const displayTime = value => {
  const date = new Date(value);
  return !value || Number.isNaN(date.getTime()) ? '暂无记录' : new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'
  }).format(date);
};
async function load() {
  const version = ++generation;
  data.value = { events: [] }; error.value = ''; expanded.value = false;
  loadingMore.value = false; moreError.value = '';
  if (!auth.hasPermission('sales_management.orders.view') || !props.orderId) return;
  loading.value = true;
  try {
    const result = await fetchOrderEvents(props.orderId);
    if (version !== generation) return;
    if (!result?.success || !Array.isArray(result.data?.events)) throw new Error('read-failed');
    data.value = result.data;
  } catch {
    if (version === generation) error.value = '订单日志读取失败，请重试。';
  } finally {
    if (version === generation) loading.value = false;
  }
}
async function loadMore() {
  if (loadingMore.value) return;
  const version = generation;
  loadingMore.value = true; moreError.value = '';
  try {
    const result = await fetchOrderEvents(props.orderId, { page: (data.value.page || 1) + 1 });
    if (version !== generation) return;
    if (!result?.success || !Array.isArray(result.data?.events)) throw new Error('read-failed');
    const known = new Set(data.value.events.map(event => event.id));
    data.value = { ...result.data, events: [...data.value.events, ...result.data.events.filter(event => !known.has(event.id))] };
  } catch {
    if (version === generation) moreError.value = '更早日志读取失败，请重试。';
  } finally { if (version === generation) loadingMore.value = false; }
}
watch(() => props.orderId, load, { immediate: true });
onBeforeUnmount(() => { generation++; });
</script>

<style scoped>
.order-log{margin-top:20px;padding-top:16px;border-top:1px solid #dce5f0;color:#203653}
header{display:flex;align-items:center;justify-content:space-between;gap:12px}h3{margin:0;font-size:16px}small,header span,.note,li p{font-size:12px;color:#65758b}
ol{list-style:none;padding:0;margin:20px 0}li{display:grid;grid-template-columns:160px minmax(0,1fr);gap:24px;padding-bottom:24px}time{font-size:12px;text-align:right;color:#65758b}
li>div{position:relative;border-left:1px solid #dce5f0;padding-left:20px}li>div::before{content:'';position:absolute;left:-5px;top:4px;width:7px;height:7px;border:1px solid #7194bc;border-radius:50%;background:white}li:first-child>div::before{background:#287858;border-color:#287858}li p{margin:6px 0 0}.empty{padding:20px;background:#f5f7fa;color:#65758b}
button{border:0;background:none;color:#245edb;cursor:pointer;padding:8px}.toggle{margin-left:184px}.note{line-height:1.6}@media(max-width:600px){li{grid-template-columns:110px minmax(0,1fr);gap:12px}.toggle{margin-left:122px}header{flex-wrap:wrap}}
details{margin-top:8px;font-size:12px}summary{cursor:pointer;color:#245edb}.original{overflow-wrap:anywhere;line-height:1.6}time{overflow-wrap:anywhere}li>div{min-width:0}</style>
