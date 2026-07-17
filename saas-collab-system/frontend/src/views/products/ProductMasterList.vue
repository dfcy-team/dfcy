<template>
  <section class="business-page">
    <header class="page-header"><div><p class="eyebrow">UI-P5 · 商品主数据</p><h1 class="page-title">商品主数据</h1><p>SPU 与 SKU 均由后端 tenant 和 data_scope 裁剪。</p></div><el-tag :type="stateTagType(state)">{{ state }}</el-tag></header>
    <el-form class="filters" inline @submit.prevent="search"><el-form-item label="名称/SPU"><el-input v-model="filters.search" clearable /></el-form-item><el-form-item label="销售状态"><el-select v-model="filters.sales_status" clearable style="width:150px"><el-option label="未刊登" value="not_listed"/><el-option label="销售中" value="on_sale"/><el-option label="暂停" value="paused"/><el-option label="停止" value="stopped"/></el-select></el-form-item><el-form-item><el-button type="primary" @click="search">查询</el-button><el-button @click="reset">重置</el-button></el-form-item></el-form>
    <el-alert v-if="message" :title="message" :type="state === 'error' ? 'error' : 'warning'" show-icon :closable="false" />
    <el-table v-loading="loading" :data="rows" border empty-text="当前范围暂无商品主数据">
      <el-table-column prop="spu_code" label="SPU" min-width="150"/><el-table-column prop="sku_codes" label="SKU" min-width="180" show-overflow-tooltip/><el-table-column prop="product_name" label="商品名称" min-width="180"/><el-table-column prop="category" label="类目" min-width="120"/><el-table-column prop="lifecycle_status" label="生命周期" min-width="120"/><el-table-column prop="sales_status" label="销售状态" min-width="110"/><el-table-column label="编码冻结" min-width="100"><template #default="{ row }">{{ row.is_code_frozen ? '已冻结' : '未冻结' }}</template></el-table-column><el-table-column label="操作" width="90"><template #default="{ row }"><router-link :to="`/products/master/${row.id}`">查看</router-link></template></el-table-column>
    </el-table>
    <footer class="pager"><span>共 {{ total }} 条</span><el-pagination v-model:current-page="page" :page-size="pageSize" layout="prev, pager, next" :total="total" @current-change="load"/></footer>
  </section>
</template>
<script setup>
import { onMounted, reactive, ref } from 'vue'; import { fetchProductMasterList, fetchProductSkuList } from '../../api/products'; import { apiState, collectionRows, collectionTotal, stateTagType } from '../../utils/businessResponse';
const filters=reactive({search:'',sales_status:''});const rows=ref([]),total=ref(0),page=ref(1),pageSize=ref(20),loading=ref(false),state=ref('loading'),message=ref('');
async function load(){loading.value=true;message.value='';const [spus,skus]=await Promise.all([fetchProductMasterList({...filters,page:page.value,page_size:pageSize.value}),fetchProductSkuList({page:1,page_size:100})]);if(spus.success&&skus.success){const skuRows=collectionRows(skus.data);rows.value=collectionRows(spus.data).map(spu=>({...spu,sku_codes:skuRows.filter(sku=>sku.spu===spu.id).map(sku=>sku.sku_code).join('、')||'-'}));total.value=collectionTotal(spus.data);state.value=apiState(spus.data)}else{rows.value=[];total.value=0;state.value='error';message.value=spus.message||skus.message}loading.value=false}
function search(){page.value=1;load()}function reset(){filters.search='';filters.sales_status='';search()}onMounted(load);
</script>
<style scoped>.business-page{display:grid;gap:16px}.page-header,.pager{display:flex;align-items:center;justify-content:space-between;gap:16px}.page-header p{margin:4px 0 0;color:#64748b}.eyebrow{font-size:12px;font-weight:700;color:#0f766e!important}.filters{padding:12px;border:1px solid #d9e2ec;border-radius:8px;background:#fff}.pager{color:#64748b;font-size:13px}</style>
