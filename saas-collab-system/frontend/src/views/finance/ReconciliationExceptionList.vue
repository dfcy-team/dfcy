<template><FinanceRecordList title="对账异常" note="拒绝错误匹配并核实资料后，填写说明登记解决。" :loader="fetchReconciliationExceptions" :columns="columns" :statuses="statuses" :platform-filter="true" exceptions /></template>
<script setup>
import FinanceRecordList from './FinanceRecordList.vue';
import { fetchReconciliationExceptions } from '../../api/financeReconciliation';
const columns = [{"prop": "exception_type", "label": "异常类型"}, {"prop": "difference_amount", "label": "差异金额"}, {"prop": "status", "label": "状态"}, {"prop": "resolution_note", "label": "处理说明"}];
const statuses = ["open", "resolved"];
</script>
