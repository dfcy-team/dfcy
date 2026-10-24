<template>
  <section class="strategy-settings" aria-label="补货策略设置">
    <div class="heading"><div><h2>补货策略</h2><p>按国家维护销量权重、订货周期、预计到仓和安全库存天数。</p></div><el-button :loading="loading" @click="load">刷新</el-button></div>
    <el-alert type="info" :closable="false" :title="configured ? '当前为已保存策略。修改后将影响之后生成的建议；已保存的运营订货单保留原计算快照。' : '以下为候选初始值：订货间隔10天、预计到仓45天、安全库存35天；需按国家实际物流周期核对并保存后，系统才会使用。销量权重合计必须为100%。'" />
    <el-alert v-if="!canEdit" class="readonly" type="info" :closable="false" title="当前为只读；修改补货策略需要供应链维护权限。" />
    <el-alert v-if="error" type="error" :closable="false" :title="error" />
    <el-button v-if="version && error.includes('版本冲突')" size="small" :disabled="loading || saving" @click="loadStrategy">重新读取最新版本</el-button>
    <el-form v-if="countries.length" label-position="top" class="strategy-form" @submit.prevent>
      <el-form-item label="适用国家"><el-select v-model="countryId" filterable aria-label="补货策略国家" :disabled="saving" @change="loadStrategy"><el-option v-for="country in countries" :key="country.id" :value="country.id" :label="`${country.name}（${country.country_code}）`" /></el-select></el-form-item>
      <el-form-item label="策略名称"><el-input v-model="form.name" maxlength="80" :disabled="!canEdit || saving" placeholder="如：菲律宾海运常规补货" /></el-form-item>
      <el-form-item label="订货间隔天数"><el-input-number v-model="form.cycle_days" :min="1" :max="365" :precision="0" :disabled="!canEdit || saving" /><small>通常隔多少天集中安排一次订货。</small></el-form-item>
      <el-form-item label="预计到仓天数"><el-input-number v-model="form.lead_days" :min="1" :max="730" :precision="0" :disabled="!canEdit || saving" /><small>从提出需求到目的仓可销售，包含生产、运输、清关和上架。</small></el-form-item>
      <el-form-item label="安全库存天数"><el-input-number v-model="form.safety_days" :min="0" :max="365" :precision="0" :disabled="!canEdit || saving" /><small>为物流延误及销量波动保留的额外库存覆盖天数。</small></el-form-item>
      <el-form-item label="销量计算方式"><el-select v-model="form.sales_model" :disabled="!canEdit || saving"><el-option label="加权日均销量" value="weighted"/><el-option label="近30天普通日均" value="ordinary"/></el-select><small>加权模式采用7／15／30天权重；普通模式使用近30天日均销量。</small></el-form-item>
      <template v-if="form.sales_model==='weighted'"><el-form-item label="7天日均销量权重"><el-input-number v-model="form.sales_weights[7]" :min="0" :max="100" :precision="0" :disabled="!canEdit || saving" /><small>默认50%，反映近期销售。</small></el-form-item>
      <el-form-item label="15天日均销量权重"><el-input-number v-model="form.sales_weights[15]" :min="0" :max="100" :precision="0" :disabled="!canEdit || saving" /><small>默认30%，平衡近期波动。</small></el-form-item>
      <el-form-item label="30天日均销量权重"><el-input-number v-model="form.sales_weights[30]" :min="0" :max="100" :precision="0" :disabled="!canEdit || saving" /><small>默认20%，提供较稳定的参考。</small></el-form-item></template>
      <el-form-item label="策略状态"><el-switch v-model="form.active" :disabled="!canEdit || saving" /><small>{{ weightTotal === 100 ? '权重合计100%，可保存。' : `当前权重合计${weightTotal}%，需调整至100%。` }}</small></el-form-item>
    </el-form>
    <el-empty v-else-if="!loading && !error" description="当前账号没有可配置的国家范围" />
    <p v-if="loadedAt" class="meta">策略更新时间：{{ formatTime(loadedAt) }} · 版本 {{ version ?? '—' }}</p>
    <div v-if="countries.length" class="formula-card"><strong>计算口径</strong><code v-if="form.sales_model==='weighted'">预测日销量＝A7×{{form.sales_weights[7]}}%＋A15×{{form.sales_weights[15]}}%＋A30×{{form.sales_weights[30]}}%</code><code v-else>预测日销量＝近30个完整自然日销量 ÷ 30</code><code>建议新增量＝向上取整［最大值（0，预测日销量×（{{form.cycle_days}}＋{{form.lead_days}}＋{{form.safety_days}}）－可用库存－有效到货－已提交需求－草稿预留）］</code><small>A7／A15／A30为近7／15／30个完整自然日的日均销量；变化率只展示，不再重复乘入预测。活动日期需求在活动版策略中单独计算。</small></div>
    <el-alert v-if="validationError" type="warning" :closable="false" :title="validationError" />
    <div v-if="countries.length" class="footer"><el-button type="primary" :loading="saving" :disabled="!canEdit || !!validationError || loading" @click="save">保存当前国家策略</el-button></div>
  </section>
</template>
<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { useAuthStore } from '../../stores/auth';
import { fetchReplenishmentStrategy, saveReplenishmentStrategy } from '../../api/replenishmentStrategyV2';
import { cockpitActorKey } from '../../utils/cockpitDraft';

const auth = useAuthStore();
const countries = ref([]), countryId = ref(null), loading = ref(false), saving = ref(false), error = ref(''), loadedAt = ref(''), version = ref(null), serverCanManage = ref(false), configured = ref(false);
const form = reactive({ name: '', cycle_days: 10, lead_days: 45, safety_days: 35, sales_model: 'weighted', sales_weights: { 7: 50, 15: 30, 30: 20 }, active: true });
const selectedCountry = computed(() => countries.value.find(country => String(country.id) === String(countryId.value)));
const canEdit = computed(() => (selectedCountry.value?.can_manage ?? serverCanManage.value) && auth.hasPermission('supply.v2.manage') && !auth.authorizationStale);
const weightTotal = computed(() => [7, 15, 30].reduce((sum, day) => sum + Number(form.sales_weights[day] || 0), 0));
const validationError = computed(() => {
  if (!countryId.value) return '请选择国家。';
  if (!form.name.trim()) return '请填写策略名称。';
  if (![form.cycle_days, form.lead_days, form.safety_days].every(Number.isInteger)) return '天数必须为整数。';
  if (form.cycle_days < 1 || form.lead_days < 1 || form.safety_days < 0 || form.cycle_days + form.lead_days + form.safety_days > 366) return '订货周期、预计到仓和安全库存合计不能超过366天。';
  if (weightTotal.value !== 100 || ![7, 15, 30].every(day => Number.isInteger(Number(form.sales_weights[day])) && Number(form.sales_weights[day]) >= 0)) return '7、15、30天权重须为非负整数，合计100%。';
  return '';
});
let token = 0;
const formatTime = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—';
function applyStrategy(strategy = {}) {
  form.name = strategy.name || `${countries.value.find(item => String(item.id) === String(countryId.value))?.name || ''}常规补货`;
  form.cycle_days = Number(strategy.cycle_days ?? 10); form.lead_days = Number(strategy.lead_days ?? 45); form.safety_days = Number(strategy.safety_days ?? 35);
  form.sales_model = strategy.sales_model || 'weighted';
  form.sales_weights = { 7: Number(strategy.sales_weights?.[7] ?? strategy.sales_weights?.['7'] ?? 50), 15: Number(strategy.sales_weights?.[15] ?? strategy.sales_weights?.['15'] ?? 30), 30: Number(strategy.sales_weights?.[30] ?? strategy.sales_weights?.['30'] ?? 20) };
  form.active = strategy.active !== false; version.value = strategy.version ?? null; loadedAt.value = strategy.updated_at || '';
}
async function load() {
  const current = ++token; loading.value = true; error.value = '';
  try {
    const response = await fetchReplenishmentStrategy();
    if (current !== token) return;
    if (!response?.success) throw new Error(response?.message || '补货策略读取失败。');
    countries.value = response.data?.countries || []; serverCanManage.value = !!response.data?.can_manage;
    if (!countries.value.some(country => String(country.id) === String(countryId.value))) countryId.value = countries.value[0]?.id ?? null;
    const selected = response.data?.strategies?.find(item => String(item.country_id) === String(countryId.value));
    configured.value = !!selected;
    applyStrategy(selected || response.data?.proposed_defaults || {});
  } catch (e) { if (current === token) { error.value = e.message || '补货策略读取失败。'; serverCanManage.value = false; } }
  finally { if (current === token) loading.value = false; }
}
async function loadStrategy() {
  const current = ++token; loading.value = true; error.value = '';
  try {
    const response = await fetchReplenishmentStrategy(countryId.value);
    if (current !== token) return;
    if (!response?.success) throw new Error(response?.message || '国家补货策略读取失败。');
    const data = response.data || {}; serverCanManage.value = !!data.can_manage;
    countries.value = data.countries || countries.value;
    configured.value = data.configured === true || !!data.strategy?.id;
    applyStrategy(data.strategy || data.proposed_defaults || data);
  } catch (e) { if (current === token) error.value = e.message || '国家补货策略读取失败。'; }
  finally { if (current === token) loading.value = false; }
}
async function save() {
  if (!canEdit.value || validationError.value || saving.value) return;
  const current = token, country = countryId.value;
  saving.value = true; error.value = '';
  try {
    const payload = { country_id: Number(countryId.value), name: form.name.trim(), cycle_days: form.cycle_days, lead_days: form.lead_days, safety_days: form.safety_days, sales_model: form.sales_model, sales_weights: { 7: form.sales_weights[7], 15: form.sales_weights[15], 30: form.sales_weights[30] }, active: form.active, ...(version.value != null ? { expected_version: version.value } : {}) };
    const response = await saveReplenishmentStrategy(countryId.value, payload);
    if (current !== token || country !== countryId.value || auth.authorizationStale) return;
    if (!response?.success) throw Object.assign(new Error(response?.message || '补货策略保存失败。'), { status: response?.http_status });
    applyStrategy(response.data?.strategy || response.data); configured.value = true;
  } catch (e) { if(current===token)error.value = e?.status === 409 || e?.response?.status === 409 ? '版本冲突：其他用户已更新该国家策略。请重新读取最新版本，再核对后保存。' : (e.message || '补货策略保存失败。'); }
  finally { if(current===token)saving.value = false; }
}
watch(() => JSON.stringify([cockpitActorKey(auth.currentUser),auth.authorizationStale]),()=>{token++;loading.value=false;saving.value=false;error.value='';countries.value=[];countryId.value=null;version.value=null;loadedAt.value='';configured.value=false;serverCanManage.value=false;Object.assign(form,{name:'',cycle_days:10,lead_days:45,safety_days:35,sales_model:'weighted',sales_weights:{7:50,15:30,30:20},active:true});if(!auth.authorizationStale)load();},{flush:'sync'});
onMounted(load); onUnmounted(() => { token++; });
defineExpose({ countries, countryId, form, canEdit, validationError, load, loadStrategy, save });
</script>
<style scoped>
.strategy-settings{padding:12px 0}.heading{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:16px}.heading h2{font-size:18px;margin:0}.heading p,.meta,small{font-size:12px;color:#64748b;line-height:1.7}.strategy-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 22px;margin-top:16px}.strategy-form :deep(.el-select),.strategy-form :deep(.el-input-number){width:100%}.strategy-form small{display:block}.formula-card{display:grid;gap:8px;padding:16px;background:#f5f8fc;border-radius:8px;margin:12px 0}.formula-card code{white-space:normal;overflow-wrap:anywhere;color:#1e3a8a}.footer{display:flex;justify-content:flex-end;margin-top:16px}@media(max-width:640px){.strategy-form{grid-template-columns:1fr}}
</style>
