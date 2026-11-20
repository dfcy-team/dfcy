<script setup>
import { computed, ref } from 'vue';

const props = defineProps({ lines: Array, extras: Array, loadBatch: Function, lookup: Function, disabled: Boolean, detailsOnly: Boolean });
const emit = defineEmits(['apply']);
const open = ref(false), input = ref(''), rows = ref([]), error = ref(''), loading = ref(false);
const filter = ref('');
const overwritePrice = ref(false), overwriteReason = ref(false), commonReason = ref('');
const title = computed(() => props.detailsOnly ? '批量填写单价与原因' : '快捷清点');
const canSelect = row => row.allocations.length || row.extra || row.existingExtra;
const target = row => row.existingExtra || row.extra;
const hasValue = value => value != null && String(value).trim() !== '';
function changes(row) {
  const line = target(row);
  if (!line) return {};
  const currentPrice = row.existingExtra ? line.unit_price : line.reference_unit_price;
  const reason = row.reason || commonReason.value.trim();
  return {
    ...(hasValue(row.price) && (overwritePrice.value || !hasValue(currentPrice)) ? { unit_price: row.price } : {}),
    ...(reason && (overwriteReason.value || !hasValue(line.difference_note)) ? { difference_note: reason } : {}),
  };
}
function differenceNotes(row) {
  const reason = row.reason || commonReason.value.trim();
  if (target(row) || !reason) return [];
  return row.allocations
    .filter(([line, quantity]) => quantity !== line.expected_quantity
      && (overwriteReason.value || !hasValue(line.difference_note)))
    .map(([line]) => [line, reason]);
}
function valueAfter(row) {
  const line = target(row);
  const price = changes(row).unit_price ?? line?.unit_price ?? line?.reference_unit_price;
  const quantity = row.quantity ?? line?.received_quantity;
  return hasValue(price) && quantity != null ? (Number(price) * quantity).toFixed(4) : '—';
}
function show() {
  input.value = ''; rows.value = []; error.value = ''; filter.value = '';
  commonReason.value = ''; overwritePrice.value = false; overwriteReason.value = false;
  open.value = true;
}

const selected = computed(() => rows.value.filter(row => row.checked && canSelect(row)));
const visible = computed(() => rows.value.filter(row => !filter.value || row.status === filter.value));
const statuses = computed(() => [...new Set(rows.value.map(row => row.status))]);
const matches = (row, code) => [row.sku, row.sku_code, row.legacy_sku_code].some(value => value?.toLowerCase() === code.toLowerCase());
const rowKey = row => row.sku_id ?? row.sku;

async function preview() {
  rows.value = [];
  error.value = '';
  const quantities = new Map();
  try {
    for (const text of input.value.split(/\r?\n/)) {
      if (!text.trim()) continue;
      const cells = text.split(text.includes('\t') ? '\t' : ',').map(cell => cell.trim());
      const sku = cells.shift();
      if (['SKU', '新SKU', '新 SKU', '旧SKU', '旧 SKU'].includes(sku)
          && /数量|实收|单价/.test(cells[0] || '')) continue;
      const raw = props.detailsOnly ? '' : cells.shift() || '';
      const [price = '', reason = '', ...rest] = cells;
      if (!sku || rest.length || (raw && !/^\d+$/.test(raw))) throw new Error('请检查 SKU、实收数量和列数。');
      if (price && !/^\d{1,10}(?:\.\d{1,4})?$/.test(price)) throw new Error(`${sku} 的单价须为非负金额，最多四位小数。`);
      if (reason.length > 10000) throw new Error(`${sku} 的添加原因超过 10000 字符。`);
      if (!raw && !price && !reason && !props.detailsOnly) continue;
      const key = sku.toLowerCase();
      const prior = quantities.get(key);
      const quantity = raw ? (prior?.quantity ?? 0) + Number(raw) : prior?.quantity ?? null;
      if (quantity > 2147483647) throw new Error('SKU 数量超过允许范围。');
      const conflict = prior?.conflict || (prior?.price && price && Number(prior.price) !== Number(price))
        || (prior?.reason && reason && prior.reason !== reason);
      quantities.set(key, { code: prior?.code || sku, quantity, price: price || prior?.price,
        reason: reason || prior?.reason, conflict });
    }
    if (!quantities.size && props.detailsOnly) {
      for (const line of props.extras) {
        const code = line.sku || line.legacy_sku_code;
        if (code) quantities.set(code.toLowerCase(), { code, quantity: null });
      }
    }
    if (!quantities.size) throw new Error('请先粘贴实盘清单。');
    loading.value = true;
    const batch = props.detailsOnly ? {} : await props.loadBatch();
    const result = [];
    const sourceIds = new Set(props.lines.map(line => line.shipment_line_id));
    const entries = [...quantities.values()];
    for (let offset = 0; offset < entries.length; offset += 5) {
      const chunk = entries.slice(offset, offset + 5);
      result.push(...await Promise.all(chunk.map(async entry => {
        const { code, quantity } = entry;
        const row = { ...entry, allocations: [], checked: false };
        if (entry.conflict) return { ...row, status: '同编码单价或原因冲突' };
        const local = [...(props.detailsOnly ? [] : props.lines), ...props.extras].filter(line => matches(line, code));
        const keys = new Set(local.map(rowKey));
        if (keys.size > 1) return { ...row, status: '编码匹配多项' };
        if (local.length) {
          const [id] = keys;
          const lines = [...props.lines, ...props.extras].filter(line => rowKey(line) === id);
          row.expected = lines.reduce((sum, line) => sum + (line.expected_quantity || 0), 0);
          row.identity = id;
          if (lines.length === 1 && props.extras.includes(lines[0])) {
            row.existingExtra = lines[0];
            if (quantity != null) row.allocations = [[lines[0], quantity]];
            return { ...row, checked: true, status: '已有额外商品' };
          }
          if (quantity == null) return { ...row, status: '发货明细沿用原单价' };
          if (entry.price) row.note = '沿用发货单价';
          if (lines.length > 1 && quantity !== row.expected) {
            return { ...row, status: '请分配差额', manual: lines.map(line => ({
              line, quantity: null,
            })) };
          }
          row.allocations = lines.map(line => [line, lines.length === 1 ? quantity : line.expected_quantity]);
          return { ...row, checked: true, status: quantity === row.expected ? '一致' : '数量差异' };
        }
        if (props.detailsOnly) return { ...row, status: '本单无此额外商品' };
        if (quantity == null) return { ...row, status: '新增额外商品需填写实收数量' };
        const others = (batch.inbound_candidates || []).filter(line =>
          !sourceIds.has(line.shipment_line_id) && matches(line, code));
        if (others.length) return { ...row, status: '同批其他发货单',
          note: [...new Set(others.map(line => line.shipment_number))].join('、') };
        const catalog = (await props.lookup(code)).filter(sku => matches(sku, code));
        if (catalog.length !== 1) return { ...row, status: catalog.length ? '编码匹配多项' : '无商品档案' };
        const [sku] = catalog;
        const sibling = (batch.inbound_candidates || []).filter(line =>
          !sourceIds.has(line.shipment_line_id) && line.sku_id === sku.id);
        if (sibling.length) return { ...row, status: '同批其他发货单',
          note: [...new Set(sibling.map(line => line.shipment_number))].join('、') };
        if ([...props.lines, ...props.extras].some(line => line.sku_id === sku.id)) {
          return { ...row, status: '请使用本单显示的编码' };
        }
        return { ...row, status: quantity ? '清单外商品' : '清单外零实收',
          identity: sku.id, extra: quantity ? sku : null };
      })));
    }
    const counts = new Map();
    for (const row of result) {
      if (row.identity != null) counts.set(row.identity, (counts.get(row.identity) || 0) + 1);
    }
    for (const row of result) {
      if (counts.get(row.identity) > 1) {
        Object.assign(row, { checked: false, allocations: [], extra: null, existingExtra: null, manual: null, status: '同商品多个编码，请合并数量' });
      }
    }
    const importedCodes = entries.filter(row => row.quantity != null).map(row => row.code);
    const missing = new Map();
    for (const line of props.detailsOnly ? [] : props.lines) {
      if (line.received_quantity != null || importedCodes.some(code => matches(line, code))) continue;
      const id = rowKey(line);
      if (!missing.has(id)) missing.set(id, { code: line.sku, quantity: null,
        expected: 0, allocations: [], checked: false, status: '未清点' });
      missing.get(id).expected += line.expected_quantity;
    }
    rows.value = [...result, ...missing.values()];
    filter.value = '';
  } catch (e) {
    error.value = e.message || '实盘清单预览失败';
  } finally {
    loading.value = false;
  }
}
function allocate(row) {
  const valid = row.manual.every(item => Number.isInteger(item.quantity) && item.quantity >= 0)
    && row.manual.reduce((sum, item) => sum + item.quantity, 0) === row.quantity;
  row.allocations = valid ? row.manual.map(item => [item.line, item.quantity]) : [];
  row.checked = valid;
}
function apply() {
  emit('apply', selected.value.map(row => ({ ...row, details: changes(row), differenceNotes: differenceNotes(row) })));
  open.value = false;
  rows.value = [];
  input.value = '';
}
</script>

<template>
  <el-button type="primary" plain :disabled="disabled" @click="show">{{ title }}</el-button>
  <el-dialog v-model="open" :title="title" width="min(900px, 96vw)" append-to-body>
    <p>{{ detailsOnly ? '粘贴 SKU、单价（CNY）、添加原因。留空后预览可批量为现有额外商品填写统一原因。' : '粘贴 SKU、累计实收、单价（CNY）、原因。单价仅用于额外商品，原因可填入数量差异行。' }}</p>
    <el-input v-model="input" type="textarea" :rows="5" :disabled="loading"
      :placeholder="detailsOnly ? '从 Excel 粘贴 SKU、单价和添加原因' : '从 Excel 粘贴 SKU、实收数量、单价和添加原因'" @input="rows = []"/>
    <el-button :loading="loading" :disabled="disabled" @click="preview">预览</el-button>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <template v-if="rows.length">
      <div v-if="rows.some(target) || (!detailsOnly && rows.some(row => row.allocations.length))">
        <el-input v-model="commonReason" maxlength="10000" placeholder="为选中的额外商品和数量差异行填写统一原因"/>
        <el-checkbox v-model="overwritePrice">覆盖已有单价</el-checkbox>
        <el-checkbox v-model="overwriteReason">覆盖已有原因</el-checkbox>
      </div>
      <p>{{ rows.filter(row => row.quantity != null).length }} 个录入编码 · {{ rows.reduce((sum, row) => sum + row.quantity, 0) }} 件</p>
      <el-button @click="filter = ''">全部</el-button>
      <el-button v-for="status in statuses" :key="status" @click="filter = status">
        {{ status }} {{ rows.filter(row => row.status === status).length }}
      </el-button>
      <el-button v-if="rows.some(row => row.extra)" @click="rows.filter(row => row.extra).forEach(row => row.checked = true)">选中全部清单外商品</el-button>
      <el-table :data="visible" max-height="420">
        <el-table-column width="55"><template #default="{row}">
          <el-checkbox v-model="row.checked" :disabled="!canSelect(row)"/>
        </template></el-table-column>
        <el-table-column prop="code" label="SKU" min-width="140"/>
        <el-table-column prop="expected" label="待点" width="75"/>
        <el-table-column prop="quantity" label="实收" width="75"/>
        <el-table-column label="差异" width="75"><template #default="{row}">
          {{ row.expected == null || row.quantity == null ? '—' : row.quantity - row.expected }}
        </template></el-table-column>
        <el-table-column v-if="rows.some(target)" label="单价与原因" min-width="210"><template #default="{row}">
          <template v-if="target(row)">
            <div>单价 {{ target(row).unit_price ?? target(row).reference_unit_price ?? '—' }} → {{ changes(row).unit_price ?? target(row).unit_price ?? target(row).reference_unit_price ?? '—' }}</div>
            <div>货值 {{ valueAfter(row) }}</div>
            <div>原因 {{ changes(row).difference_note ?? (target(row).difference_note || '—') }}</div>
          </template>
        </template></el-table-column>
        <el-table-column label="处理结果" min-width="245"><template #default="{row}">
          {{ row.status }} {{ row.note }}
          <div v-if="differenceNotes(row).length">差异说明 {{ differenceNotes(row)[0][1] }}</div>
          <div v-for="item in row.manual" :key="item.line.id">
            {{ item.line.shipment_number }} · 待点 {{ item.line.expected_quantity }}
            <el-input-number v-model="item.quantity" :min="0" :max="row.quantity" :precision="0" @change="allocate(row)"/>
          </div>
        </template></el-table-column>
      </el-table>
    </template>
    <template #footer>
      <el-button @click="open = false">返回</el-button>
      <el-button type="primary" :disabled="disabled || loading || !selected.length" @click="apply">应用 {{ selected.length }} 项到草稿</el-button>
    </template>
  </el-dialog>
</template>
