<template>
<section class="monthly"><h1>库存成本台账</h1><p>按月加权；当月每日暂估，已核定月份固定。金额为人民币。</p>
<el-form inline @submit.prevent="load"><el-form-item label="月份"><el-date-picker v-model="month" type="month" value-format="YYYY-MM" :clearable="false" /></el-form-item><el-form-item label="仓库"><el-select v-model="warehouse" clearable style="width:240px"><el-option v-for="w in warehouses" :key="w.id" :value="w.id" :label="`${w.name}（${w.country_code}）`" /></el-select></el-form-item><el-button :loading="loading" @click="page=1;load()">查询</el-button><el-button @click="download">下载缺失成本商品</el-button></el-form>
<el-alert v-if="error" :title="error" type="error" :closable="false" />
<el-alert v-if="!loading&&!rows.length&&!error" title="尚无月度记录，请先核定期初并接入来源。" type="info" :closable="false" />
<el-alert v-if="!loading&&!error" type="info" :closable="false" :title="adjustmentText()" />
<el-table :data="rows" v-loading="loading" border><el-table-column v-for="c in columns" :key="c[0]" :prop="c[0]" :label="c[1]" min-width="130" /></el-table>
<el-pagination v-model:current-page="page" :total="total" :page-size="50" layout="prev,pager,next,total" @current-change="load" /><p>未知金额留空，不计作零成本。缺失导出仅包含授权范围。</p></section>
</template>
<script setup>
import {onMounted,ref} from 'vue';
import {requestApi} from '../../api/request';
const date=new Date(),month=ref(`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}`),warehouse=ref(),warehouses=ref([]),rows=ref([]),page=ref(1),total=ref(0),loading=ref(false),error=ref(''),adjustments=ref({});
const adjustmentText=()=>`历史调整（仓库范围汇总，不分摊至店铺）：已分配库存 ${adjustments.value.inventory_amount??'0'} 元，已售 ${adjustments.value.sold_amount??'0'} 元；待处理 ${adjustments.value.pending_count??0} 笔。`;
const columns=[['sku_code','商品编码'],['product_name','商品名称'],['warehouse_name','仓库'],['opening_quantity','月初数量'],['opening_amount','月初金额'],['receipt_quantity','入库数量'],['receipt_amount','入库金额'],['sales_cost_amount','当期销售成本'],['historical_sold_adjustment','历史已售成本调整'],['other_in_quantity','其他入库数量'],['other_in_amount','其他入库金额'],['other_out_quantity','其他出库数量'],['unit_cost','月加权单价'],['outbound_quantity','出库数量'],['closing_quantity','月末数量'],['closing_amount','月末金额'],['status_label','核定状态'],['payment_status','付款状态'],['reason','待处理原因']];
const params=()=>({month:month.value,warehouse_id:warehouse.value,page:page.value});
const read=async(url)=>{const r=await requestApi({method:'get',url:'/api/internal/products/costs/monthly/'+url,params:params(),noMockFallback:true});if(r?.success===false) throw new Error(r.message||"请求失败"); return r.data??r;};
async function load(){loading.value=true;error.value='';try{const d=await read('');rows.value=d.items??[];total.value=d.total??0;adjustments.value=d.historical_adjustments??{};}catch(e){rows.value=[];total.value=0;error.value=e.message||'读取失败';}finally{loading.value=false;}}
async function download(){try{const d=await read('missing/');const u=URL.createObjectURL(new Blob(['\ufeff'+d.csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=u;a.download=`缺失成本-${month.value}.csv`;a.click();URL.revokeObjectURL(u);}catch(e){error.value=e.message||'下载失败';}}
onMounted(async()=>{try{warehouses.value=await read('warehouses/');}catch(e){error.value=e.message;}await load();});
</script><style scoped>.monthly{padding:24px;background:white}.monthly p{color:#64748b}.el-pagination{margin-top:16px}</style>
