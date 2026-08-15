<template>
  <section>
    <div class="page-head"><div><h1>平台商品明细数据</h1><p>按平台与店铺维护商品/变种，旧 SKU 编码用于关联内部 SKU。</p></div><div><el-button @click="$refs.file.click()">导入 CSV/XLSX</el-button><input ref="file" hidden type="file" accept=".csv,.xlsx" @change="onImport" /></div></div>
    <el-alert v-if="message" :title="message" :type="messageType" show-icon closable @close="message=''" />
    <el-form inline class="filters" @submit.prevent="load"><el-input v-model="filters.search" placeholder="标题/平台SKU" clearable /><el-input v-model="filters.sales_status" placeholder="销售状态" clearable /><el-button type="primary" @click="load">筛选</el-button></el-form>
    <el-table :data="rows" v-loading="loading" border><el-table-column prop="platform_name" label="平台"/><el-table-column prop="site_name" label="站点"/><el-table-column prop="store_name" label="店铺"/><el-table-column prop="platform_product_id" label="平台商品ID"/><el-table-column prop="platform_variant_id" label="变种ID"/><el-table-column prop="platform_sku" label="平台SKU"/><el-table-column prop="source_old_sku_code" label="旧SKU编码"/><el-table-column prop="internal_sku_code" label="新SKU"/><el-table-column prop="title" label="标题" min-width="180"/><el-table-column prop="variant" label="变种"/><el-table-column prop="sales_status" label="状态"/><el-table-column prop="owner" label="负责人"/><el-table-column prop="leader" label="组长"/></el-table>
    <el-dialog v-model="importDialog" title="导入结果" width="640px"><pre class="result">{{ JSON.stringify(importResult, null, 2) }}</pre><template #footer><el-button @click="importDialog=false">关闭</el-button></template></el-dialog>
  </section>
</template>
<script setup>
import { onMounted, reactive, ref } from 'vue';
import { fetchPlatformProductDetails, importPlatformProductDetails } from '../../api/platformProductDetails';
const rows=ref([]),loading=ref(false),message=ref(''),messageType=ref('success'),importDialog=ref(false),importResult=ref(null); const filters=reactive({search:'',sales_status:''});
async function load(){loading.value=true;const response=await fetchPlatformProductDetails(filters);rows.value=response?.data?.results||[];loading.value=false;if(response?.success===false){message.value=response.message;messageType.value='error'}}
async function onImport(event){const file=event.target.files?.[0];event.target.value='';if(!file)return;const response=await importPlatformProductDetails(file,{dryRun:false});importResult.value=response?.data||response;importDialog.value=true;if(response?.success){message.value='导入完成';await load()}else{message.value=response?.message||'导入失败';messageType.value='error'}}
onMounted(load);
</script>
<style scoped>.page-head{display:flex;justify-content:space-between;align-items:flex-start}.page-head h1{margin:0 0 8px}.page-head p{margin:0;color:#64748b}.filters{margin:18px 0}.filters .el-input{width:220px;margin-right:10px}.result{max-height:420px;overflow:auto;white-space:pre-wrap}</style>
