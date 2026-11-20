<template>
  <section aria-label="百世仓库接口">
    <h3>百世仓库接口</h3>
    <p>查询结果用于核对。写入须具备权限、开启写入能力并人工确认；接口执行不会自动生成本地财务记录。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <label>选择接口
      <select v-model="operationName" :disabled="busy">
        <option value="">请选择</option>
        <option v-for="item in operations" :key="item.name" :value="item.name">{{ item.module }} · {{ item.label }}{{ item.write ? '（写入）' : '（只读）' }}</option>
      </select>
    </label>
    <template v-if="selected">
      <p><a :href="selected.source" target="_blank" rel="noopener noreferrer">接口文档</a> · {{ selected.name }}</p>
      <p>必填：{{ requiredFields }}</p>
      <el-input v-model="businessJson" type="textarea" :rows="10" :disabled="busy" aria-label="百世业务参数 JSON" />
      <label v-if="selected.write"><input v-model="confirmed" type="checkbox" :disabled="busy || !canManage || !writeEnabled" />我已核对单据，确认向百世执行本次写入</label>
      <p v-if="selected.write && !writeEnabled">服务器写入能力关闭，当前仅可预览参数。</p>
      <el-button :disabled="busy" @click="preview">检查参数</el-button>
      <el-button :disabled="busy || !executionEnabled || !canRead || (selected.write && (!writeEnabled || !canManage || !confirmed))" :loading="busy" @click="execute">{{ selected.write ? '确认执行写入' : '执行只读查询' }}</el-button>
      <pre v-if="result" class="operation-result">{{ result }}</pre>
    </template>
    <h4>平台反馈</h4>
    <p>{{ callbacksEnabled ? '回调接收能力已开启' : '回调接收能力未开启' }}；已验签反馈先保存待核对，不自动改写库存或财务。</p>
    <ul><li v-for="item in callbacks" :key="item.name">{{ item.label }} · {{ item.name }}</li></ul>
    <el-button :disabled="busy" @click="loadNotifications">刷新已接收反馈</el-button>
    <ul><li v-for="item in notifications" :key="item.id">{{ item.label }} · {{ item.received_at }} · {{ item.status }} <el-button link @click="notificationDetail(item.id)">查看</el-button></li></ul>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { requestApi } from '../api/request';
const props = defineProps({ authorizationId: { type: Number, required: true }, customerCode: String, warehouseCode: String, canRead: Boolean, canManage: Boolean });
const operations = ref([]), callbacks = ref([]), notifications = ref([]), operationName = ref(''), businessJson = ref(''), result = ref(''), error = ref(''), busy = ref(false), confirmed = ref(false), writeEnabled = ref(false), executionEnabled = ref(false), callbacksEnabled = ref(false);
const selected = computed(() => operations.value.find(item => item.name === operationName.value));
const requiredFields = computed(() => selected.value?.fields.filter(item => item.required && !item.name.startsWith('└') && item.name !== 'partnerId').map(item => item.name).join('、') || '见文档条件字段');
let generation = 0, requestKey = '';
function scopedTemplate(value) {
  if (Array.isArray(value)) return value.map(scopedTemplate);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key,
    ['customerCode', 'ownerCode'].includes(key) ? props.customerCode : ['warehouseCode', 'whCode'].includes(key) ? props.warehouseCode : scopedTemplate(item)]));
  return value;
}
watch(selected, item => {
  confirmed.value = false; result.value = ''; requestKey = '';
  businessJson.value = item ? JSON.stringify({ ...scopedTemplate(item.template), customerCode: props.customerCode, warehouseCode: props.warehouseCode }, null, 2) : '';
});
async function call(method, url, data) {
  const response = await requestApi({ method, url: `/api/internal/integrations/${url}`, ...(data ? { data } : {}), noMockFallback: true });
  if (!response?.success) throw new Error(response?.message || '百世接口请求失败');
  return response.data;
}
async function action(work) {
  if (busy.value) return;
  const current = ++generation; busy.value = true; error.value = '';
  try { const data = await work(); if (current === generation) result.value = JSON.stringify(data, null, 2); }
  catch (reason) { if (current === generation) error.value = reason.message || '请求失败'; }
  finally { if (current === generation) busy.value = false; }
}
function payload() {
  const value = JSON.parse(businessJson.value);
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('业务参数须为 JSON 对象');
  return { provider: 'best_ecapi', operation: selected.value.name, payload: { bizData: JSON.stringify(value) } };
}
function preview() { if (selected.value) action(() => call('post', 'warehouse-api/preview/', payload())); }
function execute() {
  if (!selected.value || !executionEnabled.value || !props.canRead || (selected.value.write && (!writeEnabled.value || !props.canManage || !confirmed.value))) return;
  action(() => {
    const data = payload();
    requestKey ||= crypto.randomUUID();
    return call('post', `warehouse-authorizations/${props.authorizationId}/operations/`, { ...data, confirmed: confirmed.value, idempotency_key: requestKey });
  });
}
function loadNotifications() { action(async () => { const data = await call('get', `warehouse-authorizations/${props.authorizationId}/best-notifications/`); notifications.value = data.results || []; return data; }); }
function notificationDetail(id) { action(() => call('get', `warehouse-authorizations/${props.authorizationId}/best-notifications/?event_id=${id}`)); }
onMounted(async () => {
  try {
    const data = await call('get', 'warehouse-api/operations/?provider=best_ecapi');
    if (generation < 0) return;
    operations.value = data.operations || []; callbacks.value = data.callbacks || [];
    writeEnabled.value = Boolean(data.write_enabled); executionEnabled.value = Boolean(data.execution_enabled); callbacksEnabled.value = Boolean(data.callbacks_enabled);
  } catch (reason) { if (generation >= 0) error.value = reason.message; }
});
onBeforeUnmount(() => { generation = -1; });
</script>

<style scoped>
section { margin-top: 20px; border-top: 1px solid var(--el-border-color); padding-top: 12px; }
select { max-width: 100%; min-height: 32px; }
label { display: block; margin: 10px 0; }
.operation-result { max-height: 360px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
