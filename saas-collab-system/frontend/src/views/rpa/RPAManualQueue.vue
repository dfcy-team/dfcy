<template>
  <RPAResourcePage
    title="RPA人工接管队列"
    note="GET /api/internal/rpa/manual-queue/"
    boundary-note="人工接管只分配检查责任人；恢复执行必须显式授权 Mock 重试。"
    :loader="fetchRpaManualQueue"
    :columns="columns"
    :row-actions="actions"
    empty-text="暂无人工接管任务"
  />
</template>

<script setup>
import RPAResourcePage from '../../components/RPAResourcePage.vue';
import { assignRpaManual, retryRpaMock } from '../../api/rpa';
import { fetchRpaManualQueue } from '../../api/rpaStability';

const columns = [
  { prop: 'task_id', label: '任务编号' }, { prop: 'task_type', label: '任务类型', width: 220 },
  { prop: 'status', label: '任务状态', type: 'status' }, { prop: 'manual_assignee', label: '人工负责人' },
  { prop: 'manual_reason', label: '接管原因', width: 240 }, { prop: 'retry_count', label: '重试次数' }
];
const actions = [
  {
    label: '分配给我', permission: 'rpa.tasks.manage',
    confirmMessage: '确认承担此任务的人工检查，不执行平台动作。',
    handler: (row) => assignRpaManual(row.id, { reason: 'Assigned from manual queue.' })
  },
  {
    label: 'Mock重试', type: 'warning', permission: 'rpa.tasks.manage',
    confirmMessage: '仅进入 Mock/dry-run 队列，不连接真实平台。',
    handler: (row) => retryRpaMock(row.id)
  }
];
</script>
