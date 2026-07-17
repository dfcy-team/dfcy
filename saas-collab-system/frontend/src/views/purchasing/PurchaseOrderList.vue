<template>
  <section class="business-page">
    <header class="page-header"><div><p class="eyebrow">UI-P5 · 采购主链路</p><h1 class="page-title">采购订单</h1><p>只展示后端 tenant 与 data_scope 授权范围；不自动采购。</p></div><el-tag :type="stateTagType(state)">{{ state }}</el-tag></header>
    <el-form class="filters" inline @submit.prevent="search"><el-form-item label="采购单号"><el-input v-model="filters.search" clearable /></el-form-item><el-form-item label="状态"><el-select v-model="filters.status" clearable style="width:150px"><el-option label="草稿" value="draft"/><el-option label="已确认" value="confirmed"/><el-option label="生产中" value="in_production"/><el-option label="已出货" value="shipped"/></el-select></el-form-item><el-form-item><el-button type="primary" @click="search">查询</el-button><el-button @click="reset">重置</el-button></el-form-item></el-form>
    <el-alert v-if="message" :title="message" :type="state === 'error' ? 'error' : 'warning'" show-icon :closable="false" />
    <el-table v-loading="loading" :data="rows" border empty-text="当前范围暂无采购订单">
      <el-table-column prop="po_no" label="采购单号" min-width="150"/><el-table-column prop="sku_code" label="SKU" min-width="140"/><el-table-column prop="supplier_id" label="供应商ID" min-width="110"/><el-table-column prop="quantity" label="数量" min-width="90"/><el-table-column prop="unit_price" label="单价" min-width="100"/><el-table-column prop="delivery_date" label="交期" min-width="120"/><el-table-column prop="status" label="状态" min-width="110"/><el-table-column prop="approval_status" label="审批状态" min-width="110"/><el-table-column label="操作" width="90"><template #default="{ row }"><router-link :to="`/purchasing/orders/${row.id}`">查看</router-link></template></el-table-column>
    </el-table>
    <footer class="pager"><span>共 {{ total }} 条</span><el-pagination v-model:current-page="page" :page-size="pageSize" layout="prev, pager, next" :total="total" @current-change="load"/></footer>
  </section>
</template>
<script setup>
import { onMounted, reactive, ref } from 'vue'; import { fetchPurchaseOrders } from '../../api/purchasing'; import { apiState, collectionRows, collectionTotal, stateTagType } from '../../utils/businessResponse';
const filters=reactive({search:'',status:''}); const rows=ref([]),total=ref(0),page=ref(1),pageSize=ref(20),loading=ref(false),state=ref('loading'),message=ref('');
async function load(){loading.value=true;message.value='';const response=await fetchPurchaseOrders({...filters,page:page.value,page_size:pageSize.value});if(response.success){rows.value=collectionRows(response.data);total.value=collectionTotal(response.data);state.value=apiState(response.data)}else{rows.value=[];total.value=0;state.value='error';message.value=response.message}loading.value=false}
function search(){page.value=1;load()} function reset(){filters.search='';filters.status='';search()} onMounted(load);
</script>
<style scoped>.business-page{display:grid;gap:16px}.page-header,.pager{display:flex;align-items:center;justify-content:space-between;gap:16px}.page-header p{margin:4px 0 0;color:#64748b}.eyebrow{font-size:12px;font-weight:700;color:#0f766e!important}.filters{padding:12px;border:1px solid #d9e2ec;border-radius:8px;background:#fff}.pager{color:#64748b;font-size:13px}</style>
