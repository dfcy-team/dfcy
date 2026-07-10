<template>
  <Phase2DataPage
    title="同步执行记录"
    note="GET /api/internal/integrations/sync-runs/"
    :loader="fetchSyncRuns"
    :filters="['平台', '状态', '资源类型']"
    :columns="columns"
    empty-text="暂无执行记录"
  />
</template>

<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchSyncRuns } from '../../api/integrations';

const columns = [
  { prop: 'run_id', label: '执行ID' },
  { prop: 'platform', label: '平台' },
  { prop: 'resource_type', label: '资源类型' },
  { prop: 'status', label: '状态', type: 'status' },
  { prop: 'started_at', label: '开始时间' },
  { prop: 'finished_at', label: '结束时间' },
  { prop: 'fetched_count', label: '抓取数' },
  { prop: 'failed_count', label: '失败数' },
  { prop: 'retry_count', label: '重试次数' },
  { prop: 'masked_error_message', label: '脱敏错误' }
];
</script>
