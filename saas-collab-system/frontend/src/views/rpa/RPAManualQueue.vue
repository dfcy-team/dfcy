<template><Phase2DataPage title="RPA人工接管队列" note="GET /api/internal/rpa/manual-queue/" risk-note="人工接管操作必须调用后端internal管理接口；未实现时保持pending/mock。" :loader="fetchRpaManualQueue" :columns="columns" :actions="['assign-manual pending']" empty-text="暂无人工接管任务" /></template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchRpaManualQueue } from '../../api/rpaStability';
const columns = [
  { prop: 'task', label: '任务' }, { prop: 'status', label: '状态', type: 'status' }, { prop: 'failed_step', label: '失败步骤' },
  { prop: 'masked_error', label: '脱敏错误' }, { prop: 'manual_required', label: '需人工' }
];
</script>
