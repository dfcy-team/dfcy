<template>
  <el-dialog :model-value="true" title="复制店内闪购 · 同店单个时段" fullscreen class="flash-copy-editor" :close-on-click-modal="false" @close="$emit('close')">
    <p>{{ activity.store_name }} · 来源 {{ activity.platform_id }} · {{ activity.timezone }}</p><el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <el-button v-if="!items.length" :loading="loading" @click="read">读取来源商品与时段</el-button>
    <template v-if="items.length"><div class="copy-tools"><el-button :disabled="loading || publishing || !slots.length" @click="chooseSlot">＋ 选择时间段</el-button><span>已选时间段：{{ target ? 1 : 0 }} / 1</span><span v-if="target">{{ slotLabel(target) }}</span></div><p>价格和库存保留来源值，可逐规格编辑；未启用规格默认不参加。购买限额按商品设置，0 为不限。</p><el-checkbox v-model="includeDisabled" @change="setParticipation">包含未启用规格</el-checkbox>
      <div class="copy-tools"><span>共 {{ items.length }} 条规格 · 本次参加 {{ items.filter(row => row.participate).length }} 条</span><el-input v-model="query" aria-label="搜索复制商品" placeholder="搜索产品名称 / 商品或规格编号" clearable/><el-button @click="bulkOpen = !bulkOpen">批量编辑</el-button><el-button @click="selectFiltered(true)">筛选结果全部参加</el-button><el-button @click="selectFiltered(false)">筛选结果全部取消</el-button></div>
      <div v-if="bulkOpen" class="copy-tools"><span>填写到筛选内参加规格</span><el-input v-model="bulk.price" aria-label="批量活动价" placeholder="活动价"/><el-input-number v-model="bulk.stock" aria-label="批量活动库存" :min="1" :max="999999" :precision="0" placeholder="活动库存"/><el-input-number v-model="bulk.purchase_limit" aria-label="批量限购" :min="0" :max="999999" :precision="0" placeholder="限购，0不限"/><el-button :disabled="loading || publishing" @click="applyBulk">应用</el-button></div>
      <el-table :data="tableRows" :span-method="groupSpan" :row-key="row => `${row.group ? 'group' : 'model'}:${row.item_id}:${row.model_id}`" border max-height="580">
        <el-table-column label="产品信息" min-width="280"><template #default="{row}"><div v-if="row.group" class="product-heading"><el-checkbox :model-value="groupIncluded(row.item_id)" :indeterminate="groupPartial(row.item_id)" :disabled="publishing" :aria-label="`整件商品参加 ${row.item_id}`" @update:model-value="value => selectGroup(row.item_id,value)"/><div><strong>{{ row.name || row.item_id }}</strong><small>商品 ID：{{ row.item_id }}</small></div></div><template v-else>{{ row.model_name || (row.model_id === '0' ? '单规格商品' : '规格名称未返回') }}<small>规格 ID：{{ row.model_id }}</small><small>{{ row.status === 1 ? '原活动已启用' : row.status === 0 || row.status === 2 ? '原活动未启用' : '状态未返回' }}</small></template></template></el-table-column>
        <el-table-column label="来源活动价" width="130"><template #default="{row}"><template v-if="!row.group">{{ row.source_price ?? '—' }}</template></template></el-table-column>
        <el-table-column label="来源活动库存" width="120"><template #default="{row}"><template v-if="!row.group">{{ row.source_stock ?? '—' }}</template></template></el-table-column>
        <el-table-column label="活动价" min-width="140"><template #default="{row}"><el-input v-if="!row.group" v-model="row.price" :disabled="!row.participate || publishing" aria-label="活动价" @input="preview = null"/></template></el-table-column>
        <el-table-column label="活动库存" min-width="170"><template #default="{row}"><el-input-number v-if="!row.group" v-model="row.stock" :disabled="!row.participate || publishing" :min="1" :max="999999" :precision="0" @change="preview = null"/></template></el-table-column>
        <el-table-column label="来源可用库存" width="130"><template #default="{row}"><template v-if="!row.group">{{ row.available_stock ?? '未返回' }}</template></template></el-table-column>
        <el-table-column label="商品购买限额" min-width="170"><template #default="{row}"><el-input-number v-if="!row.group" v-model="row.purchase_limit" :disabled="!row.participate || publishing" :min="0" :max="999999" :precision="0" @change="value => changeLimit(row, value)"/></template></el-table-column>
        <el-table-column label="参加本次" width="100" fixed="right"><template #default="{row}"><el-checkbox v-if="!row.group" v-model="row.participate" :disabled="publishing" :aria-label="`参加 ${row.item_id}/${row.model_id}`" @change="preview = null"/></template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" :page-size="50" :total="filtered.length" layout="total, prev, pager, next"/>
      <el-alert v-if="preview" :title="`预览完成：${preview.items.length} 个规格，尚未创建活动；到 ${flashTime(preview.expires_at)}（北京）有效。`" type="success" :closable="false"/>
    </template><template #footer><el-button @click="$emit('close')">取消</el-button><el-button :disabled="!items.length || !slotId" :loading="loading" @click="makePreview">预览</el-button><el-button type="primary" :disabled="!preview || loading" :loading="publishing" @click="publish">确认发布</el-button></template>
  </el-dialog>
  <el-dialog v-model="slotOpen" title="选择时间段" width="680px" class="flash-dialog" append-to-body :close-on-click-modal="false"><div class="copy-tools"><el-input v-model="slotDate" type="date" aria-label="筛选时段日期"/><el-button @click="slotDate = ''">全部日期</el-button><span>{{ activity.timezone }} · 每次选择 1 个时段</span></div><el-radio-group v-model="slotDraft" class="slot-options"><el-radio v-for="slot in visibleSlots" :key="slot.timeslot_id" :value="String(slot.timeslot_id)">{{ slotLabel(slot) }}</el-radio></el-radio-group><p v-if="!visibleSlots.length">该日期没有可用时段</p><template #footer><el-button @click="slotOpen = false">取消选择</el-button><el-button type="primary" :disabled="!slots.some(slot => String(slot.timeslot_id) === slotDraft)" @click="confirmSlot">确定时段</el-button></template></el-dialog>
</template>
<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { flashRequest, flashTime, copyRows, copyPayload } from '../../api/flashSales';
const props = defineProps({activity:{type:Object,required:true}}), emit = defineEmits(['close','submitted']);
const items = ref([]), slots = ref([]), slotId = ref(''), includeDisabled = ref(false), preview = ref(null), loading = ref(false), publishing = ref(false), error = ref('');
const query = ref(''), page = ref(1), bulkOpen = ref(false), bulk = reactive({price:'',stock:undefined,purchase_limit:undefined});
const filtered = computed(() => items.value.filter(row => [row.name,row.model_name,row.item_id,row.model_id].join(' ').toLowerCase().includes(query.value.trim().toLowerCase())));
const paged = computed(() => filtered.value.slice((page.value - 1) * 50,page.value * 50));
const tableRows = computed(() => {const rows = [];let itemId;for (const row of paged.value) {if (itemId !== row.item_id) {rows.push({group:true,item_id:row.item_id,name:row.name});itemId = row.item_id;}rows.push(row);}return rows;});
function groupSpan({row,columnIndex}) {return row.group ? columnIndex === 0 ? [1,8] : [0,0] : [1,1];}
function groupIncluded(itemId) {return filtered.value.filter(row => row.item_id === itemId).every(row => row.participate);}
function groupPartial(itemId) {return !groupIncluded(itemId) && filtered.value.some(row => row.item_id === itemId && row.participate);}
function selectGroup(itemId,value) {for (const row of filtered.value) if (row.item_id === itemId) row.participate = value;}
const slotOpen = ref(false), slotDraft = ref(''), slotDate = ref('');
const target = computed(() => slots.value.find(slot => String(slot.timeslot_id) === slotId.value));
const visibleSlots = computed(() => slots.value.filter(slot => !slotDate.value || localSlotDate(slot) === slotDate.value));
function localSlotDate(slot) {const date = new Date(typeof slot.start_time === 'number' ? slot.start_time * 1000 : slot.start_time);try {const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:props.activity.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date).map(part => [part.type,part.value]));return `${parts.year}-${parts.month}-${parts.day}`;} catch {return '';}}
function slotLabel(slot) {return `${flashTime(slot.start_time,props.activity.timezone)} 至 ${flashTime(slot.end_time,props.activity.timezone)}`;}
function chooseSlot() {slotDraft.value = slotId.value;slotDate.value = '';slotOpen.value = true;}
function confirmSlot() {slotId.value = slotDraft.value;slotOpen.value = false;}
watch(query,() => {page.value = 1;});
watch([items,slotId],() => {preview.value = null;},{deep:true,flush:'sync'});
let requestId = null;
const message = e => e?.response?.data?.message || e?.message || '操作未完成';
async function read() {loading.value = true;error.value = '';try {const result = await flashRequest(`activities/${props.activity.id}/source/`); items.value = copyRows(result.items).map(row => ({...row,source_price:row.price,source_stock:row.stock}));slots.value = result.slots;} catch(e) {error.value = message(e);} finally {loading.value = false;}}
function selectFiltered(value) {for (const row of filtered.value) row.participate = value;}
function applyBulk() {for (const row of filtered.value.filter(row => row.participate)) {if (bulk.price.trim()) row.price = bulk.price.trim();if (bulk.stock != null) row.stock = bulk.stock;if (bulk.purchase_limit != null) changeLimit(row,bulk.purchase_limit);}}
function setParticipation(value) {for (const row of items.value) if (row.status !== 1) row.participate = value;preview.value = null;}
function changeLimit(row,value) {for (const item of items.value) if (item.item_id === row.item_id) item.purchase_limit = value;preview.value = null;}
async function makePreview() {loading.value = true;error.value = '';preview.value = null;try {const body = {store_id:props.activity.store_id,source_id:props.activity.platform_id,slot_id:slotId.value,items:copyPayload(items.value)};const signature = JSON.stringify(body);const result = await flashRequest('previews/','post',body);if (signature !== JSON.stringify({...body,slot_id:slotId.value,items:copyPayload(items.value)})) throw new Error('配置已变化，请重新生成预览');preview.value = result;requestId = crypto.randomUUID();} catch(e) {error.value = message(e);} finally {loading.value = false;}}
async function publish() {if (!preview.value || publishing.value) return;publishing.value = true;try {const result = await flashRequest('batches/','post',{request_id:requestId,operation:'copy',store_ids:[props.activity.store_id],preview_id:preview.value.id});emit('submitted',result.id);} catch(e) {error.value = message(e);} finally {publishing.value = false;}}
onMounted(read);
</script>
<style scoped>
small {display:block;color:var(--el-text-color-secondary)} .el-select {width:100%} .el-table,.el-alert {margin-top:14px} p {line-height:1.6}.copy-tools {display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:16px 0}.copy-tools .el-input {width:240px}.el-pagination {margin-top:16px}
.product-heading {display:flex;align-items:center;gap:12px}.slot-options {display:flex;flex-direction:column;align-items:flex-start;max-height:420px;overflow:auto;width:100%}.slot-options :deep(.el-radio) {height:auto;min-height:32px;margin:4px 0}.slot-options :deep(.el-radio__label) {white-space:normal;line-height:1.6}
</style>
