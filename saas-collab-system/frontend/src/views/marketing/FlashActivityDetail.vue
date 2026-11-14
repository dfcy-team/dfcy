<template>
  <el-drawer :model-value="true" title="活动商品及规格" size="1180px" class="flash-detail" @close="$emit('close')">
    <div class="detail-context"><el-tag>{{ activity.store_name }}</el-tag><span>活动 {{ activity.platform_id }}</span><el-button :loading="loading" @click="read">刷新详情</el-button></div>
    <p>{{ flashTime(activity.starts_at, activity.timezone) }} 至 {{ flashTime(activity.ends_at, activity.timezone) }} · {{ activity.timezone }}</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <template v-if="detail">
      <p>最近同步：{{ flashTime(detail.details_synced_at) }}（北京时间）</p>
      <el-alert v-if="!detail.details_synced_at" title="商品详情尚未同步，请选择此活动后同步。" type="info" :closable="false"/>
      <div class="detail-summary"><span>商品 <b>{{ products.length }}</b></span><span>规格 / 单规格商品 <b>{{ rows.length }}</b></span><span v-for="(label,key) in states" :key="key">{{ label }} <b>{{ rows.filter(row => state(row) === key).length }}</b></span></div>
      <div class="detail-filters"><el-input v-model="query" aria-label="搜索商品或规格" placeholder="搜索商品名称、规格或编号" clearable/><el-select v-model="productId" aria-label="筛选商品" filterable><el-option label="全部商品" value=""/><el-option v-for="product in products" :key="product.item_id" :value="product.item_id" :label="product.name || product.item_id"/></el-select><el-select v-model="status" aria-label="筛选启用状态"><el-option label="全部状态" value=""/><el-option v-for="(label,key) in states" :key="key" :value="key" :label="label"/></el-select></div>
      <p>共 {{ filtered.length }} 条匹配 · “—”表示平台未返回</p>
      <el-table :data="paged" :span-method="groupSpan" border stripe max-height="580" empty-text="没有匹配的商品或规格，请调整筛选条件">
        <el-table-column label="商品" min-width="220"><template #default="{row}"><img v-if="typeof row.image === 'string' && row.image.startsWith('https://') && !imageErrors.has(row.item_id)" :src="row.image" :alt="row.name || '商品图片'" loading="lazy" referrerpolicy="no-referrer" class="product-thumb" @error="imageErrors.add(row.item_id)"/>{{ row.name || '商品名称未返回' }}<small>ID {{ row.item_id }}</small></template></el-table-column>
        <el-table-column label="规格" min-width="175"><template #default="{row}">{{ row.model_name || (String(row.model_id) === '0' ? '单规格商品' : '规格名称未返回') }}<small>ID {{ row.model_id }}</small></template></el-table-column>
        <el-table-column label="活动价" width="110"><template #default="{row}"><strong>{{ value(row.price) }}</strong><small>原价 {{ value(row.original_price) }}</small></template></el-table-column>
        <el-table-column label="活动库存" width="100"><template #default="{row}">{{ value(row.stock) }}</template></el-table-column>
        <el-table-column label="可用库存" width="100"><template #default="{row}">{{ value(row.available_stock) }}</template></el-table-column>
        <el-table-column label="限购" width="100"><template #default="{row}">{{ row.purchase_limit === 0 ? '不限购' : value(row.purchase_limit) }}</template></el-table-column>
        <el-table-column label="状态 / 平台原因" min-width="185"><template #default="{row}"><el-tag :type="state(row) === 'enabled' ? 'success' : 'info'">{{ states[state(row)] }}</el-tag><small>{{ row.reject_reason }}</small></template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" v-model:page-size="size" :page-sizes="[25,50,100]" :total="filtered.length" layout="prev, pager, next, sizes, total"/>
    </template>
  </el-drawer>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { flashRequest, flashTime } from '../../api/flashSales';
const props = defineProps({activity:{type:Object,required:true}});
defineEmits(['close']);
const detail = ref(null), loading = ref(false), error = ref('');
const imageErrors = ref(new Set());
const query = ref(''), productId = ref(''), status = ref(''), page = ref(1), size = ref(50);
const states = {enabled:'已启用',disabled:'未启用',unknown:'状态未返回'};
const state = row => row.status === 1 ? 'enabled' : row.status === 0 || row.status === 2 ? 'disabled' : 'unknown';
const value = input => input === null || input === undefined || input === '' ? '—' : input;
const rows = computed(() => detail.value?.items || []);
const products = computed(() => [...new Map(rows.value.map(row => [row.item_id,row])).values()]);
const filtered = computed(() => rows.value.filter(row => (!productId.value || row.item_id === productId.value) && (!status.value || state(row) === status.value) && [row.name,row.model_name,row.item_id,row.model_id].join(' ').toLowerCase().includes(query.value.trim().toLowerCase())));
const paged = computed(() => filtered.value.slice((page.value - 1) * size.value,page.value * size.value));
function groupSpan({row,columnIndex,rowIndex}) {if (columnIndex !== 0) return [1,1];if (rowIndex > 0 && paged.value[rowIndex - 1].item_id === row.item_id) return [0,0];let count = 1;while (paged.value[rowIndex + count]?.item_id === row.item_id) count++;return [count,1];}
watch([query,productId,status,size],() => {page.value = 1;});
let sequence = 0;
async function read() {const seq = ++sequence;loading.value = true;error.value = '';try {const result = await flashRequest(`activities/${props.activity.id}/`);if (seq === sequence) {detail.value = result;imageErrors.value = new Set();}} catch(e) {if (seq === sequence) error.value = e?.response?.data?.message || e?.message || '读取未完成';} finally {if (seq === sequence) loading.value = false;}}
watch(() => props.activity.id,() => {detail.value = null;query.value = '';productId.value = '';status.value = '';page.value = 1;read();},{immediate:true});
onBeforeUnmount(() => {sequence++;});
</script>
<style scoped>
.detail-context,.detail-summary,.detail-filters {display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:16px}.detail-filters > * {width:220px} small {display:block;color:var(--el-text-color-secondary);margin-top:4px;overflow-wrap:anywhere}.el-pagination {margin-top:16px;flex-wrap:wrap}:deep(.el-pagination .el-select) {width:110px}
.product-thumb {width:56px;height:56px;object-fit:contain;float:left;margin:0 12px 8px 0;border-radius:4px}
</style>
<style>.flash-detail {max-width:100vw}.flash-detail .el-drawer__body {overflow:auto}</style>
