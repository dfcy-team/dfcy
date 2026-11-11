<template>
  <section>
    <div class="heading"><h2>入库通知</h2><el-button :disabled="loading || saving" @click="load">刷新</el-button></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert type="info" :closable="false" title="入库确认后系统自动通知配置的飞书群；失败后由系统自动重试。此页面仅配置并预览，不会发送测试消息。" />
    <el-form label-position="top" class="form">
      <el-form-item label="飞书群"><el-input v-model="form.chat_name" placeholder="群名称" :disabled="!canEdit || saving" /></el-form-item>
      <el-form-item label="群标识（chat_id）"><el-input v-model="form.chat_id" placeholder="粘贴飞书群 chat_id" :disabled="!canEdit || saving" /><small>由飞书应用获取，群名称不能替代此标识；无需输入任何密钥。</small></el-form-item>
      <el-form-item label="通知国家" class="full"><el-checkbox v-model="form.all_countries" :disabled="!canEdit || saving">全部国家</el-checkbox><el-select v-model="form.country_codes" multiple filterable collapse-tags collapse-tags-tooltip placeholder="选择一个或多个国家" :disabled="!canEdit || saving || form.all_countries"><el-option v-for="c in countries" :key="c.code" :value="c.code" :label="`${c.name} (${c.code})`" /></el-select></el-form-item>
      <el-form-item label="自动通知" class="full"><el-switch v-model="form.enabled" :disabled="!canEdit || saving" aria-label="启用入库自动通知" /><span class="note">仅在入库单确认后触发</span></el-form-item>
    </el-form>
    <section class="preview"><h3>本地预览</h3><p>入库单：IN-示例 · 国家：{{ selectedCountryNames || '未选择' }}</p><p>通知群：{{ form.chat_name || '未填写群名称' }} <code>{{ form.chat_id || 'chat_id待填写' }}</code></p><p>触发方式：{{ form.enabled ? '确认入库后自动通知' : '未启用' }}</p><small>以上为本地字段预览，不代表真实群、发送结果或服务端验证。</small></section>
    <el-button v-if="canEdit" type="primary" :loading="saving" :disabled="!valid" @click="save">保存设置</el-button><small v-if="!error" class="saved-note">保存配置不代表已验证送达。</small>
    <p v-else class="note">当前为只读。修改设置需要供应链维护权限。</p>
  </section>
</template>
<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { useAuthStore } from '../../stores/auth';
import { fetchInboundNotificationConfig, saveInboundNotificationConfig } from '../../api/supplySettingsV2';
const props = defineProps({ countries: { type: Array, default: () => [] } });
const auth = useAuthStore();
const form = reactive({ id: null, chat_id: '', chat_name: '', country_codes: [], all_countries: false, enabled: false, version: 0 });
const serverCanManage = ref(false), canEdit = computed(() => serverCanManage.value && auth.hasPermission('supply.v2.manage') && auth.hasPermission('feishu.notification.manage') && !auth.authorizationStale);
const loading = ref(false), saving = ref(false), error = ref(''); let generation = 0;
const valid = computed(() => canEdit.value && !!form.chat_id.trim() && !!form.chat_name.trim() && (form.all_countries || form.country_codes.length > 0) && !saving.value);
const selectedCountryNames = computed(() => form.all_countries ? '全部国家' : props.countries.filter(c => form.country_codes.includes(c.code)).map(c => c.name).join('、'));
async function load() { const token = ++generation; loading.value = true; error.value = ''; try { const r = await fetchInboundNotificationConfig(); if (token !== generation) return; if (!r?.success) throw new Error(r?.message || '入库通知设置读取失败'); serverCanManage.value=!!r.data?.can_manage; Object.assign(form, { id:r.data?.id ?? null, chat_id:r.data?.chat_id || '', chat_name:r.data?.chat_name || '', country_codes:r.data?.country_codes || [], all_countries:!!r.data?.all_countries, enabled:!!r.data?.enabled, version:r.data?.version || 0 }); } catch(e) { if(token===generation) { error.value=e.message || '入库通知设置读取失败'; serverCanManage.value=false; } } finally { if(token===generation) loading.value=false; } }
async function save() { if(!valid.value) return; const token=generation; saving.value=true; error.value=''; try { const r=await saveInboundNotificationConfig({ chat_id:form.chat_id.trim(), chat_name:form.chat_name.trim(), country_codes:[...form.country_codes], all_countries:form.all_countries, enabled:form.enabled, expected_version:form.version }); if(token!==generation)return; if(!r?.success) throw new Error(r?.message || '入库通知设置保存失败'); Object.assign(form, r.data); } catch(e) { if(token===generation)error.value=e.message || '入库通知设置保存失败'; } finally { if(token===generation)saving.value=false; } }
watch(() => [auth.currentUser?.id, auth.authorizationStale], ([, stale], previous) => { if (stale) { generation++; serverCanManage.value=false; saving.value=false; } else if (previous && (previous[0] !== auth.currentUser?.id || previous[1])) load(); });
onMounted(load); onUnmounted(()=>generation++);
defineExpose({ form, load, save, valid, canEdit, serverCanManage });
</script>
<style scoped>.heading{display:flex;justify-content:space-between;align-items:center}.heading h2{font-size:18px}.form{display:grid;grid-template-columns:1fr 1fr;gap:0 18px;margin-top:18px}.full{grid-column:1/-1}.form :deep(.el-select){width:100%}.note{margin-left:10px;color:#64748b;font-size:13px}.preview{margin:18px 0;padding:16px;background:#f1f5f9;border-radius:8px}.preview h3{margin-top:0}.preview p{margin:8px 0}small{color:#64748b}.saved-note{margin-left:12px}@media(max-width:600px){.form{grid-template-columns:1fr}.full{grid-column:1}}</style>
