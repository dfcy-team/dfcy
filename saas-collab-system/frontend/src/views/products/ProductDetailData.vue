<template>
  <section>
    <div class="page-head"><div><h1>商品明细数据</h1><p>直接查看 SKU 明细，并将旧商品转换为新的编码体系。</p></div>
      <div><el-button @click="downloadTemplate">下载导入模板</el-button><el-button v-if="canManage" type="primary" @click="$refs.file.click()">导入旧商品</el-button><input ref="file" hidden type="file" accept=".csv,text/csv" @change="importFile"></div>
    </div>
    <el-alert v-if="message" :title="message" :type="messageType" show-icon closable @close="message=''" />
    <el-table :data="rows" v-loading="loading" border style="margin-top:16px">
      <el-table-column prop="legacy_spu_code" label="旧 SPU 编码" min-width="130" />
      <el-table-column prop="legacy_sku_code" label="旧 SKU 编码" min-width="150" />
      <el-table-column prop="spu_code" label="新 SPU 编码" min-width="130" />
      <el-table-column prop="sku_code" label="新 SKU 编码" min-width="210" />
      <el-table-column prop="product_name" label="商品名称" min-width="180" />
      <el-table-column prop="category_name" label="分类" min-width="110" />
      <el-table-column prop="color_code" label="颜色" min-width="100" />
      <el-table-column prop="specification" label="规格" min-width="150" />
      <el-table-column prop="status_name" label="状态" width="100" />
      <el-table-column label="操作" width="120"><template #default="{row}"><el-button v-if="row.row_type==='legacy'&&row.status!=='generated'&&canManage" link type="primary" @click="edit(row)">调整并生成</el-button></template></el-table-column>
    </el-table>
    <el-dialog v-model="visible" title="调整旧商品并生成新编码" width="600px">
      <el-form label-position="top">
        <el-form-item label="商品名称"><el-input v-model="form.product_name" /></el-form-item>
        <el-form-item label="末级分类"><el-select v-model="form.category_node" filterable style="width:100%"><el-option v-for="x in leaves" :key="x.id" :label="`${x.code} ${x.name}`" :value="x.id" /></el-select></el-form-item>
        <el-form-item label="属性字段（选填，未填自动补 0）"><el-select v-model="form.attribute_code" clearable style="width:100%"><el-option v-for="x in attributes" :key="x.id" :label="`${x.code} ${x.name}`" :value="x.code" /></el-select></el-form-item>
        <el-form-item label="颜色"><el-select v-model="form.color_code" filterable style="width:100%"><el-option v-for="x in colors.filter(v=>v.is_active)" :key="x.id" :label="`${x.code} ${x.name}`" :value="x.code" /></el-select></el-form-item>
        <el-form-item label="规格"><el-select v-if="specOptions.length" v-model="form.specification" filterable allow-create style="width:100%"><el-option v-for="x in specOptions" :key="x" :label="x" :value="x" /></el-select><el-input v-else v-model="form.specification" placeholder="例如 150cm×220cm" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="visible=false">取消</el-button><el-button type="primary" :loading="saving" @click="saveGenerate">生成新编码</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import {computed,onMounted,reactive,ref} from 'vue';
import {useAuthStore} from '../../stores/auth';
import {fetchProductMasterList,fetchProductSkuList,fetchLegacyProductItems,importLegacyProductItems,updateLegacyProductItem,generateLegacyProductItem,fetchProductCategories,fetchProductColors,fetchProductAttributes} from '../../api/products';
import {collectionRows} from '../../utils/businessResponse';
const auth=useAuthStore(),canManage=computed(()=>auth.hasPermission('products.master.manage'));const loading=ref(false),saving=ref(false),message=ref(''),messageType=ref('success'),rows=ref([]),categories=ref([]),colors=ref([]),attributes=ref([]),visible=ref(false);const form=reactive({id:null,product_name:'',category_node:null,attribute_code:'',color_code:'',specification:''});
const leaves=computed(()=>categories.value.filter(x=>x.level===3&&x.is_active));const selectedCategory=computed(()=>categories.value.find(x=>x.id===form.category_node));const specOptions=computed(()=>selectedCategory.value?.spec_dimensions?.[0]?.values||[]);
async function load(){loading.value=true;const[s,k,l,c,o,a]=await Promise.all([fetchProductMasterList({page_size:1000}),fetchProductSkuList({page_size:1000}),fetchLegacyProductItems(),fetchProductCategories(),fetchProductColors(),fetchProductAttributes()]);categories.value=collectionRows(c.data);colors.value=collectionRows(o.data);attributes.value=collectionRows(a.data);const spus=collectionRows(s.data),spuMap=new Map(spus.map(x=>[x.id,x]));const skuRows=collectionRows(k.data).map(x=>{const p=spuMap.get(x.spu)||{};return{row_type:'sku',legacy_spu_code:p.legacy_spu_code||'',legacy_sku_code:x.legacy_sku_code||'',spu_code:p.spu_code,sku_code:x.sku_code,product_name:p.product_name,category_name:p.category,color_code:x.color_code,specification:x.specification,status_name:'已生成'}});const legacy=collectionRows(l.data).filter(x=>x.status!=='generated').map(x=>({...x,row_type:'legacy',spu_code:'-',sku_code:'-',status_name:x.status==='error'?'生成失败':'待转换'}));rows.value=[...legacy,...skuRows];loading.value=false}
function edit(x){Object.assign(form,{id:x.id,product_name:x.product_name,category_node:x.category_node,attribute_code:x.attribute_code==='0'?'':x.attribute_code,color_code:x.color_code,specification:x.specification});visible.value=true}
async function saveGenerate(){if(!form.category_node||!form.color_code)return show('请选择末级分类和颜色','warning');saving.value=true;const u=await updateLegacyProductItem(form.id,{product_name:form.product_name,category_node:form.category_node,attribute_code:form.attribute_code||'0',color_code:form.color_code,specification:form.specification||'0'});if(u.success){const g=await generateLegacyProductItem(form.id);if(g.success){visible.value=false;show('新 SPU/SKU 编码已生成');await load()}else show(g.message||'生成失败','error')}else show(u.message||'保存失败','error');saving.value=false}
async function importFile(e){const f=e.target.files?.[0];if(!f)return;const text=await f.text();const r=await importLegacyProductItems(text);e.target.value='';if(r.success){show('旧商品数据已导入，请逐条调整并生成新编码');await load()}else show(r.message||'导入失败','error')}
function downloadTemplate(){const csv='\ufeff旧SPU编码,旧SKU编码,商品名称,分类编码,属性码,颜色编码,规格\nOLD-SPU-001,OLD-SKU-001,示例商品,,,,\n';const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));a.download='旧商品导入模板.csv';a.click();URL.revokeObjectURL(a.href)}function show(v,t='success'){message.value=v;messageType.value=t}onMounted(load);
</script>
<style scoped>.page-head{display:flex;justify-content:space-between;align-items:flex-start}.page-head h1{margin:0 0 8px}.page-head p{margin:0;color:#64748b}</style>
