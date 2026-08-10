<template>
  <AppPage title="Listing Tasks" eyebrow="LISTING TASKS" subtitle="Inspect queued listing execution, channels, modes and attached RPA records." capability="connected">
    <div class="toolbar"><el-select v-model="status" clearable placeholder="All statuses" @change="load"><el-option v-for="item in statuses" :key="item" :value="item" :label="item" /></el-select><el-button :loading="loading" @click="load">Refresh</el-button></div>
    <el-table :data="rows" v-loading="loading" border>
      <el-table-column prop="task_no" label="Task" width="180" /><el-table-column prop="profile_no" label="Profile" min-width="160" />
      <el-table-column label="Execution" width="180"><template #default="{ row }">{{ row.execution_channel }} / {{ row.execution_mode }}</template></el-table-column>
      <el-table-column prop="status" label="Status" width="130" /><el-table-column label="Steps" width="80"><template #default="{ row }">{{ row.steps?.length || 0 }}</template></el-table-column>
      <el-table-column label="Errors" width="80"><template #default="{ row }">{{ row.errors?.length || 0 }}</template></el-table-column>
      <el-table-column prop="rpa_task" label="RPA task" width="100" /><el-table-column label="Detail" width="90"><template #default="{ row }"><el-button link type="primary" @click="open(row)">View</el-button></template></el-table-column>
    </el-table>
    <el-drawer v-model="drawer" title="Listing task detail" size="min(760px, 96vw)"><pre class="json">{{ JSON.stringify(selected, null, 2) }}</pre></el-drawer>
  </AppPage>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import AppPage from '../../components/AppPage.vue';
import { fetchListingTaskDetail, fetchListingTasks } from '../../api/listings';
const rows = ref([]); const loading = ref(false); const status = ref(''); const drawer = ref(false); const selected = ref({});
const statuses = ['pending', 'running', 'succeeded', 'failed', 'cancelled'];
function collection(data) { return Array.isArray(data) ? data : data?.results || data?.items || []; }
async function load() { loading.value = true; const response = await fetchListingTasks(status.value ? { status: status.value } : {}); loading.value = false; rows.value = response.success ? collection(response.data) : []; }
async function open(row) { const response = await fetchListingTaskDetail(row.id); selected.value = response.success ? response.data : row; drawer.value = true; }
onMounted(load);
</script>
<style scoped>.toolbar { display: flex; gap: 10px; margin-bottom: 12px; }.json { white-space: pre-wrap; word-break: break-word; background: #f8fafc; padding: 12px; border-radius: 6px; }</style>
