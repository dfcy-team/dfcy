import { successResponse } from './index';

export const mockConfigDefinitions = () => successResponse({
  status: 'mock', api_status: 'mock',
  summary: [
    { label: '配置项', value: 11 }, { label: '生效中', value: 8 }, { label: '待审批', value: 2 }, { label: '草稿', value: 1 }
  ],
  items: [
    { config_id: 'DEMO-CFG-001', config_key: 'inventory.safety_days', display_name: '库存安全天数', scope: 'tenant', value_summary: '14 天', default_summary: '10 天', version: 'v3.2', approval_status: 'approved', effective_at: '2026-07-15 00:00', sensitive: false, governance: { minimum: '7 天', rollback_version: 'v3.1', actor: 'demo-config-admin', approval_record: 'DEMO-APPROVAL-001' } },
    { config_id: 'DEMO-CFG-002', config_key: 'alerts.silence_hours', display_name: '预警静默时长', scope: 'tenant', value_summary: '4 小时', default_summary: '2 小时', version: 'v2.4-draft', approval_status: 'pending', effective_at: '待审批', sensitive: false, governance: { minimum: '1 小时', rollback_version: 'v2.3', actor: 'demo-config-editor', approval_record: 'pending' } },
    { config_id: 'DEMO-CFG-003', config_key: 'platform.credential_reference', display_name: '平台凭据引用状态', scope: 'system', value_summary: '未配置（专项安全评审）', default_summary: 'disabled', version: 'v1.0', approval_status: 'approved', effective_at: '不启用', sensitive: true, governance: { storage: 'reference metadata only', production: 'disabled', approval_record: 'security-review-required' } }
  ]
});

export const mockConfigValues = () => successResponse({
  status: 'mock', api_status: 'mock',
  summary: [
    { label: '版本记录', value: 24 }, { label: '本月变更', value: 6 }, { label: '已回滚', value: 1 }, { label: '待审批', value: 2 }
  ],
  items: [
    { version_id: 'DEMO-VER-001', config_key: 'inventory.safety_days', version: 'v3.2', old_value_summary: '10 天', new_value_summary: '14 天', change_status: 'approved', actor: 'demo-config-admin', approved_by: 'demo-approver', effective_at: '2026-07-15 00:00', rollback_reason: '', audit: { changed_at: '2026-07-10 15:20', approval_id: 'DEMO-APPROVAL-001', tenant_scope: 'demo-tenant' } },
    { version_id: 'DEMO-VER-002', config_key: 'alerts.silence_hours', version: 'v2.4-draft', old_value_summary: '2 小时', new_value_summary: '4 小时', change_status: 'pending', actor: 'demo-config-editor', approved_by: '--', effective_at: '待审批', rollback_reason: '', audit: { changed_at: '2026-07-11 09:05', approval_id: 'pending', tenant_scope: 'demo-tenant' } },
    { version_id: 'DEMO-VER-003', config_key: 'reports.visible_metrics', version: 'v1.8', old_value_summary: '8 项', new_value_summary: '6 项', change_status: 'rolled_back', actor: 'demo-config-admin', approved_by: 'demo-approver', effective_at: '已回滚', rollback_reason: '演示报表指标缺失', audit: { changed_at: '2026-07-08 13:10', approval_id: 'DEMO-APPROVAL-000', tenant_scope: 'demo-tenant' } }
  ]
});

export const mockConfigChangeLogs = () => successResponse({
  status: 'mock', api_status: 'mock',
  items: [
    { id: 'DEMO-LOG-001', config_key: 'inventory.safety_days', scope_key: 'tenant:demo', from_version: 1, to_version: 2, action: 'approve', actor_id: 'demo-approver', created_at: '2026-07-11 09:00', masked_detail: { value: '***' } }
  ]
});
