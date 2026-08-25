<template>
  <RPAResourcePage title="报表导出与下载审计" note="查看本人授权范围内的通用报表占位导出和下载审计。"
    boundary-note="通用报表仍签发 placeholder 引用；真实销售 CSV/TXT 请使用销售管理的导出页面。"
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
  { label: '再次申请', permission: 'reports.export', confirmMessage: '后端将按当前权限和 data_scope 重新生成占位导出申请。', handler: (row) => createReportExport({ report_type: row.report_type, filters: {} }) },
  { label: '申请下载', permission: 'reports.download', disabled: (row) => row.status !== 'completed', confirmMessage: '后端将重新校验权限并记录下载审计；通用报表不会返回真实文件。', handler: (row) => downloadReportExport(row.id) }
];
</script>
