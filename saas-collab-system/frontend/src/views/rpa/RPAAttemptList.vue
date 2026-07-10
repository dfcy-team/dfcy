<template><Phase2DataPage title="RPA任务尝试" note="GET /api/internal/rpa/attempts/" risk-note="错误信息已脱敏，截图仅为 placeholder evidence。" :loader="fetchRpaAttempts" :columns="columns" :filters="['状态','Agent']" empty-text="暂无任务尝试" /></template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchRpaAttempts } from '../../api/rpaStability';
const columns = [
  { prop: 'task', label: '任务' }, { prop: 'attempt_no', label: '次数' }, { prop: 'agent', label: 'Agent' },
  { prop: 'heartbeat_at', label: '心跳' }, { prop: 'status', label: '状态', type: 'status' }, { prop: 'failed_step', label: '失败步骤' },
  { prop: 'last_success_step', label: '最后成功步骤' }, { prop: 'masked_error', label: '脱敏错误' }
];
</script>
