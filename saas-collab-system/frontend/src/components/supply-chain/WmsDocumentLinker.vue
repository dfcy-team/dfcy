<script setup>
import { ref } from 'vue';
import { requestApi } from '../../api/request';
import { createIdempotencyKey } from '../../api/supplyChainV2';

const props = defineProps({ documentId: Number, editable: Boolean });
const emit = defineEmits(['updated']);
const opened = ref(false), search = ref(''), candidates = ref([]), selected = ref(null);
const preview = ref(null), reason = ref(''), error = ref(''), busy = ref(false);
let attempt = null;
let generation = 0;
function unwrap(response) {
  if (!response?.success) throw new Error(response?.message || '关联操作失败');
  return response.data;
}
const base = () => `/api/internal/supply-chain/v2/wms-inbound-documents/${props.documentId}/`;
async function loadCandidates() {
  const request = ++generation;
  busy.value = true;
  error.value = '';
  try {
    const data = unwrap(await requestApi({ method: 'get', url: base() + 'link-candidates/', params: { search: search.value } }));
    if (request === generation) candidates.value = data.items;
  } catch (e) {
    if (request === generation) error.value = e.message;
  } finally {
    if (request === generation) busy.value = false;
  }
}
async function show(id) {
  if (!props.editable) return;
  selected.value = null; preview.value = null; reason.value = ''; search.value = ''; attempt = null;
  opened.value = true;
  await loadCandidates();
}
async function select(id) {
  selected.value = id;
  preview.value = null;
  if (!id) return;
  const request = ++generation;
  busy.value = true; error.value = '';
  try {
    const data = unwrap(await requestApi({ method: 'get', url: base() + 'link-preview/', params: { inbound_id: id } }));
    if (request === generation) preview.value = data;
  } catch (e) {
    if (request === generation) error.value = e.message;
  } finally {
    if (request === generation) busy.value = false;
  }
}
async function mutate(path, body) {
  const signature = JSON.stringify([path, body]);
  if (attempt?.signature !== signature) attempt = { signature, key: createIdempotencyKey() };
  const data = unwrap(await requestApi({ method: 'post', url: base() + path, data: body,
    headers: { 'Idempotency-Key': attempt.key } }));
  attempt = null;
  return data;
}
async function save() {
  if (!preview.value || busy.value || !reason.value.trim()) return;
  busy.value = true; error.value = '';
  try {
    await mutate('links/', { inbound_id: selected.value, expected_version: preview.value.version,
      preview_token: preview.value.preview_token, reason: reason.value.trim() });
    opened.value = false;
    emit('updated');
  } catch (e) { error.value = e.message; }
  finally { busy.value = false; }
}
defineExpose({ show });
</script>

<template>
  <el-button v-if="editable" link type="primary" @click="show">关联入库单</el-button>
  <el-dialog v-model="opened" title="关联本系统入库单" append-to-body width="min(900px, 96vw)">
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <div class="link-search">
      <el-input v-model="search" placeholder="本系统入库单号 / 批次" @keyup.enter="loadCandidates"/>
      <el-button :loading="busy" @click="loadCandidates">查询</el-button>
    </div>
    <el-select :model-value="selected" filterable clearable placeholder="选择同国家、同仓库已确认的入库单"
      :disabled="busy" @change="select" style="width:100%">
      <el-option v-for="doc in candidates" :key="doc.id" :value="doc.id" :label="`${doc.number} · ${doc.batch_number} · 实收 ${doc.received_quantity} 件`"/>
    </el-select>
    <template v-if="preview">
      <p>关联后可双向查看单据。数量差异保留为待核对，可继续按 SKU 分配对账数量。</p>
      <el-table :data="preview.rows" border max-height="360">
        <el-table-column prop="sku" label="SKU" min-width="160"/>
        <el-table-column prop="legacy_sku_code" label="旧 SKU" min-width="140"/>
        <el-table-column prop="wms_quantity" label="三方仓实收" width="110"/>
        <el-table-column prop="local_quantity" label="本系统实收" width="110"/>
        <el-table-column prop="difference" label="差异" width="90"/>
      </el-table>
      <el-input v-model="reason" type="textarea" maxlength="10000" placeholder="填写补录关联说明" style="margin-top:12px"/>
    </template>
    <template #footer>
      <el-button :disabled="busy" @click="opened=false">取消</el-button>
      <el-button type="primary" :disabled="busy || !preview || !reason.trim()" @click="save">确认关联</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.link-search { display:flex; gap:10px; margin-bottom:12px; }
</style>
