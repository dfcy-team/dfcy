<template><FinanceRecordList title="银行到账" note="查看导入的银行到账资料，银行自动连接尚未接入；账号仅显示尾号掩码。" :loader="fetchBankReceipts" :columns="columns" :statuses="statuses" :platform-filter="false"  /></template>
<script setup>
import FinanceRecordList from './FinanceRecordList.vue';
import { fetchBankReceipts } from '../../api/financeReconciliation';
const columns = [{"prop": "reference_no", "label": "银行参考编号"}, {"prop": "masked_account", "label": "账号掩码"}, {"prop": "currency", "label": "币种"}, {"prop": "receipt_amount", "label": "到账金额"}, {"prop": "receipt_date", "label": "到账日期"}, {"prop": "status", "label": "状态"}];
const statuses = ["imported", "matched", "exception"];
</script>
