import { successResponse } from './index';

const platforms = [
  {
    id: 'risk-bigseller',
    platform: 'BigSeller',
    access_status: 'security_review_required',
    environment_status: 'sandbox_pending',
    production_status: 'production_disabled',
    security_review_done: false,
    credential_custody_done: false,
    network_isolation_done: false,
    permission_audit_done: false,
    rollback_plan_done: false,
    gray_release_done: false,
    high_risk_action_allowed: false,
    risk_note: 'Real platform access requires a dedicated security review.',
    forbidden_items: 'No real account, credential, Cookie, Session, or production connection.'
  },
  {
    id: 'risk-shopee',
    platform: 'Shopee',
    access_status: 'security_review_required',
    environment_status: 'mock_ready',
    production_status: 'production_disabled',
    security_review_done: false,
    credential_custody_done: false,
    network_isolation_done: false,
    permission_audit_done: false,
    rollback_plan_done: false,
    gray_release_done: false,
    high_risk_action_allowed: false,
    risk_note: 'OAuth and production authorization are not enabled in Phase 2.',
    forbidden_items: 'No real OAuth redirect, shop authorization, token, or API Secret.'
  },
  {
    id: 'risk-tiktok',
    platform: 'TikTok/TK',
    access_status: 'sandbox_pending',
    environment_status: 'mock_ready',
    production_status: 'production_disabled',
    security_review_done: false,
    credential_custody_done: false,
    network_isolation_done: false,
    permission_audit_done: false,
    rollback_plan_done: false,
    gray_release_done: false,
    high_risk_action_allowed: false,
    risk_note: 'Production listing and pricing actions remain disabled.',
    forbidden_items: 'No real marketplace SDK, token, Cookie, Session, or account password.'
  },
  {
    id: 'risk-bank',
    platform: 'Bank',
    access_status: 'security_review_required',
    environment_status: 'mock_ready',
    production_status: 'production_disabled',
    security_review_done: false,
    credential_custody_done: false,
    network_isolation_done: false,
    permission_audit_done: false,
    rollback_plan_done: false,
    gray_release_done: false,
    high_risk_action_allowed: false,
    risk_note: 'Bank access is finance-sensitive and requires separate approval.',
    forbidden_items: 'No real bank account, transfer, payment, withdrawal, or credential config.'
  },
  {
    id: 'risk-payment',
    platform: 'Payment',
    access_status: 'security_review_required',
    environment_status: 'mock_ready',
    production_status: 'production_disabled',
    security_review_done: false,
    credential_custody_done: false,
    network_isolation_done: false,
    permission_audit_done: false,
    rollback_plan_done: false,
    gray_release_done: false,
    high_risk_action_allowed: false,
    risk_note: 'Payment access is read-only placeholder only in Phase 2.',
    forbidden_items: 'No real payment key, merchant account, payout, refund, or capture action.'
  }
];

const checklist = [
  {
    id: 'review-security',
    item: 'Dedicated security review',
    status: 'security_review_required',
    owner: 'security-owner-pending',
    required_for: 'production',
    evidence_status: 'pending',
    note: 'Required before any real platform access.'
  },
  {
    id: 'review-custody',
    item: 'Credential custody plan',
    status: 'security_review_required',
    owner: 'security-owner-pending',
    required_for: 'sandbox_or_production',
    evidence_status: 'pending',
    note: 'Secrets must be stored outside frontend code and Git.'
  },
  {
    id: 'review-network',
    item: 'Network isolation',
    status: 'security_review_required',
    owner: 'infra-owner-pending',
    required_for: 'production',
    evidence_status: 'pending',
    note: 'Production network path must be reviewed separately.'
  },
  {
    id: 'review-permission',
    item: 'Permission audit',
    status: 'security_review_required',
    owner: 'backend-owner-pending',
    required_for: 'sandbox_or_production',
    evidence_status: 'pending',
    note: 'Real permissions must come from backend roles and permissions.'
  },
  {
    id: 'review-rollback',
    item: 'Rollback and gray release plan',
    status: 'security_review_required',
    owner: 'release-owner-pending',
    required_for: 'production',
    evidence_status: 'pending',
    note: 'High-risk automation remains disabled until reviewed.'
  }
];

export const mockPlatformAccessRisks = () => successResponse({
  status: 'mock',
  module: 'settings.platform_access_risk',
  items: platforms
});

export const mockPlatformIntegrationReadiness = () => successResponse({
  status: 'mock',
  module: 'settings.platform_integration_readiness',
  items: platforms.map((item) => ({
    id: `${item.id}-readiness`,
    platform: item.platform,
    current_access_status: item.access_status,
    mock_sandbox_status: item.environment_status,
    production_status: item.production_status,
    security_review_done: item.security_review_done,
    credential_custody_done: item.credential_custody_done,
    network_isolation_done: item.network_isolation_done,
    permission_audit_done: item.permission_audit_done,
    rollback_plan_done: item.rollback_plan_done,
    gray_release_done: item.gray_release_done,
    high_risk_action_allowed: item.high_risk_action_allowed
  }))
});

export const mockSecurityReviewChecklist = () => successResponse({
  status: 'mock',
  module: 'settings.security_review_checklist',
  items: checklist
});
