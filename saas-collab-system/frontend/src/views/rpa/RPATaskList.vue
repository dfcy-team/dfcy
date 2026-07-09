<template>
  <section class="rpa-page">
    <header class="rpa-header">
      <div>
        <h1 class="page-title">RPA任务列表</h1>
        <p class="page-note">后续对接API路径：GET /api/internal/rpa/tasks/；Agent 执行接口 /api/rpa/* 不在前端管理页调用。</p>
      </div>
      <el-tag :type="statusTagType">{{ dataStatus }}</el-tag>
    </header>

    <el-alert title="管理后台仅查看RPA任务状态，不执行真实RPA，不模拟RPA Agent token，不连接真实BigSeller。" type="info" show-icon :closable="false" />

    <el-form class="rpa-search" inline>
      <el-form-item label="任务编号"><el-input v-model="filters.task_id" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item label="任务类型"><el-input v-model="filters.task_type" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item label="状态"><el-input v-model="filters.status" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item label="Agent"><el-input v-model="filters.agent" placeholder="Mock搜索条件" /></el-form-item>
      <el-form-item>
        <el-button disabled>搜索占位</el-button>
        <el-button disabled>重置占位</el-button>
      </el-form-item>
    </el-form>

    <el-alert v-if="warningMessage" :title="warningMessage" type="warning" show-icon :closable="false" />
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

    <el-table v-loading="loading" :data="rows" border empty-text="暂无RPA任务">
      <el-table-column prop="task_id" label="任务编号" min-width="170" />
      <el-table-column prop="task_type" label="任务类型" min-width="230" show-overflow-tooltip />
      <el-table-column prop="business_type" label="业务类型" min-width="130" />
      <el-table-column prop="business_id" label="业务ID" min-width="150" />
      <el-table-column prop="agent" label="Agent" min-width="150" />
      <el-table-column label="状态" min-width="130">
        <template #default="{ row }">
          <el-tag :type="rpaStatusType(row.status)">{{ row.status || '-' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="retry_count" label="重试次数" min-width="100" />
      <el-table-column prop="created_at" label="创建时间" min-width="180" />
      <el-table-column prop="completed_at" label="完成时间" min-width="180" />
      <el-table-column label="操作" fixed="right" min-width="210">
        <template #default>
          <el-button link type="primary" disabled>查看详情</el-button>
          <el-button link type="warning" disabled>标记人工接管占位</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && !errorMessage && rows.length === 0" description="暂无RPA任务" />
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { fetchRpaTasks } from '../../api/rpa';

const filters = reactive({
  task_id: '',
  task_type: '',
  status: '',
  agent: ''
});
const rows = ref([]);
const loading = ref(false);
const errorMessage = ref('');
const warningMessage = ref('');
const dataStatus = ref('loading');

const statusTagType = computed(() => {
  if (dataStatus.value === 'mock') return 'info';
  if (dataStatus.value === 'fallback') return 'warning';
  if (dataStatus.value === 'error') return 'danger';
  return 'success';
});

function getRows(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.items)) return data.items;
  return [];
}

function rpaStatusType(status) {
  const typeMap = {
    pending: 'info',
    claimed: 'info',
    running: 'primary',
    success: 'success',
    failed: 'danger',
    retrying: 'warning',
    manual_required: 'warning',
    cancelled: 'info'
  };
  return typeMap[status] || 'info';
}

async function loadRpaTasks() {
  loading.value = true;
  errorMessage.value = '';
  warningMessage.value = '';

  try {
    const response = await fetchRpaTasks();
    if (!response.success) throw new Error(response.message || 'RPA任务接口返回失败');

    rows.value = getRows(response.data);
    dataStatus.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') {
      warningMessage.value = response.message || 'RPA任务接口失败，已显示Mock fallback数据';
    }
  } catch (error) {
    dataStatus.value = 'error';
    errorMessage.value = error?.message || 'RPA任务接口请求失败';
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

onMounted(loadRpaTasks);
</script>

<style scoped>
.rpa-page {
  display: grid;
  gap: 16px;
}

.rpa-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.page-note {
  margin: -8px 0 0;
  color: #64748b;
  font-size: 13px;
}

.rpa-search {
  padding: 12px;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
  background: #fff;
}
</style>
