<template>
  <AppPage title="供应链设置" subtitle="按业务单据设置单号规则，统一用于系统新建、导入与拆单。" :capability="loadError ? 'degraded' : 'connected'">
    <div class="heading"><h2>单号规则</h2><el-button :loading="loading" :disabled="saving" @click="loadRules">刷新</el-button></div>
    <el-alert type="info" :closable="false" title="规则只对后续新建单据生效，已有单号保持不变。流水号按单据类型独立递增，作废后不回收；预览不会占用单号。" />
    <p class="hint">编号日期取系统创建当天（业务时区），不随单据填写的业务日期回溯。修改前缀或位数不会清零同一周期内已使用的流水号。</p>
    <p v-if="!loading && !canEdit" class="hint">当前为只读。修改规则需要具有全部数据范围的供应链维护权限。</p>
    <el-alert v-if="loadError" type="error" :closable="false" :title="loadError" />
    <div class="rules-table">
      <el-table :data="rules" border v-loading="loading" row-key="kind">
        <el-table-column prop="label" label="业务单据" min-width="145" />
        <el-table-column label="规则说明" min-width="245"><template #default="{row}"><el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{row.enabled ? '自定义规则' : '系统默认'}}</el-tag><div class="rule-summary"><span v-if="row.enabled">{{row.include_country ? '国家前缀 · ' : ''}}{{row.prefix}} · {{dateName(row.date_format)}} · {{row.sequence_width}} 位流水 · {{resetName(row.reset_period)}}</span><span v-else>{{row.legacy_description}}</span></div><small>版本 {{row.version || 0}}<template v-if="row.updated_at"> · {{formatTime(row.updated_at)}}</template></small></template></el-table-column>
        <el-table-column label="当前生成示例" min-width="230"><template #default="{row}"><code>{{row.example}}</code></template></el-table-column>
        <el-table-column label="操作" width="95" fixed="right"><template #default="{row}"><el-button link type="primary" @click="editRule(row)">{{canEdit ? '设置规则' : '查看规则'}}</el-button></template></el-table-column>
      </el-table>
    </div>
    <p class="hint">示例以查询时的流水号为准，实际单号在保存新单据时分配。运营订货单在销售管理创建，其编号在这里统一维护。</p>

    <el-dialog v-model="dialogOpen" class="supply-number-rule-dialog" :title="`${editing?.label || ''} · 单号规则`" width="min(700px, 96vw)" top="4vh" :show-close="!saving" :close-on-click-modal="!saving" :close-on-press-escape="!saving" @closed="closed">
      <el-form label-position="top" class="rule-form" @submit.prevent>
        <el-form-item label="启用自定义单号" class="full"><el-switch v-model="form.enabled" aria-label="启用自定义单号" :disabled="!canEdit || saving" /><span class="switch-note">{{form.enabled ? '使用下方规则生成新单号' : '沿用系统默认规则'}}</span></el-form-item>
        <el-form-item label="按国家加前缀" class="full"><el-switch v-model="form.include_country" aria-label="按国家加前缀" :disabled="!form.enabled || !canEdit || saving" /><span class="switch-note">启用后按国家独立递增流水号</span></el-form-item>
        <div v-if="form.include_country" class="country-prefixes full"><h3>各国家前缀</h3><p class="hint">留空使用国家代码。国家前缀置于单据前缀之前，例如 USPO202610150001。</p><div class="country-grid"><el-form-item v-for="country in countries" :key="country.code" :label="`${country.name}（${country.code}）`"><el-input :model-value="form.country_prefixes[country.code] || ''" :aria-label="`${country.code} 国家前缀`" :placeholder="country.code" maxlength="8" :disabled="!form.enabled || !canEdit || saving" @update:model-value="value => setCountryPrefix(country.code, value)" /></el-form-item></div><el-alert v-if="!countries.length" title="请先在基础档案维护国家资料。" type="warning" :closable="false" /></div>
        <el-form-item label="单号前缀"><el-input v-model="form.prefix" aria-label="单号前缀" maxlength="12" placeholder="例如 PO" :disabled="!form.enabled || !canEdit || saving" /><small>大写英文字母开头，可含数字，最多 12 位。</small></el-form-item>
        <el-form-item label="日期格式"><el-select v-model="form.date_format" aria-label="日期格式" :disabled="!form.enabled || !canEdit || saving"><el-option v-for="option in dateOptions" :key="option.value" :label="option.label" :value="option.value" /></el-select></el-form-item>
        <el-form-item label="分隔符"><el-select v-model="form.separator" aria-label="分隔符" :disabled="!form.enabled || !canEdit || saving"><el-option label="无分隔符（推荐）" value="none" /><el-option label="横线 -" value="-" /><el-option label="下划线 _" value="_" /></el-select></el-form-item>
        <el-form-item label="流水号位数"><el-input-number v-model="form.sequence_width" aria-label="流水号位数" :min="3" :max="8" :step="1" step-strictly :disabled="!form.enabled || !canEdit || saving" /><small>不足补零，达到位数上限时提示调整规则。</small></el-form-item>
        <el-form-item label="流水重置周期" class="full"><el-select v-model="form.reset_period" aria-label="流水重置周期" :disabled="!form.enabled || !canEdit || saving"><el-option v-for="option in resetOptions" :key="option.value" :label="option.label" :value="option.value" /></el-select><small>重置周期需要日期格式包含对应的年月日，避免跨周期出现重复单号。</small></el-form-item>
        <div class="preview full" aria-live="polite"><div class="preview-title">生成示例 <span>{{preview?.business_date || businessDate}}</span></div><el-select v-if="form.include_country" v-model="previewCountry" aria-label="预览国家" :disabled="saving" class="preview-country"><el-option v-for="country in countries" :key="country.code" :label="`${country.name}（${country.code}）`" :value="country.code" /></el-select><code v-if="preview && !previewStale">{{preview.example}}</code><p v-else>规则或国家已变化，请重新预览。</p><small>预览不会保存设置或占用流水号。</small><el-button size="small" :loading="previewing" :disabled="!!validationError || saving" @click="runPreview">预览单号</el-button></div>
        <el-form-item v-if="canEdit" label="修改说明" class="full"><el-input v-model="reason" aria-label="修改说明" type="textarea" :rows="2" maxlength="300" show-word-limit placeholder="例如：统一采购订单编号格式" :disabled="saving" /></el-form-item>
      </el-form>
      <el-alert v-if="validationError || editError" :title="validationError || editError" type="error" :closable="false" />
      <section v-if="editing?.history?.length" class="history"><h3>最近修改</h3><div v-for="entry in editing.history" :key="entry.version"><strong>版本 {{entry.version}}</strong><span>{{entry.actor}} · {{formatTime(entry.created_at)}}</span><p>{{entry.reason}}</p></div></section>
      <template #footer><el-button :disabled="saving" @click="dialogOpen = false">关闭</el-button><el-button v-if="canEdit" type="primary" :loading="saving" :disabled="!canSave" @click="saveRule">保存规则</el-button></template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import { useAuthStore } from '../../stores/auth';
import { createIdempotencyKey } from '../../api/supplyChainV2';
import { fetchSupplyNumberRules, previewSupplyNumberRule, saveSupplyNumberRule } from '../../api/supplySettingsV2';

const auth = useAuthStore();
const rules = ref([]), countries = ref([]), previewCountry = ref(''), businessDate = ref(''), loading = ref(false), loadError = ref(''), serverCanManage = ref(false);
const canEdit = computed(() => serverCanManage.value && auth.hasPermission('supply.v2.manage') && !auth.authorizationStale);
const dialogOpen = ref(false), editing = ref(null), reason = ref(''), editError = ref(''), saving = ref(false), previewing = ref(false), preview = ref(null), previewSignature = ref('');
const form = reactive({ enabled: false, prefix: 'PO', date_format: 'YYYYMMDD', separator: 'none', sequence_width: 4, reset_period: 'day', include_country: false, country_prefixes: {} });
const dateOptions = [
  { value: 'YYYYMMDD', label: '年月日 · YYYYMMDD（20261015）' }, { value: 'YYMMDD', label: '短年月日 · YYMMDD（261015）' },
  { value: 'YYYYMM', label: '年月 · YYYYMM（202610）' }, { value: 'YYYY', label: '年份 · YYYY（2026）' }, { value: 'none', label: '不含日期' }
];
const resetOptions = [{ value: 'day', label: '每天从 1 递增' }, { value: 'month', label: '每月从 1 递增' }, { value: 'year', label: '每年从 1 递增' }, { value: 'never', label: '持续递增，不重置' }];
const dateName = value => dateOptions.find(option => option.value === value)?.label.split(' · ')[0] || value;
const resetName = value => resetOptions.find(option => option.value === value)?.label || value;
const formatTime = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '';
const fields = () => ({ ...form, country_prefixes: { ...form.country_prefixes } });
const signature = computed(() => JSON.stringify({ ...fields(), country_code: form.include_country ? previewCountry.value : '' }));
const previewStale = computed(() => previewSignature.value !== signature.value);
const validationError = computed(() => {
  if (!/^[A-Z][A-Z0-9]{0,11}$/.test(form.prefix)) return '前缀需以大写字母开头，仅包含大写字母和数字，最多 12 位。';
  if (!Number.isInteger(form.sequence_width) || form.sequence_width < 3 || form.sequence_width > 8) return '流水号位数须为 3 至 8 的整数。';
  const valid = { day: ['YYYYMMDD', 'YYMMDD'], month: ['YYYYMMDD', 'YYMMDD', 'YYYYMM'], year: ['YYYYMMDD', 'YYMMDD', 'YYYYMM', 'YYYY'], never: dateOptions.map(option => option.value) };
  if (!valid[form.reset_period]?.includes(form.date_format)) return '日期格式需要包含流水重置周期，例如按天重置应选择年月日。';
  if (Object.values(form.country_prefixes).some(value => !/^[A-Z][A-Z0-9]{0,7}$/.test(value))) return '国家前缀需以大写字母开头，仅包含大写字母和数字，最多 8 位。';
  if (form.include_country && !previewCountry.value) return '请选择预览国家；国家资料需要先在基础档案维护。';
  return '';
});
const canSave = computed(() => canEdit.value && !saving.value && !validationError.value && !!reason.value.trim() && !!preview.value && !previewStale.value && !previewing.value);
let loadToken = 0, previewToken = 0, saveKey = '', saveSignature = '';

async function loadRules() {
  const token = ++loadToken;
  loading.value = true; loadError.value = '';
  try {
    const result = await fetchSupplyNumberRules();
    if (token !== loadToken) return;
    if (!result?.success) throw new Error(result?.message || '单号规则读取失败。');
    rules.value = result.data?.rules || []; countries.value = result.data?.countries || []; businessDate.value = result.data?.business_date || ''; serverCanManage.value = !!result.data?.can_manage;
  } catch (error) { if (token === loadToken) { loadError.value = error.message || '单号规则读取失败。'; serverCanManage.value = false; } }
  finally { if (token === loadToken) loading.value = false; }
}
function editRule(row) {
  editing.value = { ...row };
  for (const key of Object.keys(form)) form[key] = key === 'country_prefixes' ? { ...(row[key] || {}) } : key === 'include_country' ? !!row[key] : row[key];
  previewCountry.value = countries.value[0]?.code || '';
  reason.value = ''; editError.value = ''; preview.value = null; previewSignature.value = ''; saveKey = ''; saveSignature = '';
  dialogOpen.value = true; runPreview();
}
async function runPreview() {
  if (!dialogOpen.value || !editing.value || validationError.value || saving.value) return;
  const token = ++previewToken, kind = editing.value.kind, captured = signature.value;
  previewing.value = true; editError.value = '';
  try {
    const result = await previewSupplyNumberRule(kind, { ...fields(), country_code: form.include_country ? previewCountry.value : '' });
    if (token !== previewToken || editing.value?.kind !== kind || !dialogOpen.value || captured !== signature.value) return;
    if (!result?.success) throw new Error(result?.message || '预览失败。');
    preview.value = result.data; previewSignature.value = captured;
  } catch (error) { if (token === previewToken) { preview.value = null; editError.value = error.message || '预览失败。'; } }
  finally { if (token === previewToken) previewing.value = false; }
}
async function saveRule() {
  if (!canSave.value) return;
  const kind = editing.value.kind;
  const payload = { ...fields(), expected_version: editing.value.version, reason: reason.value.trim() };
  const digest = JSON.stringify({ kind, payload });
  if (digest !== saveSignature || !saveKey) { saveKey = createIdempotencyKey(); saveSignature = digest; }
  saving.value = true; editError.value = '';
  try {
    const result = await saveSupplyNumberRule(kind, payload, saveKey);
    if (!result?.success) throw new Error(result?.message || '规则保存失败。');
    rules.value = rules.value.map(row => row.kind === kind ? result.data : row);
    dialogOpen.value = false; ElMessage.success('单号规则已保存，对后续新建单据生效。');
  } catch (error) { editError.value = error.message || '规则保存失败。'; }
  finally { saving.value = false; }
}
function closed() { previewToken++; previewing.value = false; preview.value = null; editing.value = null; }
function setCountryPrefix(code, value) { const updated = { ...form.country_prefixes }; if (value.trim()) updated[code] = value.trim(); else delete updated[code]; form.country_prefixes = updated; }
onMounted(loadRules);
onUnmounted(() => { loadToken++; previewToken++; });
defineExpose({ rules, countries, previewCountry, canEdit, editing, form, reason, preview, previewStale, canSave, editRule, runPreview, saveRule, loadRules });
</script>

<style scoped>
.heading{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:16px}.heading h2{font-size:18px;margin:0}.hint{font-size:13px;line-height:1.8;color:#64748b;margin:14px 0}.rules-table{overflow-x:auto;margin-top:20px}.rules-table :deep(.el-table){min-width:980px}small{display:block;font-size:12px;line-height:1.65;color:#64748b;margin-top:6px}code{font-family:ui-monospace,Consolas,monospace;overflow-wrap:anywhere;color:#1e40af}.rule-form{display:grid;grid-template-columns:1fr 1fr;gap:0 20px}.rule-form .full{grid-column:1/-1}.rule-form :deep(.el-select){width:100%}.switch-note{margin-left:12px;font-size:13px;color:#64748b}.preview{padding:18px;background:#eff6ff;border:1px solid #dbeafe;border-radius:10px;margin:0 0 20px}.preview-title{display:flex;justify-content:space-between;font-size:13px;color:#475569;margin-bottom:10px}.preview code{font-size:21px;font-weight:600}.preview p{font-size:13px;color:#64748b}.preview .el-button{margin-top:12px}.history{margin-top:18px;border-top:1px solid #e2e8f0}.history h3{font-size:14px}.history>div{font-size:12px;margin:12px 0}.history span{margin-left:12px;color:#64748b}.history p{line-height:1.6;margin:5px 0;color:#475569}@media(max-width:600px){.rule-form{grid-template-columns:1fr}.rule-form .full{grid-column:1}.preview code{font-size:17px}.history span{display:block;margin-left:0;margin-top:4px}}
.country-prefixes h3{font-size:14px;margin:0}.country-prefixes .hint{margin:6px 0 14px}.country-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 20px}.preview .preview-country{width:100%;display:block;margin-bottom:14px}@media(max-width:600px){.country-grid{grid-template-columns:1fr}}
.rules-table :deep(.el-table){min-width:715px}.rule-summary{margin-top:6px}
:global(.supply-number-rule-dialog){max-height:92vh;display:flex;flex-direction:column;margin-bottom:4vh}:global(.supply-number-rule-dialog .el-dialog__header),:global(.supply-number-rule-dialog .el-dialog__footer){flex-shrink:0}:global(.supply-number-rule-dialog .el-dialog__body){overflow-y:auto;min-height:0}
</style>
