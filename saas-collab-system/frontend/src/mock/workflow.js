import { successResponse } from './index';

const approvals = [
  {
    id: 1, approval_type: 'purchase', title: 'Demo采购建议审批', business_type: 'purchase_suggestion',
    business_id: 'demo-purchase-001', status: 'pending', requested_by_id: 1001, reviewed_by_id: null,
    reason: '仅用于UI-P4 Mock流程验证', decision_note: '', created_at: '2026-07-16T08:00:00Z',
    audit_events: [{ action: 'submit_mock', from_status: '', to_status: 'pending', created_at: '2026-07-16T08:00:00Z' }]
  },
  {
    id: 2, approval_type: 'report_export', title: 'Demo报表导出审批', business_type: 'report_export',
    business_id: 'demo-export-001', status: 'approved', requested_by_id: 1002, reviewed_by_id: 1003,
    reason: '演示脱敏导出审批', decision_note: 'Demo approved', created_at: '2026-07-16T07:00:00Z',
    audit_events: [{ action: 'approve', from_status: 'pending', to_status: 'approved', created_at: '2026-07-16T07:10:00Z' }]
  }
];

const exceptions = [
  {
    id: 1, module: 'integration', title: 'Demo同步结果待人工核对', severity: 'high', status: 'assigned',
    business_type: 'sync_run', business_id: 'demo-run-001', assigned_to_id: 1003,
    description: 'Mock数据质量差异', resolution: '', created_at: '2026-07-16T08:20:00Z',
    audit_events: [{ action: 'assign', from_status: 'open', to_status: 'assigned', created_at: '2026-07-16T08:25:00Z' }]
  }
];

const collaborationEvents = [
  {
    id: 1, channel: 'feishu', event_id: 'demo-event-001', event_type: 'mock_feedback',
    payload_hash: 'demo-payload-hash', masked_summary: { subject: 'Demo回填', action: 'acknowledge', reference: 'demo-001' },
    status: 'pending_confirmation', confirmed_by_id: null, decision_note: '', received_at: '2026-07-16T08:30:00Z',
    audit_events: [{ action: 'receive_mock', from_status: '', to_status: 'pending_confirmation' }]
  }
];

const page = (results) => successResponse({ status: 'mock', count: results.length, next: null, previous: null, results });
export const mockApprovals = () => page(approvals);
export const mockApprovalDetail = (id) => successResponse({ api_status: 'mock', ...(approvals.find((item) => String(item.id) === String(id)) || approvals[0]) });
export const mockExceptions = () => page(exceptions);
export const mockExceptionDetail = (id) => successResponse({ api_status: 'mock', ...(exceptions.find((item) => String(item.id) === String(id)) || exceptions[0]) });
export const mockCollaborationEvents = () => page(collaborationEvents);
