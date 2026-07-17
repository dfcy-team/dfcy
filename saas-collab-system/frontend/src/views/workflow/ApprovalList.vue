<template>
  <RPAResourcePage title="审批中心" note="统一查看采购、价格、刊登、清仓、财务和报表导出审批。"
    boundary-note="审批动作必须由后端状态机、permission-specific data_scope和申请/审批人分离规则校验；不会直接执行高风险业务动作。"
    :loader="fetchApprovals" :columns="columns" :filters="filters" :row-actions="actions" empty-text="暂无授权范围内的审批" />
</template>

<script setup>
import RPAResourcePage from '../../components/RPAResourcePage.vue';
import { approveApproval, fetchApprovals, rejectApproval, withdrawApproval } from '../../api/workflow';

const filters = [
  { key: 'approval_type', label: '审批类型', options: ['purchase', 'price', 'listing', 'clearance', 'finance', 'report_export'] },
  { key: 'status', label: '状态', options: ['pending', 'approved', 'rejected', 'withdrawn'] }
];
const columns = [
  { prop: 'title', label: '审批主题', width: 210 }, { prop: 'approval_type', label: '类型' },
  { prop: 'business_type', label: '业务类型' }, { prop: 'business_id', label: '业务ID', width: 150 },
  { prop: 'requested_by_id', label: '申请人' }, { prop: 'status', label: '状态', type: 'status' },
  { prop: 'created_at', label: '申请时间', width: 180 }
];
const actions = [
  { label: '详情', permission: 'workflow.approvals.view', route: (row) => `/workflow/approvals/${row.id}` },
  { label: '通过', permission: 'workflow.approvals.review', disabled: (row) => row.status !== 'pending', confirmMessage: '仅确认审批结论，不执行采购、改价、刊登、清仓、财务或RPA动作。', handler: (row) => approveApproval(row.id, { note: 'Reviewed from UI-P4.' }) },
  { label: '驳回', type: 'danger', permission: 'workflow.approvals.review', disabled: (row) => row.status !== 'pending', confirmMessage: '确认驳回此审批？', handler: (row) => rejectApproval(row.id, { note: 'Rejected from UI-P4.' }) },
  { label: '撤回', permission: 'workflow.approvals.withdraw', disabled: (row) => row.status !== 'pending', confirmMessage: '仅申请人可撤回自己的待审批记录。', handler: (row) => withdrawApproval(row.id, { note: 'Withdrawn from UI-P4.' }) }
];
</script>
