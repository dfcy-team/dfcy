<template><Phase2DataPage title="供应商绩效详情" note="GET /api/internal/suppliers/performance/{supplier_id}/" mode="detail" :loader="() => fetchSupplierPerformanceDetail(route.params.supplierId || 10001)" :detail-fields="fields" empty-text="暂无绩效详情" /></template>
<script setup>
import { useRoute } from 'vue-router';
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchSupplierPerformanceDetail } from '../../api/supplierPerformance';
const route = useRoute();
const fields = [
  { prop: 'supplier_id', label: '供应商ID' }, { prop: 'supplier_name', label: '供应商' }, { prop: 'period', label: '周期' },
  { prop: 'total_tasks', label: '任务总数' }, { prop: 'on_time_tasks', label: '及时任务' }, { prop: 'overdue_tasks', label: '逾期任务' },
  { prop: 'exception_tasks', label: '异常任务' }, { prop: 'total_shipments', label: '出货数' }, { prop: 'accurate_shipments', label: '准确出货' },
  { prop: 'on_time_rate', label: '交付及时率' }, { prop: 'shipment_accuracy_rate', label: '出货准确率' }, { prop: 'total_score', label: '评分' }, { prop: 'rule_version', label: '规则版本' }
];
</script>
