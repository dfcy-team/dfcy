<template>
  <RPAResourcePage
    title="RPA运行记录"
    note="GET /api/internal/rpa/runs/"
    boundary-note="运行状态与任务状态分别展示；错误和证据引用均已脱敏。"
    :loader="fetchRpaRuns"
    :columns="columns"
    :filters="filters"
    :row-actions="actions"
    empty-text="暂无运行记录"
  />
</template>

<script setup>
import { useRouter } from 'vue-router';
import RPAResourcePage from '../../components/RPAResourcePage.vue';
import { fetchRpaRuns } from '../../api/rpaStability';

const router = useRouter();
const columns = [
  { prop: 'task_code', label: '任务编号' }, { prop: 'attempt_no', label: '运行次数', width: 100 },
  { prop: 'agent', label: '设备' }, { prop: 'status', label: '运行状态', type: 'status' },
  { prop: 'heartbeat_at', label: '最近心跳', width: 180 }, { prop: 'failed_step', label: '失败步骤' },
  { prop: 'last_success_step', label: '最后成功步骤' }, { prop: 'masked_error', label: '脱敏错误', width: 220 }
];
const filters = [{ key: 'status', label: '状态', options: ['claimed', 'running', 'success', 'failed', 'retrying', 'manual_required', 'cancelled'] }];
const actions = [{ label: '详情', permission: 'rpa.tasks.view', handler: (row) => router.push(`/rpa/runs/${row.id}`) }];
</script>
