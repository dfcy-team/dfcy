<template>
  <Phase2DataPage
    title="对账差异异常"
    note="GET /api/finance/reconciliation/exceptions/；处理动作使用独立 finance.exception.handle 权限。"
    risk-note="差异处理仅记录人工结论和审计，不执行付款、转账或提现。"
    :loader="fetchReconciliationExceptions"
    :columns="columns"
    :filter-configs="filters"
    :row-action-configs="rowActions"
    empty-text="暂无对账异常"
  />
</template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchReconciliationExceptions, resolveReconciliationException } from '../../api/financeReconciliation';
const columns = [
  { prop: 'exception_type', label: '异常类型' }, { prop: 'difference_amount', label: '差异金额' }, { prop: 'status', label: '状态', type: 'status' },
  { prop: 'assigned_to', label: '分配给' }, { prop: 'resolution_note', label: '处理说明' }
];
const filters = [
  { key: 'platform', label: '平台', placeholder: 'demo-platform' },
  { key: 'currency', label: '币种', placeholder: 'USD' },
  { key: 'status', label: '状态', options: [{ label: '待处理', value: 'open' }, { label: '已解决', value: 'resolved' }] }
];
const rowActions = [{
  label: '确认已处理',
  permission: 'finance.exception.handle',
  confirmMessage: '仅记录该合成差异的人工处理结论，不执行任何资金动作。',
  handler: ({ row }) => resolveReconciliationException(row.id, { resolution_note: 'Synthetic exception reviewed.' })
}];
</script>
