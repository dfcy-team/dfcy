<template><Phase2DataPage title="银行到账" note="GET /api/finance/bank-receipts/" risk-note="银行账号仅掩码展示，不接真实银行。" :loader="fetchBankReceipts" :columns="columns" :filters="['币种','状态']" empty-text="暂无到账记录" /></template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchBankReceipts } from '../../api/financeReconciliation';
const columns = [
  { prop: 'masked_account', label: '掩码账号' }, { prop: 'currency', label: '币种' }, { prop: 'receipt_amount', label: '到账金额' },
  { prop: 'receipt_date', label: '到账日期' }, { prop: 'reference_no', label: '参考号' }, { prop: 'status', label: '状态', type: 'status' }
];
</script>
