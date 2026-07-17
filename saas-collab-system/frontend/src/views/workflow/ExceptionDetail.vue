<template>
  <WorkflowDetailPage title="异常详情" subtitle="查看异常上下文、处理结果和审计时间线。"
    boundary-note="关闭动作只能用于已解决异常；异常页面不直接修改业务主数据。"
    :loader="() => fetchWorkflowException(route.params.id)" :fields="fields" :actions="actions" />
</template>

<script setup>
import { useRoute } from 'vue-router';
import WorkflowDetailPage from '../../components/WorkflowDetailPage.vue';
import { assignWorkflowException, closeWorkflowException, fetchWorkflowException, resolveWorkflowException } from '../../api/workflow';
import { useAuthStore } from '../../stores/auth';

const route = useRoute();
const auth = useAuthStore();
const fields = [
  { prop: 'module', label: '模块' }, { prop: 'title', label: '异常主题' },
  { prop: 'severity', label: '级别', type: 'status' }, { prop: 'status', label: '状态', type: 'status' },
  { prop: 'business_type', label: '业务类型' }, { prop: 'business_id', label: '业务ID' },
  { prop: 'assigned_to_id', label: '负责人' }, { prop: 'description', label: '异常说明' },
  { prop: 'resolution', label: '解决记录' }, { prop: 'created_at', label: '发现时间' }
];
const actions = [
  { label: '分配给我', permission: 'workflow.exceptions.manage', disabled: (row) => !['open', 'assigned'].includes(row.status), confirmMessage: '确认由当前登录用户处理此异常？', handler: (row) => assignWorkflowException(row.id, { assignee_id: auth.currentUser?.user_id }) },
  { label: '解决', permission: 'workflow.exceptions.manage', disabled: (row) => !['open', 'assigned'].includes(row.status), confirmMessage: '仅更新异常闭环状态。', handler: (row) => resolveWorkflowException(row.id, { resolution: 'Resolved from UI-P4 detail.' }) },
  { label: '关闭', permission: 'workflow.exceptions.manage', disabled: (row) => row.status !== 'resolved', confirmMessage: '确认关闭？', handler: (row) => closeWorkflowException(row.id) }
];
</script>
