<template>
  <Phase2DataPage
    title="清仓申请"
    note="GET /api/internal/workflow/approvals/?approval_type=clearance"
    risk-note="清仓申请仅进入审批流，不改变商品状态、不改价、不下架，也不触发采购或RPA。"
    :loader="loadClearanceRequests"
    :columns="columns"
    :action-configs="actionConfigs"
    empty-text="当前授权范围内暂无清仓申请"
  />
</template>

<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { createMockApproval, fetchApprovals } from '../../api/workflow';

const loadClearanceRequests = () => fetchApprovals({ approval_type: 'clearance', page: 1, page_size: 20 });
const actionConfigs = [
  {
    label: '创建Mock申请',
    permission: 'workflow.approvals.submit',
    confirmMessage: '仅创建清仓审批占位，不执行清仓、改价、下架或RPA。',
    handler: () => createMockApproval({
      approval_type: 'clearance',
      title: 'Demo clearance review',
      business_type: 'product_lifecycle',
      business_id: 'demo-clearance-item',
      reason: 'Demo review only',
      idempotency_key: 'ui-p6-demo-clearance'
    })
  }
];
const columns = [
  { prop: 'id', label: '申请编号' },
  { prop: 'title', label: '申请主题', width: 200 },
  { prop: 'business_id', label: '业务ID' },
  { prop: 'status', label: '审批状态', type: 'status' },
  { prop: 'requested_by_id', label: '申请人' },
  { prop: 'created_at', label: '申请时间', width: 180 }
];
</script>
