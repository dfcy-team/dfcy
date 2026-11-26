<template>
  <section v-if="enabled" class="adjustments" aria-label="历史已售成本调整">
    <h2>历史已售成本调整</h2><label>生效月份 <input v-model="month" type="month" @change="load" /></label>
    <p v-if="error" role="alert">历史调整读取失败：{{ error }}</p>
    <p v-else>按仓库汇总，未分配到店铺；不会改写原订单毛利或库存。</p>
    <table v-if="!error"><thead><tr><th>国家</th><th>仓库</th><th>库存增加/减少</th><th>已售费用增加/减少</th><th>毛利影响</th></tr></thead>
      <tbody><tr v-for="r in rows" :key="r.warehouse_id"><td>{{ r.country }}</td><td>{{ r.warehouse }}</td><td>{{ r.inventory_amount }}</td><td>{{ r.sold_amount }}</td><td>{{ r.gross_profit_impact }}</td></tr><tr v-if="!rows.length"><td colspan="5">本月无已分配调整</td></tr></tbody></table>
  </section>
</template>
<script setup>
import { onMounted, ref } from 'vue'
import { requestApi } from '../../api/request'
const enabled = ref(false), rows = ref([]), error = ref('')
const now = new Date(), month = ref(`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`)
async function load() {
  try {
    error.value = ''
    const response = await requestApi({ method: 'get', url: '/api/finance/monthly-adjustments/', params: { month: month.value }, noMockFallback: true })
    const body = response?.data ?? response
    if (body.success !== true) throw new Error(body.message || '请求失败')
    enabled.value = body.data?.enabled === true
    rows.value = body.data?.rows || []
  } catch (e) { enabled.value = true; error.value = e?.message || '请求失败' }
}
onMounted(load)
</script>
<style scoped>
.adjustments{padding:16px;background:#fff;border:1px solid #dce5f3;border-radius:8px}.adjustments h2{font-size:15px;margin:0 0 8px}.adjustments p{color:#526176}.adjustments table{border-collapse:collapse;width:100%}.adjustments th,.adjustments td{padding:8px;border-bottom:1px solid #dce5f3;text-align:left}
</style>
