<template><FinanceRecordList title="提现记录" note="查看导入的已完成提现资料，自动平台提现采集尚未接入。" :loader="fetchWithdrawalRecords" :columns="columns" :statuses="statuses" :platform-filter="true"  /></template>
<script setup>
import FinanceRecordList from './FinanceRecordList.vue';
import { fetchWithdrawalRecords } from '../../api/financeReconciliation';
const columns = [{"prop": "platform", "label": "平台"}, {"prop": "withdrawal_no", "label": "提现编号"}, {"prop": "currency", "label": "币种"}, {"prop": "requested_amount", "label": "申请金额"}, {"prop": "expected_amount", "label": "预计到账"}, {"prop": "completed_at", "label": "完成时间"}, {"prop": "status", "label": "状态"}];
const statuses = ["requested", "completed", "cancelled"];
</script>
