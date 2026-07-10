<template>
  <section class="fix-page">
    <header class="fix-header">
      <div>
        <h1 class="page-title">RPA任务列表</h1>
        <p>管理查询 pending: GET /api/internal/rpa/tasks/；前端不调用 Agent 执行接口 /api/rpa/*。</p>
      </div>
      <el-tag :type="tagType">{{ status }}</el-tag>
    </header>

    <el-alert title="前端 RPA 页面仅用于 internal 管理后台查看，不模拟 RPA Agent token，不执行真实 RPA，不连接真实 BigSeller。" type="info" show-icon :closable="false" />
    <el-alert v-if="message" :title="message" :type="status === 'error' ? 'error' : 'warning'" show-icon :closable="false" />

    <el-table v-loading="loading" :data="rows" border empty-text="暂无RPA任务">
      <el-table-column prop="task_id" label="任务编号" min-width="170" />
      <el-table-column prop="task_type" label="任务类型" min-width="230" show-overflow-tooltip />
      <el-table-column prop="business_type" label="业务类型" min-width="130" />
      <el-table-column prop="business_id" label="业务ID" min-width="150" />
      <el-table-column prop="agent" label="Agent" min-width="150" />
      <el-table-column label="状态" min-width="130">
        <template #default="{ row }"><el-tag :type="rpaStatusType(row.status)">{{ row.status || '-' }}</el-tag></template>
      </el-table-column>
      <el-table-column prop="retry_count" label="重试次数" min-width="100" />
      <el-table-column label="操作" fixed="right" min-width="220">
        <template #default>
          <el-button link type="primary" disabled>查看详情</el-button>
          <el-button link type="warning" disabled>人工接管 pending</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && !message && rows.length === 0" description="暂无RPA任务" />
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { fetchRpaTasks } from '../../api/rpa';

const rows = ref([]);
const loading = ref(false);
const status = ref('loading');
const message = ref('');
const tagType = computed(() => (status.value === 'error' ? 'danger' : status.value === 'fallback' ? 'warning' : 'info'));

function getRows(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.items)) return data.items;
  return [];
}

function rpaStatusType(value) {
  return { success: 'success', failed: 'danger', retrying: 'warning', manual_required: 'warning', running: 'primary' }[value] || 'info';
}

onMounted(async () => {
  loading.value = true;
  try {
    const response = await fetchRpaTasks();
    if (!response.success) throw new Error(response.message || 'RPA任务接口失败');
    rows.value = getRows(response.data);
    status.value = response.data?.api_status || response.data?.status || 'mock';
    if (response.data?.api_status === 'fallback') message.value = response.message;
  } catch (error) {
    status.value = 'error';
    message.value = error?.message || 'RPA任务请求失败';
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.fix-page { display: grid; gap: 16px; }
.fix-header { display: flex; justify-content: space-between; gap: 16px; }
.fix-header p { margin: -8px 0 0; color: #64748b; font-size: 13px; }
</style>
