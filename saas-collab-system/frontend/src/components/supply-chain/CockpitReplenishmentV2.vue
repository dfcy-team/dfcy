<template>
  <section class="cockpit-replenishment" aria-label="驾驶舱补货参考">
    <div class="parameter-grid">
      <label>参考类型
        <el-select v-model="parameters.source_kind" :disabled="disabled" aria-label="参考类型">
          <el-option label="周期补货" value="cycle" />
          <el-option label="季节补货" value="season" />
        </el-select>
      </label>
      <label>销售开始
        <el-date-picker v-model="parameters.sales_start" type="date" value-format="YYYY-MM-DD" :disabled="disabled" aria-label="销售开始" />
      </label>
      <label>销售结束
        <el-date-picker v-model="parameters.sales_end" type="date" value-format="YYYY-MM-DD" :disabled="disabled" aria-label="销售结束" />
      </label>
      <label>目标库销比
        <el-input-number v-model="parameters.target_stock_sales_ratio" :min="0.0001" :max="100" :precision="4" :step="0.1" :disabled="disabled" aria-label="目标库销比" />
      </label>
      <label class="transit-option">计入按期有效到货
        <el-switch v-model="parameters.include_in_transit" :disabled="disabled" aria-label="计入按期有效到货" />
      </label>
    </div>
    <el-alert v-if="validationIssue" :title="validationIssue" type="error" :closable="false" />
    <OperatingReferenceV2 :parameters="parameters" :disabled="disabled" :validate="validate" :issue-label="issueLabel" action-label="带入运营订货草稿" @select="selectRows" />
  </section>
</template>

<script setup>
import { reactive, ref, watch } from 'vue';
import OperatingReferenceV2 from './OperatingReferenceV2.vue';

const props = defineProps({ countryId: { type: [Number, String], default: null }, disabled: Boolean });
const emit = defineEmits(['select']);

function businessToday() {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
  return `${parts.find(part => part.type === 'year').value}-${parts.find(part => part.type === 'month').value}-${parts.find(part => part.type === 'day').value}`;
}
function shiftDate(date, days) {
  const value = new Date(`${date}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}
const yesterday = shiftDate(businessToday(), -1);
const parameters = reactive({ country_id: props.countryId, source_kind: 'cycle', sales_start: shiftDate(yesterday, -29), sales_end: yesterday, target_stock_sales_ratio: 1, include_in_transit: true });
const validationIssue = ref('');

watch(() => props.countryId, value => { parameters.country_id = value; validationIssue.value = ''; });
function validCountry(value) { return /^\d+$/.test(String(value ?? '')) && Number.isSafeInteger(Number(value)) && Number(value) > 0; }
function validDate(value) { return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value; }
function validate() {
  validationIssue.value = '';
  if (!validCountry(parameters.country_id)) validationIssue.value = '请先选择有效国家。';
  else if (!validDate(parameters.sales_start) || !validDate(parameters.sales_end)) validationIssue.value = '请填写有效的销售开始和结束日期。';
  else if (parameters.sales_start > parameters.sales_end) validationIssue.value = '销售开始日期不能晚于结束日期。';
  else if (parameters.sales_end >= businessToday()) validationIssue.value = '销售日期必须是已完成的北京时间日期。';
  else if ((Date.parse(`${parameters.sales_end}T00:00:00Z`) - Date.parse(`${parameters.sales_start}T00:00:00Z`)) / 86400000 > 365) validationIssue.value = '销售周期最多 366 天。';
  else {
    const ratio = Number(parameters.target_stock_sales_ratio);
    if (!Number.isFinite(ratio) || ratio <= 0 || ratio > 100 || !/^\d+(?:\.\d{1,4})?$/.test(String(parameters.target_stock_sales_ratio))) validationIssue.value = '目标库销比须大于 0 且不超过 100，最多 4 位小数。';
  }
  return !validationIssue.value;
}
function selectRows(rows) {
  if (props.disabled || !validate()) return;
  emit('select', { parameters: { ...parameters }, rows });
}

const ISSUE_LABELS = {
  missing_inventory_snapshot: '缺少库存快照', available_quantity_unverified: '可用库存未核实', inventory_source_incomplete: '库存来源不完整',
  stale_inventory_snapshot: '库存快照已过期', ambiguous_inventory_aliases: '库存 SKU 映射不明确', unmapped_inventory: '存在未映射库存',
  no_sales_facts: '缺少销售事实', unmapped_sales_lines: '存在未映射销售明细', collection_coverage_unproven: '销售采集覆盖未确认',
  invalid_store_timezone: '店铺时区无效', unfinished_store_day: '店铺销售日尚未完成', no_authorized_sales_store: '没有授权销售店铺',
  bundle_composition_unverified: '组合商品构成未核实', supply_summary_not_authorized: '无权读取供应汇总',
  warehouse_supply_scope_incomplete: '仓库供应范围不完整', unassigned_warehouse_supply: '存在未分配仓库供应',
  wms_receipt_overlap_unresolved: 'WMS 到货重叠待核对', refunds_not_deducted: '销量未扣除退款'
};
function issueLabel(issue) { return ISSUE_LABELS[issue] || issue; }
</script>

<style scoped>
.parameter-grid{display:flex;align-items:end;gap:14px;flex-wrap:wrap}.parameter-grid label{display:flex;flex-direction:column;gap:6px;font-size:13px;color:#475569}.parameter-grid .el-select,.parameter-grid .el-date-editor{width:180px}.transit-option{flex-direction:row!important;align-items:center;gap:10px!important}.cockpit-replenishment{margin-top:12px}
</style>
