<template>
  <AppPage title="刊登任务" eyebrow="LISTING TASKS" subtitle="查看每次刊登的执行通道、模式、步骤和 RPA 关联。" boundary-note="任务记录的是内部排队与执行结果，暂不代表外部平台已发布。" capability="connected">
    <div class="toolbar"><el-select v-model="status" clearable placeholder="全部状态" @change="load"><el-option v-for="item in statuses" :key="item" :value="item" :label="item" /></el-select><el-button @click="load">刷新</el-button></div>
    <el-table :data="rows" v-loading="loading" border>
      <el-table-column prop="task_no" label="任务编号" width="180" />
      <el-table-column prop="profile_no" label="刊登资料" min-width="160" />
      <el-table-column label="执行" width="180"><template #default="{row}">{{ row.execution_channel }} / {{ row.execution_mode }}</template></el-table-column>
      <el-table-column prop="status" label="状态" width="130" />
      <el-table-column label="步骤" width="90"><template #default="{row}">{{ row.steps?.length || 0 }}</template></el-table-column>
      <el-table-column label="异常" width="90"><template #default="{row}">{{ row.errors?.length || 0 }}</template></el-table-column>
      <el-table-column label="RPA Task" width="100"><template #default="{row}">{{ row.rpa_task || row.rpa_task_id || '—' }}</template></el-table-column>
      <el-table-column label="详情" width="90"><template #default="{row}"><el-button link type="primary" @click="open(row)">查看</el-button></template></el-table-column>
    </el-table>
    <el-drawer v-model="drawer" title="刊登任务详情" size="min(760px, 96vw)"><pre class="json">{{ JSON.stringify(selected, null, 2) }}</pre></el-drawer>
  </AppPage>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import AppPage from '../../components/AppPage.vue';
import { fetchListingTaskDetail, fetchListingTasks } from '../../api/listings';
const rows = ref([]); const loading = ref(false); const status = ref(''); const drawer = ref(false); const selected = ref({});
const statuses = ['pending', 'running', 'succeeded', 'failed', 'cancelled'];
async function load() { loading.value = true; const response = await fetchListingTasks(status.value ? { status: status.value } : {}); loading.value = false; rows.value = response.success ? (response.data?.results || response.data || []) : []; }
async function open(row) { const response = await fetchListingTaskDetail(row.id); selected.value = response.success ? response.data : row; drawer.value = true; }
onMounted(load);
</script>

<style scoped>
.toolbar { display:flex; gap:10px; margin-bottom:12px; }
.json { white-space:pre-wrap; word-break:break-word; background:#f8fafc; padding:12px; border-radius:6px; }
</style>
