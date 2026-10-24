<template>
  <section class="cockpit-replenishment" aria-label="驾驶舱销售与补货参考">
    <OperatingReferenceV2 :parameters="parameters" :disabled="disabled || !countryId" audience="procurement" :issue-label="issueLabel" @procurement="$emit('procurement')" />
  </section>
</template>
<script setup>
import { reactive, watch } from 'vue';
import OperatingReferenceV2 from './OperatingReferenceV2.vue';

const props = defineProps({ countryId: { type: [Number, String], default: null }, disabled: Boolean });
defineEmits(['procurement']);
const parameters = reactive({ country_id: props.countryId, source_kind: 'cycle' });
watch(() => props.countryId, value => { parameters.country_id = value; });
const ISSUE_LABELS = {
  missing_inventory_snapshot:'缺少库存快照',available_quantity_unverified:'可用库存未核实',inventory_source_incomplete:'库存来源不完整',stale_inventory_snapshot:'库存快照已过期',ambiguous_inventory_aliases:'库存SKU映射不明确',unmapped_inventory:'存在未映射库存',no_sales_facts:'缺少销售事实',unmapped_sales_lines:'存在未映射销售明细',collection_coverage_unproven:'销售采集覆盖未确认',invalid_store_timezone:'店铺时区无效',unfinished_store_day:'店铺销售日尚未完成',no_authorized_sales_store:'没有授权销售店铺',bundle_composition_unverified:'组合商品构成未核实',supply_summary_not_authorized:'无权读取供应汇总',warehouse_supply_scope_incomplete:'仓库供应范围不完整',unassigned_warehouse_supply:'存在未分配仓库供应',wms_receipt_overlap_unresolved:'WMS到货重叠待核对',refunds_not_deducted:'销量未扣除退款'
};
function issueLabel(issue){return ISSUE_LABELS[issue]||issue;}
</script>
<style scoped>.cockpit-replenishment{margin-top:12px}</style>
