<template>
  <section class="creator-page">
    <header><div><span>CREATOR OPERATIONS</span><h1>建联任务</h1><p>任务下发人与实际负责 BD 分离记录，状态变更保留时间与版本。</p></div><el-button type="primary" :disabled="!canManage" @click="dialog=true">新建任务</el-button></header>
    <el-card shadow="never"><el-table v-loading="loading" :data="rows" empty-text="暂无建联任务">
      <el-table-column prop="task_no" label="任务编号" min-width="150"/><el-table-column prop="influencer" label="达人 ID"/><el-table-column prop="store" label="店铺 ID"/><el-table-column prop="owner" label="负责 BD"/><el-table-column prop="status" label="状态"/><el-table-column prop="started_at" label="首次开始" min-width="170"/><el-table-column prop="finalized_at" label="最终时间" min-width="170"/>
      <el-table-column label="操作" width="160"><template #default="{row}"><el-button text :disabled="!canManage||row.status!=='pending'" @click="changeStatus(row,'in_progress')">开始</el-button><el-button text :disabled="!canManage||row.status!=='in_progress'" @click="changeStatus(row,'completed')">完成</el-button></template></el-table-column>
    </el-table><el-pagination v-if="total > 0" v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20,50,100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="changePageSize"/></el-card>
    <el-dialog v-model="dialog" title="新建建联任务" width="520px"><el-form label-width="100px"><el-form-item label="任务编号"><el-input v-model="form.task_no"/></el-form-item><el-form-item label="达人 ID"><el-input-number v-model="form.influencer" :min="1"/></el-form-item><el-form-item label="店铺 ID"><el-input-number v-model="form.store" :min="1"/></el-form-item><el-form-item label="负责 BD ID"><el-input-number v-model="form.owner" :min="1"/></el-form-item></el-form><template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" :loading="saving" @click="submit">创建</el-button></template></el-dialog>
  </section>
</template>
<script setup>
import { computed,onMounted,reactive,ref } from 'vue';import{ElMessage}from'element-plus';import{useAuthStore}from'../../stores/auth';import{createOutreachTask,fetchOutreachTasks,updateOutreachStatus}from'../../api/influencers';import{collectionRows,collectionTotal}from'../../utils/businessResponse';
const auth=useAuthStore(),rows=ref([]),total=ref(0),page=ref(1),pageSize=ref(20),loading=ref(false),saving=ref(false),dialog=ref(false);const form=reactive({task_no:'',influencer:1,store:1,owner:1});const canManage=computed(()=>auth.hasPermission('influencers.outreach.manage'));
async function load(){loading.value=true;const r=await fetchOutreachTasks({page:page.value,page_size:pageSize.value});loading.value=false;if(r.success){rows.value=collectionRows(r.data);total.value=collectionTotal(r.data)}else{rows.value=[];total.value=0;ElMessage.error(r.message)}}
function changePageSize(){page.value=1;load()}
async function submit(){saving.value=true;const r=await createOutreachTask({...form});saving.value=false;if(!r.success)return ElMessage.error(r.message);dialog.value=false;ElMessage.success('任务已创建');await load()}
async function changeStatus(row,status){const r=await updateOutreachStatus(row.id,status,row.version);if(!r.success)return ElMessage.error(r.message);ElMessage.success('状态已更新');await load()}
onMounted(load);
</script>
<style scoped>.creator-page{display:grid;gap:18px}header{display:flex;align-items:end;justify-content:space-between;padding:24px;border-radius:16px;background:linear-gradient(120deg,#0b5345,#167d68);color:#fff}header span{font-size:11px;letter-spacing:.18em;opacity:.75}h1{margin:6px 0;font-size:30px}p{margin:0;opacity:.8}</style>
