import { successResponse } from './index';

export const mockReportExports = () => successResponse({
  status: 'mock', api_status: 'mock',
  summary: [
    { label: '可申请报表', value: 6 }, { label: '含敏感字段', value: 2 }, { label: '待授权', value: 1 }, { label: '本月审计记录', value: 18 }
  ],
  items: [
    {
      report_code: 'DEMO-RPT-SALES', report_name: '销售经营分析', data_scope: '当前租户授权范围', sensitive_fields: '无',
      export_policy: '需 report.export', retention_days: 30, last_export_at: '2026-07-10 15:20', audit_status: 'approved',
      audit: { requester: 'demo-analyst', purpose: '经营复盘演示', format: 'CSV', row_count: 120, sensitive_masking: 'not_required', event_id: 'DEMO-AUDIT-001' }
    },
    {
      report_code: 'DEMO-RPT-FINANCE', report_name: '财务对账摘要', data_scope: '当前租户财务授权范围', sensitive_fields: '金额、银行账号',
      export_policy: '需 finance.export，强制脱敏', retention_days: 7, last_export_at: '--', audit_status: 'pending',
      audit: { requester: '--', purpose: '尚未申请', format: 'CSV', row_count: 0, sensitive_masking: 'required', event_id: 'pending' }
    },
    {
      report_code: 'DEMO-RPT-INVENTORY', report_name: '库存风险明细', data_scope: '当前租户商品范围', sensitive_fields: '采购金额摘要',
      export_policy: '需 report.export，金额脱敏', retention_days: 14, last_export_at: '2026-07-09 11:05', audit_status: 'approved',
      audit: { requester: 'demo-inventory-manager', purpose: '补货建议复核演示', format: 'XLSX', row_count: 48, sensitive_masking: 'applied', event_id: 'DEMO-AUDIT-002' }
    }
  ]
});
