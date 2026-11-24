<script setup>
import { computed, ref, watch } from 'vue';
import { requestApi } from '../../api/request';
import { createIdempotencyKey } from '../../api/supplyChainV2';
import PaymentLedgerV2 from './PaymentLedgerV2.vue';

const props = defineProps({ shipment: Object, editable: Boolean, disabled: Boolean, hideSave: Boolean, transportDefaults: Object });
const emit = defineEmits(['updated']);
const groups = ref([]), lines = ref([]), suppliers = ref([]), carriers = ref([]);
const loaded = ref(false);
const loading = ref(false), saving = ref(false), error = ref(''), version = ref(0);
const ledgerOpen = ref(false), ledgerGroup = ref(null);
let generation = 0;
let pending = null;
const url = computed(() => `/api/internal/supply-chain/v2/supplier-shipments/${props.shipment.id}/domestic-expenses/`);
function unwrap(response) {
  if (!response?.success) throw new Error(response?.message || '费用操作失败');
  return response.data;
}
function assign(data) {
  groups.value = data.groups || [];
  lines.value = (data.lines || []).map(line => ({ ...line }));
  suppliers.value = data.suppliers || [];
  carriers.value = data.carriers || [];
  version.value = data.version;
}
async function load() {
  const token = ++generation;
  loading.value = true;
  error.value = '';
  try {
    const data = unwrap(await requestApi({ method: 'get', url: url.value }));
    if (token === generation) { assign(data); loaded.value = true; }
  } catch (e) {
    if (token === generation) error.value = e.message;
  } finally {
    if (token === generation) loading.value = false;
  }
}
function add(name = '国内运费') {
  const defaults = props.transportDefaults || props.shipment;
  lines.value.push({ name, amount: '', currency: 'CNY',
    payee_type: defaults.domestic_freight_settlement_mode !== 'company_direct' ? 'supplier' : 'carrier',
    payee_id: defaults.domestic_freight_settlement_mode !== 'company_direct'
      ? props.shipment.supplier_id : defaults.domestic_carrier_id,
    include_in_cost: true, method: 'quantity', notes: '' });
}
async function save() {
  if (loading.value || !loaded.value) { error.value = '费用尚未成功加载，请关闭重开后重试'; return false; }
  if (lines.value.some(row => !row.name?.trim() || !Number.isFinite(Number(row.amount)) || Number(row.amount) <= 0 || !row.payee_id)) { error.value = '请填写费用名称、大于零的金额及收款单位'; return false; }
  if (saving.value || props.disabled || !props.editable) return false;
  const body = { expected_version: props.shipment.version ?? version.value, lines: lines.value };
  const signature = JSON.stringify(body);
  if (pending?.signature !== signature) pending = { signature, key: createIdempotencyKey() };
  saving.value = true;
  error.value = '';
  try {
    const data = unwrap(await requestApi({ method: 'put', url: url.value, data: body,
      headers: { 'Idempotency-Key': pending.key } }));
    assign(data);
    emit('updated', { version: data.version });
    pending = null;
    return true;
  } catch (e) { error.value = e.message; return false; }
  finally { saving.value = false; }
}
function payeeName(row) { return (row.payee_type === 'supplier' ? suppliers.value : carriers.value).find(p => p.id === row.payee_id)?.name || '待选择收款单位'; }
function payments(group) {
  ledgerGroup.value = group;
  ledgerOpen.value = true;
}
watch(() => props.shipment.id, () => { pending = null; loaded.value = false; lines.value = []; load(); }, { immediate: true });
defineExpose({ save });
</script>

<template>
  <section v-loading="loading" class="shipment-expenses">
    <h3>国内运输费用明细</h3>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <el-table :data="lines" border empty-text="暂无我司承担费用；需要付款时添加费用">
      <el-table-column label="费用项目" min-width="150"><template #default="{row}">
        <el-input v-model="row.name" :disabled="!editable || saving || disabled" placeholder="运费 / 装卸费 / 提货费"/>
      </template></el-table-column>
      <el-table-column label="金额 / 币种" min-width="180"><template #default="{row}">
        <el-input v-model="row.amount" :disabled="!editable || saving || disabled" placeholder="0.0000"/>
        <details><summary>更多设置</summary><el-input v-model="row.currency" maxlength="3" :disabled="!editable || saving || disabled" placeholder="CNY"/></details>
      </template></el-table-column>
      <el-table-column label="收款单位" min-width="210"><template #default="{row}">
        <el-select v-model="row.payee_type" :disabled="!editable || saving || disabled" @change="row.payee_id = null">
          <el-option label="供应商" value="supplier"/><el-option label="承运商" value="carrier"/>
        </el-select>
        <el-select v-model="row.payee_id" filterable :disabled="!editable || saving || disabled" placeholder="选择收款单位">
          <el-option v-for="party in row.payee_type === 'supplier' ? suppliers : carriers" :key="party.id" :value="party.id" :label="party.name"/>
        </el-select>
      </template></el-table-column>
      <el-table-column label="成本分摊" min-width="150"><template #default="{row}">
        <el-checkbox v-model="row.include_in_cost" :disabled="!editable || saving || disabled">计入本发货单成本</el-checkbox>
        <details v-if="row.include_in_cost"><summary>分摊设置</summary><el-select v-model="row.method" :disabled="!editable || saving || disabled">
          <el-option label="按数量" value="quantity"/><el-option label="按体积" value="volume"/>
          <el-option label="按重量" value="weight"/>
        </el-select></details>
      </template></el-table-column>
      <el-table-column label="备注" min-width="150"><template #default="{row}">
        <el-input v-model="row.notes" :disabled="!editable || saving || disabled"/><small>付款给 {{ payeeName(row) }}；{{ row.include_in_cost ? '成本计入当前发货单' : '不计入商品成本' }}</small>
      </template></el-table-column>
      <el-table-column v-if="editable" label="操作" width="75"><template #default="{$index}">
        <el-button link type="danger" :disabled="saving || disabled" @click="lines.splice($index, 1)">删除</el-button>
      </template></el-table-column>
    </el-table>
    <div v-if="editable" class="expense-actions">
      <el-button :disabled="saving || disabled" @click="add('其他费用')">＋其他费用</el-button>
      <el-button v-for="name in ['国内运费','装卸费','提货费']" :key="name" :disabled="saving || disabled" @click="add(name)">＋{{name}}</el-button>
      <el-button v-if="!hideSave" type="primary" :loading="saving" :disabled="disabled" @click="save">保存费用</el-button>
    </div>
    <el-table v-if="groups.length" :data="groups" border>
      <el-table-column prop="payee_name" label="收款单位" min-width="160"/>
      <el-table-column prop="currency" label="币种" width="85"/>
      <el-table-column prop="amount" label="应付金额" min-width="110"/>
      <el-table-column prop="requested_amount" label="申请中" min-width="110"/>
      <el-table-column prop="paid_amount" label="已付款" min-width="110"/>
      <el-table-column prop="remaining_amount" label="待付款" min-width="110"/>
      <el-table-column label="付款" width="130"><template #default="{row}">
        <el-button link type="primary" @click="payments(row)">申请 / 查看付款</el-button>
      </template></el-table-column>
    </el-table>
    <el-dialog v-model="ledgerOpen" title="国内运输费用付款" append-to-body width="min(1100px, 96vw)" @closed="load">
      <PaymentLedgerV2 v-if="ledgerOpen && ledgerGroup" kind="domestic_expense" :id="ledgerGroup.id" :disabled="disabled"/>
    </el-dialog>
  </section>
</template>

<style scoped>
.shipment-expenses { margin: 16px 0; padding: 16px; border: 1px solid #dce4ef; border-radius: 6px; }
.shipment-expenses h3 { margin: 0 0 12px; font-size: 15px; }
.expense-actions { display: flex; gap: 10px; margin: 12px 0; }
</style>
