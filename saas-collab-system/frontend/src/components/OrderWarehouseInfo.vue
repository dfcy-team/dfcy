<template>
  <section v-if="auth.hasPermission('sales_management.orders.view')" class="warehouse-info" aria-label="订单仓库信息">
    <div class="warehouse-heading">
      <h3>仓库信息</h3>
      <div class="warehouse-actions">
        <el-button :loading="loading" @click="load">刷新查询状态</el-button>
        <el-button v-if="data.can_retry" :disabled="waiting || loading" :loading="submitting" @click="retry">{{ data.snapshot?.packages?.length ? '重新查询仓库' : '查询／重试' }}</el-button>
      </div>
    </div>
    <p v-if="error" role="alert" class="warehouse-error">{{ error }}</p>
    <p v-else role="status">{{ loading && !data.status ? '正在读取查询状态…' : data.status_label }}<span v-if="data.message"> · {{ data.message }}</span></p>
    <p v-if="data.stale" class="warehouse-warning">以下为上次成功查询的快照，本次查询尚未确认，不能作为当前仓库状态。</p>
    <dl v-if="data.snapshot?.warehouse_code" class="warehouse-summary">
      <div><dt>关联仓库</dt><dd>{{ data.snapshot.warehouse_name }}（{{ data.snapshot.warehouse_code }}）</dd></div>
      <div><dt>快照时间（北京时间）</dt><dd>{{ displayTime(data.snapshot_at) }}</dd></div>
      <div><dt>最近查询（北京时间）</dt><dd>{{ displayTime(data.checked_at) }}</dd></div>
    </dl>
    <p v-if="data.next_query_at" class="warehouse-note">下次自动检查：{{ displayTime(data.next_query_at) }}</p><p class="warehouse-note">订单履约状态、付款或包裹单号变化后后台查询；未查到时有限复查，发货信息完整后停止轮询。仅唯一匹配时关联仓库；“未提供”表示接口未返回该字段，不代表未发货。</p>
    <div v-if="data.snapshot?.packages?.length" class="warehouse-table" tabindex="0" aria-label="仓库包裹明细，可横向滚动">
      <table>
        <thead><tr><th>仓库订单号／ERP 单号</th><th>预约单号／包裹号</th><th>运单号／承运商</th><th>仓库状态</th><th>发货时间（北京时间）</th><th>揽收时间（北京时间）</th><th>商品与数量</th></tr></thead>
        <tbody><tr v-for="(item, index) in data.snapshot.packages" :key="item.erp_no || item.warehouse_order_no || index">
          <td>{{ item.warehouse_order_no || '未提供' }}<br />{{ item.erp_no || '未提供' }}</td>
          <td>{{ item.booking_no || '未提供' }}<br />{{ item.package_no || '未提供' }}</td>
          <td>{{ item.tracking_no || '未提供' }}<br />{{ item.carrier || '未提供' }}</td>
          <td>{{ item.status_label || '未提供' }}<span v-if="item.status != null">（{{ item.status }}）</span></td>
          <td>{{ displayTime(item.shipped_at_utc) }}</td><td>{{ displayTime(item.pickup_at_utc) }}</td>
          <td><template v-if="item.items?.length"><div v-for="(sku, skuIndex) in item.items" :key="skuIndex">{{ sku.sku || sku.warehouse_sku || '未提供 SKU' }} × {{ sku.quantity ?? '未提供数量' }}</div></template><span v-else>未提供</span></td>
        </tr></tbody>
      </table>
    </div>
    <details v-if="data.checks?.length"><summary>各仓库查询结果（{{ data.checks.length }}）</summary>
      <ul><li v-for="check in data.checks" :key="check.authorization_id || check.warehouse_id">{{ check.warehouse }}：{{ checkLabels[check.status] || check.status }}<span v-if="check.message"> · {{ check.message }}</span></li></ul>
    </details>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useAuthStore } from '../stores/auth';
import { fetchOrderWarehouse, retryOrderWarehouse } from '../api/salesManagement';

const props = defineProps({ orderId: { type: [Number, String], required: true } });
const emit = defineEmits(['updated']);
const auth = useAuthStore();
const data = ref({}), error = ref(''), loading = ref(false), submitting = ref(false);
const waiting = computed(() => ['pending', 'running'].includes(data.value.status));
const checkLabels = { matched: '查到订单', not_found: '未查到', blocked: '条件未就绪', failed: '查询失败' };
let timer, generation = 0, requestVersion = 0;
const displayTime = value => {
  if (!value) return '未提供';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '时间格式异常' : new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'
  }).format(date);
};
async function load() {
  clearTimeout(timer);
  if (!props.orderId || !auth.hasPermission('sales_management.orders.view')) return;
  const version = ++requestVersion, current = generation;
  loading.value = true;
  try {
    const result = await fetchOrderWarehouse(props.orderId);
    if (current !== generation || version !== requestVersion) return;
    if (!result?.success) throw new Error('read-failed');
    data.value = result.data; error.value = '';
    emit('updated', { orderId: props.orderId, summary: result.data });
    if (waiting.value) timer = setTimeout(load, 5000);
  } catch {
    if (current === generation && version === requestVersion) error.value = '仓库查询状态读取失败，请刷新重试。';
  } finally {
    if (current === generation && version === requestVersion) loading.value = false;
  }
}
async function retry() {
  if (submitting.value || waiting.value) return;
  const current = generation;
  submitting.value = true;
  try {
    const result = await retryOrderWarehouse(props.orderId);
    if (current !== generation) return;
    if (!result?.success) throw new Error('submit-failed');
    await load();
  } catch {
    if (current === generation) error.value = '未能提交仓库查询，请检查权限或稍后重试。';
  } finally {
    if (current === generation) submitting.value = false;
  }
}
watch(() => props.orderId, () => {
  generation += 1; clearTimeout(timer); data.value = {}; error.value = ''; submitting.value = false;
  load();
}, { immediate: true });
onBeforeUnmount(() => { generation += 1; clearTimeout(timer); });
</script>

<style scoped>
.warehouse-info { margin: 20px 0; border-top: 1px solid var(--el-border-color); padding-top: 12px; }
.warehouse-heading, .warehouse-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.warehouse-heading { justify-content: space-between; }
.warehouse-heading h3 { margin: 8px 0; }
.warehouse-summary { display: flex; gap: 16px; flex-wrap: wrap; }
.warehouse-summary dt, .warehouse-note { color: var(--el-text-color-regular); }
.warehouse-summary dd { margin: 4px 0; }
.warehouse-error { color: var(--el-color-danger); }
.warehouse-warning { color: var(--el-text-color-primary); font-weight: 600; }
.warehouse-table { max-width: 100%; overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 8px; border-bottom: 1px solid var(--el-border-color); min-width: 120px; vertical-align: top; overflow-wrap: anywhere; }
th { background: var(--el-fill-color-light); }
details { margin-top: 12px; } summary { cursor: pointer; }
</style>
