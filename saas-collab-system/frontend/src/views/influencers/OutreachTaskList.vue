<template>
  <section class="creator-page">
    <header>
      <div><span>CREATOR OPERATIONS</span><h1>建联任务</h1><p>统一查看任务、进度、负责人、商品店铺快照和履约反馈。</p></div>
      <el-button type="primary" :disabled="!canManage" @click="openCreate">新建任务</el-button>
    </header>

    <el-card shadow="never">
      <div class="toolbar">
        <el-input v-model="filters.search" clearable placeholder="搜索任务/店铺/商品/负责人" @keyup.enter="applyFilters" />
        <el-select v-model="filters.status" clearable placeholder="全部状态" @change="applyFilters"><el-option v-for="(label,value) in OUTREACH_STATUS_LABELS" :key="value" :label="label" :value="value" /></el-select>
        <el-select v-model="filters.store" clearable filterable placeholder="全部店铺" @change="applyFilters"><el-option v-for="store in rowStores" :key="store.id" :label="store.name" :value="store.id" /></el-select>
        <el-button type="primary" @click="applyFilters">查询</el-button><el-button @click="resetFilters">重置</el-button>
      </div>
      <el-table v-loading="loading" :data="rows" empty-text="暂无建联任务" row-key="id">
        <el-table-column label="任务" min-width="180"><template #default="{row}"><b>{{ row.task_no }}</b><small>{{ row.task_name }}</small></template></el-table-column>
        <el-table-column label="店铺 / 商品快照" min-width="220"><template #default="{row}"><b>{{ row.store_name||row.store||'—' }}</b><small>{{ row.product_name_snapshot||row.external_product_id||'未匹配商品' }}</small><small v-if="row.product_name_snapshot&&row.external_product_id">商品 ID {{ row.external_product_id }}</small></template></el-table-column>
        <el-table-column label="优先级" width="100"><template #default="{row}"><el-tag v-if="row.priority" :type="priorityTag(row.priority)">{{ statusLabel(OUTREACH_PRIORITY_LABELS,row.priority) }}</el-tag><span v-else>—</span></template></el-table-column>
        <el-table-column label="建联进度" min-width="150"><template #default="{row}"><el-progress v-if="row.target_count" :percentage="progress(row)" :format="()=>`${row.linked_count||0}/${row.target_count||0}`" /><span v-else>—</span></template></el-table-column>
        <el-table-column label="负责人" min-width="130"><template #default="{row}"><b>{{ row.owner_name||row.owner||'—' }}</b><small v-if="row.owner_name&&row.owner">ID {{ row.owner }}</small></template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{row}"><el-tag>{{ statusLabel(OUTREACH_STATUS_LABELS,row.status) }}</el-tag></template></el-table-column>
        <el-table-column prop="dispatcher_name" label="任务下发人" min-width="130" /><el-table-column prop="notes" label="履约反馈" min-width="160" />
        <el-table-column prop="dispatch_time" label="下发时间" min-width="165" /><el-table-column prop="started_at" label="启动时间" min-width="165" /><el-table-column prop="finalized_at" label="截止时间" min-width="165" />
        <el-table-column label="操作" min-width="260" fixed="right"><template #default="{row}"><el-button link @click="openTargets(row)">达人目标</el-button><el-button link :disabled="!canManage || row.status !== 'pending'" @click="changeStatus(row,'in_progress')">开始</el-button><el-button link :disabled="!canManage || row.status !== 'in_progress'" @click="changeStatus(row,'completed')">完成</el-button><el-button link type="danger" :disabled="!canManage||isTerminal(row)" @click="changeStatus(row,'cancelled')">取消</el-button><el-button link :disabled="!canManage" @click="openEdit(row)">修改</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-if="total" v-model:current-page="page" v-model:page-size="pageSize" :total="total" layout="total, prev, pager, next" @current-change="load" />
    </el-card>

    <el-dialog v-model="createVisible" :title="editingTask?'修改建联任务':'新建建联任务'" width="620px">
      <el-form label-width="110px">
        <el-form-item label="任务编号" required><el-input v-if="!editingTask" v-model="form.task_no" /><el-input v-else :model-value="editingTask.task_no" readonly /></el-form-item>
        <el-form-item label="任务名称" required><el-input v-model="form.task_name" /></el-form-item>
        <el-form-item label="任务优先级" required><el-select v-model="form.priority" placeholder="请选择优先级"><el-option v-for="(label,value) in OUTREACH_PRIORITY_LABELS" :key="value" :label="label" :value="value" /></el-select></el-form-item>
        <el-form-item label="店铺" required><el-select v-model="form.store" filterable placeholder="按店铺名称搜索" @change="selectMatchedStore"><el-option v-for="store in visibleStoreOptions" :key="store.id" :label="`${store.name}（${store.code||'—'} / ${store.country_code||'—'}）`" :value="store.id" /></el-select></el-form-item>
        <el-form-item label="商品 ID"><el-input v-model="form.external_product_id" @change="matchProduct" /></el-form-item>
        <el-form-item v-if="productMatchHint" label="匹配结果"><el-alert :closable="false" :type="productMatchType" :title="productMatchHint" /></el-form-item>
        <el-form-item label="SKU 前缀"><el-select v-if="matchedSkuPrefixes.length>1" v-model="form.sku_prefix" placeholder="请选择 SKU 前缀"><el-option v-for="prefix in matchedSkuPrefixes" :key="prefix" :label="prefix" :value="prefix" /></el-select><el-input v-else v-model="form.sku_prefix" /></el-form-item>
        <el-form-item label="目标建联人数" required><el-input-number v-model="form.target_count" :min="editingTask?0:1" :step="1" step-strictly /></el-form-item>
        <el-form-item label="负责 BD" required><el-select v-model="form.owner" filterable placeholder="按姓名或账号搜索"><el-option v-for="user in bdOptions" :key="user.id" :label="`${user.full_name||user.username}（${user.username}）`" :value="user.id" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button @click="createVisible=false">取消</el-button><el-button type="primary" :loading="saving" @click="submit">{{ editingTask?'保存修改':'创建' }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="targetsVisible" :title="`达人目标 · ${activeTask?.task_name||''}`" width="820px">
      <div class="target-bar"><el-select v-if="influencerOptions.length" v-model="targetForm.influencer" filterable clearable placeholder="搜索达人名称/账号"><el-option v-for="influencer in influencerOptions" :key="influencer.id" :label="influencerLabel(influencer)" :value="influencer.id" /></el-select><el-input-number v-else v-model="targetForm.influencer" :min="1" placeholder="达人 ID" /><el-input v-model="targetForm.notes" placeholder="备注（可选）" /><el-button type="primary" :disabled="!canManage||isTerminal(activeTask)" @click="addTarget">添加达人目标</el-button></div>
      <el-table v-loading="targetLoading" :data="displayTargets" empty-text="暂无达人目标"><el-table-column label="达人" min-width="220"><template #default="{row}"><b>{{ row.influencer_name||row.influencer_code||(row.influencer?`达人 ${row.influencer}`:'—') }}</b><small>{{ row.influencer_platform||(row.influencer?'ID '+row.influencer:'') }}</small></template></el-table-column><el-table-column label="建联结果" min-width="160"><template #default="{row}"><el-select v-if="!row.is_deleted" v-model="row.outreach_result" :disabled="!canManage||isTerminal(activeTask)||isTargetTerminal(row)" @change="updateResult(row)"><el-option v-for="(label,value) in OUTREACH_RESULT_LABELS" :key="value" :label="label" :value="value" /></el-select><el-tag v-else>已删除</el-tag></template></el-table-column><el-table-column prop="notes" label="备注" /><el-table-column prop="version" label="版本" width="70" /><el-table-column label="操作" width="120"><template #default="{row}"><el-button v-if="!row.is_deleted" link type="danger" :disabled="!canManage||isTerminal(activeTask)||isTargetTerminal(row)" @click="removeTarget(row)">删除</el-button><el-button v-else link type="primary" :disabled="!canManage||isTerminal(activeTask)" @click="restoreTarget(row)">恢复</el-button></template></el-table-column></el-table>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed,onMounted,reactive,ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useAuthStore } from '../../stores/auth';
import { addOutreachTarget,createOutreachTask,deleteOutreachTarget,fetchOutreachTargets,fetchOutreachTaskOptions,fetchOutreachTasks,formatInfluencerError,matchOutreachProduct,OUTREACH_PRIORITY_LABELS,OUTREACH_RESULT_LABELS,OUTREACH_STATUS_LABELS,restoreOutreachTarget,statusLabel,updateOutreachStatus,updateOutreachTarget,updateOutreachTask } from '../../api/influencers';
import { collectionRows,collectionTotal,detailData } from '../../utils/businessResponse';

const auth=useAuthStore();
const rows=ref([]),total=ref(0),page=ref(1),pageSize=ref(20),loading=ref(false),saving=ref(false),createVisible=ref(false),targetsVisible=ref(false),targetLoading=ref(false),activeTask=ref(null),targets=ref([]),deletedTargets=ref([]),editingTask=ref(null);
const displayTargets=computed(()=>[...targets.value,...deletedTargets.value]);
const canManage=computed(()=>auth.hasPermission('influencers.outreach.manage'));
const form=reactive({task_no:'',task_name:'',priority:'normal',store:null,external_product_id:'',sku_prefix:'',target_count:1,owner:null});
const targetForm=reactive({influencer:null,notes:''});
const filters=reactive({search:'',status:'',store:null});
const storeOptions=ref([]),bdOptions=ref([]),influencerOptions=ref([]);
const matchedStoreIds=ref([]),matchedCandidates=ref([]),matchedSkuPrefixes=ref([]),productMatching=ref(false),productMatchHint=ref(''),productMatchType=ref('info'),productMatchSeq=ref(0);
const rowStores=computed(()=>[...new Map(rows.value.filter(row=>row.store).map(row=>[row.store,{id:row.store,name:row.store_name||`店铺 ${row.store}`}])).values()]);
const visibleStoreOptions=computed(()=>{
  if(!matchedStoreIds.value.length)return storeOptions.value;
  const optionsById=new Map(storeOptions.value.map(store=>[store.id,store]));
  matchedCandidates.value.forEach(candidate=>optionsById.set(candidate.store_id,{id:candidate.store_id,name:candidate.store_name,code:candidate.store_code,country_code:candidate.country_code}));
  return matchedStoreIds.value.map(storeId=>optionsById.get(storeId)).filter(Boolean);
});
const isTerminal=(row)=>['completed','cancelled'].includes(row?.status);
const isTargetTerminal=(row)=>['success','rejected','no_response','blocked'].includes(row?.outreach_result);
const progress=(row)=>row.target_count?Math.min(100,Math.round((row.linked_count||0)*100/row.target_count)):0;
const priorityTag=(value)=>({urgent:'danger',high:'warning',low:'info',normal:'success'})[value]||'info';
const influencerLabel=(item)=>{const name=item.name||item.code||`达人 ${item.id}`;const extra=[item.platform,item.handle].filter(Boolean).join(' · ');return extra?`${name}（${extra}）`:name};

async function load(){loading.value=true;const params={ page: page.value, page_size: pageSize.value };if(filters.search.trim())params.search=filters.search.trim();if(filters.status)params.status=filters.status;if(filters.store)params.store=filters.store;const r=await fetchOutreachTasks(params);loading.value=false;if(r.success){rows.value=collectionRows(r.data);total.value=collectionTotal(r.data)}else ElMessage.error(formatInfluencerError(r,'任务加载失败'))}
function applyFilters(){page.value=1;load()}
function resetFilters(){Object.assign(filters,{search:'',status:'',store:null});applyFilters()}
async function loadOptions(){const r=await fetchOutreachTaskOptions();if(!r.success){ElMessage.error(formatInfluencerError(r,'店铺、BD 和达人选项加载失败'));return false}storeOptions.value=r.data?.stores||[];bdOptions.value=r.data?.bd_users||[];influencerOptions.value=(r.data?.influencers||[]).filter(item=>item?.id!==undefined&&item?.id!==null);return true}
function resetMatch(){matchedStoreIds.value=[];matchedCandidates.value=[];matchedSkuPrefixes.value=[];productMatchHint.value='';productMatchType.value='info'}
async function openCreate(){editingTask.value=null;Object.assign(form,{task_no:`DRJL${Date.now().toString().slice(-6)}`,task_name:'',priority:'normal',store:null,external_product_id:'',sku_prefix:'',target_count:1,owner:null});resetMatch();if(await loadOptions())createVisible.value=true}
async function openEdit(row){if(!canManage.value)return;editingTask.value={...row};Object.assign(form,{task_no:row.task_no||'',task_name:row.task_name||'',priority:row.priority||'normal',store:row.store??null,external_product_id:row.external_product_id||'',sku_prefix:row.sku_prefix||'',target_count:row.target_count??0,owner:row.owner??null});resetMatch();if(await loadOptions())createVisible.value=true}
function selectMatchedStore(storeId){const candidate=matchedCandidates.value.find(item=>item.store_id===storeId);matchedSkuPrefixes.value=candidate?.sku_prefixes||[];form.sku_prefix=matchedSkuPrefixes.value.length===1?matchedSkuPrefixes.value[0]:''}
async function matchProduct(){const productId=form.external_product_id.trim(),requestSeq=++productMatchSeq.value;form.store=null;form.sku_prefix='';matchedStoreIds.value=[];matchedCandidates.value=[];matchedSkuPrefixes.value=[];if(!productId){productMatchHint.value='';return}productMatching.value=true;const r=await matchOutreachProduct(productId);if(requestSeq!==productMatchSeq.value||productId!==form.external_product_id.trim())return;productMatching.value=false;if(!r.success){productMatchType.value='error';productMatchHint.value=formatInfluencerError(r,'商品匹配失败');return}const candidates=r.data?.candidates||[];matchedCandidates.value=candidates;matchedStoreIds.value=candidates.map(item=>item.store_id);if(!candidates.length){productMatchType.value='warning';productMatchHint.value='商品数据未导入，请手动选择店铺和填写 SKU 前缀';return}if(r.data?.unique){const candidate=candidates[0];form.store=candidate.store_id;selectMatchedStore(candidate.store_id);productMatchType.value='success';productMatchHint.value=`已匹配店铺：${candidate.store_name}${candidate.sku_prefixes?.length===1?`，SKU 前缀：${candidate.sku_prefixes[0]}`:'，请选择 SKU 前缀'}`;return}productMatchType.value='warning';productMatchHint.value=`匹配到 ${candidates.length}${r.data?.truncated?'+':''} 家店铺，请选择正确店铺`}
async function submit(){if(!form.task_name||!form.store||!form.owner)return ElMessage.warning('请填写必填字段');saving.value=true;const r=editingTask.value?await updateOutreachTask(editingTask.value.id,{task_name:form.task_name,priority:form.priority,store:form.store,external_product_id:form.external_product_id,sku_prefix:form.sku_prefix,target_count:form.target_count,owner:form.owner},editingTask.value.version):await createOutreachTask({...form});saving.value=false;if(!r.success){ElMessage.error(formatInfluencerError(r));return}createVisible.value=false;editingTask.value?ElMessage.success('任务已修改'):ElMessage.success('任务已创建');await load()}
async function changeStatus(row,status){const r=await updateOutreachStatus(row.id,status,row.version);if(!r.success)return ElMessage.error(formatInfluencerError(r));Object.assign(row,detailData(r.data));ElMessage.success('状态已更新');await load()}
async function openTargets(row){activeTask.value=row;targetsVisible.value=true;deletedTargets.value=[];await loadTargets()}
async function loadTargets(){targetLoading.value=true;const r=await fetchOutreachTargets(activeTask.value.id,{page:1,page_size:100});targetLoading.value=false;targets.value=r.success?collectionRows(r.data):[];if(!r.success)ElMessage.error(formatInfluencerError(r))}
async function refreshActiveTask(){await load();activeTask.value=rows.value.find(item=>item.id===activeTask.value?.id)||activeTask.value}
async function addTarget(){if(!targetForm.influencer)return ElMessage.warning('请选择达人');const r=await addOutreachTarget(activeTask.value.id,targetForm.influencer,undefined,targetForm.notes);if(!r.success)return ElMessage.error(formatInfluencerError(r));Object.assign(targetForm,{influencer:null,notes:''});ElMessage.success('达人已关联');await loadTargets();await refreshActiveTask()}
async function updateResult(row){const r=await updateOutreachTarget(activeTask.value.id,row.id,{outreach_result:row.outreach_result},row.version);if(!r.success){ElMessage.error(formatInfluencerError(r));return loadTargets()}Object.assign(row,detailData(r.data));await refreshActiveTask()}
async function removeTarget(row){const r=await deleteOutreachTarget(activeTask.value.id,row.id,row.version);if(!r.success)return ElMessage.error(formatInfluencerError(r));deletedTargets.value.push({...row,...detailData(r.data),is_deleted:true});targets.value=targets.value.filter(item=>item.id!==row.id);ElMessage.success('达人目标已删除');await refreshActiveTask()}
async function restoreTarget(row){const r=await restoreOutreachTarget(activeTask.value.id,row,row.version);if(!r.success)return ElMessage.error(formatInfluencerError(r));deletedTargets.value=deletedTargets.value.filter(item=>item.id!==row.id);targets.value.push(detailData(r.data));ElMessage.success('达人目标已恢复');await refreshActiveTask()}
onMounted(load);
</script>

<style scoped>.creator-page{display:grid;gap:18px}.creator-page header{display:flex;justify-content:space-between;align-items:end;padding:24px;border-radius:16px;background:linear-gradient(120deg,#0b5345,#167d68);color:#fff}.creator-page h1{margin:6px 0}.creator-page p{margin:0;opacity:.82}.toolbar{display:flex;gap:10px;margin-bottom:16px}.toolbar .el-input{max-width:340px}.creator-page small{display:block;color:#84909c;font-size:12px}.target-bar{display:flex;gap:10px;margin-bottom:14px}.target-bar .el-input,.target-bar .el-select{max-width:320px}.el-pagination{margin-top:16px;justify-content:flex-end}@media(max-width:800px){.creator-page header,.target-bar{align-items:stretch;flex-direction:column}.toolbar{flex-wrap:wrap}}</style>
