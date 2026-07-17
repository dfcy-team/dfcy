<template>
  <section class="business-page">
    <header class="page-header">
      <div><p class="eyebrow">UI-P5 · 商品主链路</p><h1 class="page-title">新品市调</h1><p>按后端 tenant 与 data_scope 返回可见市调记录。</p></div>
      <el-tag :type="stateTagType(state)">{{ state }}</el-tag>
    </header>
    <el-form class="filters" inline @submit.prevent="search">
      <el-form-item label="商品名称"><el-input v-model="filters.search" clearable placeholder="输入商品名称" /></el-form-item>
      <el-form-item label="平台"><el-input v-model="filters.platform" clearable placeholder="平台编码" /></el-form-item>
      <el-form-item><el-button type="primary" @click="search">查询</el-button><el-button @click="reset">重置</el-button></el-form-item>
    </el-form>
    <el-alert v-if="message" :title="message" :type="state === 'error' ? 'error' : 'warning'" show-icon :closable="false" />
    <el-table v-loading="loading" :data="rows" border empty-text="当前范围暂无市调数据">
      <el-table-column prop="research_no" label="市调编号" min-width="150" />
      <el-table-column prop="product_name" label="商品名称" min-width="180" />
      <el-table-column prop="platform" label="平台" min-width="120" />
      <el-table-column prop="estimated_sales" label="预估销量" min-width="110" />
      <el-table-column prop="estimated_gross_margin" label="预估毛利" min-width="110" />
      <el-table-column label="风险点" min-width="180"><template #default="{ row }">{{ formatList(row.risk_points) }}</template></el-table-column>
      <el-table-column prop="approval_status" label="审批状态" min-width="110" />
      <el-table-column label="操作" width="90"><template #default="{ row }"><router-link :to="`/products/research/${row.id}`">查看</router-link></template></el-table-column>
    </el-table>
    <footer class="pager"><span>共 {{ total }} 条</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" layout="prev, pager, next" :total="total" @current-change="load" /></footer>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { fetchResearchList } from '../../api/products';
import { apiState, collectionRows, collectionTotal, stateTagType } from '../../utils/businessResponse';

const filters = reactive({ search: '', platform: '' });
const rows = ref([]); const total = ref(0); const page = ref(1); const pageSize = ref(20);
const loading = ref(false); const state = ref('loading'); const message = ref('');
function formatList(value) { return Array.isArray(value) ? value.join('、') : value || '-'; }
async function load() {
  loading.value = true; message.value = '';
  const response = await fetchResearchList({ ...filters, page: page.value, page_size: pageSize.value });
  if (response.success) { rows.value = collectionRows(response.data); total.value = collectionTotal(response.data); state.value = apiState(response.data); }
  else { rows.value = []; total.value = 0; state.value = 'error'; message.value = response.message; }
  loading.value = false;
}
function search() { page.value = 1; load(); }
function reset() { filters.search = ''; filters.platform = ''; search(); }
onMounted(load);
</script>

<style scoped>
.business-page { display: grid; gap: 16px; }.page-header,.pager { display:flex;align-items:center;justify-content:space-between;gap:16px }.page-header p { margin:4px 0 0;color:#64748b }.eyebrow { font-size:12px;font-weight:700;color:#0f766e!important }.filters { padding:12px;border:1px solid #d9e2ec;border-radius:8px;background:#fff }.pager { color:#64748b;font-size:13px }
</style>
