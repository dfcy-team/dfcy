<template><Phase2DataPage title="取款记录" note="GET /api/finance/withdrawals/" :loader="fetchWithdrawalRecords" :columns="columns" :filters="['平台','状态']" empty-text="暂无取款记录" /></template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchWithdrawalRecords } from '../../api/financeReconciliation';
const columns = [
  { prop: 'platform', label: '平台' }, { prop: 'withdrawal_no', label: '取款编号' }, { prop: 'requested_amount', label: '申请金额' },
  { prop: 'expected_amount', label: '预计到账' }, { prop: 'completed_at', label: '完成时间' }, { prop: 'status', label: '状态', type: 'status' }
];
</script>
