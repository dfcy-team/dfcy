<template><AppPage title="刊登异常" eyebrow="刊登异常" subtitle="查看校验、排队和执行错误。" capability="connected"><el-table :data="rows" v-loading="loading" border><el-table-column prop="task" label="任务" width="100" /><el-table-column prop="error_code" label="错误码" width="150" /><el-table-column prop="message" label="消息" /><el-table-column label="是否已解决" width="100"><template #default="{ row }"><el-tag :type="row.is_resolved ? 'success' : 'danger'">{{ row.is_resolved ? '是' : '否' }}</el-tag></template></el-table-column><el-table-column prop="created_at" label="创建时间" width="180" /></el-table></AppPage></template>
<script setup>
import { onMounted, ref } from 'vue';
import AppPage from '../../components/AppPage.vue';
import { fetchListingExceptions } from '../../api/listings';
const rows = ref([]); const loading = ref(false);
async function load() { loading.value = true; const response = await fetchListingExceptions(); loading.value = false; const data = response.data; rows.value = response.success ? (Array.isArray(data) ? data : data?.results || data?.items || []) : []; }
onMounted(load);
</script>
