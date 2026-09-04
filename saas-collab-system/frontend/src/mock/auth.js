import { successResponse } from './index';

export const mockAuthUser = {
  id: 1,
  user_id: 'mock-user-001',
  username: 'stage0_internal_user',
  full_name: '演示用户',
  email: 'demo@example.com',
  phone: '13800000000',
  user_type: 'internal',
  tenant_id: 'mock-tenant-001',
  is_superuser: false,
  roles: ['stage0_viewer'],
  permissions: [
    'mock.view',
    'system.organization.view', 'system.organization.manage',
    'system.users.view', 'system.users.manage',
    'system.roles.view', 'system.roles.manage',
    'masterdata.view', 'masterdata.manage',
    'security.operations.view',
    'products.research.view', 'products.research.manage',
    'products.master.view', 'products.master.manage', 'products.master.freeze',
    'purchasing.orders.view', 'purchasing.orders.manage',
    'rpa.tasks.view', 'rpa.tasks.manage',
    'rpa.devices.view', 'rpa.devices.dry_run',
    'rpa.stability.view',
    'workflow.approvals.view', 'workflow.approvals.submit', 'workflow.approvals.review', 'workflow.approvals.withdraw',
    'workflow.exceptions.view', 'workflow.exceptions.manage',
    'workflow.collaboration.view', 'workflow.collaboration.confirm',
    'analytics.view', 'analytics.calculate',
    'finance.view',
    'products.lifecycle.view', 'products.lifecycle.evaluate',
    'integrations.view', 'integrations.manage', 'integrations.run', 'integrations.audit.view',
    'integrations.store.view', 'integrations.store.authorize', 'integrations.store.revoke',
    'integrations.warehouse.view', 'integrations.warehouse.authorize', 'integrations.warehouse.revoke',
    'integrations.credential.rotate', 'integrations.rotate',
    'integrations.config.view', 'integrations.config.verify', 'integrations.config.create', 'integrations.config.update', 'integrations.config.disable',
    'integrations.run_live_readonly',
    'config.view', 'config.manage', 'config.approve', 'config.rollback', 'config.system.manage',
    'reports.view', 'reports.export', 'reports.download',
    'governance.api.view', 'governance.api.check',
    'governance.assistants.view', 'governance.assistants.evaluate',
    'pilot.readiness.view', 'pilot.topology.view', 'pilot.topology.verify',
    'pilot.recovery.view', 'pilot.recovery.plan', 'pilot.recovery.review', 'pilot.recovery.record', 'pilot.recovery.execute',
    'pilot.release.view', 'pilot.release.plan', 'pilot.release.review', 'pilot.release.record', 'pilot.release.rollback', 'pilot.release.execute', 'pilot.release.rollback.execute',
    'pilot.capacity.view',
    'pilot.control.view',
    'pilot.security_review.view', 'pilot.security_review.plan', 'pilot.security_review.review',
    'pilot.verification.view', 'pilot.verification.plan', 'pilot.verification.review', 'pilot.verification.record', 'pilot.verification.cancel',
    'pilot.performance.view', 'pilot.performance.plan', 'pilot.performance.review', 'pilot.performance.record', 'pilot.performance.cancel', 'pilot.performance.execute',
    'pilot.entry.view', 'pilot.entry.plan', 'pilot.entry.review'
  ],
  menu_permission_codes: [
    'menu.system.organization.view', 'menu.system.users.view', 'menu.system.roles.view',
    'menu.system.security_operations.view'
  ],
  action_permission_codes: [
    'mock.view',
    'system.organization.view', 'system.organization.manage',
    'system.users.view', 'system.users.manage',
    'system.roles.view', 'system.roles.manage',
    'masterdata.view', 'masterdata.manage',
    'security.operations.view',
    'products.research.view', 'products.research.manage',
    'products.master.view', 'products.master.manage', 'products.master.freeze',
    'purchasing.orders.view', 'purchasing.orders.manage',
    'rpa.tasks.view', 'rpa.tasks.manage', 'rpa.devices.view', 'rpa.devices.dry_run', 'rpa.stability.view',
    'workflow.approvals.view', 'workflow.approvals.submit', 'workflow.approvals.review', 'workflow.approvals.withdraw',
    'workflow.exceptions.view', 'workflow.exceptions.manage', 'workflow.collaboration.view', 'workflow.collaboration.confirm',
    'analytics.view', 'analytics.calculate', 'finance.view',
    'products.lifecycle.view', 'products.lifecycle.evaluate', 'integrations.view', 'integrations.manage', 'integrations.run',
    'integrations.store.view', 'integrations.store.authorize', 'integrations.store.revoke', 'integrations.credential.rotate',
    'integrations.warehouse.view', 'integrations.warehouse.authorize', 'integrations.warehouse.revoke',
    'integrations.rotate', 'integrations.config.view', 'integrations.config.verify', 'integrations.config.create', 'integrations.config.update', 'integrations.config.disable',
    'integrations.run_live_readonly', 'config.view', 'config.manage', 'config.approve', 'config.rollback', 'config.system.manage',
    'integrations.audit.view', 'reports.view', 'reports.export', 'reports.download',
    'governance.api.view', 'governance.api.check', 'governance.assistants.view', 'governance.assistants.evaluate',
    'pilot.readiness.view', 'pilot.topology.view', 'pilot.topology.verify', 'pilot.recovery.view', 'pilot.recovery.plan',
    'pilot.recovery.review', 'pilot.recovery.record', 'pilot.recovery.execute', 'pilot.release.view', 'pilot.release.plan',
    'pilot.release.review', 'pilot.release.record', 'pilot.release.rollback', 'pilot.release.execute', 'pilot.release.rollback.execute',
    'pilot.capacity.view', 'pilot.control.view', 'pilot.security_review.view', 'pilot.security_review.plan', 'pilot.security_review.review',
    'pilot.verification.view', 'pilot.verification.plan', 'pilot.verification.review', 'pilot.verification.record',
    'pilot.verification.cancel', 'pilot.performance.view', 'pilot.performance.plan', 'pilot.performance.review',
    'pilot.performance.record', 'pilot.performance.cancel', 'pilot.performance.execute', 'pilot.entry.view', 'pilot.entry.plan', 'pilot.entry.review'
  ],
  field_permission_codes: [],
  data_scope: []
};

// Keep mock authentication aligned with the production module-gate contract.
// The mock defaults to a safe pilot posture while still exposing the complete
// shape returned by /api/internal/auth/me/.
mockAuthUser.module_statuses = {
  core: 'enabled',
  masterdata: 'enabled',
  product_development: 'disabled',
  supply_chain: 'disabled',
  inventory: 'pilot_readonly',
  global_listing: 'disabled',
  sales: 'pilot_readonly',
  influencer: 'disabled',
  finance: 'pilot_readonly',
  analytics: 'pilot_readonly',
  decision: 'pilot_readonly',
  reports: 'pilot_readonly',
  workflow: 'disabled',
  rpa: 'disabled',
  api_integrations: 'pilot_readonly',
  system: 'enabled',
  governance: 'enabled'
};

export const mockLogin = () => successResponse({
  status: 'mock',
  session: 'mock-session-only',
  user: mockAuthUser
});

export const mockCurrentUser = () => successResponse(mockAuthUser);

const mockProfileState = {
  username: mockAuthUser.username,
  full_name: mockAuthUser.full_name,
  email: mockAuthUser.email,
  phone: mockAuthUser.phone,
};

export const mockMyProfile = () => successResponse({ ...mockProfileState });

export const mockUpdateMyProfile = (payload = {}) => {
  Object.assign(mockProfileState, {
    full_name: payload.full_name ?? mockProfileState.full_name,
    email: payload.email ?? mockProfileState.email,
    phone: payload.phone ?? mockProfileState.phone,
  });
  Object.assign(mockAuthUser, mockProfileState);
  return successResponse({ ...mockProfileState });
};

export const mockChangeMyPassword = () => successResponse({ password_changed: true });
