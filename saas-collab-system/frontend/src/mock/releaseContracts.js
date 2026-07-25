import { successResponse } from './index';

const gateCodes = [
  'engineering-quality',
  'miniapp-special',
  'backend-compatibility',
  'end-to-end',
  'release-readiness',
  'evidence-integrity'
];

const now = () => new Date().toISOString();
const tomorrow = () => new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();
const gateSummary = (passed = 6) => ({
  required: gateCodes.length,
  passed,
  missing: gateCodes.slice(passed),
  failed: [],
  expired: []
});

const contracts = [
  {
    id: 1001,
    contract_no: 'RC-20260724-1001',
    application_code: 'saas-miniapp',
    environment: 'test',
    commit_sha: '7c2ea1f64f04aaf32038f1d296b7b890d61be972',
    api_contract_version: 'miniapp-v1',
    scope: ['小程序登录', '发布合同只读工作台'],
    risk_level: 'medium',
    rollback_version: '0.1.0',
    rollback_point: 'artifact:miniapp-0.1.0',
    stop_conditions: [{ metric: 'login_error_rate', operator: '>', threshold: 0.05 }],
    observation_minutes: 30,
    status: 'review_pending',
    scheduled_at: null,
    completed_at: null,
    version: 8,
    artifact: null,
    gate_results: gateCodes.map((code, index) => ({
      code,
      category: index < 2 ? 'quality' : 'readiness',
      status: 'passed',
      evidence_ref: `evidence:${code}:masked`,
      evaluated_at: now(),
      expires_at: tomorrow(),
      version: 1,
      updated_at: now()
    })),
    approvals: [],
    audit_events: [],
    gate_summary: gateSummary(),
    created_at: now(),
    updated_at: now()
  },
  {
    id: 1002,
    contract_no: 'RC-20260724-1002',
    application_code: 'saas-miniapp',
    environment: 'preview',
    commit_sha: '9e0d1a98e9957400e137af2c9c94bbdc6437ac47',
    api_contract_version: 'miniapp-v1',
    scope: ['真实登录联调'],
    risk_level: 'high',
    rollback_version: '0.1.0',
    rollback_point: 'artifact:miniapp-0.1.0',
    stop_conditions: [{ metric: 'auth_5xx_rate', operator: '>', threshold: 0.01 }],
    observation_minutes: 60,
    status: 'draft',
    scheduled_at: null,
    completed_at: null,
    version: 2,
    artifact: null,
    gate_results: gateCodes.slice(0, 2).map((code) => ({
      code,
      category: 'quality',
      status: 'passed',
      evidence_ref: `evidence:${code}:masked`,
      evaluated_at: now(),
      expires_at: tomorrow(),
      version: 1,
      updated_at: now()
    })),
    approvals: [],
    audit_events: [],
    gate_summary: gateSummary(2),
    created_at: now(),
    updated_at: now()
  },
  {
    id: 1003,
    contract_no: 'RC-20260723-1003',
    application_code: 'saas-miniapp',
    environment: 'production',
    commit_sha: '42cf76fac29239cad852b31c8b259aaec82e850a',
    api_contract_version: 'miniapp-v1',
    scope: ['工程底座'],
    risk_level: 'low',
    rollback_version: '0.0.9',
    rollback_point: 'artifact:miniapp-0.0.9',
    stop_conditions: [{ metric: 'crash_rate', operator: '>', threshold: 0.02 }],
    observation_minutes: 30,
    status: 'completed',
    scheduled_at: now(),
    completed_at: now(),
    version: 18,
    artifact: {
      build_no: 'build-1003',
      commit_sha: '42cf76fac29239cad852b31c8b259aaec82e850a',
      artifact_hash: 'b'.repeat(64),
      config_version: 'config-v1',
      manifest: { channel: 'controlled-record-only' },
      created_at: now()
    },
    gate_results: gateCodes.map((code) => ({
      code,
      category: 'release',
      status: 'passed',
      evidence_ref: `evidence:${code}:masked`,
      evaluated_at: now(),
      expires_at: tomorrow(),
      version: 1,
      updated_at: now()
    })),
    approvals: ['business', 'technical', 'security'].map((approval_type) => ({
      approval_type,
      decision: 'approved',
      reason: '受控演示审批通过',
      decided_at: now()
    })),
    audit_events: [],
    gate_summary: gateSummary(),
    created_at: now(),
    updated_at: now()
  }
];

const clone = (value) => JSON.parse(JSON.stringify(value));
const findContract = (id) => contracts.find((item) => item.id === Number(id));
const notFound = () => ({
  success: false,
  code: 'NOT_FOUND',
  message: '发布合同不存在或不在当前数据范围内。',
  data: null,
  http_status: 404
});

export function mockFetchReleaseContracts(params = {}) {
  const results = contracts.filter(
    (item) =>
      (!params.status || item.status === params.status) &&
      (!params.environment || item.environment === params.environment)
  );
  return successResponse({
    count: results.length,
    results: clone(results),
    api_status: 'mock'
  });
}

export function mockFetchReleaseContract(id) {
  const contract = findContract(id);
  return contract
    ? successResponse({ ...clone(contract), api_status: 'mock' })
    : notFound();
}

export function mockCreateReleaseContract(payload) {
  const contract = {
    id: Math.max(...contracts.map((item) => item.id)) + 1,
    contract_no: `RC-MOCK-${Date.now()}`,
    ...clone(payload),
    status: 'draft',
    scheduled_at: null,
    completed_at: null,
    version: 1,
    artifact: null,
    gate_results: [],
    approvals: [],
    audit_events: [],
    gate_summary: gateSummary(0),
    created_at: now(),
    updated_at: now()
  };
  contracts.unshift(contract);
  return successResponse({ replayed: false, contract: clone(contract), api_status: 'mock' });
}

export function mockRecordReleaseGate(id, payload) {
  const contract = findContract(id);
  if (!contract) return notFound();
  const nextGate = {
    code: payload.code,
    category: payload.category,
    status: payload.status,
    evidence_ref: payload.evidence_ref,
    evaluated_at: payload.evaluated_at,
    expires_at: payload.expires_at,
    version: 1,
    updated_at: now()
  };
  contract.gate_results = [
    ...contract.gate_results.filter((gate) => gate.code !== payload.code),
    nextGate
  ];
  contract.version += 1;
  const passed = gateCodes.filter((code) =>
    contract.gate_results.some((gate) => gate.code === code && gate.status === 'passed')
  ).length;
  contract.gate_summary = gateSummary(passed);
  return successResponse({ replayed: false, gate: clone(nextGate), api_status: 'mock' });
}

export function mockDecideReleaseApproval(id, payload) {
  const contract = findContract(id);
  if (!contract) return notFound();
  const approval = {
    approval_type: payload.approval_type,
    decision: payload.decision,
    reason: payload.reason,
    decided_at: now()
  };
  contract.approvals.push(approval);
  contract.version += 1;
  if (payload.decision === 'rejected') contract.status = 'rejected';
  const approved = new Set(
    contract.approvals
      .filter((item) => item.decision === 'approved')
      .map((item) => item.approval_type)
  );
  if (['business', 'technical', 'security'].every((type) => approved.has(type))) {
    contract.status = 'approved';
  }
  return successResponse({
    replayed: false,
    approval: clone(approval),
    contract: clone(contract),
    api_status: 'mock'
  });
}

export function mockConfirmReleaseBuild(id, payload) {
  const contract = findContract(id);
  if (!contract) return notFound();
  contract.artifact = {
    build_no: payload.build_no,
    commit_sha: payload.commit_sha,
    artifact_hash: payload.artifact_hash,
    config_version: payload.config_version,
    manifest: payload.manifest || {},
    created_at: now()
  };
  contract.status = 'built';
  contract.version += 1;
  return successResponse({
    replayed: false,
    artifact: clone(contract.artifact),
    contract: clone(contract),
    api_status: 'mock'
  });
}

export function mockRunReleaseAction(id, action, payload) {
  const contract = findContract(id);
  if (!contract) return notFound();
  const transitions = {
    'submit-review': 'review_pending',
    upload: 'uploaded',
    'submit-platform-review': 'platform_review',
    'start-release': 'releasing',
    'start-observation': 'observing',
    complete: 'completed',
    'request-rollback': 'rollback_required',
    'execute-rollback': 'rolled_back',
    cancel: 'cancelled'
  };
  if (action === 'record-platform-review') {
    contract.status = payload.result_status === 'approved' ? 'scheduled' : 'review_failed';
    contract.scheduled_at = payload.scheduled_at || null;
  } else if (action === 'record-release-result') {
    contract.status = payload.result_status === 'released' ? 'released' : 'release_failed';
  } else {
    contract.status = transitions[action] || contract.status;
  }
  contract.version += 1;
  if (['completed', 'rolled_back'].includes(contract.status)) contract.completed_at = now();
  return successResponse({ replayed: false, contract: clone(contract), api_status: 'mock' });
}

export { gateCodes as requiredReleaseGateCodes };
