<template><Phase2DataPage title="对账差异异常" note="GET /api/finance/reconciliation/exceptions/" :loader="fetchReconciliationExceptions" :columns="columns" :actions="['异常分配占位']" empty-text="暂无对账异常" /></template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchReconciliationExceptions } from '../../api/financeReconciliation';
const columns = [
  { prop: 'exception_type', label: '异常类型' }, { prop: 'difference_amount', label: '差异金额' }, { prop: 'status', label: '状态', type: 'status' },
  { prop: 'assigned_to', label: '分配给' }, { prop: 'resolution_note', label: '处理说明' }
];
</script>
