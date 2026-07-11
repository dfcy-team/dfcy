<template><Phase2DataPage title="供应商绩效列表" note="GET /api/internal/suppliers/performance/" :loader="fetchSupplierPerformance" :columns="columns" :filters="['周期','供应商']" empty-text="暂无绩效列表" /></template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchSupplierPerformance } from '../../api/supplierPerformance';
const columns = [
  { prop: 'supplier_id', label: '供应商ID' }, { prop: 'supplier_name', label: '供应商' }, { prop: 'total_tasks', label: '任务数' },
  { prop: 'overdue_tasks', label: '逾期任务' }, { prop: 'exception_tasks', label: '异常任务' }, { prop: 'feedback_timeliness_rate', label: '反馈及时率' }, { prop: 'total_score', label: '评分' }
];
</script>
