<template>
  <section class="sku-report" :aria-busy="loading" aria-label="产品销量信息">
    <div class="sku-toolbar">
      <div><h2>产品销量信息</h2><p>按现有 SKU 销售接口展示，门店与币种分别保留。搜索仅影响下方明细。</p></div>
      <form class="sku-search" @submit.prevent="search"><label for="overview-sku-search">SKU 编号</label><el-input id="overview-sku-search" v-model="draft" placeholder="输入 SKU，模糊搜索" clearable /><el-button native-type="submit" :loading="loading">搜索</el-button></form>
    </div>
    <div class="sku-options"><span>{{ total }} 条 · 金额按来源币种展示</span><details><summary>展示列</summary><div class="column-options"><label v-for="column in columns" :key="column.prop"><input v-model="visible" type="checkbox" :value="column.prop">{{ column.label }}</label></div></details></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-table v-loading="loading" :data="rows" stripe empty-text="当前筛选范围没有 SKU 销量记录，请调整日期或 SKU 搜索。">
      <el-table-column label="产品名称 / SKU" min-width="260"><template #default="{ row }"><div class="product-cell"><strong>{{ row.product_name || '商品名称未提供' }}</strong><span>平台 SKU：{{ row.seller_sku || '—' }}</span><span>内部 SKU：{{ row.internal_sku || '未关联' }}</span></div></template></el-table-column>
      <el-table-column v-for="column in shownColumns" :key="column.prop" :prop="column.prop" :label="column.label" :min-width="column.width || 130" :align="column.numeric ? 'right' : 'left'" show-overflow-tooltip><template #default="{ row }">{{ formatField(row[column.prop], column) }}</template></el-table-column>
    </el-table>
    <div class="sku-pagination"><label>每页 <select v-model.number="size" aria-label="SKU 明细每页条数" @change="search"><option :value="20">20 条</option><option :value="50">50 条</option><option :value="100">100 条</option></select></label><el-pagination v-model:current-page="page" :page-size="size" :total="total" layout="prev, pager, next, total" background @current-change="load" /></div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { fetchSalesPage } from '../../api/salesManagement';
import { formatApiError } from '../../api/request';
import { formatField } from './display';
const props = defineProps({ filters: { type: Object, required: true } });
const rows = ref([]), total = ref(0), page = ref(1), size = ref(20), draft = ref(''), term = ref(''), loading = ref(false), error = ref('');
const columns = [
  { prop: 'store_name', label: '门店', width: 180 }, { prop: 'platform', label: '平台', format: 'platform' },
  { prop: 'platform_product_id', label: '平台商品 ID', width: 170 }, { prop: 'platform_variant_id', label: '平台规格 ID', width: 170 },
  { prop: 'currency', label: '币种', width: 80 },
  ...[['gross_sales', '商品销售额'], ['net_sales', '商品净销售额'], ['refund_amount', '退款金额']].map(([prop, label]) => ({ prop, label, numeric: true, format: 'money' })),
  ...[['order_count', '订单数'], ['units_sold', '销售数量'], ['refund_units', '退款数量']].map(([prop, label]) => ({ prop, label, numeric: true })),
  { prop: 'mapping_status', label: 'SKU 关联', format: 'enum' }
];
const visible = ref(['store_name', 'platform_product_id', 'currency', 'gross_sales', 'order_count', 'units_sold', 'refund_amount']);
const shownColumns = computed(() => columns.filter(column => visible.value.includes(column.prop)));
let sequence = 0;
async function load() {
  const current = ++sequence;
  loading.value = true; error.value = ''; rows.value = []; total.value = 0;
  try {
    const response = await fetchSalesPage('skus', { ...props.filters, page: page.value, page_size: size.value, ...(term.value ? { sku: term.value } : {}) });
    if (current !== sequence) return;
    if (!response?.success) { error.value = formatApiError(response); return; }
    rows.value = response.data?.results || []; total.value = Number(response.data?.count || 0);
  } catch (exception) { if (current === sequence) error.value = formatApiError({ message: exception?.message }); }
  finally { if (current === sequence) loading.value = false; }
}
function search() { term.value = draft.value.trim(); page.value = 1; load(); }
watch(() => props.filters, () => { page.value = 1; load(); }, { immediate: true, deep: true });
onBeforeUnmount(() => { sequence++; });
</script>

<style scoped>
.sku-report { min-width: 0; padding: 18px; background: #fff; border: 1px solid #dce3ec; border-radius: 6px; }
.sku-toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 16px; }
.sku-toolbar h2 { margin: 0; font-size: 15px; }
.sku-toolbar p, .sku-options { color: #475569; font-size: 12px; line-height: 1.7; }
.sku-search { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; font-size: 12px; }
.sku-search :deep(.el-input) { width: 220px; }
.sku-options { display: flex; justify-content: space-between; gap: 16px; margin: 14px 0; }
.sku-options details { max-width: 70%; text-align: right; }
.sku-options summary { cursor: pointer; color: #513ab9; }
.column-options { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px 14px; padding: 12px 0; }
.column-options label { white-space: nowrap; }
.product-cell { display: grid; gap: 5px; padding: 7px 0; line-height: 1.6; }
.product-cell strong { font-weight: 500; color: #243c60; overflow-wrap: anywhere; }
.product-cell span { color: #475569; font-size: 12px; overflow-wrap: anywhere; }
.sku-pagination { display: flex; justify-content: flex-end; align-items: center; flex-wrap: wrap; gap: 14px; margin-top: 16px; font-size: 12px; }
.sku-pagination select { padding: 6px; border: 1px solid #cbd5e1; border-radius: 4px; background: #fff; color: #334155; }
@media (max-width: 600px) { .sku-report { padding: 12px; } .sku-options { flex-direction: column; } .sku-options details { max-width: 100%; text-align: left; } .sku-pagination { justify-content: flex-start; } }
</style>
