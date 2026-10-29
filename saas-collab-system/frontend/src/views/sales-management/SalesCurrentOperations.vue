<template>
  <section class="current-sales" :aria-busy="loading">
    <header><div><h1>今日累计 · 店铺排行榜</h1><p>各店铺当地零点至本次取数时刻。打开或刷新会读取最新已入库数据，可能与飞书图片不同。</p></div><button :disabled="loading" @click="load">{{ loading ? '读取中…' : '刷新数据' }}</button></header>
    <p><router-link to="/sales-management/overview?view=operations">查看已结束日期</router-link></p>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="data">
      <p>取数时间：{{ capturedAt }}（北京）</p>
      <p class="notice">今日没有历史同点比较基准，不显示涨跌幅；ROI 按已入库销售和广告费暂估。</p>
      <div class="totals"><article v-for="group in data.currency_groups" :key="group.currency"><span>{{ group.currency }} · 完整查询范围</span><strong>{{ amount(group.sales_amount) }}</strong><span>ROI {{ roi(group) }}</span></article></div>
      <p v-for="(notice, index) in data.notices || []" :key="index">{{ notice }}</p>
      <div class="scroll"><table><thead><tr><th>店铺 / 国家</th><th>GMV / 币种</th><th>订单量（单）</th><th>销量（件）</th><th>广告费 / 币种</th><th>ROI（倍，暂估）</th></tr></thead><tbody><tr v-for="row in data.rows" :key="`${row.store_id}-${row.currency}`"><td>{{ row.store_name }}<small>{{ row.country }} · {{ row.business_date || '' }}</small></td><td>{{ amount(row.sales_amount) }} {{ row.currency }}</td><td>{{ row.order_count }}</td><td>{{ row.units_sold ?? '未取得' }}</td><td>{{ row.ad_spend == null ? '未取得' : amount(row.ad_spend) }} {{ row.currency }}</td><td>{{ roi(row) }}</td></tr></tbody></table></div>
      <p v-if="!data.rows?.length">当前授权范围暂无今日已入库销售记录，不表示销量为零。</p>
      <footer><button :disabled="loading || page === 1" @click="changePage(-1)">上一页</button><span>第 {{ page }} 页</span><button :disabled="loading || !data.has_next" @click="changePage(1)">下一页</button></footer>
    </template>
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { fetchSalesOperations } from '../../api/salesOperations';
import { amount } from './salesOperations';
const route = useRoute(), data = ref<any>(null), error = ref(''), loading = ref(false), page = ref(1);
let controller: AbortController | null = null, generation = 0;
const capturedAt = computed(() => data.value?.generated_at ? new Date(data.value.generated_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '未取得');
const roi = (row: any) => row.roi == null ? (row.ad_reason || '广告数据未齐，暂不可算') : amount(row.roi);
async function load() {
  const id = ++generation; controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''; data.value = null;
  try {
    const params: Record<string, any> = { period: 'current', view: 'stores', page: page.value, page_size: 20 };
    for (const [key, value] of Object.entries(route.query)) {
      if (['view', 'period'].includes(key)) continue;
      if (!['platform', 'store_id', 'region', 'currency'].includes(key) || typeof value !== 'string') throw new Error('今日累计链接参数无效，请重新打开报表链接。');
      params[key] = value;
    }
    const response = await fetchSalesOperations(params, controller.signal);
    if (id !== generation) return;
    if (!response?.success) throw new Error(response?.message || '今日累计数据暂不可用。');
    data.value = response.data;
  } catch (failure: any) { if (id === generation) error.value = failure?.message || '今日累计数据暂不可用。'; }
  finally { if (id === generation) loading.value = false; }
}
function changePage(step: number) { page.value += step; load(); }
watch(() => route.query, () => { page.value = 1; load(); }, { immediate: true });
onBeforeUnmount(() => { generation++; controller?.abort(); });
</script>
<style scoped>
.current-sales{padding:24px;color:#243247}.current-sales header{display:flex;justify-content:space-between;align-items:center;gap:20px}.current-sales h1{font-size:24px}.current-sales p{line-height:1.7;color:#64748b}.current-sales button{padding:8px 16px;border:1px solid #cad5e3;background:white;border-radius:6px;cursor:pointer}.notice{background:#fff8e8;padding:12px}.totals{display:flex;gap:16px;flex-wrap:wrap}.totals article{display:grid;gap:12px;border:1px solid #dae4ef;border-radius:10px;padding:20px;min-width:210px}.totals strong{font-size:28px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap}th,td{padding:14px;border-bottom:1px solid #e2e8f0;text-align:right}th:first-child,td:first-child{text-align:left}small{display:block;color:#718096;margin-top:6px}footer{display:flex;justify-content:flex-end;gap:16px;margin-top:18px}@media(max-width:700px){.current-sales{padding:12px}.current-sales header{align-items:flex-start}.current-sales h1{font-size:20px}.totals article{flex:1}}
</style>
