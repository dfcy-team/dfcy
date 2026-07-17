<template>
  <RPAResourcePage title="报表导出与下载审计" note="查看本人授权范围内的占位导出和下载审计。"
    boundary-note="下载必须由后端重新校验tenant、data_scope、报表权限和敏感字段策略；当前只签发短期placeholder引用，不生成真实文件。"
    :loader="fetchReportExports" :columns="columns" :filters="filters" :row-actions="actions" empty-text="暂无导出申请" />
</template>

<script setup>
import RPAResourcePage from '../../components/RPAResourcePage.vue';
import { createReportExport, downloadReportExport, fetchReportExports } from '../../api/reportExports';

const filters = [
  { key: 'report_type', label: '报表类型', options: ['analytics_summary', 'inventory_alerts', 'replenishment', 'lifecycle', 'business_alerts', 'finance_summary'] },
  { key: 'status', label: '状态', options: ['completed', 'rejected'] }
];
const columns = [
  { prop: 'id', label: '导出编号' }, { prop: 'report_type', label: '报表类型', width: 190 },
  { prop: 'status', label: '状态', type: 'status' }, { prop: 'row_count', label: '行数' },
  { prop: 'audit_count', label: '审计次数' }, { prop: 'masked_file_reference', label: '脱敏引用', width: 260 },
  { prop: 'requested_at', label: '申请时间', width: 180 }
];
const actions = [
  { label: '再次申请', permission: 'reports.export', confirmMessage: '后端将按当前权限和data_scope重新生成占位导出申请。', handler: (row) => createReportExport({ report_type: row.report_type, filters: {} }) },
  { label: '申请下载', permission: 'reports.download', disabled: (row) => row.status !== 'completed', confirmMessage: '后端将重新校验权限并记录下载审计；不会返回真实文件。', handler: (row) => downloadReportExport(row.id) }
];
</script>
