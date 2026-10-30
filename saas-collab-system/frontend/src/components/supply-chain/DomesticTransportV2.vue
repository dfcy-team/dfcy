<template>
  <section class="domestic-transport">
    <header><h3>国内运输 · 供应商至集货站</h3><router-link v-if="!supplier" to="/master-data/freight-companies">维护货运公司档案</router-link></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <div class="transport-fields">
      <el-form-item label="国内承运商"><el-select v-model="form.domestic_carrier_id" filterable remote clearable :remote-method="search" :loading="loading" :disabled="!editable||disabled||saving" placeholder="选择支持国内运输的公司" @visible-change="visible=>visible&&load()"><el-option v-for="c in options" :key="c.id" :value="c.id" :label="c.name"/><template #footer><el-button v-if="hasMore" link :disabled="loading" @click="load(true)">加载更多</el-button></template></el-select></el-form-item>
      <el-form-item label="国内运单号"><el-input v-model="form.domestic_tracking_number" :disabled="!editable||disabled||saving" maxlength="200" placeholder="填写供应商至集货站的运单号"/></el-form-item>
    </div>
    <p class="hint">与集货发运批次的货运公司分别记录。没有委托国内承运商时可留空；发生国内运费付款后，更换承运商需先冲销原付款。</p>
    <el-button v-if="editable" :disabled="disabled||saving||!dirty" :loading="saving" @click="save">保存国内运输信息</el-button>
    <p v-if="saved" class="saved">国内运输信息已保存。</p>
  </section>
</template>
<script setup>
import {computed,onUnmounted,reactive,ref,watch} from 'vue';
import * as api from '../../api/supplyShipmentsV2';
const props=defineProps({shipment:{type:Object,required:true},supplier:Boolean,editable:Boolean,disabled:Boolean});
const emit=defineEmits(['updated']);
const form=reactive({domestic_carrier_id:null,domestic_tracking_number:''}),rows=ref([]),loading=ref(false),saving=ref(false),error=ref(''),saved=ref(false),hasMore=ref(false);
let generation=0,documentGeneration=0,query='',page=0,loaded=false,timer=null,attempt=null;
const baseline=()=>({domestic_carrier_id:props.shipment.domestic_carrier_id||null,domestic_tracking_number:props.shipment.domestic_tracking_number||''});
const dirty=computed(()=>JSON.stringify(form)!==JSON.stringify(baseline()));
const options=computed(()=>{const list=[...rows.value];const id=props.shipment.domestic_carrier_id;if(id&&!list.some(r=>r.id===id))list.unshift({id,name:props.shipment.domestic_carrier_name||`已选承运商 ${id}`});return list;});
function unwrap(r){if(!r?.success)throw new Error(`${r?.message||'国内运输信息读取失败'}${r?.data?'：'+JSON.stringify(r.data):''}`);return r.data;}
async function load(more=false,force=false){if(loading.value&&!force)return;if(loaded&&!more&&!force)return;const token=++generation,id=props.shipment.id,supplier=props.supplier,next=more?page+1:1;loading.value=true;error.value='';try{const response=await api.fetchDomesticCarriers(id,supplier,{search:query,limit:20,offset:(next-1)*20});const result=unwrap(response);if(token!==generation)return;const values=Array.isArray(result)?result:result.results||result.items||[];rows.value=more?[...rows.value,...values.filter(v=>!rows.value.some(r=>r.id===v.id))]:values;page=next;hasMore.value=!!response.next||rows.value.length<Number(response.count??result.count??rows.value.length);loaded=true;}catch(e){if(token===generation)error.value=e.message;}finally{if(token===generation)loading.value=false;}}
function search(value){query=value;loaded=false;generation++;loading.value=false;clearTimeout(timer);timer=setTimeout(()=>load(false,true),250);}
async function save(){if(!props.editable||props.disabled||saving.value||!dirty.value)return;const id=props.shipment.id,supplier=props.supplier,token=documentGeneration;const body={...form,domestic_carrier_id:form.domestic_carrier_id||null,domestic_tracking_number:form.domestic_tracking_number.trim(),expected_version:props.shipment.version};const signature=JSON.stringify([id,supplier,body]);if(attempt?.signature!==signature)attempt={signature,key:api.createIdempotencyKey()};saving.value=true;saved.value=false;error.value='';try{const result=unwrap(await api.saveDomesticTransport(id,body,supplier,attempt.key));if(token!==documentGeneration)return;attempt=null;Object.assign(form,{domestic_carrier_id:result.domestic_carrier_id||null,domestic_tracking_number:result.domestic_tracking_number||''});emit('updated',result);saved.value=true;}catch(e){if(token===documentGeneration)error.value=e.message;}finally{if(token===documentGeneration)saving.value=false;}}
watch(()=>[props.shipment.id,props.supplier],()=>{generation++;documentGeneration++;saving.value=false;clearTimeout(timer);query='';page=0;loaded=false;loading.value=false;rows.value=[];error.value='';saved.value=false;attempt=null;Object.assign(form,baseline());},{immediate:true});
watch(()=>[props.shipment.domestic_carrier_id,props.shipment.domestic_tracking_number],()=>Object.assign(form,baseline()));
onUnmounted(()=>{generation++;documentGeneration++;clearTimeout(timer);});
defineExpose({load,search,save,form,rows,hasMore,error});
</script>
<style scoped>
.domestic-transport{margin:16px 0;padding:16px;border:1px solid #dce4ef;border-radius:6px}.domestic-transport header{display:flex;align-items:center;justify-content:space-between;gap:12px}.domestic-transport h3{margin:0 0 12px;font-size:15px}.domestic-transport a{font-size:13px;color:#2563eb}.transport-fields{display:grid;grid-template-columns:1fr 1fr;gap:16px}.transport-fields :deep(.el-select){width:100%}.hint{font-size:13px;line-height:1.6;color:#64748b}.saved{font-size:13px;color:#15803d}@media(max-width:640px){.transport-fields{grid-template-columns:1fr}.domestic-transport header{align-items:start;flex-direction:column}}
</style>
