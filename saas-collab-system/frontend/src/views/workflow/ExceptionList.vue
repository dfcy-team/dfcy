<template>
  <RPAResourcePage title="异常中心" note="集中处理商品、采购、供应商、刊登、财务、RPA和同步异常。"
    boundary-note="异常处置只更新异常闭环状态，不修改原业务记录，也不触发真实RPA或资金操作。"
    :loader="fetchWorkflowExceptions" :columns="columns" :filters="filters" :row-actions="actions" empty-text="暂无授权范围内的异常" />
</template>

<script setup>
import RPAResourcePage from '../../components/RPAResourcePage.vue';
import { assignWorkflowException, closeWorkflowException, fetchWorkflowExceptions, resolveWorkflowException } from '../../api/workflow';
import { useAuthStore } from '../../stores/auth';

const auth = useAuthStore();

const filters = [
  { key: 'module', label: '模块', options: ['product', 'purchasing', 'supplier', 'listing', 'finance', 'rpa', 'integration'] },
  { key: 'status', label: '状态', options: ['open', 'assigned', 'resolved', 'closed'] }
];
const columns = [
  { prop: 'title', label: '异常主题', width: 220 }, { prop: 'module', label: '模块' },
  { prop: 'severity', label: '级别', type: 'status' }, { prop: 'status', label: '状态', type: 'status' },
  { prop: 'assigned_to_id', label: '负责人' }, { prop: 'business_id', label: '业务ID', width: 150 },
  { prop: 'created_at', label: '发现时间', width: 180 }
];
const actions = [
  { label: '详情', permission: 'workflow.exceptions.view', route: (row) => `/workflow/exceptions/${row.id}` },
  { label: '分配给我', permission: 'workflow.exceptions.manage', disabled: (row) => !['open', 'assigned'].includes(row.status), confirmMessage: '确认由当前登录用户处理此异常？', handler: (row) => assignWorkflowException(row.id, { assignee_id: auth.currentUser?.user_id }) },
  { label: '解决', permission: 'workflow.exceptions.manage', disabled: (row) => !['open', 'assigned'].includes(row.status), confirmMessage: '仅记录异常解决说明，不修改原业务数据。', handler: (row) => resolveWorkflowException(row.id, { resolution: 'Resolved from UI-P4 demo flow.' }) },
  { label: '关闭', permission: 'workflow.exceptions.manage', disabled: (row) => row.status !== 'resolved', confirmMessage: '确认关闭已解决异常？', handler: (row) => closeWorkflowException(row.id) }
];
</script>
