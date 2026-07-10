<template><Phase2DataPage title="我的绩效历史" note="GET /api/external/supplier/performance/history/" risk-note="供应商端不得传入其他 supplier_id 获取数据。" :loader="fetchMySupplierPerformanceHistory" :columns="columns" :filters="['周期']" empty-text="暂无绩效历史" /></template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchMySupplierPerformanceHistory } from '../../api/supplierPerformance';
const columns = [
  { prop: 'period', label: '周期' }, { prop: 'total_tasks', label: '任务数' }, { prop: 'on_time_rate', label: '及时率' },
  { prop: 'overdue_rate', label: '逾期率' }, { prop: 'exception_rate', label: '异常率' }, { prop: 'total_score', label: '评分' }
];
</script>
