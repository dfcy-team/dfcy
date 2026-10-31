<template>
  <section class="signature-panel" v-loading="loading">
    <header><h3>合同签署件 <el-tag :type="data?.status==='signed'?'success':'warning'">{{!data?'尚未读取':data.status==='signed'?'已登记签署':'待核对'}}</el-tag></h3><el-button :disabled="busy" @click="load">刷新签署记录</el-button></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <template v-if="data">
      <p>上传不等于确认签署。请核对双方签章及文件内容后登记；补传新文件会重新进入待核对，已有文件和状态历史保留。</p>
      <p v-if="data.status==='signed'">签署日期：{{data.signed_date}}</p>
      <ul class="files"><li v-for="file in data.attachments" :key="file.id"><span>{{file.file_name}} · {{Math.ceil(file.byte_size/1024)}} KB · {{file.uploaded_by}}</span><el-button link :disabled="busy" @click="preview(file)">预览</el-button><el-button link :disabled="busy" @click="download(file)">下载</el-button></li></ul>
      <p v-if="!data.attachments.length">尚未上传签署件</p>
      <div v-if="editable" class="upload"><label>选择签署件（PDF / JPG / PNG，单份不超过 10 MB，最多 20 份）<input type="file" accept=".pdf,.jpg,.jpeg,.png" :disabled="busy||data.attachments.length>=20" @change="selectFile"/></label><span v-if="selectedFile">已选：{{selectedFile.name}}</span><el-button :disabled="busy||!selectedFile" :loading="busy" @click="upload">上传签署件</el-button></div>
      <el-form v-if="editable" label-position="top" :disabled="busy" @submit.prevent>
        <el-form-item v-if="data.status!=='signed'" label="双方完成签署日期" required><el-date-picker v-model="signedDate" type="date" value-format="YYYY-MM-DD"/></el-form-item>
        <el-form-item label="登记说明 / 撤回原因" required><el-input v-model="reason" maxlength="500" placeholder="说明已核对的签署文件；撤回时说明原因"/></el-form-item>
        <el-checkbox v-if="data.status!=='signed'" v-model="confirmed">已核对文件内容及双方签章，确认登记已签署</el-checkbox>
        <div class="actions"><el-button v-if="data.status!=='signed'" type="primary" :disabled="busy||!confirmed||!data.attachments.length||!signedDate||!reason.trim()" @click="saveStatus('signed')">确认已签署</el-button><el-button v-else type="warning" plain :disabled="busy||!reason.trim()" @click="saveStatus('pending')">撤回为待核对</el-button></div>
      </el-form>
      <details v-if="data.history?.length"><summary>签署状态历史（最近 {{data.history.length}} 条<span v-if="data.history_total>data.history.length">，共 {{data.history_total}} 条</span>）</summary><ul><li v-for="(row,index) in data.history" :key="row.id||index">{{displayTime(row.created_at)}} · {{row.uploaded_by}} · {{row.status==='signed'?'登记已签署':'待核对'}} · {{row.reason}} <span v-if="row.signed_date">· 签署日期 {{row.signed_date}}</span><span v-if="row.attachment_ids?.length"> · 文件：{{row.attachment_ids.map(id=>data.attachments.find(a=>a.id===id)?.file_name||`附件${id}`).join('、')}}</span></li></ul></details>
    </template>
    <el-dialog v-model="previewOpen" title="签署件预览" width="min(1000px,95vw)" append-to-body @closed="clearPreview"><img v-if="previewUrl && previewType.startsWith('image/')" :src="previewUrl" alt="合同签署件" class="preview-image"/><template v-else-if="previewUrl"><p>PDF 可在新窗口查看，或下载后查看。</p><a :href="previewUrl" target="_blank" rel="noopener noreferrer">打开 PDF 签署件</a></template></el-dialog>
  </section>
</template>
<script setup>
import {computed,onMounted,onUnmounted,ref,watch} from 'vue';
import {useAuthStore} from '../../stores/auth';
import {cockpitActorKey} from '../../utils/cockpitDraft';
import * as api from '../../api/contractSignaturesV2';
const props=defineProps({shipmentId:{type:[String,Number],required:true}}),emit=defineEmits(['updated','busy']);
const auth=useAuthStore(),editable=computed(()=>!auth.authorizationStale&&auth.hasPermission('supply.v2.manage'));
const data=ref(null),loading=ref(false),busy=ref(false),error=ref(''),selectedFile=ref(null),reason=ref(''),signedDate=ref(''),confirmed=ref(false);
const previewOpen=ref(false),previewUrl=ref(''),previewType=ref('');
let generation=0,uploadAttempt=null,statusAttempt=null;
function displayTime(value){const d=new Date(value);return Number.isNaN(d.getTime())?'—':d.toLocaleString('zh-CN');}
function details(value){if(value==null)return [];if(Array.isArray(value))return value.flatMap(details);if(typeof value==='object')return Object.values(value).flatMap(details);return typeof value==='string'?[value]:[];}
function unwrap(result){if(!result?.success)throw new Error((result?.data?.version!=null?'':details(result?.data).join('；'))||result?.message||'签署件操作失败');return result.data;}
function accept(value){data.value=value;signedDate.value=value.signed_date||'';reason.value='';confirmed.value=false;}
async function load(){if(busy.value)return;const token=++generation;loading.value=true;error.value='';try{const value=unwrap(await api.fetchSignatures(props.shipmentId));if(token===generation)accept(value);}catch(e){if(token===generation)error.value=e.message;}finally{if(token===generation)loading.value=false;}}
function selectFile(event){const file=event.target.files?.[0];event.target.value='';selectedFile.value=null;uploadAttempt=null;if(!file)return;if(!/\.(pdf|jpe?g|png)$/i.test(file.name)||file.size<=0||file.size>10*1024*1024){error.value='请选择不超过 10 MB 的 PDF、JPG 或 PNG 文件';return;}selectedFile.value=file;error.value='';}
async function upload(){if(busy.value||!editable.value||!selectedFile.value||!data.value||data.value.attachments.length>=20)return;const file=selectedFile.value,token=generation;if(uploadAttempt?.file!==file)uploadAttempt={file,key:api.createIdempotencyKey()};busy.value=true;error.value='';try{const value=unwrap(await api.uploadSignature(props.shipmentId,file,uploadAttempt.key));if(token!==generation)return;accept(value);selectedFile.value=null;uploadAttempt=null;emit('updated');}catch(e){if(token===generation)error.value=e.message;}finally{busy.value=false;}}
async function saveStatus(status){if(busy.value||!editable.value||!data.value)return;if(!reason.value.trim()){error.value='请填写登记说明或撤回原因';return;}if(status==='signed'&&(!confirmed.value||!signedDate.value||!data.value.attachments.length)){error.value='请先上传签署件、填写日期并确认已核对双方签章';return;}const body={expected_version:data.value.version,status,signed_date:status==='signed'?signedDate.value:null,reason:reason.value.trim()},signature=JSON.stringify(body),token=generation;if(statusAttempt?.signature!==signature)statusAttempt={signature,key:api.createIdempotencyKey()};busy.value=true;error.value='';try{const value=unwrap(await api.saveSignatureStatus(props.shipmentId,body,statusAttempt.key));if(token!==generation)return;accept(value);statusAttempt=null;emit('updated');}catch(e){if(token===generation)error.value=e.message;}finally{busy.value=false;}}
function clearPreview(){if(previewUrl.value)URL.revokeObjectURL(previewUrl.value);previewUrl.value='';previewType.value='';}
async function preview(file){if(busy.value)return;const token=generation;busy.value=true;error.value='';try{const result=await api.previewSignature(props.shipmentId,file);unwrap(result);if(token!==generation)return;clearPreview();previewUrl.value=URL.createObjectURL(result.blob);previewType.value=file.media_type;previewOpen.value=true;}catch(e){if(token===generation)error.value=e.message;}finally{busy.value=false;}}
async function download(file){if(busy.value)return;const token=generation;busy.value=true;error.value='';try{unwrap(await api.downloadSignature(props.shipmentId,file));}catch(e){if(token===generation)error.value=e.message;}finally{busy.value=false;}}
watch(busy,value=>emit('busy',value),{flush:'sync'});
watch(()=>[props.shipmentId,cockpitActorKey(auth.currentUser),auth.authorizationStale],()=>{generation++;data.value=null;selectedFile.value=null;reason.value='';signedDate.value='';confirmed.value=false;uploadAttempt=null;statusAttempt=null;previewOpen.value=false;clearPreview();if(!auth.authorizationStale)load();},{flush:'sync'});
onMounted(load);onUnmounted(()=>{generation++;clearPreview();emit('busy',false);});
defineExpose({load,selectFile,upload,saveStatus,preview,download,data,error,reason,signedDate,confirmed,selectedFile});
</script>
<style scoped>
.signature-panel{border:1px solid #dce3ed;border-radius:8px;padding:16px;margin:16px 0}.signature-panel header{display:flex;justify-content:space-between;align-items:center;gap:12px}.signature-panel h3{margin:0;font-size:16px}.signature-panel p,.signature-panel li{font-size:13px;line-height:1.6}.files{padding:0;list-style:none}.files li{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:8px 0;border-bottom:1px solid #eef2f6}.files span{overflow-wrap:anywhere}.upload{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin:16px 0}.upload input{display:block;margin-top:8px}.actions{margin:12px 0}.preview-image{display:block;max-width:100%;max-height:75vh;margin:auto}
</style>
