<template><Phase2DataPage title="提现记录（只读）" note="GET /api/finance/withdrawals/；本页不执行提现。" :loader="fetchWithdrawalRecords" :columns="columns" :filter-configs="filters" empty-text="暂无提现记录" /></template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchWithdrawalRecords } from '../../api/financeReconciliation';
const columns = [
  { prop: 'platform', label: '平台' }, { prop: 'withdrawal_no', label: '取款编号' }, { prop: 'requested_amount', label: '申请金额' },
  { prop: 'expected_amount', label: '预计到账' }, { prop: 'completed_at', label: '完成时间' }, { prop: 'status', label: '状态', type: 'status' }
];
const filters = [
  { key: 'platform', label: '平台', placeholder: 'demo-platform' },
  { key: 'currency', label: '币种', placeholder: 'USD' },
  { key: 'status', label: '状态', options: [{ label: '已申请', value: 'requested' }, { label: '已完成', value: 'completed' }, { label: '已取消', value: 'cancelled' }] }
];
</script>
