<script setup>
import { computed, reactive, watch } from 'vue';

const props = defineProps({ modelValue: Boolean, batch: { type: Object, default: null }, warehouses: { type: Array, default: () => [] }, busy: Boolean, error: String });
const emit = defineEmits(['update:modelValue', 'create']);
const form = reactive({ warehouse_id: '', reason: '', notes: '', quantities: {} });
const candidates = computed(() => props.batch?.inbound_candidates || []);
const available = row => Math.max(0, Number(row.available_quantity ?? row.remaining_quantity ?? 0));
const groups = computed(() => {
  const byShipment = new Map();
  for (const row of candidates.value) {
    if (!byShipment.has(row.shipment_id)) byShipment.set(row.shipment_id, []);
    byShipment.get(row.shipment_id).push(row);
  }
  return [...byShipment.values()];
});
const selectedCount = computed(() => groups.value.filter(rows =>
  rows.some(row => form.quantities[row.shipment_line_id] > 0)).length);
const total = (rows, field) => rows.reduce((sum, row) => sum + Number(row[field] || 0), 0);
function selectRows(rows, checked) {
  for (const row of rows) form.quantities[row.shipment_line_id] = checked ? available(row) : 0;
}
watch(() => [props.modelValue, props.batch?.id], () => {
  if (!props.modelValue) return;
  form.warehouse_id = props.batch?.arrived_warehouse_id || props.batch?.planned_warehouse_id || '';
  form.reason = ''; form.notes = ''; form.quantities = {};
  for (const row of candidates.value) form.quantities[row.shipment_line_id] = 0;
}, { immediate: true });
function submit(splitByShipment) {
  if (props.busy || !form.warehouse_id || candidates.value.some(row => {const n=Number(form.quantities[row.shipment_line_id]);return !Number.isInteger(n)||n<0||n>available(row);})) return;
  const lines = candidates.value.filter(row => Number(form.quantities[row.shipment_line_id]) > 0)
    .map(row => ({ shipment_line_id: row.shipment_line_id, quantity: Number(form.quantities[row.shipment_line_id]) }));
  if (!lines.length) return;
  emit('create', { warehouse_id: form.warehouse_id, reason: form.reason.trim(), notes: form.notes.trim(), split_by_shipment: splitByShipment, lines });
}
</script>

<template>
  <el-dialog :model-value="modelValue" title="新建入库单" width="min(760px, 96vw)" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" @close="emit('update:modelValue', false)">
    <el-alert v-if="error" :title="error" type="error" :closable="false"/><p>{{ batch?.number }} · 可创建多张入库单；勾选本次到货的发货单，部分到货可展开调整待点数量。</p>
    <el-form-item label="目的仓"><el-select v-model="form.warehouse_id" :disabled="busy || !warehouses.length"><el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id"/></el-select></el-form-item>
    <el-form-item v-if="batch?.planned_warehouse_id && String(form.warehouse_id)!==String(batch.planned_warehouse_id)" label="改仓原因"><el-input v-model="form.reason" :disabled="busy" placeholder="必填"/></el-form-item>
    <el-alert v-if="!candidates.length" title="当前没有可入库商品" type="info" :closable="false"/>
    <el-button :disabled="busy" @click="selectRows(candidates, true)">选中全部剩余明细</el-button>
    <div v-for="rows in groups" :key="rows[0].shipment_id">
      <el-checkbox :model-value="rows.some(row => form.quantities[row.shipment_line_id] > 0)"
        :disabled="busy || !total(rows, 'available_quantity')" @change="checked => selectRows(rows, checked)">
        {{ rows[0].shipment_number }} · 发运 {{ total(rows, 'allocated_quantity') }} · 已收 {{ total(rows, 'received_quantity') }} · 草稿占用 {{ total(rows, 'reserved_quantity') }} · 可建 {{ total(rows, 'available_quantity') }}
      </el-checkbox>
      <details><summary>查看 SKU 与调整数量</summary>
    <section v-for="row in rows" :key="row.shipment_line_id" class="manual-inbound-row">
      <span>{{ row.sku || row.legacy_sku_code }} · {{ row.product_name }} · 可入 {{ available(row) }} / 剩余 {{ row.remaining_quantity ?? available(row) }}</span>
      <el-input-number v-model="form.quantities[row.shipment_line_id]" :min="0" :max="available(row)" :precision="0" :controls="false" :disabled="busy || available(row)===0" :aria-label="`${row.sku || 'SKU'} 本次入库数量`"/>
    </section>
      </details>
    </div>
    <el-form-item label="备注"><el-input v-model="form.notes" type="textarea" :disabled="busy"/></el-form-item>
    <template #footer><el-button :disabled="busy" @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="busy" :disabled="busy || !form.warehouse_id || !candidates.some(row=>Number(form.quantities[row.shipment_line_id])>0) || (batch?.planned_warehouse_id && String(form.warehouse_id)!==String(batch.planned_warehouse_id) && !form.reason.trim())" @click="submit(false)">合并创建 1 张草稿</el-button><el-button v-if="selectedCount > 1" type="primary" :loading="busy"
      :disabled="!form.warehouse_id || (batch?.planned_warehouse_id && String(form.warehouse_id)!==String(batch.planned_warehouse_id) && !form.reason.trim())"
      @click="submit(true)">分别创建 {{ selectedCount }} 张草稿</el-button></template>
  </el-dialog>
</template>

<style scoped>
.manual-inbound-row{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:10px 0;border-bottom:1px solid var(--el-border-color-lighter)}
</style>
