<template>
  <section class="creator-page">
    <header><div><span>CREATOR OPERATIONS</span><h1>建联任务</h1><p>一个任务可关联多个达人，任务进度、负责人和关键时间统一记录。</p></div><el-button type="primary" :disabled="!canManage" @click="openCreate">新建任务</el-button></header>
    <el-card shadow="never"><el-table v-loading="loading" :data="rows" empty-text="暂无建联任务">
      <el-table-column prop="task_no" label="任务编号" min-width="130"/><el-table-column prop="task_name" label="任务名称" min-width="150"/><el-table-column prop="store" label="店铺"/><el-table-column prop="external_product_id" label="商品 ID" min-width="120"/><el-table-column prop="sku_prefix" label="SKU 前缀"/>
      <el-table-column label="建联进度" min-width="150"><template #default="{row}"><el-progress :percentage="progress(row)" :format="()=>`${row.linked_count||0}/${row.target_count||0}`"/></template></el-table-column>
      <el-table-column prop="owner" label="负责 BD"/><el-table-column label="状态"><template #default="{row}"><el-tag>{{ statusLabel(OUTREACH_STATUS_LABELS,row.status) }}</el-tag></template></el-table-column>
      <el-table-column prop="dispatch_time" label="下发时间" min-width="165"/><el-table-column prop="started_at" label="启动时间" min-width="165"/><el-table-column prop="finalized_at" label="截止时间" min-width="165"/>
      <el-table-column label="操作" min-width="230"><template #default="{row}"><el-button link @click="openTargets(row)">达人目标</el-button><el-button link :disabled="!canManage || row.status !== 'pending'" @click="changeStatus(row,'in_progress')">开始</el-button><el-button link :disabled="!canManage || row.status !== 'in_progress'" @click="changeStatus(row,'completed')">完成</el-button><el-button link type="danger" :disabled="!canManage||isTerminal(row)" @click="changeStatus(row,'cancelled')">取消</el-button></template></el-table-column>
    </el-table><el-pagination v-if="total" v-model:current-page="page" v-model:page-size="pageSize" :total="total" layout="total, prev, pager, next" @current-change="load"/></el-card>

    <el-dialog v-model="createVisible" title="新建建联任务" width="580px"><el-form label-width="110px">
      <el-form-item label="任务编号" required><el-input v-model="form.task_no"/></el-form-item><el-form-item label="任务名称" required><el-input v-model="form.task_name"/></el-form-item>
      <el-form-item label="店铺" required><el-select v-model="form.store" filterable placeholder="按店铺名称搜索"><el-option v-for="store in storeOptions" :key="store.id" :label="`${store.name}（${store.code} / ${store.country_code}）`" :value="store.id"/></el-select></el-form-item>
      <el-form-item label="商品 ID"><el-input v-model="form.external_product_id"/></el-form-item><el-form-item label="SKU 前缀"><el-input v-model="form.sku_prefix"/></el-form-item><el-form-item label="目标建联人数" required><el-input-number v-model="form.target_count" :min="1" :step="1" step-strictly/></el-form-item>
      <el-form-item label="负责 BD" required><el-select v-model="form.owner" filterable placeholder="按姓名或账号搜索"><el-option v-for="user in bdOptions" :key="user.id" :label="`${user.full_name||user.username}（${user.username}）`" :value="user.id"/></el-select></el-form-item>
    </el-form><template #footer><el-button @click="createVisible=false">取消</el-button><el-button type="primary" :loading="saving" @click="submit">创建</el-button></template></el-dialog>

    <el-dialog v-model="targetsVisible" :title="`达人目标 · ${activeTask?.task_name||''}`" width="760px"><div class="target-bar"><el-input-number v-model="targetForm.influencer" :min="1" placeholder="达人 ID"/><el-input v-model="targetForm.notes" placeholder="备注（可选）"/><el-button type="primary" :disabled="!canManage||isTerminal(activeTask)" @click="addTarget">添加达人目标</el-button></div>
      <el-table v-loading="targetLoading" :data="displayTargets" empty-text="暂无达人目标"><el-table-column prop="influencer" label="达人 ID"/><el-table-column label="建联结果" min-width="160"><template #default="{row}"><el-select v-if="!row.is_deleted" v-model="row.outreach_result" :disabled="!canManage||isTerminal(activeTask)||isTargetTerminal(row)" @change="updateResult(row)"><el-option v-for="(label,value) in OUTREACH_RESULT_LABELS" :key="value" :label="label" :value="value"/></el-select><el-tag v-else>已删除</el-tag></template></el-table-column><el-table-column prop="notes" label="备注"/><el-table-column prop="version" label="版本" width="70"/><el-table-column label="操作" width="90"><template #default="{row}"><el-button v-if="!row.is_deleted" link type="danger" :disabled="!canManage||isTerminal(activeTask)||isTargetTerminal(row)" @click="removeTarget(row)">删除</el-button><el-button v-else link type="primary" :disabled="!canManage||isTerminal(activeTask)" @click="restoreTarget(row)">恢复</el-button></template></el-table-column></el-table>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed,onMounted,reactive,ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useAuthStore } from '../../stores/auth';
import { addOutreachTarget,createOutreachTask,deleteOutreachTarget,fetchOutreachTargets,fetchOutreachTaskOptions,fetchOutreachTasks,formatInfluencerError,OUTREACH_RESULT_LABELS,OUTREACH_STATUS_LABELS,restoreOutreachTarget,statusLabel,updateOutreachStatus,updateOutreachTarget } from '../../api/influencers';
import { collectionRows,collectionTotal,detailData } from '../../utils/businessResponse';
const auth=useAuthStore(),rows=ref([]),total=ref(0),page=ref(1),pageSize=ref(20),loading=ref(false),saving=ref(false),createVisible=ref(false),targetsVisible=ref(false),targetLoading=ref(false),activeTask=ref(null),targets=ref([]),deletedTargets=ref([]);
const displayTargets=computed(()=>[...targets.value,...deletedTargets.value]);
const canManage=computed(()=>auth.hasPermission('influencers.outreach.manage'));
const form=reactive({task_no:'',task_name:'',store:null,external_product_id:'',sku_prefix:'',target_count:1,owner:null});
const targetForm=reactive({influencer:null,notes:''});
const storeOptions=ref([]),bdOptions=ref([]);
const isTerminal=(row)=>['completed','cancelled'].includes(row?.status);const isTargetTerminal=(row)=>['success','rejected','no_response','blocked'].includes(row?.outreach_result);const progress=(row)=>row.target_count?Math.min(100,Math.round((row.linked_count||0)*100/row.target_count)):0;
async function load(){loading.value=true;const r=await fetchOutreachTasks({page:page.value,page_size:pageSize.value});loading.value=false;if(r.success){rows.value=collectionRows(r.data);total.value=collectionTotal(r.data)}else ElMessage.error(formatInfluencerError(r,'任务加载失败'))}
async function openCreate(){Object.assign(form,{task_no:`DRJL${Date.now().toString().slice(-6)}`,task_name:'',store:null,external_product_id:'',sku_prefix:'',target_count:1,owner:null});const r=await fetchOutreachTaskOptions();if(!r.success)return ElMessage.error(formatInfluencerError(r,'店铺和 BD 选项加载失败'));storeOptions.value=r.data?.stores||[];bdOptions.value=r.data?.bd_users||[];createVisible.value=true}
async function submit(){if(!form.task_no||!form.task_name||!form.store||!form.owner)return ElMessage.warning('请填写必填字段');saving.value=true;const r=await createOutreachTask({...form});saving.value=false;if(!r.success)return ElMessage.error(formatInfluencerError(r));createVisible.value=false;ElMessage.success('任务已创建');load()}
async function changeStatus(row,status){const r=await updateOutreachStatus(row.id,status,row.version);if(!r.success)return ElMessage.error(formatInfluencerError(r));ElMessage.success('状态已更新');load()}
async function openTargets(row){activeTask.value=row;targetsVisible.value=true;deletedTargets.value=[];await loadTargets()}
async function loadTargets(){targetLoading.value=true;const r=await fetchOutreachTargets(activeTask.value.id,{page:1,page_size:100});targetLoading.value=false;targets.value=r.success?collectionRows(r.data):[];if(!r.success)ElMessage.error(formatInfluencerError(r))}
async function refreshActiveTask(){await load();activeTask.value=rows.value.find(item=>item.id===activeTask.value?.id)||activeTask.value}
async function addTarget(){if(!targetForm.influencer)return ElMessage.warning('请输入达人 ID');const r=await addOutreachTarget(activeTask.value.id,targetForm.influencer,undefined,targetForm.notes);if(!r.success)return ElMessage.error(formatInfluencerError(r));Object.assign(targetForm,{influencer:null,notes:''});ElMessage.success('达人已关联');await loadTargets();await refreshActiveTask()}
async function updateResult(row){const r=await updateOutreachTarget(activeTask.value.id,row.id,{outreach_result:row.outreach_result},row.version);if(!r.success){ElMessage.error(formatInfluencerError(r));return loadTargets()}Object.assign(row,detailData(r.data));await refreshActiveTask()}
async function removeTarget(row){const r=await deleteOutreachTarget(activeTask.value.id,row.id,row.version);if(!r.success)return ElMessage.error(formatInfluencerError(r));const deleted={...row,...detailData(r.data),is_deleted:true};deletedTargets.value.push(deleted);targets.value=targets.value.filter(item=>item.id!==row.id);ElMessage.success('达人目标已删除');await refreshActiveTask()}
async function restoreTarget(row){const r=await restoreOutreachTarget(activeTask.value.id,row,row.version);if(!r.success)return ElMessage.error(formatInfluencerError(r));deletedTargets.value=deletedTargets.value.filter(item=>item.id!==row.id);targets.value.push(detailData(r.data));ElMessage.success('达人目标已恢复');await refreshActiveTask()}
onMounted(load);
</script>

<style scoped>.creator-page{display:grid;gap:18px}.creator-page header{display:flex;justify-content:space-between;align-items:end;padding:24px;border-radius:16px;background:linear-gradient(120deg,#0b5345,#167d68);color:#fff}.creator-page h1{margin:6px 0}.creator-page p{margin:0;opacity:.82}.target-bar{display:flex;gap:10px;margin-bottom:14px}.target-bar .el-input{max-width:320px}.el-pagination{margin-top:16px;justify-content:flex-end}@media(max-width:800px){.creator-page header,.target-bar{align-items:stretch;flex-direction:column}}</style>
