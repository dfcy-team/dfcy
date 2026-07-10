<template>
  <Phase2DataPage
    title="同步任务"
    note="GET /api/internal/integrations/sync-jobs/"
    risk-note="仅允许 Mock运行或Sandbox占位，不连接真实平台。"
    :loader="fetchSyncJobs"
    :filters="['资源类型', '状态', '计划类型']"
    :actions="['run-mock 占位', 'disable 占位']"
    :columns="columns"
    empty-text="暂无同步任务"
  />
</template>

<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchSyncJobs } from '../../api/integrations';

const columns = [
  { prop: 'resource_type', label: '资源类型' },
  { prop: 'schedule_type', label: '计划类型' },
  { prop: 'status', label: '状态', type: 'status' },
  { prop: 'is_enabled', label: '启用' },
  { prop: 'last_run_at', label: '上次运行' },
  { prop: 'next_run_at', label: '下次运行' },
  { prop: 'retry_count', label: '重试次数' }
];
</script>
