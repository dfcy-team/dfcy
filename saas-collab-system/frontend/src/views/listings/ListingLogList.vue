<template><AppPage title="Listing Logs" eyebrow="LISTING LOGS" subtitle="Review step-level execution evidence by task." capability="connected"><el-table :data="rows" v-loading="loading" border><el-table-column prop="task" label="Task" width="100" /><el-table-column prop="step_no" label="Step" width="80" /><el-table-column prop="step_name" label="Step name" /><el-table-column prop="status" label="Status" width="120" /><el-table-column prop="message" label="Message" /></el-table></AppPage></template>
<script setup>
import { onMounted, ref } from 'vue';
import AppPage from '../../components/AppPage.vue';
import { fetchListingLogs } from '../../api/listings';
const rows = ref([]); const loading = ref(false);
async function load() { loading.value = true; const response = await fetchListingLogs(); loading.value = false; const data = response.data; rows.value = response.success ? (Array.isArray(data) ? data : data?.results || data?.items || []) : []; }
onMounted(load);
</script>
