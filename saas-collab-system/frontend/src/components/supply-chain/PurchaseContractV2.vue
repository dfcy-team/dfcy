<template>
  <el-button link type="primary" @click="open">采购合同</el-button>
  <el-drawer v-model="visible" title="采购合同" size="min(1150px,96vw)" :close-on-click-modal="false" :before-close="close">
    <div v-loading="loading">
      <el-alert v-if="error" :title="error" type="error" :closable="false"/>
      <template v-if="payload">
        <p>合同号：{{contract?.number||'正式生成时分配'}}　订单号（供应商发货单）：{{state.shipment_number}}</p>
        <el-alert :title="issued?'正式内容已冻结。请上传双方签署件并核对后登记签署状态；生成文件不代表已签署。':'草稿可修改；修改不回写发货单、商品资料或成本。请核对买卖双方、税率和条款。'" type="info" :closable="false"/>
        <ContractSignaturesV2 v-if="issued && visible" :shipment-id="shipmentId" @busy="signatureBusy=$event" @updated="emit('updated')"/>
        <el-form label-position="top" :disabled="busy||!editable||issued" class="contract-form">
          <div class="header-fields"><el-form-item label="合同性质"><el-select v-model="nature"><el-option value="corporate" label="对公合同"/><el-option value="personal" label="对私合同"/></el-select></el-form-item><el-form-item v-if="nature==='corporate'&&payload.pricing_basis==='net_plus_tax'" label="对公合同税费处理（必选）"><el-select v-model="payload.tax_treatment" placeholder="选择退税或免税"><el-option value="refund" label="退税：税费增加应付，不计成本"/><el-option value="exempt" label="免税：税费增加应付，计入成本"/></el-select></el-form-item><el-form-item label="签订日期"><el-date-picker v-model="payload.contract_date" type="date" value-format="YYYY-MM-DD"/></el-form-item><el-form-item label="导出订单号"><el-switch v-model="payload.include_order_number" active-text="显示供应商发货单号"/></el-form-item></div>
          <div class="parties"><section v-for="(label,key) in {buyer:'甲方（需方）',seller:'乙方（供方）'}" :key="key"><h3>{{label}}</h3><el-form-item v-for="(fieldLabel,field) in partyFields" :key="field" :label="fieldLabel"><el-input v-model="payload[key][field]" :maxlength="500"/></el-form-item></section></div>
          <el-alert v-if="legacyDraft" type="warning" :closable="false" title="旧草稿按含税单价口径保存。保持原口径，或确认转换后逐项重填未税业务单价。"/><el-button v-if="legacyDraft" @click="keepLegacy">保持原口径</el-button><el-button v-if="legacyDraft" @click="convertLegacy">确认转换并重填未税单价</el-button>
          <h3>商品明细（{{payload.pricing_basis==='net_plus_tax'?'未税业务单价':'历史含税单价'}}，税点单位 %）</h3>
          <el-table :data="payload.lines" border><el-table-column prop="sku" label="商品 SKU" min-width="150"/><el-table-column label="商品名称" min-width="160"><template #default="{row}"><el-input v-model="row.product_name"/></template></el-table-column><el-table-column label="规格" min-width="140"><template #default="{row}"><el-input v-model="row.specification"/></template></el-table-column><el-table-column label="单位" width="80"><template #default="{row}"><el-input v-model="row.unit"/></template></el-table-column><el-table-column label="数量" width="105"><template #default="{row}"><el-input v-model="row.quantity" inputmode="decimal"/></template></el-table-column><el-table-column :label="payload.pricing_basis==='net_plus_tax'?'未税单价':'含税单价'" width="125"><template #default="{row}"><el-input v-model="row.unit_price" inputmode="decimal"/></template></el-table-column><el-table-column label="税点 %（可手动改）" width="130"><template #default="{row}"><el-input v-model="row.tax_rate" :disabled="nature==='personal'" inputmode="decimal" placeholder="例如 0 或 13"/></template></el-table-column><el-table-column label="金额预览" min-width="220"><template #default="{row}">{{taxPreview(row)}}</template></el-table-column></el-table>
          <p v-if="contract?.payload?.lines?.length">上次保存：未税合计 {{savedTotal('net_total')}} · {{payload.pricing_basis==='net_plus_tax'?'税点新增':'其中税费'}} {{savedTotal('tax_amount')}} · 含税合计 {{savedTotal('line_total')}}<span v-if="dirty">（存在未保存修改）</span></p>
          <p v-if="nature==='corporate'&&payload.pricing_basis==='net_plus_tax'">正式生成时新增税费同步到供应商应付，不改变源单未税金额；退税税费不计商品成本，免税税费按原商品未税货值分摊入成本。合同未税金额若另作修改，请核对与发货单的差异。</p><p v-if="payload.pricing_basis==='net_plus_tax'">未税金额=数量×未税单价；税费=未税金额×税点；含税合计=未税金额+税费。默认税点来自供应商档案，可手动改；对私不加税。预览仅供核对，保存后由服务端精确计算。</p><p v-else>历史含税口径：原含税金额不另加税，拆分未税金额及其中税费。</p>

          <section v-for="(term,index) in payload.terms" :key="index"><el-form-item :label="term.title"><el-input v-model="term.text" type="textarea" :autosize="{minRows:2,maxRows:8}"/></el-form-item></section>
          <el-form-item v-if="!issued" label="保存说明"><el-input v-model="reason" maxlength="500" placeholder="说明本次填写或修改内容"/></el-form-item>
        </el-form>
        <p v-if="state.source_changed || (contract && contract.source_version!==state.source_version)" class="warning">发货单已由版本 {{contract?.source_version}} 更新至 {{state.source_version}}。请对照发货单核对商品、数量和价格，修改并保存草稿后再生成正式合同。</p>
        <el-checkbox v-if="!issued&&editable" v-model="confirmed" :disabled="busy||dirty">已核对双方资料、税率、条款及发货单差异，确认冻结正式合同及退税／免税选择；新增税费同步增加应付，并按选择处理成本</el-checkbox>
        <p class="hint">同一发货单仅一张合同；合同性质不限制该单对公或对私付款，对公无合同仍可办理付款。</p>
      </template>
    </div>
    <template #footer><el-button :disabled="busy||signatureBusy" @click="close(()=>visible=false)">关闭</el-button><el-button v-if="payload&&!issued&&editable" :loading="busy" @click="save">保存草稿</el-button><el-button v-if="contract&&!issued&&editable" type="primary" :disabled="busy||dirty||!confirmed||legacyDraft" @click="issue">生成正式合同</el-button><el-button v-if="issued" type="primary" :disabled="signatureBusy" :loading="busy" @click="download">下载正式 Excel</el-button></template>
  </el-drawer>
</template>
<script setup>
import {computed,onUnmounted,ref,watch} from 'vue';
import {ElMessageBox} from 'element-plus';
import {useAuthStore} from '../../stores/auth';
import {cockpitActorKey} from '../../utils/cockpitDraft';
import * as api from '../../api/purchaseContractsV2';
import ContractSignaturesV2 from './ContractSignaturesV2.vue';
const props=defineProps({shipmentId:[Number,String]}),emit=defineEmits(['updated']);
const auth=useAuthStore(),editable=computed(()=>!auth.authorizationStale&&auth.hasPermission('supply.v2.manage'));
const signatureBusy=ref(false);
const visible=ref(false),loading=ref(false),busy=ref(false),error=ref(''),state=ref({}),contract=ref(null),payload=ref(null),nature=ref('corporate'),reason=ref(''),confirmed=ref(false),saved=ref('');
const partyFields={name:'单位名称',address:'单位地址',representative:'法定代表人',tax_id:'纳税识别号',bank:'开户银行',account:'账号',phone:'电话'};
const savedTotal=field=>contract.value?.payload?.lines?.some(row=>row[field]==null||row[field]==='')?'待完善':contract.value.payload.lines.reduce((sum,row)=>sum+Number(row[field]||0),0).toFixed(2);
const issued=computed(()=>contract.value?.status==='issued');
const legacyDraft=computed(()=>contract.value?.status==='draft'&&!contract.value?.payload?.pricing_basis&&payload.value?.pricing_basis!=='gross_inclusive'&&payload.value?.pricing_basis!=='net_plus_tax');
const signature=()=>JSON.stringify([nature.value,payload.value]);
const dirty=computed(()=>!!payload.value&&signature()!==saved.value);
let generation=0,attempt=null;
const labels={payload:'合同',buyer:'买方',seller:'卖方',name:'名称',lines:'商品行',quantity:'数量',unit_price:'含税单价',tax_rate:'税率',contract_date:'签订日期',reason:'保存说明',terms:'条款',source_version:'发货单版本'};
function messages(value,path=[]){if(value==null)return [];if(Array.isArray(value))return value.flatMap((v,i)=>messages(v,typeof v==='object'?[...path,`第${i+1}行`]:path));if(typeof value==='object')return Object.entries(value).filter(([k])=>!['source_changed','source_version','contract_source_version','version'].includes(k)).flatMap(([k,v])=>messages(v,[...path,labels[k]||k]));return [`${path.length?path.join(' / ')+'：':''}${value}`];}
function unwrap(r){if(!r?.success)throw new Error(messages(r?.data).join('；')||r?.message||'合同操作失败');return r.data;}
function errorMessage(e){return messages(e?.response?.data?.data).join('；')||e.message||'合同操作失败';}
function accept(value){state.value=value;contract.value=value.contract;payload.value=structuredClone(value.contract?.payload||value.defaults);nature.value=value.contract?.nature||'corporate';saved.value=signature();reason.value='';confirmed.value=false;}
async function open(){visible.value=true;loading.value=true;error.value='';payload.value=null;const token=++generation;try{const data=unwrap(await api.fetchContract(props.shipmentId));if(token===generation)accept(data);}catch(e){if(token===generation)error.value=errorMessage(e);}finally{if(token===generation)loading.value=false;}}
async function mutate(action,body){if(busy.value||!editable.value)return;const id=props.shipmentId,token=generation,key=JSON.stringify([id,action,body]);if(attempt?.signature!==key)attempt={signature:key,key:api.createIdempotencyKey()};busy.value=true;error.value='';try{const value=unwrap(await api[action](id,body,attempt.key));if(token!==generation)return;attempt=null;accept(value);emit('updated');}catch(e){if(token===generation)error.value=errorMessage(e);}finally{busy.value=false;}}
function taxPreview(row){const q=Number(row.quantity),u=Number(row.unit_price),r=nature.value==='personal'?0:Number(row.tax_rate);if(row.unit_price==null||row.unit_price===''||(nature.value==='corporate'&&(row.tax_rate==null||row.tax_rate===''))||![q,u,r].every(Number.isFinite))return '待填写单价和税点';const amount=Math.round(q*u*100)/100;const net=payload.value.pricing_basis==='net_plus_tax'?amount:Math.round(amount/(1+r/100)*100)/100;const tax=payload.value.pricing_basis==='net_plus_tax'?Math.round(net*r)/100:amount-net;return `未税 ${net.toFixed(2)} · 税费 ${tax.toFixed(2)} · 含税 ${(net+tax).toFixed(2)}`;}
function keepLegacy(){payload.value.pricing_basis='gross_inclusive';}
async function convertLegacy(){try{await ElMessageBox.confirm('转换后请逐项重新填写未税业务单价，系统不会自动猜测或换算原单价。继续？','确认转换');payload.value.pricing_basis='net_plus_tax';for(const row of payload.value.lines)row.unit_price=null;}catch{}}
function save(){if(issued.value)return;if(!reason.value.trim()){error.value='请填写保存说明';return;}if(legacyDraft.value){error.value='请先明确选择旧口径保持或转换';return;}return mutate('saveContract',{expected_version:contract.value?.version||0,expected_source_version:state.value.source_version,nature:nature.value,payload:payload.value,reason:reason.value.trim()});}
function issue(){if(legacyDraft.value||!confirmed.value||dirty.value||!contract.value||issued.value)return;return mutate('issueContract',{expected_version:contract.value.version,expected_source_version:state.value.source_version,confirmed:true});}
async function download(){busy.value=true;try{unwrap(await api.downloadContract(props.shipmentId,contract.value.number));}catch(e){error.value=errorMessage(e);}finally{busy.value=false;}}
async function close(done){if(busy.value||signatureBusy.value)return;if(dirty.value){try{await ElMessageBox.confirm('未保存的合同编辑将丢失，确认关闭？','关闭合同');}catch{return;}}generation++;visible.value=false;if(typeof done==='function')done();}
watch(()=>[props.shipmentId,cockpitActorKey(auth.currentUser),auth.authorizationStale],()=>{generation++;visible.value=false;payload.value=null;contract.value=null;attempt=null;},{flush:'sync'});
watch(nature,value=>{if(value==='personal'&&!issued.value&&payload.value)for(const row of payload.value.lines)row.tax_rate='0';});
watch(dirty,()=>{confirmed.value=false;});
onUnmounted(()=>generation++);
defineExpose({open,save,issue,reason,nature,payload,confirmed,contract,error,dirty,keepLegacy,convertLegacy});
</script>
<style scoped>
.header-fields,.parties{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.contract-form{margin-top:18px}.parties section{padding:12px;background:#f7f9fc}.warning{color:#b45309}.hint{font-size:13px;color:#64748b}h3{font-size:15px}@media(max-width:700px){.header-fields,.parties{grid-template-columns:1fr}}
</style>
