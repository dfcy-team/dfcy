<template>
  <section class="notify-card" aria-label="供应商通知绑定">
    <header><div><h3>供应商订单通知</h3><p>{{ supplierName || `供应商 ${supplierId}` }} · 登记订单通知的发送通道和目标群</p></div><el-button :loading="loading" @click="load">刷新</el-button></header>
    <p class="notice">当前通道采用人工核验群名或群备注，无法自动拉取群成员。保存绑定不会发送消息。</p>
    <el-alert v-if="auth.authorizationStale" type="warning" :closable="false" title="权限信息已过期，当前禁止保存；请刷新登录信息后重试。" />
    <el-skeleton v-if="loading && !loaded" :rows="3" animated />
    <el-form v-else label-position="top" class="binding-grid">
      <el-form-item label="发送账号 / 通道"><el-select v-model="form.channel_id" :disabled="!canNotify || busy || loading || !loaded" placeholder="请选择已配置通道"><el-option v-for="c in channels" :key="c.id" :value="c.id" :label="`${c.sender_name} · ${c.name}`" /></el-select></el-form-item>
      <el-form-item label="群名（人工登记）"><el-input v-model="form.group_name" :disabled="!canNotify || busy || loading || !loaded" maxlength="160" /></el-form-item>
      <el-form-item label="群备注（人工登记）"><el-input v-model="form.group_note" :disabled="!canNotify || busy || loading || !loaded" maxlength="500" /></el-form-item>
      <el-form-item label="用于查找的完整群名 / 唯一群备注"><el-input v-model="form.target_title" :disabled="!canNotify || busy || loading || !loaded" maxlength="60" /><small>与企微客户端完整显示的名称一致，避免空格、减号、括号、@ 和数字开头。</small></el-form-item>
      <el-form-item label="群成员数"><el-input-number v-model="form.member_count" :disabled="!canNotify || busy || loading || !loaded" :min="0" :max="100000" /></el-form-item>
      <el-form-item label="证据"><el-input v-model="form.evidence" :disabled="!canNotify || busy || loading || !loaded" type="textarea" maxlength="1000" placeholder="记录人工核验方式和时间" /></el-form-item>
      <el-checkbox v-model="form.contains_external_member" :disabled="!canNotify || busy || loading || !loaded">已确认群内有供应商外部成员</el-checkbox>
      <el-checkbox v-model="form.sender_member_confirmed" :disabled="!canNotify || busy || loading || !loaded">已确认发送账号是群成员</el-checkbox>
      <el-checkbox v-model="form.unique_target_confirmed" :disabled="!canNotify || busy || loading || !loaded">已确认目标群唯一</el-checkbox>
      <el-form-item label="启用此供应商通知绑定"><el-switch v-model="form.enabled" :disabled="!canNotify || busy || loading || !loaded" /></el-form-item>
    </el-form>
    <div v-if="binding?.verified" class="verify-state"><el-tag type="success">已核验</el-tag><span>{{ binding.group_name }} · {{ binding.member_count }} 人 · {{ binding.channel_name }}</span></div>
    <p v-if="error" class="error">{{ error }}</p><el-button type="primary" :disabled="!canNotify || busy || !valid" :loading="busy" @click="save">保存绑定</el-button>
    <p class="footnote">停用绑定可暂停后续投递；保存不会立即发送通知。启用时须完成三项核验并填写依据。</p>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useAuthStore } from '../../stores/auth';
import { fetchNotificationChannels, fetchSupplierNotificationBinding, saveSupplierNotificationBinding } from '../../api/supplyNotificationsV2';

const props = defineProps({ supplierId: { type: [String, Number], required: true }, supplierName: { type: String, default: '' } });
const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission('supply.v2.manage'));
const canNotify = computed(() => canManage.value && auth.hasPermission('supply.v2.notify') && !auth.authorizationStale);
const channels = ref([]); const binding = ref(null); const loading = ref(false); const loaded = ref(false); const busy = ref(false); const error = ref('');
const empty = () => ({ channel_id: '', group_name: '', group_note: '', target_title: '', member_count: null, contains_external_member: false, sender_member_confirmed: false, unique_target_confirmed: false, evidence: '', enabled: false });
const form = reactive(empty());
const valid = computed(() => Boolean(loaded.value && !loading.value && form.channel_id && form.group_name.trim() && form.target_title.trim() && (form.member_count == null || form.member_count >= 2) && (!form.enabled || (form.contains_external_member && form.sender_member_confirmed && form.unique_target_confirmed && form.evidence.trim()))));
async function load() {
  loading.value = true; error.value = '';
  try {
    const [channelResponse, bindingResponse] = await Promise.all([fetchNotificationChannels(), fetchSupplierNotificationBinding(props.supplierId)]);
    if (!channelResponse?.success || !bindingResponse?.success) throw new Error(channelResponse?.message || bindingResponse?.message || '读取通知配置失败');
    channels.value = channelResponse.data || []; binding.value = bindingResponse.data || null;
    Object.assign(form, empty(), binding.value ? { channel_id: binding.value.channel_id, group_name: binding.value.group_name || '', group_note: binding.value.group_note || '', target_title: binding.value.target_title || '', member_count: binding.value.member_count ?? null, enabled: !!binding.value.enabled, contains_external_member: !!binding.value.contains_external_member, sender_member_confirmed: !!binding.value.sender_member_confirmed, unique_target_confirmed: !!binding.value.unique_target_confirmed, evidence: binding.value.evidence || '' } : {});
    loaded.value = true;
  } catch (e) { error.value = e?.message || '读取通知配置失败'; }
  finally { loading.value = false; }
}
async function save() {
  if (!canNotify.value || !valid.value || busy.value) return;
  busy.value = true; error.value = '';
  const payload = { expected_version: binding.value?.version ?? 0, channel_id: form.channel_id, group_name: form.group_name.trim(), group_note: form.group_note.trim(), target_title: form.target_title.trim(), member_count: form.member_count, contains_external_member: form.contains_external_member, sender_member_confirmed: form.sender_member_confirmed, unique_target_confirmed: form.unique_target_confirmed, evidence: form.evidence.trim(), enabled: form.enabled };
  try { const response = await saveSupplierNotificationBinding(props.supplierId, payload); if (!response?.success) throw new Error(response?.message || '保存失败'); await load(); }
  catch (e) { error.value = e?.message || '保存失败；若网络结果未知，请先刷新确认状态。'; }
  finally { busy.value = false; }
}
watch(() => props.supplierId, load); onMounted(load);
</script>

<style scoped>
.notify-card{border:1px solid #dce3ed;border-radius:12px;padding:18px;background:#fff}.notify-card header{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.notify-card h3{margin:0 0 5px}.notify-card p{color:#657184;margin:5px 0 12px}.notice{padding:10px;background:#f3f7fb;border-radius:8px}.binding-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px}.binding-grid :deep(.el-select){width:100%}.verify-state{display:flex;align-items:center;gap:10px;margin:12px 0}.footnote{font-size:12px}.error{color:#c0392b}@media(max-width:600px){.binding-grid{grid-template-columns:minmax(0,1fr)}.notify-card{padding:14px}}
</style>
