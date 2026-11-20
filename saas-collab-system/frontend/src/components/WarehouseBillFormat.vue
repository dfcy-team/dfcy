<template>
  <section aria-label="原文件格式配置" class="format-workspace">
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-alert v-if="feedback" :title="feedback" type="success" :closable="false" />
    <p v-if="!job.id" role="status">可先选择新增或修改规则，再在页面顶部选择 Excel 文件。</p>
    <p v-else-if="!loaded" role="status">{{ busy || disabled ? '正在读取原文件工作表，请稍候…' : '工作表尚未加载，不能保存规则或解析。' }}</p>
    <el-button v-if="job.id && !loaded && !busy && !disabled" @click="loadFormat">重新读取工作表</el-button>
    <el-form label-position="top" :disabled="busy || disabled">
      <el-radio-group :model-value="ruleMode" aria-label="格式操作" @change="selectMode"><el-radio-button value="new">新增取数逻辑</el-radio-button><el-radio-button value="edit">修改已保存逻辑</el-radio-button></el-radio-group>
      <div v-if="ruleMode !== 'new'">
        <el-select :model-value="ruleId" clearable placeholder="选择已保存的取数逻辑" aria-label="已保存格式规则" @change="selectRule"><el-option v-for="r in availableRules" :key="r.id" :value="r.id" :label="`${r.name} · ${r.warehouse_code}`" :disabled="r.config?.schema_version !== 3">
          <el-tooltip placement="right" :show-after="250" effect="light">
            <template #content><div class="rule-file-history"><p v-if="ruleMismatch(r)">{{ ruleMismatch(r) }}</p><strong>成功解析过的文件</strong><ul v-if="r.successful_files?.length"><li v-for="file in r.successful_files" :key="file">{{ file }}</li></ul><p v-else>暂无成功解析记录</p></div></template>
            <span class="rule-option-label" tabindex="0">{{ r.name }} · {{ r.warehouse_code }}<small v-if="ruleMismatch(r)">（与当前文件不匹配）</small></span>
          </el-tooltip>
        </el-option></el-select>
        <p>保存修改将更新所选规则；另存为使用新名称，保留原规则。历史账单保留原配置，月份取当前文件。</p>
      </div>
      <p v-if="loaded && !specs.length" role="status">{{ feedback || '请选择匹配的已保存规则，或点击“新增取数逻辑”开始配置。' }}</p>
      <div v-if="loaded && specs.length" class="configuration-summary" role="status"><strong>工作表配置 {{ configuredCount }} / {{ specs.length }}</strong><span>先在左侧选择工作表，再依次设置用途、字段名称所在行、读取字段和数据范围；结算表还需核对总额与费用分类。</span></div>
      <div v-if="loaded" class="sheet-layout">
        <nav aria-label="这张工作表用于"><el-button v-for="s in specs" :key="s.name" :type="current === s.name ? 'primary' : 'default'" :aria-pressed="current === s.name" @click="current = s.name"><span class="sheet-choice"><strong>{{ s.name }}</strong><span>{{ sheetPurpose(s) }} · {{ sheetState(s) }}</span></span></el-button></nav>
        <div v-if="spec" class="sheet-editor">
          <h3>{{ spec.name }}</h3>
          <el-form-item v-if="!samples.some(s => s.name === spec.name) && !(spec.kind === 'ignore' && spec.optional_sheet)" label="对应当前文件的工作表" required>
            <el-select placeholder="选择工作表，保留原配置" @change="name => mapSheet(spec.name, name)"><el-option v-for="s in samples.filter(s => !specs.some(x => x.name === s.name && x.kind))" :key="s.name" :label="s.name" :value="s.name" /></el-select>
            <el-button @click="removeSourceSheet(spec.name)">不使用此原规则工作表</el-button>
          </el-form-item>
          <h4 class="logic-step">一、确定这张表的用途</h4>
          <el-form-item label="这张工作表用于" required><el-select v-model="spec.kind" @change="resetColumns"><el-option label="逐单处理费明细" value="order" /><el-option label="账单汇总及其他费用" value="settlement" /><el-option label="辅助资料，不计入费用" value="ignore" /></el-select></el-form-item>
          <p v-if="!spec.kind" class="format-guidance">订单计费明细选“订单明细”；总额、费用小计及其他收费项目选“结算表”；不重复计费的辅助表选“忽略”并填写原因。混仓账单的订单仓库取 SaaS 匹配结果，格式不限定整单仓库。</p>
          <template v-if="spec.kind && spec.kind !== 'ignore'">
            <h4 class="logic-step">二、找到字段名称所在的行</h4>
            <el-form-item label="以后上传同类账单时，如何找到这一行">
              <el-radio-group :model-value="spec.header_mode || 'exact'" aria-label="以后上传同类账单时，如何找到这一行" @change="value => { if (value === 'fields') spec.header_mode = value; else delete spec.header_mode; }">
                <el-radio value="fields">按字段名称自动查找</el-radio><el-radio value="exact">使用固定行，并核对整行名称</el-radio>
              </el-radio-group>
              <p v-if="spec.header_mode === 'fields'" class="muted">例如，含有“平台订单号、实际应收”的一行就是字段名称行。下方行号用于读取当前样本；以后按所选字段名称查找，不要求行号、列位置固定。</p>
            </el-form-item>
            <div class="ownership mapping-fields">
              <el-form-item :label="spec.header_mode === 'fields' ? '当前文件的字段名称在第几行（1—30）' : '固定使用第几行作为字段名称行（1—30）'" required><el-input-number v-model="spec.header" :min="1" :max="30" :precision="0" @change="resetColumns" /></el-form-item>
              <template v-if="spec.warehouse_column && !manualContext">
            <p>原文件仓库核对：发现其他仓库时停止解析，防止混仓账单整单归属错误。</p>
            <div class="ownership">
              <el-form-item label="仓库表头行"><el-input-number v-model="spec.warehouse_header" :min="1" :max="30" :precision="0" /></el-form-item>
              <el-form-item label="仓库名称列"><el-input v-model="spec.warehouse_column" /></el-form-item>
              <el-form-item label="允许的原文件仓库名称"><el-select v-model="spec.warehouse_values" multiple filterable allow-create default-first-option /></el-form-item>
            </div>
          </template>
          </div>
            <h4 class="logic-step">三、选择要读取的字段</h4>
            <p class="muted">从上一步所在行中选择字段。系统读取该字段下方的内容；括号中的列号只表示当前文件位置。</p>
            <div class="ownership mapping-fields">
          <el-form-item :label="spec.kind === 'order' ? '哪一列是订单号' : '哪一列是费用名称'" required><el-select v-model="spec.columns[spec.kind === 'order' ? 'number' : 'item']" @change="spec.items = {}; items = []"><el-option v-for="c in columns" :key="c.column" :value="c.column" :label="c.label" /></el-select></el-form-item>
              <el-form-item label="哪一列是最终计费金额（按 CNY 登记）" required><el-select v-model="spec.columns.amount" @change="spec.items = {}; items = []"><el-option v-for="c in columns" :key="c.column" :value="c.column" :label="c.label" /></el-select></el-form-item>
            </div>
            <h4 class="logic-step">四、确定读取哪些明细</h4>
            <p v-if="spec.kind === 'settlement' && ['sequence_total','total_row'].includes(spec.settlement_auto)" class="muted">当前逻辑会自动识别费用项目所在范围，不必逐月填写开始行、结束行。识别方式在下一步设置。</p>
            <div v-else class="ownership mapping-fields">
              <el-form-item label="从哪一行开始读取（不填：字段名称行的下一行）"><el-input-number v-model="spec.start" :min="spec.header + 1" :precision="0" /></el-form-item>
              <el-form-item label="读到哪一行结束（不填：工作表末行）"><el-input-number v-model="spec.end" :min="spec.header + 1" :precision="0" @change="spec.items = {}; items = []" /></el-form-item>
            </div>
            <template v-if="spec.kind === 'order'">
              <el-form-item label="同一笔业务有多行费用时，按哪个字段合并（可不选）"><el-select v-model="spec.group_by" clearable><el-option v-for="c in columns" :key="c.column" :value="c.column" :label="c.label" /></el-select></el-form-item>
              <el-checkbox v-model="spec.skip_zero">跳过零金额行</el-checkbox>
              <div v-for="(condition, index) in spec.filters || []" :key="index" class="ownership">
                <el-select v-model="condition.column" placeholder="筛选列"><el-option v-for="c in columns" :key="c.column" :value="c.column" :label="c.label" /></el-select>
                <el-select v-model="condition.values" multiple filterable allow-create default-first-option placeholder="允许值（可输入）"><el-option label="空值" value="" /></el-select>
                <el-checkbox v-if="spec.header_mode === 'fields'" v-model="condition.optional">明确允许旧版缺少此筛选字段</el-checkbox><el-button @click="spec.filters.splice(index, 1)">删除筛选</el-button>
              </div>
              <el-button @click="(spec.filters ||= []).push({column:'',values:[]})">只读取符合条件的行</el-button>
            </template>
            <template v-if="spec.kind === 'settlement'">
              <h4 class="logic-step">五、核对账单总额和费用分类</h4>
              <el-form-item label="账单总额从哪里读取">
                <el-select :model-value="totalMode" aria-label="账单总额从哪里读取" @change="setTotalMode">
                  <el-option label="读取有序号的项目，并找到其后的合计金额" value="sequence_total" />
                  <el-option label="读取标有“合计／总计／费用合计”的那一行" value="total_row" />
                  <el-option label="读取指定单元格中的总额" value="cell" />
                  <el-option label="原表没有单独总额，将费用项目相加" value="sum" />
                  <el-option label="在下面的项目列表中指定哪一项是总额" value="project" />
                  <el-option v-if="spec.settlement_auto === 'items_in_range'" label="保留已有固定范围及按月项目配置" value="items_in_range" />
                </el-select>
              </el-form-item>
              <el-form-item v-if="totalMode === 'cell'" label="总额所在单元格（如 G14）"><el-input v-model="spec.total_source" placeholder="例如 G14" /></el-form-item>
              <p v-if="['sequence_total','total_row'].includes(totalMode)" class="muted">总额与项目分别读取；金额不一致会保留待核提示，不自动覆盖原表总额。点击下方按钮识别当前文件并核对费用用途。</p>
              <el-button :loading="busy" @click="loadItems">读取当前文件的费用项目</el-button>
              <el-table :data="items" max-height="320" aria-label="结算项目用途">
                <el-table-column prop="row" label="原行" width="70" /><el-table-column prop="item" label="项目" min-width="150" />
                <el-table-column label="原金额" min-width="110"><template #default="{ row }"><span :title="row.raw">{{ row.amount == null ? '待读取' : money(row.amount) }}</span></template></el-table-column>
                <el-table-column label="这项金额如何使用" min-width="190"><template #default="{ row }"><el-select v-model="spec.items[row.item].role"><el-option v-for="(label, value) in roles" :key="value" :label="label" :value="value" /></el-select></template></el-table-column>
                <el-table-column label="忽略原因" min-width="170"><template #default="{ row }"><el-input v-if="spec.items[row.item].role === 'ignore'" v-model="spec.items[row.item].reason" maxlength="500" /></template></el-table-column>
              </el-table>
            </template>
          </template>
          <el-collapse class="logic-advanced"><el-collapse-item title="其他文件兼容设置（通常无需修改）" name="advanced">
          <el-form-item label="已知备用工作表名称（仅匹配这些名称）"><el-select v-model="spec.sheet_aliases" multiple filterable allow-create default-first-option /></el-form-item>
          <el-checkbox v-if="spec.kind === 'ignore'" v-model="spec.optional_sheet">已知辅助表允许缺省；出现未知工作表仍需配置</el-checkbox>
          <el-checkbox v-model="spec.month_name">工作表名称中的年月允许变化（其他文字须一致）</el-checkbox>
            <template v-if="spec.header_mode === 'fields'"><el-form-item v-for="col in Object.values(spec.columns || {})" :key="col" :label="`${col}列字段的已知备用名称`"><el-select :model-value="spec.field_aliases?.[col] || []" multiple filterable allow-create default-first-option @update:model-value="value => { (spec.field_aliases ||= {})[col] = value; }" /></el-form-item></template>
          </el-collapse-item></el-collapse>
          <el-form-item :label="spec.kind === 'ignore' ? '为什么这张表不计入费用（必填）' : '未读取的其他行是什么内容（如标题、说明、合计）'" :required="spec.kind === 'ignore'"><el-input v-model="spec.reason" maxlength="500" /></el-form-item>
          <el-collapse><el-collapse-item title="查看原表前40行（完整解析不截断）" name="sample"><el-table :data="sample?.sample || []" max-height="300"><el-table-column prop="row" label="原行" width="70" /><el-table-column v-for="c in sampleColumns" :key="c" :label="c" min-width="140"><template #default="{ row }">{{ row.cells[c] }}</template></el-table-column></el-table></el-collapse-item></el-collapse>
        </div>
      </div>
      <p v-if="manualContext">订单费用按匹配到的 SaaS 订单仓库归属；未匹配或仓库未确认的订单需先核对。其他费用可逐项指定仓库。</p>
      <div v-if="job.id && (!manualContext || previewContextVisible)" class="ownership">
        <el-form-item label="国家" required><el-select v-model="country" @change="warehouseId = null"><el-option v-for="c in options.countries" :key="c.code" :value="c.code" :label="c.name" /></el-select></el-form-item>
        <el-form-item :label="manualContext ? '其他费用默认仓库（可留空，逐项核对）' : '仓库'" :required="!manualContext"><el-select v-model="warehouseId" filterable clearable><el-option v-for="w in warehouses" :key="w.id" :value="w.id" :label="`${w.code} · ${w.name}`" /></el-select></el-form-item>
        <el-form-item label="当前文件来源月份" required><el-date-picker v-model="month" type="month" value-format="YYYY-MM" /></el-form-item>
      </div>
      <div class="format-actions">
        <p class="format-action-status">{{ !loaded ? '请先读取工作表。' : !configurationReady ? `还需完成 ${specs.length - configuredCount} 个工作表，并确认仓库和来源月份。` : '配置已就绪。预览只解析核对，不登记费用。' }}</p>
        <el-input v-model="ruleName" maxlength="100" placeholder="取数逻辑名称（最多100字）" aria-label="取数逻辑名称" />
        <el-button :loading="busy" :disabled="!saveReady || !ruleName.trim() || (ruleMode !== 'new' && (!ruleId || requiresSaveAs))" @click="saveRule()">{{ ruleMode === 'edit' ? '保存修改' : '保存为新逻辑' }}</el-button>
        <el-button v-if="ruleMode === 'edit'" :loading="busy" :disabled="!saveReady || !ruleId" @click="saveAs">另存为</el-button>
        <el-button type="primary" :loading="busy" :disabled="!layoutReady" @click="preview">解析预览（不登记）</el-button>
      </div>
    </el-form>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { ElMessageBox } from 'element-plus';
import { requestApi } from '../api/request';
import { warehouseMoney as money } from '../utils/warehouseMoney';
const props = defineProps({ job: { type: Object, default: () => ({}) }, initialSelection: { type:Object, default:() => ({}) }, options: { type: Object, required: true }, disabled: Boolean });
const emit = defineEmits(['preview', 'selection']);
const BASE = '/api/finance/warehouse-fees/';
const busy = ref(false), error = ref(''), feedback = ref(''), samples = ref([]), specs = ref([]), current = ref(''), items = ref([]);
const loaded = ref(false);
const ruleResolutions = ref({});
const manualContext = computed(() => !props.job.id || Boolean(props.job.overrides?.order_warehouse));
const fileCountry = computed(() => {
  if (manualContext.value) return '';
  const known = props.job.summary?.country || props.job.overrides?.country;
  if (known) return known;
  const matches = [['菲律宾','PH'],['马来','MY'],['泰国','TH']].filter(([name]) => props.job.file_name?.includes(name));
  return matches.length === 1 ? matches[0][1] : '';
});
const country = ref(props.job.overrides?.country || (manualContext.value ? '' : fileCountry.value)), warehouseId = ref(props.job.summary?.settlement_warehouse_id || props.job.overrides?.warehouse_id || null);
const month = ref(manualContext.value ? props.job.overrides?.bill_month || '' : props.job.summary?.bill_month || props.job.overrides?.bill_month || ''), rules = ref([]), ruleId = ref(null), ruleName = ref('');
const previewContextVisible = ref(false);
const totalChoices = ref({});
const ruleMode = ref('edit');
const ruleVersion = ref(null);
const requiresSaveAs = ref(false);
const loadedRuleSpecs = ref('');
const cleanState = ref('');
const state = computed(() => JSON.stringify({ country:country.value, warehouse:warehouseId.value, month:month.value, specs:specs.value, totalChoices:totalChoices.value, name:ruleName.value, mode:ruleMode.value, ruleId:ruleId.value }));
const dirty = computed(() => Boolean(cleanState.value) && state.value !== cleanState.value);
async function canLeave() {
  if (busy.value || props.disabled) return false;
  if (dirty.value) {
    try { await ElMessageBox.confirm('尚未保存或应用的格式配置将丢弃，是否返回？已保存到服务器的规则不受影响。', '未保存的格式配置'); } catch { return false; }
  }
  return true;
}
defineExpose({ canLeave, dirty });
watch([ruleMode, ruleId, country, month, warehouseId], () => emit('selection', {mode:ruleMode.value, id:ruleId.value, ...(manualContext.value ? {country:country.value, bill_month:month.value, warehouse_id:warehouseId.value} : {})}));
const roles = { order: '订单处理费小计，仅用于核对', other: '登记为其他处理费', total: '作为账单总额，只能选一项', empty: '仅允许空白或零金额', ignore: '不计入费用，填写原因' };
const warehouses = computed(() => props.options.warehouses.filter(w => w.country === country.value));
const availableRules = computed(() => rules.value.filter(r => !fileCountry.value || r.country === fileCountry.value));
function sheetPurpose(s) { return {order:'订单费用',settlement:'汇总与其他费用',ignore:'辅助资料'}[s.kind] || '未选用途'; }
const spec = computed(() => specs.value.find(s => s.name === current.value));
const totalMode = computed(() => {
  const s = spec.value;
  if (!s) return 'project';
  if (totalChoices.value[s.name] === 'cell' && !s.total_source && !s.settlement_auto) return 'cell';
  if (s.settlement_auto) return s.settlement_auto;
  return s.total_source === 'sum' ? 'sum' : s.total_source ? 'cell' : 'project';
});
function setTotalMode(mode) {
  const s = spec.value;
  if (!s) return;
  totalChoices.value[s.name] = mode;
  if (['sequence_total', 'total_row', 'items_in_range'].includes(mode)) {
    s.settlement_auto = mode;
    if (!s.total_source || s.total_source === 'sum') s.total_source = `${s.columns.amount || 'G'}${(s.header || 1) + 2}`;
  } else {
    delete s.settlement_auto;
    if (mode === 'sum') s.total_source = 'sum';
    else if (mode === 'project') delete s.total_source;
    else if (s.total_source === 'sum') delete s.total_source;
  }
}
const sample = computed(() => samples.value.find(s => s.name === current.value));
const sampleColumns = computed(() => [...new Set((sample.value?.sample || []).flatMap(r => Object.keys(r.cells)))]);
const header = computed(() => sample.value?.sample.find(r => r.row === spec.value?.header)?.cells || {});
const columns = computed(() => Object.entries(header.value).map(([column, label]) => ({ column, label: `${label}（当前${column}列）` })));
const configuredCount = computed(() => specs.value.filter(s => ['已配置', '已忽略'].includes(sheetState(s))).length);
const layoutReady = computed(() => loaded.value && specs.value.length > 0 && configuredCount.value === specs.value.length && samples.value.every(x => specs.value.some(s => s.name === x.name)));
const configurationReady = computed(() => layoutReady.value && Boolean(country.value && (manualContext.value || warehouseId.value) && month.value));
const saveReady = computed(() => manualContext.value ? layoutReady.value : configurationReady.value);
watch(() => [current.value, spec.value?.items], () => {
  items.value = Object.keys(spec.value?.items || {}).map(item => ({item, amount:null, raw:'请读取结算项目核对当前文件金额'}));
});
function sheetState(s) {
  if (s.name && !samples.value.some(x => x.name === s.name)) return s.kind === 'ignore' && s.optional_sheet && s.reason?.trim() ? '已忽略' : '待对应';
  if (!s.kind) return '待配置';
  if (s.kind === 'ignore') return s.reason?.trim() ? '已忽略' : '待说明';
  if (!s.columns?.amount || !s.columns[s.kind === 'order' ? 'number' : 'item']) return '待选列';
  if (s.kind === 'settlement') {
    if (totalChoices.value[s.name] === 'cell' && !s.total_source) return '待核对';
    const entries = Object.values(s.items || {});
    if (!entries.length || entries.some(item => !item.role || (item.role === 'ignore' && !item.reason?.trim()))
      || entries.filter(item => item.role === 'total').length !== (s.total_source ? 0 : 1)) return '待核对';
  }
  return '已配置';
}
async function api(config) { const result = await requestApi({ timeout: 120000, noMockFallback: true, ...config }); if (!result.success) throw new Error(result.message); return result.data; }
async function run(fn) { if (busy.value || props.disabled) return; busy.value = true; error.value = ''; feedback.value = ''; try { await fn(); } catch (e) { error.value = e.message; } finally { busy.value = false; } }
function resetColumns() { spec.value.columns = {}; spec.value.items = {}; items.value = []; for (const key of ['start','total_source','filters','group_by','skip_zero','settlement_auto','expected','field_aliases']) delete spec.value[key]; }
function ruleMismatch(rule) {
  if (rule.config?.schema_version !== 3) return '旧规则需重新配置。';
  if (fileCountry.value && rule.country !== fileCountry.value) return '规则国家与当前账单不同，请选择对应国家的规则。';
  if (!props.job.id) return '';
  if (!loaded.value) return '请先读取当前文件。';
  const resolution = ruleResolutions.value[rule.id];
  if (resolution && resolution.version === rule.version) return resolution.error || '';
  const names = new Set(rule.config.sheets.map(s => s.name));
  if (names.size !== samples.value.length || samples.value.some(s => !names.has(s.name))) {
    return '规则工作表与当前文件不一致，请选择匹配规则；如需适配新格式，请调整工作表对应关系后“另存为”。';
  }
  return '';
}
function useRule(id) {
  totalChoices.value = {};
  if (!id) { specs.value = []; current.value = ''; ruleId.value = null; ruleName.value = ''; loadedRuleSpecs.value = ''; return; }
  const rule = rules.value.find(r => r.id === id);
  if (!rule) return;
  if (!props.job.id) {
    ruleId.value = id; ruleName.value = rule.name;
    if (!manualContext.value) { country.value = rule.country; warehouseId.value = rule.warehouse_id; }
    return;
  }
  const mismatch = ruleMismatch(rule);
  if (mismatch && (rule.config?.schema_version !== 3 || (fileCountry.value && rule.country !== fileCountry.value))) {
    error.value = mismatch; ruleId.value = null; loadedRuleSpecs.value = ''; return;
  }
  error.value = '';
  feedback.value = '';
  if (mismatch) error.value = '已保留原规则全部配置，请为不同名称的工作表选择对应关系，再另存为；原规则不会被覆盖。';
  requiresSaveAs.value = Boolean(mismatch);
  ruleId.value = id; ruleVersion.value = rule.version;
  ruleName.value = rule.name;
  specs.value = JSON.parse(JSON.stringify(ruleResolutions.value[rule.id]?.version === rule.version && ruleResolutions.value[rule.id]?.config ? ruleResolutions.value[rule.id].config.sheets : rule.config.sheets));
  for (const sample of samples.value) if (!specs.value.some(s => s.name === sample.name)) specs.value.push(blankSheet(sample.name));
  if (!manualContext.value) { country.value = rule.country; warehouseId.value = rule.warehouse_id; }
  current.value = specs.value[0]?.name || ''; items.value = [];
  loadedRuleSpecs.value = mismatch ? '' : JSON.stringify(specs.value);
}
function blankSheet(name) { return {name,kind:'',header:1,end:null,columns:{},items:{},reason:''}; }
function mapSheet(from, to) {
  const source = specs.value.find(s => s.name === from);
  if (!source || !samples.value.some(s => s.name === to) || specs.value.some(s => s.name === to && s.kind)) return;
  specs.value = specs.value.filter(s => s.name !== to);
  source.name = to; current.value = to;
}
function removeSourceSheet(name) {
  if (samples.value.some(s => s.name === name)) return;
  specs.value = specs.value.filter(s => s.name !== name); current.value = specs.value[0]?.name || '';
}
async function selectMode(mode) {
  if (mode === ruleMode.value || !await canLeave()) return;
  ruleMode.value = mode; changeMode(); cleanState.value = state.value;
}
async function selectRule(id) {
  if (!await canLeave()) return;
  useRule(id); cleanState.value = state.value;
}
function resetSpecs() {
  totalChoices.value = {};
  specs.value = samples.value.map(s => ({ name:s.name, kind:'', header:1, end:null, columns:{}, items:{}, reason:'' }));
  current.value = specs.value[0]?.name || ''; items.value = [];
}
function changeMode() {
  if (ruleMode.value === 'new') { requiresSaveAs.value = false; ruleId.value = null; ruleName.value = ''; resetSpecs(); }
  else if (ruleId.value) useRule(ruleId.value);
}
function configuration(requireContext = true) {
  if (!loaded.value || !samples.value.length || !specs.value.length) throw new Error('请先完整读取原文件工作表，不能保存空规则。');
  if (specs.value.some(s => !samples.value.some(x => x.name === s.name) && !(s.kind === 'ignore' && s.optional_sheet)) || samples.value.some(s => !specs.value.some(x => x.name === s.name))) throw new Error('规则工作表与原文件不一致，请重新配置。');
  if (specs.value.some(s => !['已配置', '已忽略'].includes(sheetState(s)))) throw new Error('请完成每个工作表的用途、列及结算项目配置。');
  if (requireContext && ((!manualContext.value && !warehouseId.value) || !country.value || !month.value)) throw new Error('请确认国家、当前文件来源月份及必要的仓库归属。');
  return { schema_version: 3, sheets: specs.value.map(s => {
    if (s.kind === 'ignore') return { name:s.name, kind:s.kind, reason:s.reason || '', ...Object.fromEntries(['warehouse_column','warehouse_header','warehouse_values','month_name','optional_sheet','sheet_aliases'].filter(k => k in s).map(k => [k,s[k]])) };
    const cells = samples.value.find(x => x.name === s.name)?.sample.find(r => r.row === s.header)?.cells;
    const clean = { ...s, start: s.start || s.header + 1, end: s.end || null, expected: Object.fromEntries(Object.entries(cells || {}).filter(([,v]) => String(v).trim()).map(([k,v]) => [k,String(v)])) };
    for (const condition of s.filters || []) if (condition.optional && !clean.expected[condition.column] && s.expected?.[condition.column]) clean.expected[condition.column] = s.expected[condition.column];
    if (s.kind === 'order') delete clean.items;
    for (const key of ['total_source','group_by']) if (!clean[key]) delete clean[key];
    return clean;
  }) };
}
async function loadItems() { await run(async () => {
  const result = await api({ method:'post', url:BASE + `original-bills/${props.job.id}/format-preview/`, data:{ spec:{...spec.value, expected:Object.fromEntries(Object.entries(header.value).map(([k,v]) => [k,String(v)]))} } });
  if (result.range) Object.assign(spec.value, result.range);
  const previous = spec.value.items || {}; spec.value.items = {...(spec.value.settlement_auto ? previous : {}), ...Object.fromEntries(result.items.map(r => [r.item, previous[r.item] || { role:'', reason:'' }]))}; items.value = result.items;
}); }
async function saveAs() {
  if (busy.value || props.disabled || !saveReady.value || !ruleId.value) return;
  let name;
  try {
    name = (await ElMessageBox.prompt('输入新规则名称，原规则保持不变。', '另存为', {
      inputValue: `${ruleName.value}（副本）`,
      inputValidator: value => Boolean(value?.trim()) && value.trim().length <= 100 && value.trim() !== rules.value.find(r => r.id === ruleId.value)?.name || '请输入不同于原规则的名称（最多100字）。',
    })).value;
  } catch { return; }
  await saveRule(true, name.trim());
}
async function saveRule(asNew = false, newName = '') { await run(async () => {
  const config = configuration(!manualContext.value);
  if (ruleMode.value !== 'new' && !ruleId.value) throw new Error('请先选择已保存规则。');
  const original = rules.value.find(r => r.id === ruleId.value);
  if (!asNew && requiresSaveAs.value) throw new Error('工作表结构不同，请另存为新规则。');
  if (asNew && (!newName || newName === original?.name || newName.length > 100)) throw new Error('请输入不同于原规则的新名称（最多100字）。');
  const saved = await api({ method:'post', url:BASE + 'format-rules/', data:{ name:asNew ? newName : ruleName.value, warehouse_id:manualContext.value ? null : warehouseId.value, config, ...(ruleMode.value === 'edit' && !asNew ? { id:original.id, version:ruleVersion.value } : {}) } });
  rules.value = (await api({ url:BASE + 'format-rules/' })).results; ruleId.value = saved.id; ruleVersion.value = saved.version; ruleMode.value = 'edit'; feedback.value = '规则已保存到服务器，未登记费用。';
  if (asNew) ruleName.value = newName;
  requiresSaveAs.value = false;
  loadedRuleSpecs.value = JSON.stringify(specs.value);
  cleanState.value = state.value;
}); }
function preview() {
  if (busy.value || props.disabled) return;
  if (manualContext.value && (!country.value || !month.value)) {
    previewContextVisible.value = true;
    error.value = '请在本页填写国家和账单月份，再点击解析预览。';
    return;
  }
  try {
    error.value = '';
    const config = configuration();
    const rule = rules.value.find(r => r.id === ruleId.value);
    const unchanged = ruleMode.value === 'edit' && rule && (manualContext.value || (rule.country === country.value && rule.warehouse_id === warehouseId.value)) && loadedRuleSpecs.value === JSON.stringify(specs.value);
    emit('preview', { country:country.value, ...(warehouseId.value ? {warehouse_id:warehouseId.value} : {}), bill_month:month.value, ...(manualContext.value ? {order_warehouse:true} : {}),
      ...(unchanged ? { format_rule_id:rule.id, format_rule_version:ruleVersion.value } : { format_config:config }) });
  } catch (e) { error.value = e.message; }
}
async function loadFormat() { await run(async () => {
  if (!props.job.id) {
    rules.value = (await api({url:BASE + 'format-rules/'})).results;
    cleanState.value = state.value;
    return;
  }
  const data = await api({ url:BASE + `original-bills/${props.job.id}/format-preview/` });
  if (!Array.isArray(data.sheets) || !data.sheets.length) throw new Error('未读取到工作表，请重试或检查原文件。');
  samples.value = data.sheets;
  ruleResolutions.value = data.rule_resolutions || {};
  rules.value = (await api({ url:BASE + 'format-rules/' })).results;
  loaded.value = true;
  const applied = props.job.summary?.applied_rule;
  const savedConfig = props.job.overrides?.format_config || applied?.config;
  const savedId = props.job.overrides?.format_config ? null : props.job.overrides?.format_rule_id || applied?.id;
  const savedVersion = props.job.overrides?.format_rule_version ?? applied?.record_version;
  const savedRule = rules.value.find(r => r.id === savedId);
  if (props.initialSelection.mode) {
    ruleMode.value = props.initialSelection.mode;
    if (ruleMode.value === 'new') resetSpecs();
    else if (props.initialSelection.id) useRule(props.initialSelection.id);
    cleanState.value = state.value;
    return;
  }
  if (savedConfig?.schema_version === 3) {
    specs.value = JSON.parse(JSON.stringify((data.resolved_snapshot || savedConfig).sheets));
    current.value = specs.value[0]?.name || '';
    ruleId.value = savedRule?.id || null; ruleVersion.value = savedVersion ?? savedRule?.version;
    ruleName.value = applied?.name || savedRule?.name || '本批配置';
    ruleMode.value = savedRule ? 'edit' : 'new';
    loadedRuleSpecs.value = savedRule && savedVersion != null ? JSON.stringify(specs.value) : '';
    feedback.value = '已恢复本批次的配置。';
  } else if (savedRule && savedVersion === savedRule.version && !ruleMismatch(savedRule)) {
    useRule(savedRule.id);
  } else if (savedId) {
    error.value = '原规则已更新或删除，请重新选择规则；不会自动替换本批配置。';
  } else {
    const matches = availableRules.value.filter(r => !ruleMismatch(r) && (ruleResolutions.value[r.id] && ruleResolutions.value[r.id].version === r.version ? Boolean(ruleResolutions.value[r.id].config) : r.config.sheets.every(s => {
      const rows = samples.value.find(x => x.name === s.name)?.sample || [];
      const cells = rows.find(row => row.row === s.header)?.cells || {};
      const expected = Object.entries(s.expected || {});
      if (s.kind !== 'ignore' && (!expected.length || expected.some(([key,value]) => String(cells[key] ?? '').trim() !== String(value).trim()))) return false;
      return manualContext.value || !s.warehouse_column || rows.filter(row => row.row > s.warehouse_header && String(row.cells[s.warehouse_column] ?? '').trim()).every(row => s.warehouse_values?.includes(String(row.cells[s.warehouse_column]).trim()));
    })));
    if (matches.length === 1) { useRule(matches[0].id); feedback.value = '已匹配并完整载入保存的规则，请核对后解析预览。'; }
    else feedback.value = matches.length ? '存在多个匹配规则，请选择后载入配置。' : '未找到可确认匹配的规则，请选择已保存的取数逻辑或新增取数逻辑。';
  }
  cleanState.value = state.value;
}); }
watch(() => props.disabled, disabled => { if (!disabled && !loaded.value) loadFormat(); }, { immediate:true });
</script>

<style scoped>
.rule-option-label { display:block; width:100%; }
.rule-file-history { max-width:460px; max-height:260px; overflow:auto; overflow-wrap:anywhere; }
.rule-file-history ul { margin:8px 0 0; padding-left:18px; }
.rule-file-history li { margin:4px 0; line-height:1.5; }
.format-workspace { min-width: 0; }
.logic-step { margin:24px 0 16px; padding-top:16px; border-top:1px solid #e5eaf3; color:#182c45; font-size:15px; }
.logic-advanced { margin:20px 0; }
.muted { color:#465971; line-height:1.7; }
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
