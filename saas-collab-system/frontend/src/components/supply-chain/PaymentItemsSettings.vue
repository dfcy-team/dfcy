<template>
 <section>
  <div class="heading"><h2>付款项目档案</h2><div><el-button v-if="!items.length" :disabled="!canManage" :loading="initializing" @click="initialize">初始化默认项目</el-button><el-button :disabled="!canManage" @click="open()">新增项目</el-button></div></div>
  <el-alert title="默认性质与税点供新费用分项引用，单据可手动调整；历史快照不随档案修改。海运正报对公费用按含税金额拆分税额，不重复加税。" type="info" :closable="false" />
  <el-table :data="items" v-loading="loading" row-key="id" border>
   <el-table-column prop="name" label="项目名称"/><el-table-column label="适用对象"><template #default="s">{{party[s.row.party_type]}}</template></el-table-column>
   <el-table-column label="默认性质"><template #default="s">{{nature[s.row.default_nature]}}</template></el-table-column><el-table-column label="默认税点 %"><template #default="s">{{s.row.default_tax_rate ?? '未维护'}}</template></el-table-column><el-table-column label="计入成本"><template #default="s">{{s.row.counts_as_cost?'是':'否'}}</template></el-table-column>
   <el-table-column label="默认分摊"><template #default="s">{{allocation[s.row.default_allocation]}}</template></el-table-column><el-table-column label="状态"><template #default="s">{{s.row.is_active?'启用':'停用'}}</template></el-table-column>
   <el-table-column label="操作"><template #default="s"><el-button link :disabled="!canManage" @click="open(s.row)">编辑</el-button><el-button v-if="s.row.is_active" link type="danger" :disabled="!canManage" @click="disable(s.row)">停用</el-button></template></el-table-column>
  </el-table>
  <el-dialog v-model="dialog" :title="form.id?'编辑付款项目':'新增付款项目'" width="min(520px,96vw)">
   <el-form label-position="top"><el-form-item label="项目名称"><el-input v-model="form.name" maxlength="100"/></el-form-item>
   <el-form-item label="适用对象"><el-select v-model="form.party_type"><el-option v-for="(v,k) in party" :key="k" :label="v" :value="k"/></el-select></el-form-item>
   <el-form-item label="默认性质"><el-select v-model="form.default_nature"><el-option v-for="(v,k) in nature" :key="k" :label="v" :value="k"/></el-select></el-form-item>
   <el-form-item label="默认对公税点 %（可留空，0表示不加税）"><el-input v-model="form.default_tax_rate" inputmode="decimal" placeholder="如6，不填写百分号"/></el-form-item><el-form-item label="计入成本"><el-switch v-model="form.counts_as_cost"/></el-form-item><el-form-item label="默认分摊"><el-select v-model="form.default_allocation"><el-option v-for="(v,k) in allocation" :key="k" :label="v" :value="k"/></el-select></el-form-item>
   <el-form-item label="启用"><el-switch v-model="form.is_active"/></el-form-item><el-form-item label="排序"><el-input-number v-model="form.sort_order" :min="0"/></el-form-item><el-form-item label="修改说明"><el-input v-model="form.reason" maxlength="300"/></el-form-item></el-form>
   <template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
  </el-dialog>
 </section>
</template>
<script setup>
import { onMounted, reactive, ref } from 'vue'; import { ElMessage } from 'element-plus'; import { fetchPaymentItems, initializePaymentItems, savePaymentItem } from '../../api/supplySettingsV2'; import { createIdempotencyKey } from '../../api/supplyChainV2';
const items=ref([]), loading=ref(false), saving=ref(false), initializing=ref(false), dialog=ref(false), canManage=ref(false);
const party={supplier:'供应商',carrier:'承运商',both:'供应商和承运商'}, nature={corporate:'对公',personal:'对私'}, allocation={volume:'体积',weight:'重量',mixed:'混合'};
const blank=()=>({id:null,version:0,name:'',party_type:'both',default_nature:'corporate',default_tax_rate:null,counts_as_cost:true,default_allocation:'volume',is_active:true,sort_order:0}); const form=reactive(blank()); let saveKey='', saveSignature='';
async function load(){loading.value=true;try{const r=await fetchPaymentItems();items.value=r.data.items;canManage.value=r.data.can_manage}catch(e){ElMessage.error(e.message||'付款项目加载失败')}finally{loading.value=false}}
async function initialize(){if(initializing.value)return;initializing.value=true;try{const r=await initializePaymentItems();if(!r?.success)throw Error(r?.message||'初始化失败');items.value=r.data.items;canManage.value=r.data.can_manage;ElMessage.success('默认付款项目已初始化')}catch(e){ElMessage.error(e.message||'初始化失败')}finally{initializing.value=false}}
function open(row){Object.keys(form).forEach(k=>delete form[k]);Object.assign(form,blank(),row||{});form.reason='';saveKey='';saveSignature='';dialog.value=true}
async function save(){if(saving.value)return;saving.value=true;try{const body={name:form.name,party_type:form.party_type,default_nature:form.default_nature,default_tax_rate:form.default_tax_rate===''?null:form.default_tax_rate,counts_as_cost:form.counts_as_cost,default_allocation:form.default_allocation,is_active:form.is_active,sort_order:form.sort_order,reason:form.reason,expected_version:form.version||0};const sig=JSON.stringify({id:form.id,body});if(sig!==saveSignature){saveSignature=sig;saveKey=createIdempotencyKey()}const r=await savePaymentItem(form.id,body,saveKey);if(!r?.success)throw Error(r?.message||'保存失败');dialog.value=false;await load()}catch(e){ElMessage.error(e.message||'保存失败')}finally{saving.value=false}}
function disable(row){open({...row,is_active:false})}
onMounted(load);
</script>
<style scoped>.heading{display:flex;align-items:center;justify-content:space-between;margin:18px 0}.heading h2{font-size:18px}</style>
