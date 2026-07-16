<template>
  <RPAResourcePage
    title="RPA任务中心"
    note="GET /api/internal/rpa/tasks/"
    boundary-note="管理端只查看任务状态并授权 Mock 重试；不领取、执行或完成 Agent 任务。"
    :loader="fetchRpaTasks"
    :columns="columns"
    :filters="filters"
    :row-actions="actions"
    empty-text="暂无RPA任务"
  />
</template>

<script setup>
import { useRouter } from 'vue-router';
import RPAResourcePage from '../../components/RPAResourcePage.vue';
import { assignRpaManual, fetchRpaTasks, retryRpaMock } from '../../api/rpa';

const router = useRouter();
const columns = [
  { prop: 'task_id', label: '任务编号', width: 120 },
  { prop: 'task_type', label: '任务类型', width: 220 },
  { prop: 'business_type', label: '业务类型' },
  { prop: 'business_id', label: '业务ID' },
  { prop: 'agent', label: '设备' },
  { prop: 'status', label: '任务状态', type: 'status' },
  { prop: 'retry_count', label: '重试次数', width: 100 },
  { prop: 'manual_assignee', label: '人工负责人' }
];
const filters = [
  { key: 'status', label: '状态', options: ['pending', 'claimed', 'running', 'success', 'failed', 'retrying', 'manual_required', 'cancelled'] },
  { key: 'task_type', label: '任务类型' }
];
const actions = [
  { label: '详情', permission: 'rpa.tasks.view', handler: (row) => router.push(`/rpa/tasks/${row.id}`) },
  {
    label: '分配人工', type: 'warning', permission: 'rpa.tasks.manage',
    disabled: (row) => row.status !== 'manual_required',
    confirmMessage: '仅分配人工检查负责人，不执行平台操作。',
    handler: (row) => assignRpaManual(row.id, { reason: 'Assigned from UI-P3 manual queue.' })
  },
  {
    label: 'Mock重试', type: 'warning', permission: 'rpa.tasks.manage',
    disabled: (row) => !['failed', 'manual_required'].includes(row.status),
    confirmMessage: '仅将任务放回 Mock/dry-run 队列，不触发真实浏览器或平台。',
    handler: (row) => retryRpaMock(row.id)
  }
];
</script>
