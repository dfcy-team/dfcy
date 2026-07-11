<template><Phase2DataPage title="供应商绩效看板" note="GET /api/internal/suppliers/performance/" risk-note="内部汇总以后端权限为准，不展示财务敏感信息。" :loader="fetchSupplierPerformance" :columns="columns" :filters="['周期','供应商']" :actions="['calculate-mock 占位']" empty-text="暂无绩效数据" /></template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchSupplierPerformance } from '../../api/supplierPerformance';
const columns = [
  { prop: 'supplier_id', label: '供应商ID' }, { prop: 'supplier_name', label: '供应商' }, { prop: 'period', label: '周期' },
  { prop: 'total_tasks', label: '任务数' }, { prop: 'on_time_rate', label: '交付及时率' }, { prop: 'overdue_rate', label: '逾期率' },
  { prop: 'exception_rate', label: '异常率' }, { prop: 'shipment_accuracy_rate', label: '出货准确率' }, { prop: 'total_score', label: '评分' }
];
</script>
