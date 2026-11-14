<template>
  <section aria-label="原文件格式配置" class="format-workspace">
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-alert v-if="feedback" :title="feedback" type="success" :closable="false" />
    <p v-if="!loaded" role="status">{{ busy || disabled ? '正在读取原文件工作表，请稍候…' : '工作表尚未加载，不能保存规则或解析。' }}</p>
    <el-button v-if="!loaded && !busy && !disabled" @click="loadFormat">重新读取工作表</el-button>
    <el-form label-position="top" :disabled="busy || disabled">
      <div class="ownership">
        <el-form-item label="国家" required><el-select v-model="country" @change="warehouseId = null"><el-option v-for="c in options.countries" :key="c.code" :value="c.code" :label="c.name" /></el-select></el-form-item>
        <el-form-item label="仓库" required><el-select v-model="warehouseId" filterable><el-option v-for="w in warehouses" :key="w.id" :value="w.id" :label="`${w.code} · ${w.name}`" /></el-select></el-form-item>
        <el-form-item label="当前文件来源月份" required><el-date-picker v-model="month" type="month" value-format="YYYY-MM" /></el-form-item>
      </div>
      <el-collapse><el-collapse-item title="使用已保存规则（可选）" name="rules">
        <el-select v-model="ruleId" clearable placeholder="选择已有规则" aria-label="已保存格式规则" @change="useRule"><el-option v-for="r in availableRules" :key="r.id" :value="r.id" :label="`${r.name} · ${r.warehouse_code}`" /></el-select>
        <p>规则按仓库共享；修订请另存新名称，不覆盖历史配置。月份取当前文件。</p>
      </el-collapse-item></el-collapse>
      <div v-if="loaded" class="configuration-summary" role="status"><strong>工作表配置 {{ configuredCount }} / {{ specs.length }}</strong><span>逐表选择用途，再核对表头、金额列和结算项目。全部配置完成后可预览。</span></div>
      <div v-if="loaded" class="sheet-layout">
        <nav aria-label="工作表用途"><el-button v-for="s in specs" :key="s.name" :type="current === s.name ? 'primary' : 'default'" :aria-pressed="current === s.name" @click="current = s.name"><span class="sheet-choice"><strong>{{ s.name }}</strong><span>{{ sheetState(s) }}</span></span></el-button></nav>
        <div v-if="spec" class="sheet-editor">
          <h3>{{ spec.name }}</h3>
          <el-form-item label="工作表用途" required><el-select v-model="spec.kind" @change="resetColumns"><el-option label="订单明细" value="order" /><el-option label="结算表" value="settlement" /><el-option label="忽略（需说明）" value="ignore" /></el-select></el-form-item>
          <p v-if="!spec.kind" class="format-guidance">订单计费明细选“订单明细”；总额、费用小计及其他收费项目选“结算表”；不重复计费的辅助表选“忽略”并填写原因。</p>
          <template v-if="spec.kind && spec.kind !== 'ignore'">
            <div class="ownership mapping-fields">
              <el-form-item label="表头行（1—30）" required><el-input-number v-model="spec.header" :min="1" :max="30" :precision="0" @change="resetColumns" /></el-form-item>
              <el-form-item label="结束行（空为末行）"><el-input-number v-model="spec.end" :min="spec.header + 1" :precision="0" @change="spec.items = {}; items = []" /></el-form-item>
              <el-form-item :label="spec.kind === 'order' ? '单号列' : '项目列'" required><el-select v-model="spec.columns[spec.kind === 'order' ? 'number' : 'item']" @change="spec.items = {}; items = []"><el-option v-for="c in columns" :key="c.column" :value="c.column" :label="c.label" /></el-select></el-form-item>
              <el-form-item label="金额列（原数字 CNY）" required><el-select v-model="spec.columns.amount" @change="spec.items = {}; items = []"><el-option v-for="c in columns" :key="c.column" :value="c.column" :label="c.label" /></el-select></el-form-item>
            </div>
            <template v-if="spec.kind === 'settlement'">
              <el-button :loading="busy" @click="loadItems">读取结算项目并逐项核对</el-button>
              <el-table :data="items" max-height="320" aria-label="结算项目用途">
                <el-table-column prop="row" label="原行" width="70" /><el-table-column prop="item" label="项目" min-width="150" />
                <el-table-column label="原金额" min-width="110"><template #default="{ row }"><span :title="row.raw">{{ money(row.amount) }}</span></template></el-table-column>
                <el-table-column label="用途（不自动选择）" min-width="190"><template #default="{ row }"><el-select v-model="spec.items[row.item].role"><el-option v-for="(label, value) in roles" :key="value" :label="label" :value="value" /></el-select></template></el-table-column>
                <el-table-column label="忽略原因" min-width="170"><template #default="{ row }"><el-input v-if="spec.items[row.item].role === 'ignore'" v-model="spec.items[row.item].reason" maxlength="500" /></template></el-table-column>
              </el-table>
            </template>
          </template>
          <el-form-item :label="spec.kind === 'ignore' ? '忽略原因（必填）' : '范围外非空行说明'" :required="spec.kind === 'ignore'"><el-input v-model="spec.reason" maxlength="500" /></el-form-item>
          <el-collapse><el-collapse-item title="查看原表前30行（完整解析不截断）" name="sample"><el-table :data="sample?.sample || []" max-height="300"><el-table-column prop="row" label="原行" width="70" /><el-table-column v-for="c in sampleColumns" :key="c" :label="c" min-width="140"><template #default="{ row }">{{ row.cells[c] }}</template></el-table-column></el-table></el-collapse-item></el-collapse>
        </div>
      </div>
      <div class="format-actions">
        <p class="format-action-status">{{ !loaded ? '请先读取工作表。' : !configurationReady ? `还需完成 ${specs.length - configuredCount} 个工作表，并确认仓库和来源月份。` : '配置已就绪。预览只解析核对，不登记费用。' }}</p>
        <el-input v-model="ruleName" maxlength="100" placeholder="新规则名称（最多100字）" aria-label="新规则名称" />
        <el-button :loading="busy" :disabled="!configurationReady || !ruleName.trim()" @click="saveRule">保存为共享规则</el-button>
        <el-button type="primary" :loading="busy" :disabled="!configurationReady" @click="preview">解析预览（不登记）</el-button>
      </div>
    </el-form>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { ElMessageBox } from 'element-plus';
import { requestApi } from '../api/request';
import { warehouseMoney as money } from '../utils/warehouseMoney';
const props = defineProps({ job: { type: Object, required: true }, options: { type: Object, required: true }, disabled: Boolean });
const emit = defineEmits(['preview']);
const BASE = '/api/finance/warehouse-fees/';
const busy = ref(false), error = ref(''), feedback = ref(''), samples = ref([]), specs = ref([]), current = ref(''), items = ref([]);
const loaded = ref(false);
const country = ref(props.job.summary?.country || props.job.overrides?.country || ''), warehouseId = ref(props.job.summary?.settlement_warehouse_id || props.job.overrides?.warehouse_id || null);
const month = ref(props.job.summary?.bill_month || props.job.overrides?.bill_month || ''), rules = ref([]), ruleId = ref(null), ruleName = ref('');
const cleanState = ref('');
const state = computed(() => JSON.stringify({ country:country.value, warehouse:warehouseId.value, month:month.value, specs:specs.value, name:ruleName.value }));
const dirty = computed(() => Boolean(cleanState.value) && state.value !== cleanState.value);
async function canLeave() {
  if (busy.value || props.disabled) return false;
  if (dirty.value) {
    try { await ElMessageBox.confirm('尚未保存或应用的格式配置将丢弃，是否返回？已保存到服务器的规则不受影响。', '未保存的格式配置'); } catch { return false; }
  }
  return true;
}
defineExpose({ canLeave, dirty });
const roles = { order: '处理费小计（控制额）', other: '其他处理费', total: '结算总额（只能一项）', empty: '仅空白／零金额跳过', ignore: '忽略（需原因）' };
const warehouses = computed(() => props.options.warehouses.filter(w => w.country === country.value));
const availableRules = computed(() => rules.value.filter(r => (!country.value || r.country === country.value) && (!warehouseId.value || r.warehouse_id === warehouseId.value)));
const spec = computed(() => specs.value.find(s => s.name === current.value));
const sample = computed(() => samples.value.find(s => s.name === current.value));
const sampleColumns = computed(() => [...new Set((sample.value?.sample || []).flatMap(r => Object.keys(r.cells)))]);
const header = computed(() => sample.value?.sample.find(r => r.row === spec.value?.header)?.cells || {});
const columns = computed(() => Object.entries(header.value).map(([column, label]) => ({ column, label: `${column} · ${label}` })));
const configuredCount = computed(() => specs.value.filter(s => ['已配置', '已忽略'].includes(sheetState(s))).length);
const configurationReady = computed(() => loaded.value && specs.value.length > 0 && configuredCount.value === specs.value.length && Boolean(country.value && warehouseId.value && month.value));
watch(current, () => { items.value = []; });
function sheetState(s) {
  if (!s.kind) return '待配置';
  if (s.kind === 'ignore') return s.reason?.trim() ? '已忽略' : '待说明';
  if (!s.columns?.amount || !s.columns[s.kind === 'order' ? 'number' : 'item']) return '待选列';
  if (s.kind === 'settlement') {
    const entries = Object.values(s.items || {});
    if (!entries.length || entries.some(item => !item.role || (item.role === 'ignore' && !item.reason?.trim()))
      || entries.filter(item => item.role === 'total').length !== 1) return '待核对';
  }
  return '已配置';
}
async function api(config) { const result = await requestApi({ timeout: 120000, noMockFallback: true, ...config }); if (!result.success) throw new Error(result.message); return result.data; }
async function run(fn) { if (busy.value || props.disabled) return; busy.value = true; error.value = ''; feedback.value = ''; try { await fn(); } catch (e) { error.value = e.message; } finally { busy.value = false; } }
function resetColumns() { spec.value.columns = {}; spec.value.items = {}; items.value = []; }
function useRule(id) {
  if (!id) return;
  const rule = rules.value.find(r => r.id === id);
  if (rule.config.schema_version !== 3) { error.value = '旧规则需重新配置，不能直接套用。'; return; }
  specs.value = JSON.parse(JSON.stringify(rule.config.sheets)); country.value = rule.country; warehouseId.value = rule.warehouse_id;
  current.value = specs.value[0]?.name || ''; items.value = [];
}
function configuration() {
  if (!loaded.value || !samples.value.length || !specs.value.length) throw new Error('请先完整读取原文件工作表，不能保存空规则。');
  if (samples.value.length !== specs.value.length || samples.value.some(s => !specs.value.some(x => x.name === s.name))) throw new Error('规则工作表与原文件不一致，请重新配置。');
  if (specs.value.some(s => !['已配置', '已忽略'].includes(sheetState(s)))) throw new Error('请完成每个工作表的用途、列及结算项目配置。');
  if (!warehouseId.value || !country.value || !month.value) throw new Error('请确认国家、仓库及当前文件来源月份。');
  return { schema_version: 3, sheets: specs.value.map(s => {
    if (s.kind === 'ignore') return { name:s.name, kind:s.kind, reason:s.reason || '' };
    const cells = samples.value.find(x => x.name === s.name)?.sample.find(r => r.row === s.header)?.cells;
    const clean = { ...s, end: s.end || null, expected: Object.fromEntries(Object.entries(cells || {}).filter(([,v]) => String(v).trim()).map(([k,v]) => [k,String(v)])) };
    if (s.kind === 'order') delete clean.items;
    return clean;
  }) };
}
async function loadItems() { await run(async () => {
  const result = await api({ method:'post', url:BASE + `original-bills/${props.job.id}/format-preview/`, data:{ spec:spec.value } });
  const previous = spec.value.items || {}; spec.value.items = Object.fromEntries(result.items.map(r => [r.item, previous[r.item] || { role:'', reason:'' }])); items.value = result.items;
}); }
async function saveRule() { await run(async () => {
  const saved = await api({ method:'post', url:BASE + 'format-rules/', data:{ name:ruleName.value, warehouse_id:warehouseId.value, config:configuration() } });
  rules.value = (await api({ url:BASE + 'format-rules/' })).results; ruleId.value = saved.id; feedback.value = '规则已保存到服务器，未登记费用。';
  cleanState.value = state.value;
}); }
function preview() { if (busy.value || props.disabled) return; try { error.value = ''; emit('preview', { country:country.value, warehouse_id:warehouseId.value, bill_month:month.value, format_config:configuration() }); } catch (e) { error.value = e.message; } }
async function loadFormat() { await run(async () => {
  const data = await api({ url:BASE + `original-bills/${props.job.id}/format-preview/` });
  if (!Array.isArray(data.sheets) || !data.sheets.length) throw new Error('未读取到工作表，请重试或检查原文件。');
  samples.value = data.sheets;
  specs.value = data.sheets.map(s => ({ name:s.name, kind:'', header:1, end:null, columns:{}, items:{}, reason:'' })); current.value = specs.value[0]?.name || '';
  rules.value = (await api({ url:BASE + 'format-rules/' })).results;
  const applied = props.job.summary?.applied_rule?.config;
  if (applied?.schema_version === 3) specs.value = JSON.parse(JSON.stringify(applied.sheets));
  loaded.value = true;
  cleanState.value = state.value;
}); }
watch(() => props.disabled, disabled => { if (!disabled && !loaded.value) loadFormat(); }, { immediate:true });
</script>

<style scoped>
.format-workspace { min-width: 0; }
.configuration-summary { display:flex; flex-wrap:wrap; gap:8px 20px; padding:16px 0 8px; color:#465971; }
.configuration-summary strong { color:#182c45; }
.sheet-choice { display:flex; flex-direction:column; align-items:flex-start; gap:6px; text-align:left; }
.sheet-choice span { font-size:12px; }
.format-guidance { color:#465971; line-height:1.7; margin:0 0 16px; }
.format-action-status { width:100%; margin:0; color:#465971; line-height:1.6; }
.ownership { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.mapping-fields { grid-template-columns:repeat(2,minmax(0,1fr)); }
.sheet-layout { display:grid; grid-template-columns:170px minmax(0,1fr); gap:24px; margin:16px 0; align-items:start; }
nav { display:flex; flex-direction:column; gap:8px; } nav .el-button { margin:0; height:auto; white-space:normal; }
.sheet-editor { min-width:0; }.sheet-editor h3 { margin:0 0 16px; color:#182c45; }
.format-actions { position:sticky; bottom:0; z-index:3; padding:12px 0; border-top:1px solid #e5eaf3; background:white; display:flex; flex-wrap:wrap; gap:12px; }
.format-actions .el-input { max-width:300px; }
:deep(.el-select), :deep(.el-date-editor) { width:100%; }
@media(max-width:700px) { .ownership, .sheet-layout { grid-template-columns:minmax(0,1fr); } nav { flex-direction:row; overflow-x:auto; } nav .el-button { flex-shrink:0; } }
</style>
