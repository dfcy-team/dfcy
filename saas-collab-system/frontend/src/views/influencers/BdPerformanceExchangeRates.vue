<template>
  <section class="bd-exchange-rates" aria-labelledby="bd-exchange-title">
    <el-card shadow="never" class="rate-card">
      <template #header>
        <div class="rate-heading">
          <div><strong id="bd-exchange-title">BD 绩效汇率</strong><p>1 单位外币 = 配置的人民币金额。仅用于 BD 绩效换算，不影响其他模块。</p></div>
          <el-tag :type="loadStatus === 'connected' ? 'success' : 'warning'">{{ loadStatus === 'connected' ? '配置服务已连接' : '配置服务不可用' }}</el-tag>
        </div>
      </template>
      <el-alert title="按订单统计日期／送样业务日期选择当日适用汇率。修改历史适用日期的汇率会影响重新查询的历史报表；旧配置版本和本币金额仍保留。" type="warning" :closable="false" show-icon />
      <div class="version-summary">
        <span>当前生效：{{ activeVersion ? `v${activeVersion.version}` : '原有 BD 汇率' }}</span>
        <span>最新版本：{{ latestVersion ? `v${latestVersion.version} · ${statusLabel(latestVersion.status)}` : '未提交' }}</span>
      </div>
      <el-alert v-if="latestVersion?.status === 'pending_approval' || latestVersion?.status === 'approved'" :title="latestVersion.status === 'pending_approval' ? '下面载入的是旧版待审批清单，不会自动启用；修改或删除后点击“保存汇率”，新版本无需审批、立即生效。' : '下面载入的是旧版已批准的延时启用清单；点击“保存汇率”可立即启用新版本，取代旧版清单。'" type="info" :closable="false" />
      <el-alert v-if="error" :title="error" type="error" :closable="false" class="load-error" />
      <p class="edit-help">修改：直接编辑下方单元格后保存。删除：点击行末“删除”，再保存。未保存的改动不会影响报表。</p>
      <el-alert v-if="hasUnsavedChanges" title="有未保存的修改或删除，请点击“保存汇率”生效。" type="warning" :closable="false" />
      <div class="rate-scroll">
        <table class="rate-table">
          <thead><tr><th>币种</th><th>1 外币 = 人民币</th><th>适用起始日期</th><th>备注</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="(row, index) in rows" :key="index">
              <td><el-select v-model="row.currency" :disabled="!canManage" :aria-label="`第${index + 1}行币种`"><el-option v-for="currency in currencies" :key="currency" :label="currency" :value="currency" /></el-select></td>
              <td><el-input v-model="row.rate" :disabled="!canManage" placeholder="填写汇率" inputmode="decimal" :aria-label="`第${index + 1}行汇率`" /></td>
              <td><el-date-picker v-model="row.effective_from" :disabled="!canManage" type="date" value-format="YYYY-MM-DD" placeholder="业务适用日期" :aria-label="`第${index + 1}行适用日期`" /></td>
              <td><el-input v-model="row.note" :disabled="!canManage" :maxlength="240" placeholder="可选" :aria-label="`第${index + 1}行备注`" /></td>
              <td><el-button :disabled="!canManage" type="danger" link @click="removeRow(index)">删除</el-button></td>
            </tr>
            <tr v-if="!rows.length"><td colspan="5" class="empty-rate">清单为空；保存后恢复读取原有 BD 汇率。人民币固定为 1，无需配置。</td></tr>
          </tbody>
        </table>
      </div>
      <div class="rate-tools">
        <el-button :disabled="!canManage || rows.length >= maxRows" @click="addRow">新增汇率</el-button>
        <small>同一币种可添加多个日期；当日选择最近一条已适用的记录。未覆盖的币种或更早日期继续使用原有 BD 汇率；两者均缺失时不猜测金额。</small>
      </div>
      <div class="rate-actions">
        <small>无需审批，保存后立即生效；每次保存保留历史版本。删除全部并保存会恢复原有 BD 汇率，不删除历史记录。</small>
        <el-button type="primary" :disabled="!canManage" :loading="saving" @click="saveVersion">保存汇率</el-button>
        <el-button :disabled="saving || removing" :loading="loading" @click="load">重新加载</el-button>
      </div>
      <details v-if="activeRows.length" class="active-rates">
        <summary>查看当前生效汇率清单（{{ activeRows.length }} 条）</summary>
        <ul><li v-for="row in activeRows" :key="`${row.currency}:${row.effective_from}`">1 {{ row.currency }} = {{ row.rate }} CNY，自 {{ row.effective_from }} 起适用{{ row.note ? ` · ${row.note}` : '' }}</li></ul>
      </details>
    </el-card>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { createConfigValue, fetchConfigDefinitions, fetchConfigValues } from '../../api/configCenter';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';
import { BD_EXCHANGE_RATE_CONFIG_KEY as CONFIG_KEY, BD_EXCHANGE_RATE_CURRENCIES as currencies, MAX_BD_EXCHANGE_RATE_ROWS as maxRows, readBdExchangeRateRows, validateBdExchangeRates } from '../../utils/bdExchangeRates';

const auth = useAuthStore();
const rows = ref([]);
const activeRows = ref([]);
const versions = ref([]);
const activeVersion = ref(null);
const definition = ref(null);
const loadStatus = ref('pending');
const error = ref('');
const saving = ref(false);
const removing = ref(false);
const loading = ref(false);
const loadedDraft = ref('');
const latestVersion = computed(() => [...versions.value].sort((a, b) => Number(b.version) - Number(a.version))[0] || null);
const hasUnsavedChanges = computed(() => loadStatus.value === 'connected' && JSON.stringify(rows.value) !== loadedDraft.value);
const canManage = computed(() => getActionAccess(auth, { permission: 'config.manage' }).allowed && loadStatus.value === 'connected' && !saving.value && !removing.value && !loading.value);

function items(response) {
  const data = response?.data;
  return Array.isArray(data) ? data : (data?.items || data?.results || []);
}
function statusLabel(status) {
  return { pending_approval: '待审批', approved: '待启用', effective: '生效中', superseded: '已替代', rejected: '已拒绝' }[status] || status;
}
function addRow() {
  if (canManage.value && rows.value.length < maxRows) rows.value.push({ currency: 'PHP', rate: '', effective_from: '', note: '' });
}
async function removeRow(index) {
  if (!canManage.value || !rows.value[index]) return;
  const row = rows.value[index];
  removing.value = true;
  try {
    await ElMessageBox.confirm(
      `删除 ${row.currency} 自 ${row.effective_from || '未填写日期'} 起的汇率？保存后才生效，历史版本仍保留。`,
      '删除汇率', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    );
    rows.value.splice(index, 1);
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') ElMessage.error('删除确认失败，请重试。');
  } finally { removing.value = false; }
}
async function load() {
  if (loading.value || removing.value) return;
  loading.value = true;
  loadStatus.value = 'pending';
  error.value = '';
  try {
    const responses = await Promise.all([
      fetchConfigDefinitions({ config_key: CONFIG_KEY }),
      fetchConfigValues({ config_key: CONFIG_KEY, scope: 'tenant', page: 1, page_size: 100 }),
      fetchConfigValues({ config_key: CONFIG_KEY, scope: 'tenant', status: 'effective', page: 1, page_size: 100 })
    ]);
    if (responses.some((response) => !response?.success || (response?.data?.api_status && response.data.api_status !== 'connected'))) throw new Error('BD 绩效汇率加载失败，请重试。');
    definition.value = items(responses[0]).find((item) => item.config_key === CONFIG_KEY);
    if (!definition.value || definition.value.scope_type !== 'tenant' || definition.value.requires_approval !== false) throw new Error('BD 绩效汇率免审批配置尚未安装，请联系管理员。');
    versions.value = items(responses[1]).filter((item) => item.config_key === CONFIG_KEY);
    activeVersion.value = items(responses[2]).filter((item) => item.config_key === CONFIG_KEY && item.status === 'effective' && new Date(item.effective_at).getTime() <= Date.now()).sort((a, b) => Number(b.version) - Number(a.version))[0] || null;
    activeRows.value = readBdExchangeRateRows(activeVersion.value?.value);
    const editable = ['pending_approval', 'approved'].includes(latestVersion.value?.status) ? latestVersion.value : activeVersion.value;
    rows.value = readBdExchangeRateRows(editable?.value);
    loadedDraft.value = JSON.stringify(rows.value);
    loadStatus.value = 'connected';
  } catch (cause) {
    loadStatus.value = 'degraded';
    error.value = cause?.message || 'BD 绩效汇率加载失败，请重试。';
  } finally {
    loading.value = false;
  }
}
async function saveVersion() {
  if (!canManage.value || saving.value) return;
  let value;
  try {
    value = validateBdExchangeRates(rows.value, { allowEmpty: true });
  } catch (cause) { return ElMessage.error(cause.message); }
  saving.value = true;
  try {
    const response = await createConfigValue({ config_key: CONFIG_KEY, value, effective_at: new Date().toISOString() });
    if (!response?.success) throw new Error(response?.message || '汇率保存失败');
    ElMessage.success('汇率已保存并生效');
    await load();
  } catch (cause) { ElMessage.error(cause?.message || '汇率保存失败'); }
  finally { saving.value = false; }
}
onMounted(load);
</script>

<style scoped>
.bd-exchange-rates { margin-top: 18px; color: #172620; }
.rate-card { border: 1px solid #dce7e1; border-radius: 16px; }
.rate-heading, .version-summary, .rate-tools, .rate-actions { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.rate-heading p { margin: 6px 0 0; color: #718079; font-size: 13px; }
.version-summary { justify-content: flex-start; flex-wrap: wrap; margin: 18px 0; font-size: 14px; }
.load-error { margin-top: 12px; }
.rate-scroll { overflow-x: auto; margin: 18px 0; }
.rate-table { width: 100%; min-width: 780px; border-collapse: collapse; text-align: left; }
.rate-table th { padding: 12px 8px; background: #f3f6f4; font-size: 13px; }
.rate-table td { padding: 10px 8px; border-bottom: 1px solid #edf1ef; }
.rate-table :deep(.el-select) { min-width: 100px; }
.rate-table :deep(.el-date-editor) { width: 155px; }
.empty-rate { text-align: center; color: #718079; }
.rate-tools { margin: 16px 0 24px; justify-content: flex-start; }
.rate-tools small, .rate-actions small { color: #718079; line-height: 1.6; }
.rate-actions { flex-wrap: wrap; justify-content: flex-end; padding-top: 18px; border-top: 1px solid #e7eeea; }
.rate-actions small { flex: 1; }
.active-rates { margin-top: 20px; font-size: 13px; line-height: 1.8; }
.edit-help { margin: 18px 0; color: #718079; font-size: 13px; line-height: 1.8; }
@media (max-width: 900px) { .rate-heading, .rate-tools { align-items: stretch; flex-direction: column; } .rate-actions small { flex-basis: 100%; } }
</style>
