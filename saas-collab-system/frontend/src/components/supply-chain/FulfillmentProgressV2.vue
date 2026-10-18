<template>
  <ol v-if="progress" class="fulfillment-progress" :class="{ compact }" aria-label="采购单履约进度">
    <li v-for="step in steps" :key="step.key" :class="{ reached: step.quantity > 0 }">
      <span class="step-label">{{ step.label }}</span>
      <strong>{{ number(step.quantity) }}</strong>
      <small v-if="!compact">{{ step.hint }}</small>
    </li>
  </ol>
  <span v-else class="progress-missing">进度待加载</span>
</template>
<script setup>
import { computed } from 'vue';
const props = defineProps({ progress: { type: Object, default: null }, compact: Boolean });
const number = value => Number(value || 0).toLocaleString('zh-CN');
const steps = computed(() => {
  const p = props.progress || {};
  return [
    { key: 'ordered', label: '下单', quantity: p.ordered_quantity, hint: '采购需求数量' },
    { key: 'shipped', label: '发货', quantity: p.shipped_quantity, hint: `未发 ${number(p.unshipped_quantity)} 件` },
    { key: 'dispatched', label: '集货', quantity: p.dispatched_quantity, hint: '已分配有效批次' },
    { key: 'received', label: '入库', quantity: p.received_quantity, hint: '已确认实收数量' }
  ];
});
</script>
<style scoped>
.fulfillment-progress{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));padding:0;margin:0;list-style:none;gap:20px}.fulfillment-progress li{display:flex;flex-direction:column;gap:8px;min-width:0;border-top:2px solid #e5eaf0;padding:12px 0}.fulfillment-progress li.reached{border-color:#2563eb}.step-label{font-size:13px;color:#64748b}.fulfillment-progress strong{color:#172033;font-size:20px;font-variant-numeric:tabular-nums}.fulfillment-progress small{color:#64748b;font-size:12px;line-height:1.6}.compact{gap:12px;min-width:230px}.compact li{padding:3px 0;border:0;gap:3px}.compact .step-label{font-size:11px}.compact strong{font-size:14px}.compact .reached strong{color:#2563eb}.progress-missing{font-size:12px;color:#64748b}@media(max-width:600px){.fulfillment-progress{gap:12px;grid-template-columns:repeat(2,minmax(0,1fr))}.compact{grid-template-columns:repeat(4,minmax(0,1fr))}}
</style>
