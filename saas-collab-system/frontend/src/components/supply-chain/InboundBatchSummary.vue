<script setup>
import { computed, ref } from 'vue';

const props = defineProps({ batch: Object });
const emit = defineEmits(['open']);
const view = ref('shipment');
const fields = [
  ['allocated_quantity', '发运'], ['received_quantity', '已确认实收'],
  ['reserved_quantity', '草稿占用'], ['available_quantity', '剩余可建'],
];
const summary = computed(() => {
  const groups = new Map();
  for (const row of props.batch.inbound_candidates || []) {
    const key = view.value === 'shipment' ? row.shipment_number : row.sku_id ?? row.sku;
    if (!groups.has(key)) {
      groups.set(key, {
        name: view.value === 'shipment' ? row.shipment_number : [row.sku, row.legacy_sku_code, row.product_name].filter(Boolean).join(' · '),
      });
    }
    const group = groups.get(key);
    for (const [field] of fields) group[field] = (group[field] || 0) + Number(row[field] || 0);
  }
  return [...groups.values()];
});
</script>

<template>
  <details>
    <summary>入库汇总 · 入库单（{{ batch.inbounds?.length || 0 }}）</summary>
    <el-radio-group v-model="view">
      <el-radio-button value="shipment">按发货单</el-radio-button>
      <el-radio-button value="sku">按 SKU</el-radio-button>
    </el-radio-group>
    <el-table :data="summary" max-height="360">
      <el-table-column prop="name" :label="view === 'shipment' ? '发货单' : '商品 SKU'" min-width="190"/>
      <el-table-column v-for="[field, label] in fields" :key="field" :prop="field" :label="label" min-width="100"/>
    </el-table>
    <div v-for="doc in batch.inbounds" :key="doc.id">
      <el-button link type="primary" @click="emit('open', doc)">{{ doc.number }}</el-button>
      {{ doc.warehouse_name }} · {{ {draft:'待核对', confirmed:'已确认', cancelled:'已取消'}[doc.status] || doc.status }}
    </div>
  </details>
</template>
