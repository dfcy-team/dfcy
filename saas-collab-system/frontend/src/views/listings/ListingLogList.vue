<template><AppPage title="刊登日志" eyebrow="刊登日志" subtitle="按任务查看步骤级执行记录。" capability="connected"><el-table :data="rows" v-loading="loading" border><el-table-column prop="task" label="任务" width="100" /><el-table-column prop="step_no" label="步骤" width="80" /><el-table-column prop="step_name" label="步骤名称" /><el-table-column prop="status" label="状态" width="120" /><el-table-column prop="message" label="消息" /></el-table></AppPage></template>
<script setup>
import { onMounted, ref } from 'vue';
import AppPage from '../../components/AppPage.vue';
import { fetchListingLogs } from '../../api/listings';
const rows = ref([]); const loading = ref(false);
async function load() { loading.value = true; const response = await fetchListingLogs(); loading.value = false; const data = response.data; rows.value = response.success ? (Array.isArray(data) ? data : data?.results || data?.items || []) : []; }
onMounted(load);
</script>
