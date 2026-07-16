<template>
  <Phase3DecisionPage
    eyebrow="报表治理"
    title="报表导出"
    subtitle="查看导出范围、敏感字段规则和审计记录。"
    boundary-note="导出必须由后端校验 data_scope 和独立导出权限，并记录审计；财务字段默认聚合或脱敏。当前申请按钮不会生成真实文件。"
    :loader="fetchReportExports"
    :filters="filters"
    :columns="columns"
    :row-actions="rowActions"
    :detail-fields="detailFields"
    table-title="可申请报表"
    table-note="下载文件应遵守保留周期并避免在终端或日志输出敏感内容"
  />
</template>

<script setup>
import Phase3DecisionPage from '../../components/Phase3DecisionPage.vue';
import { fetchReportExports } from '../../api/reportExports';

const filters = [
  { key: 'audit_status', label: '审计状态', options: [{ label: '待授权', value: 'pending' }, { label: '已批准', value: 'approved' }, { label: '已拒绝', value: 'rejected' }] },
  { key: 'sensitive', label: '敏感数据', options: [{ label: '包含', value: 'true' }, { label: '不包含', value: 'false' }] }
];
const columns = [
  { prop: 'report_code', label: '报表编码', width: 170 }, { prop: 'report_name', label: '报表名称', width: 160 },
  { prop: 'data_scope', label: '数据范围', width: 210 }, { prop: 'sensitive_fields', label: '敏感字段', width: 170 },
  { prop: 'export_policy', label: '导出策略', width: 220 }, { prop: 'retention_days', label: '保留天数' },
  { prop: 'last_export_at', label: '最近导出', width: 160 }, { prop: 'audit_status', label: '审计状态', type: 'status' }
];
const rowActions = [
  { label: '审计记录', mode: 'detail' },
  { label: '申请导出', permission: 'reports.export', confirmMessage: '导出需要后端重新校验权限、数据范围和敏感字段策略。当前操作不会生成文件。', message: '报表导出接口尚未提供，当前保持 pending。' }
];
const detailFields = [
  { prop: 'report_code', label: '报表编码' }, { prop: 'data_scope', label: '数据范围' }, { prop: 'export_policy', label: '导出策略' },
  { prop: 'retention_days', label: '保留天数' }, { prop: 'audit', label: '审计详情', type: 'json' }
];
</script>
