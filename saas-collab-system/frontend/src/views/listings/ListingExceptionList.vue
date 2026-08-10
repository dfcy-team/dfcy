<template><AppPage title="Listing Exceptions" eyebrow="LISTING EXCEPTIONS" subtitle="Review validation, queue and execution errors." capability="connected"><el-table :data="rows" v-loading="loading" border><el-table-column prop="task" label="Task" width="100" /><el-table-column prop="error_code" label="Error code" width="150" /><el-table-column prop="message" label="Message" /><el-table-column label="Resolved" width="100"><template #default="{ row }"><el-tag :type="row.is_resolved ? 'success' : 'danger'">{{ row.is_resolved ? 'Yes' : 'No' }}</el-tag></template></el-table-column><el-table-column prop="created_at" label="Created" width="180" /></el-table></AppPage></template>
<script setup>
import { onMounted, ref } from 'vue';
import AppPage from '../../components/AppPage.vue';
import { fetchListingExceptions } from '../../api/listings';
const rows = ref([]); const loading = ref(false);
async function load() { loading.value = true; const response = await fetchListingExceptions(); loading.value = false; const data = response.data; rows.value = response.success ? (Array.isArray(data) ? data : data?.results || data?.items || []) : []; }
onMounted(load);
</script>
