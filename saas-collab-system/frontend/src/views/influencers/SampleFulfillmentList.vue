<template>
  <section class="sample-page">
    <header><div><span>FULFILLMENT DESK</span><h1>送样履约</h1><p>从建联任务和达人目标创建送样，店铺、商品与负责 BD 自动继承。</p></div><el-button type="primary" :disabled="!canManage" @click="openCreate">创建送样</el-button></header>
    <el-card shadow="never"><el-table v-loading="loading" :data="rows" empty-text="暂无送样履约"><el-table-column prop="fulfillment_no" label="履约编号" min-width="130"/><el-table-column prop="outreach_task" label="建联任务"/><el-table-column prop="influencer" label="达人"/><el-table-column prop="store" label="店铺"/><el-table-column prop="product_name_snapshot" label="商品" min-width="150"/><el-table-column prop="owner" label="负责 BD"/><el-table-column label="状态"><template #default="{row}"><el-tag>{{ statusLabel(FULFILLMENT_STATUS_LABELS,row.status) }}</el-tag></template></el-table-column><el-table-column prop="sample_order_no" label="样品订单号" min-width="130"/></el-table><el-pagination v-if="total" v-model:current-page="page" v-model:page-size="pageSize" :total="total" layout="total, prev, pager, next" @current-change="load"/></el-card>

    <el-dialog v-model="visible" title="创建送样履约" width="720px" @closed="discardDraft"><el-form label-width="110px">
      <el-form-item label="履约编号" required><el-input v-model="form.fulfillment_no"/></el-form-item><el-form-item label="建联任务" required><el-select v-model="form.outreach_task" filterable @change="selectTask"><el-option v-for="task in tasks" :key="task.id" :label="`${task.task_name||task.task_no} (${task.task_no})`" :value="task.id"/></el-select></el-form-item><el-form-item label="达人目标" required><el-select v-model="form.outreach_target" :disabled="!form.outreach_task" @change="selectTarget"><el-option v-for="target in targets" :key="target.id" :label="`达人 ${target.influencer}`" :value="target.id"/></el-select></el-form-item>
      <el-form-item label="继承信息"><el-alert :closable="false" type="info" :title="inheritedTask?`店铺 ${inheritedTask.store} · 商品 ${inheritedTask.external_product_id||'未填写'} · BD ${inheritedTask.owner}`:'请先选择建联任务'"/></el-form-item><el-form-item label="样品订单号"><el-input v-model="form.sample_order_no" placeholder="填写后自动标记为已发货"/></el-form-item>
      <el-divider content-position="left">SKU 明细</el-divider><div v-for="(item,index) in items" :key="index" class="sku-row"><el-input v-model="item.site_code" placeholder="站点"/><el-input v-model="item.requested_sku" placeholder="SKU 可空"/><el-input-number v-model="item.quantity" :min="1"/><el-button link type="danger" :disabled="items.length===1" @click="items.splice(index,1)">删除</el-button></div><el-button link type="primary" @click="items.push(newItem())">+ 添加 SKU 行</el-button>
      <el-alert class="price-note" type="warning" :closable="false" title="价格未导入时会标记“数据源未导入”，不会阻止送样记录保存。"/>
    </el-form><template #footer><el-button @click="visible=false">取消</el-button><el-button type="primary" :loading="saving" @click="submit">创建</el-button></template></el-dialog>
  </section>
</template>

<script setup>
import { computed,onMounted,reactive,ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useAuthStore } from '../../stores/auth';
import { createSampleFulfillment,fetchOutreachTargets,fetchOutreachTasks,fetchSampleFulfillments,formatInfluencerError,FULFILLMENT_STATUS_LABELS,statusLabel } from '../../api/influencers';
import { collectionRows,collectionTotal } from '../../utils/businessResponse';
const auth=useAuthStore(),rows=ref([]),tasks=ref([]),targets=ref([]),total=ref(0),page=ref(1),pageSize=ref(20),loading=ref(false),saving=ref(false),visible=ref(false),inheritedTask=ref(null),selectedTarget=ref(null),draftIdempotencyKey=ref('');
const canManage=computed(()=>auth.hasPermission('influencers.fulfillment.manage'));
const form=reactive({fulfillment_no:'',outreach_task:null,outreach_target:null,sample_order_no:''});
const newItem=()=>({site_code:'PH',external_product_id:'',requested_sku:null,quantity:1});const items=ref([newItem()]);
async function load(){loading.value=true;const r=await fetchSampleFulfillments({page:page.value,page_size:pageSize.value});loading.value=false;if(r.success){rows.value=collectionRows(r.data);total.value=collectionTotal(r.data)}else ElMessage.error(formatInfluencerError(r,'送样列表加载失败'))}
const newDraftKey=()=>globalThis.crypto?.randomUUID?.()||`${Date.now()}-${Math.random()}`;
function discardDraft(){draftIdempotencyKey.value=''}
async function openCreate(){Object.assign(form,{fulfillment_no:`SAMPLE-${Date.now()}`,outreach_task:null,outreach_target:null,sample_order_no:''});inheritedTask.value=null;selectedTarget.value=null;targets.value=[];items.value=[newItem()];draftIdempotencyKey.value=newDraftKey();const r=await fetchOutreachTasks({page:1,page_size:100,status:'in_progress'});tasks.value=r.success?collectionRows(r.data):[];visible.value=true}
async function selectTask(id){inheritedTask.value=tasks.value.find(item=>item.id===id)||null;form.outreach_target=null;selectedTarget.value=null;const r=await fetchOutreachTargets(id,{page:1,page_size:100});targets.value=r.success?collectionRows(r.data):[]}
function selectTarget(id){selectedTarget.value=targets.value.find(item=>item.id===id)||null}
async function submit(){if(!form.fulfillment_no||!form.outreach_task||!form.outreach_target)return ElMessage.warning('请选择任务和达人目标');saving.value=true;const payload={...form,items:items.value.map(item=>({...item,external_product_id:inheritedTask.value?.external_product_id||'',requested_sku:item.requested_sku?.trim()||null}))};const r=await createSampleFulfillment(payload,draftIdempotencyKey.value);saving.value=false;if(!r.success)return ElMessage.error(formatInfluencerError(r,'送样创建失败'));draftIdempotencyKey.value='';visible.value=false;ElMessage.success(r.data?.status==='shipped'?'送样已创建并标记为已发货':'送样已创建');load()}
onMounted(load);
</script>

<style scoped>.sample-page{display:grid;gap:18px}.sample-page header{display:flex;justify-content:space-between;align-items:end;padding:24px;border-radius:16px;background:linear-gradient(120deg,#19324a,#285f7d);color:#fff}.sample-page h1{margin:6px 0}.sample-page p{margin:0;opacity:.82}.sku-row{display:grid;grid-template-columns:110px 1fr 130px 60px;gap:10px;margin-bottom:10px}.price-note{margin-top:14px}.el-pagination{margin-top:16px;justify-content:flex-end}@media(max-width:700px){.sample-page header{align-items:stretch;flex-direction:column}.sku-row{grid-template-columns:1fr}}</style>
