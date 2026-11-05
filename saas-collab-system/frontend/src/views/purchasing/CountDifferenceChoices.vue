<template>
  <main class="page">
    <header><div><h1>清点超发差额</h1><p>记录差额处置选择。选择不会直接创建付款或库存流水。</p></div><el-button :loading="loading" @click="load">刷新</el-button></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-table :data="rows" v-loading="loading" stripe>
      <el-table-column prop="source_purchase" label="源采购单" min-width="145"/>
      <el-table-column prop="purchase_number" label="系统采购单" min-width="160"/>
      <el-table-column prop="supplier" label="供应商" min-width="100"/>
      <el-table-column prop="source_shipment" label="源发货单" min-width="145"/>
      <el-table-column prop="shipment_number" label="系统发货单" min-width="160"/>
      <el-table-column label="清点差额" min-width="130" align="right"><template #default="{row}">{{ money(row.difference_amount) }}</template></el-table-column>
      <el-table-column label="处置选择" min-width="180"><template #default="{row}"><el-select v-model="row.option" @change="save(row)"><el-option label="继续待核" value="pending_review"/><el-option label="补付供应商" value="supplement_supplier"/><el-option label="供应商免收" value="supplier_waived"/><el-option label="退回商品" value="return_goods"/></el-select></template></el-table-column>
      <el-table-column label="说明" min-width="220"><template #default="{row}"><el-input v-model="row.notes" @change="save(row)" placeholder="可填写处理依据"/></template></el-table-column>
    </el-table>
  </main>
</template>
<script setup>
import {onMounted,ref} from 'vue';
import {ElMessage} from 'element-plus';
import {fetchCountDifferenceChoices,saveCountDifferenceChoice} from '../../api/countDifferenceChoices';
const rows=ref([]),loading=ref(false),error=ref('');
const money=v=>Number(v||0).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:4});
const requestKey=()=>globalThis.crypto?.randomUUID?.()||String(Date.now())+'-'+Math.random();
async function load(){loading.value=true;error.value='';try{const r=await fetchCountDifferenceChoices();rows.value=(r.data?.data||r.data||[]).map(x=>({...x,option:x.option||'pending_review',notes:x.notes||''}));}catch(e){error.value=e?.response?.data?.detail||'清点差额加载失败。';}finally{loading.value=false;}}
async function save(row){try{const r=await saveCountDifferenceChoice({...row,expected_event_id:row.event_id},requestKey());Object.assign(row,r.data?.data||r.data||{});ElMessage.success('处置选择已保存。');}catch(e){error.value=e?.response?.data?.detail||'保存失败，请刷新重试。';await load();}}
onMounted(load);
</script>
<style scoped>
.page{padding:24px}header{display:flex;justify-content:space-between;margin-bottom:18px}h1{margin:0 0 8px;font-size:22px}p{margin:0;color:#64748b}
</style>
