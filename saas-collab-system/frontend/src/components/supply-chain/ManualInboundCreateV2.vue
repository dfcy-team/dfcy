<script setup>
import { computed, reactive, watch } from 'vue';

const props = defineProps({ modelValue: Boolean, batch: { type: Object, default: null }, warehouses: { type: Array, default: () => [] }, busy: Boolean, error: String });
const emit = defineEmits(['update:modelValue', 'create']);
const form = reactive({ warehouse_id: '', reason: '', notes: '', quantities: {} });
const candidates = computed(() => props.batch?.inbound_candidates || []);
const available = row => Math.max(0, Number(row.available_quantity ?? row.remaining_quantity ?? 0));
watch(() => [props.modelValue, props.batch?.id], () => {
  if (!props.modelValue) return;
  form.warehouse_id = props.batch?.arrived_warehouse_id || props.batch?.planned_warehouse_id || '';
  form.reason = ''; form.notes = ''; form.quantities = {};
  for (const row of candidates.value) form.quantities[row.shipment_line_id] = 0;
}, { immediate: true });
function submit() {
  if (props.busy || !form.warehouse_id || candidates.value.some(row => {const n=Number(form.quantities[row.shipment_line_id]);return !Number.isInteger(n)||n<0||n>available(row);})) return;
  const lines = candidates.value.filter(row => Number(form.quantities[row.shipment_line_id]) > 0)
    .map(row => ({ shipment_line_id: row.shipment_line_id, quantity: Number(form.quantities[row.shipment_line_id]) }));
  if (!lines.length) return;
  emit('create', { warehouse_id: form.warehouse_id, reason: form.reason.trim(), notes: form.notes.trim(), lines });
}
</script>

<template>
  <el-dialog :model-value="modelValue" title="新建入库单" width="min(760px, 96vw)" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" @close="emit('update:modelValue', false)">
    <el-alert v-if="error" :title="error" type="error" :closable="false"/><p>{{ batch?.number }} · 可创建多张入库单；每次只填本次实际到货数量。</p>
    <el-form-item label="目的仓"><el-select v-model="form.warehouse_id" :disabled="busy || !warehouses.length"><el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id"/></el-select></el-form-item>
    <el-form-item v-if="batch?.planned_warehouse_id && String(form.warehouse_id)!==String(batch.planned_warehouse_id)" label="改仓原因"><el-input v-model="form.reason" :disabled="busy" placeholder="必填"/></el-form-item>
    <el-alert v-if="!candidates.length" title="当前没有可入库商品" type="info" :closable="false"/>
    <section v-for="row in candidates" :key="row.shipment_line_id" class="manual-inbound-row">
      <span>{{ row.sku || row.legacy_sku_code }} · {{ row.product_name }} · 可入 {{ available(row) }} / 剩余 {{ row.remaining_quantity ?? available(row) }}</span>
      <el-input-number v-model="form.quantities[row.shipment_line_id]" :min="0" :max="available(row)" :precision="0" :controls="false" :disabled="busy || available(row)===0" :aria-label="`${row.sku || 'SKU'} 本次入库数量`"/>
    </section>
    <el-form-item label="备注"><el-input v-model="form.notes" type="textarea" :disabled="busy"/></el-form-item>
    <template #footer><el-button :disabled="busy" @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="busy" :disabled="busy || !form.warehouse_id || !candidates.some(row=>Number(form.quantities[row.shipment_line_id])>0) || (batch?.planned_warehouse_id && String(form.warehouse_id)!==String(batch.planned_warehouse_id) && !form.reason.trim())" @click="submit">创建草稿</el-button></template>
  </el-dialog>
</template>

<style scoped>
.manual-inbound-row{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:10px 0;border-bottom:1px solid var(--el-border-color-lighter)}
</style>
