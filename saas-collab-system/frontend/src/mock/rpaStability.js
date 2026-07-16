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

const device = {
  id: 1,
  name: 'demo-dry-run-device',
  status: 'active',
  execution_mode: 'dry_run',
  availability: 'online',
  fingerprint_masked: 'demo***0001',
  last_heartbeat_at: '2026-07-10T00:03:00Z'
};

const page = (results) => ({ status: 'mock', count: results.length, next: null, previous: null, results });

export const mockRpaStabilityDashboard = () => successResponse({
  status: 'mock',
  module: 'rpa.stability.dashboard',
  task_states: [
    { status: 'manual_required', count: 1 },
    { status: 'retrying', count: 2 }
  ],
  run_states: [
    { status: 'manual_required', count: 1 },
    { status: 'retrying', count: 1 }
  ],
  manual_required: 1,
  boundary: 'internal_read_only_no_agent_execution'
});
export const mockRpaAttempts = () => successResponse({ ...page([attempt]), module: 'rpa.runs' });
export const mockRpaAttemptDetail = () => successResponse({ status: 'mock', module: 'rpa.attempts.detail', ...attempt });
export const mockRpaManualQueue = () => successResponse({ ...page([{ ...attempt, task_id: 1, manual_assignee: '', manual_reason: 'mock page changed' }]), module: 'rpa.manual_queue' });
export const mockRpaAccountLocks = () => successResponse({ ...page([{ id: 1, platform: 'mock-platform', account_alias: 'demo-account', task_id: 1, lock_status: 'held', acquired_at: '2026-07-10T00:00:00Z', expires_at: '2026-07-10T00:10:00Z', released_at: '' }]), module: 'rpa.account_locks' });
export const mockRpaPageSignatures = () => successResponse({ ...page([{ id: 1, platform: 'mock-platform', page_type: 'product_form', signature_hash_masked: 'mock-sig***', detected_status: 'changed', created_at: '2026-07-10T00:00:00Z' }]), module: 'rpa.page_signatures' });
export const mockRpaDevices = () => successResponse({ ...page([device]), module: 'rpa.devices' });
export const mockRpaDeviceDetail = () => successResponse({ status: 'mock', module: 'rpa.devices.detail', ...device, checks: { platform_connection: 'not_attempted', browser_automation: 'not_attempted' } });
