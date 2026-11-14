<template>
  <section aria-label="百世仓配接入">
    <el-alert :title="statusLabel" :type="state.status === 'verified' ? 'success' : 'info'" :closable="false"
      description="使用百世仓配 API（2.0）签名认证，无需极风 Email 或一次性 Token。保存配置不会启用同步。" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-form label-position="top" @submit.prevent="save">
      <el-form-item label="partnerID" required><el-input v-model="form.partner_id" :disabled="busy || !canManage" /></el-form-item>
      <el-form-item label="partnerKey" :required="!state.key_configured">
        <el-input v-model="form.partner_key" type="password" autocomplete="new-password" :disabled="busy || !canManage"
          :placeholder="state.key_configured ? '密钥已托管，留空保留；不回显原值' : '填写百世提供的密钥'" />
      </el-form-item>
      <el-form-item label="客户编码 customerCode" required><el-input v-model="form.customer_code" :disabled="busy || !canManage" /></el-form-item>
      <el-form-item label="百世仓库编码 warehouseCode" required><el-input v-model="form.warehouse_code" :disabled="busy || !canManage" /></el-form-item>
      <el-form-item label="HTTPS 网关地址" required><el-input v-model="form.gateway" :disabled="busy || !canManage" placeholder="填写百世提供的地址，以 /ecapi/api/process 结尾" /></el-form-item>
      <el-button v-if="canManage" native-type="submit" type="primary" :loading="busy" :disabled="busy || !ready">保存接入配置</el-button>
    </el-form>
    <p v-if="!state.execution_enabled">真实调用暂未开启，可先保存配置。不会拉取订单、库存或下发仓库单据。</p>
    <template v-if="state.authorization_id">
      <el-form label-position="top" @submit.prevent="check">
        <el-form-item label="只读校验 SKU"><el-input v-model="sku" :disabled="busy || !state.execution_enabled" placeholder="填写此仓库实际存在的SKU，不导入库存" /></el-form-item>
        <el-button native-type="submit" :loading="busy" :disabled="busy || !canCheck || !state.execution_enabled || !sku.trim()">检查连接</el-button>
      </el-form>
      <p>库存接口按指定 SKU 分批查询，每批最多 50 个；空 SKU 范围不会被当作全仓库存。</p>
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { requestApi } from '../api/request';
const props = defineProps({ warehouseId: { type: Number, required: true }, canManage: Boolean, canCheck: Boolean });
const emit = defineEmits(['changed']);
const state = ref({}), error = ref(''), busy = ref(false), sku = ref('');
const form = reactive({ partner_id: '', partner_key: '', customer_code: '', warehouse_code: '', gateway: '' });
let generation = 0;
const statusLabel = computed(() => ({ verified: '百世连接已验证', failed: '百世接入异常，请核对', pending: '百世已配置 · 待验证' }[state.value.status] || '百世尚未配置'));
const ready = computed(() => ['partner_id', 'customer_code', 'warehouse_code', 'gateway'].every(key => form[key].trim()) && (state.value.key_configured || form.partner_key.trim()));
async function request(method, data, suffix = '') {
  const current = ++generation; busy.value = true; error.value = '';
  try {
    const response = await requestApi({ method, url: `/api/internal/integrations/warehouses/${props.warehouseId}/best-access/${suffix}`, ...(data ? { data } : {}), noMockFallback: true });
    if (!response?.success) throw new Error(response?.message || '百世接入配置请求失败');
    if (current !== generation) return;
    state.value = response.data;
    for (const key of Object.keys(form)) form[key] = key === 'partner_key' ? '' : response.data[key] || '';
    if (method === 'post') emit('changed');
  } catch (e) { if (current === generation) error.value = e.message || '百世接入配置请求失败'; }
  finally { if (current === generation) { busy.value = false; form.partner_key = ''; } }
}
function save() {
  if (!busy.value && props.canManage && ready.value) request('post', { ...form, version: state.value.version || 0, idempotency_key: crypto.randomUUID() });
}
function check() {
  if (!busy.value && props.canCheck && state.value.execution_enabled && sku.value.trim()) request('post', { sku_code: sku.value.trim() }, 'check/');
}
watch(() => props.warehouseId, () => { state.value = {}; for (const key of Object.keys(form)) form[key] = ''; request('get'); }, { immediate: true });
onBeforeUnmount(() => { generation++; form.partner_key = ''; });
</script>

<style scoped>
.el-form { margin-top: 16px; }
p { line-height: 1.6; color: var(--el-text-color-secondary); }
</style>
