<template><Phase2DataPage title="我的供应商绩效" note="GET /api/external/supplier/performance/" risk-note="供应商端只展示当前供应商自己的绩效，真实过滤以后端 tenant_id + supplier_id 为准。" mode="detail" :loader="fetchMySupplierPerformance" :detail-fields="fields" empty-text="暂无我的绩效" /></template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchMySupplierPerformance } from '../../api/supplierPerformance';
const fields = [
  { prop: 'period', label: '周期' }, { prop: 'total_tasks', label: '任务数' }, { prop: 'on_time_rate', label: '交付及时率' },
  { prop: 'overdue_rate', label: '逾期率' }, { prop: 'exception_rate', label: '异常率' }, { prop: 'shipment_accuracy_rate', label: '出货准确率' },
  { prop: 'feedback_timeliness_rate', label: '反馈及时率' }, { prop: 'total_score', label: '评分' }, { prop: 'rule_version', label: '评分说明' }
];
</script>
