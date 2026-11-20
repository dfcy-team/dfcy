<template>
  <section aria-label="百世仓配接入">
    <el-alert :title="statusLabel" :type="state.status === 'verified' ? 'success' : 'info'" :closable="false"
      description="使用百世海外仓 GLINK 签名认证。保存后查询可用仓库并确认绑定，不会自动启用同步。" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-form label-position="top" @submit.prevent="save">
      <el-form-item label="partnerId" required><el-input v-model="form.partner_id" :disabled="busy || !canManage" /></el-form-item>
      <el-form-item label="partnerKey" :required="!state.key_configured">
        <el-input v-model="form.partner_key" type="password" autocomplete="new-password" :disabled="busy || !canManage"
          :placeholder="state.key_configured ? '密钥已托管，留空保留；不回显原值' : '填写百世提供的密钥'" />
      </el-form-item>
      <el-form-item label="客户编码 customerCode" required><el-input v-model="form.customer_code" :disabled="busy || !canManage" /></el-form-item>
      <el-button v-if="canManage" native-type="submit" type="primary" :loading="busy" :disabled="busy || !ready">保存接入配置</el-button>
    </el-form>
    <p v-if="!state.execution_enabled">真实调用暂未开启，可先保存配置。不会拉取订单、库存或下发仓库单据。</p>
    <template v-if="state.authorization_id">
      <el-form label-position="top" @submit.prevent="check">
        <el-form-item v-if="state.selection_required" label="选择百世仓库" required>
          <select v-model="selectedWarehouse" :disabled="busy || !canCheck"><option value="">请选择</option><option v-for="item in state.warehouses" :key="item.code" :value="item.code">{{ item.name }}（{{ item.code }}）</option></select>
        </el-form-item>
        <template v-if="state.country_confirmation_required && chosenWarehouse">
          <p>本地国家：{{ state.local_country }}；百世国家：{{ chosenWarehouse.country || '未提供' }}；百世时区：{{ chosenWarehouse.time_zone || '未提供' }}。请核实仓库编码及实际所在地。</p>
          <label><input v-model="confirmCountry" type="checkbox" :disabled="busy || !canManage" />我确认这是实际使用的仓库，接受国家资料差异并绑定</label>
        </template>
        <el-button native-type="submit" :loading="busy" :disabled="busy || !canCheck || !canManage || !state.execution_enabled || (state.selection_required && !selectedWarehouse)">{{ state.selection_required ? '确认仓库绑定' : '查询并验证仓库' }}</el-button>
      </el-form>
      <p>仅查询当前客户可用仓库；不创建订单或导入库存。</p>
      <BestWarehouseOperations v-if="state.status === 'verified'" :key="state.authorization_id"
        :authorization-id="state.authorization_id" :customer-code="state.customer_code" :warehouse-code="state.warehouse_code"
        :can-read="canCheck" :can-manage="canManage" />
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { requestApi } from '../api/request';
import BestWarehouseOperations from './BestWarehouseOperations.vue';
const props = defineProps({ warehouseId: { type: Number, required: true }, canManage: Boolean, canCheck: Boolean });
const emit = defineEmits(['changed']);
const state = ref({}), error = ref(''), busy = ref(false), selectedWarehouse = ref('');
const form = reactive({ partner_id: '', partner_key: '', customer_code: '' });
const confirmCountry = ref(false);
const chosenWarehouse = computed(() => state.value.warehouses?.find(item => item.code === selectedWarehouse.value));
watch(selectedWarehouse, () => { confirmCountry.value = false; });
let generation = 0;
const statusLabel = computed(() => ({ verified: '百世连接已验证', failed: '百世接入异常，请核对', pending: '百世已配置 · 待验证', legacy: '旧仓配配置，请重新保存并验证海外仓授权' }[state.value.status] || '百世尚未配置'));
const ready = computed(() => ['partner_id', 'customer_code'].every(key => form[key].trim()) && (state.value.key_configured || form.partner_key.trim()));
function saveError(response) {
  const labels = { partner_id: 'partnerId', partner_key: 'partnerKey', customer_code: '客户编码', version: '配置版本', idempotency_key: '请求标识', gateway: '后台网关', warehouse_code: '仓库编码', non_field_errors: '', detail: '' };
  const messages = [];
  const append = (label, value) => {
    for (const message of Array.isArray(value) ? value : [value]) {
      if (typeof message === 'string') messages.push(label ? `${label}：${message}` : message);
    }
  };
  if (Array.isArray(response?.data)) append('', response.data);
  else if (response?.data && typeof response.data === 'object') {
    for (const [key, label] of Object.entries(labels)) append(label, response.data[key]);
  }
  const message = messages.join('；') || response?.message || '百世接入配置请求失败';
  return form.partner_key ? message.split(form.partner_key).join('***') : message;
}
async function request(method, data, suffix = '') {
  const current = ++generation; busy.value = true; error.value = '';
  try {
    const response = await requestApi({ method, url: `/api/internal/integrations/warehouses/${props.warehouseId}/best-access/${suffix}`, ...(data ? { data } : {}), noMockFallback: true });
    if (!response?.success) throw new Error(saveError(response));
    if (current !== generation) return;
    state.value = response.data;
    confirmCountry.value = false;
    for (const key of Object.keys(form)) form[key] = key === 'partner_key' ? '' : response.data[key] || '';
    if (method === 'post') emit('changed');
  } catch (e) { if (current === generation) error.value = e.message || '百世接入配置请求失败'; }
  finally { if (current === generation) { busy.value = false; form.partner_key = ''; } }
}
function save() {
  if (!busy.value && props.canManage && ready.value) request('post', { ...form, version: state.value.version || 0, idempotency_key: crypto.randomUUID() });
}
function check() {
  if (state.value.country_confirmation_required && !confirmCountry.value) return;
  if (!busy.value && props.canCheck && props.canManage && state.value.execution_enabled && (!state.value.selection_required || selectedWarehouse.value)) request('post', { warehouse_code: selectedWarehouse.value,
    ...(state.value.country_confirmation_required ? { confirm_country_mismatch: confirmCountry.value, version: state.value.version, confirmed_country: chosenWarehouse.value?.country } : {}) }, 'check/');
}
watch(() => props.warehouseId, () => { state.value = {}; selectedWarehouse.value = ''; for (const key of Object.keys(form)) form[key] = ''; request('get'); }, { immediate: true });
onBeforeUnmount(() => { generation++; form.partner_key = ''; });
</script>

<style scoped>
.el-form { margin-top: 16px; }
p { line-height: 1.6; color: var(--el-text-color-secondary); }
</style>
