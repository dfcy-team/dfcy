<template>
  <WorkflowDetailPage title="审批详情" subtitle="查看申请依据、当前结论和不可变审计时间线。"
    boundary-note="前端不能绕过后端审批权限和状态机；审批通过也不会在UI-P4自动执行高风险业务动作。"
    :loader="() => fetchApproval(route.params.id)" :fields="fields" :actions="actions" />
</template>

<script setup>
import { useRoute } from 'vue-router';
import WorkflowDetailPage from '../../components/WorkflowDetailPage.vue';
import { approveApproval, fetchApproval, rejectApproval, withdrawApproval } from '../../api/workflow';

const route = useRoute();
const fields = [
  { prop: 'approval_type', label: '审批类型' }, { prop: 'title', label: '审批主题' },
  { prop: 'business_type', label: '业务类型' }, { prop: 'business_id', label: '业务ID' },
  { prop: 'requested_by_id', label: '申请人' }, { prop: 'reviewed_by_id', label: '审批人' },
  { prop: 'status', label: '状态', type: 'status' }, { prop: 'reason', label: '申请理由' },
  { prop: 'decision_note', label: '审批意见' }, { prop: 'created_at', label: '申请时间' }
];
const actions = [
  { label: '通过', permission: 'workflow.approvals.review', disabled: (row) => row.status !== 'pending', confirmMessage: '仅记录审批结论，不执行后续业务动作。', handler: (row) => approveApproval(row.id, { note: 'Reviewed from detail.' }) },
  { label: '驳回', type: 'danger', permission: 'workflow.approvals.review', disabled: (row) => row.status !== 'pending', confirmMessage: '确认驳回？', handler: (row) => rejectApproval(row.id, { note: 'Rejected from detail.' }) },
  { label: '撤回', permission: 'workflow.approvals.withdraw', disabled: (row) => row.status !== 'pending', confirmMessage: '仅申请人可撤回。', handler: (row) => withdrawApproval(row.id, { note: 'Withdrawn from detail.' }) }
];
</script>
