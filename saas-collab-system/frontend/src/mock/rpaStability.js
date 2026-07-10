import { successResponse } from './index';

const attempt = {
  id: 1,
  task: 'MOCK-RPA-TASK-001',
  attempt_no: 2,
  agent: 'mock-agent',
  started_at: '2026-07-10T00:00:00Z',
  heartbeat_at: '2026-07-10T00:03:00Z',
  finished_at: '',
  status: 'manual_required',
  failed_step: 'mock_login_check',
  last_success_step: 'mock_open_page',
  masked_error: 'mock masked captcha or page signature issue',
  manual_required: true,
  evidence_type: 'screenshot_placeholder',
  placeholder_url: 'https://example.invalid/mock-evidence.png',
  payload_hash: 'mock-payload-hash'
};

export const mockRpaStabilityDashboard = () => successResponse({ status: 'mock', module: 'rpa.stability.dashboard', items: [{ status: 'manual_required', count: 1 }, { status: 'retry_wait', count: 2 }] });
export const mockRpaAttempts = () => successResponse({ status: 'mock', module: 'rpa.attempts', items: [attempt] });
export const mockRpaAttemptDetail = () => successResponse({ status: 'mock', module: 'rpa.attempts.detail', ...attempt });
export const mockRpaManualQueue = () => successResponse({ status: 'mock', module: 'rpa.manual_queue', items: [attempt] });
export const mockRpaAccountLocks = () => successResponse({ status: 'mock', module: 'rpa.account_locks', items: [{ platform: 'BigSeller', account_alias: 'demo-account', task: 'MOCK-RPA-TASK-001', lock_status: 'locked', acquired_at: '2026-07-10T00:00:00Z', expires_at: '2026-07-10T00:10:00Z', released_at: '' }] });
export const mockRpaPageSignatures = () => successResponse({ status: 'mock', module: 'rpa.page_signatures', items: [{ platform: 'BigSeller', page_type: 'product_form', signature_hash: 'mock-signature-hash', detected_status: 'manual_check_required', created_at: '2026-07-10T00:00:00Z' }] });
