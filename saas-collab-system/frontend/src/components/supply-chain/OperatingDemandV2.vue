<template>
  <div class="demand-basis">
    <div>直接销量 {{ show(evidence.direct_sales_quantity) }}</div>
    <div>组合折算 {{ show(evidence.bundle_sales_quantity) }}</div>
    <strong>合计需求 {{ show(total) }}</strong>
    <small v-if="!hasBreakdown">历史依据未记录拆分明细，请重新计算查看。</small>
  </div>
</template>
<script setup>
import { computed } from 'vue';
const props = defineProps({ evidence: { type: Object, default: () => ({}) } });
const hasBreakdown = computed(() => Object.hasOwn(props.evidence, 'total_demand_quantity'));
const total = computed(() => hasBreakdown.value ? props.evidence.total_demand_quantity : props.evidence.sales_quantity);
const show = value => value == null ? '—' : value;
</script>
<style scoped>
.demand-basis{line-height:1.65}.demand-basis small{display:block;color:#64748b}
</style>
