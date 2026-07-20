import { successResponse } from './index';

const emptyRequestFields = [];
const contracts = [
  {
    id: 1,
    module: 'pilot',
    name: 'Pilot readiness',
    path: '/api/internal/pilot/readiness/',
    method: 'GET',
    owner: 'architecture',
    status: 'mock',
    version: 'ui-p7-v1',
    permission: 'pilot.readiness.view',
    scope_keys: ['environment_ids', 'gate_codes'],
    response_schema_version: 'ui-p7-v1',
    evidence_status: 'valid',
    updated_at: '2026-07-17T00:00:00Z',
    request_fields: emptyRequestFields,
    response_fields: [],
    error_codes: [],
    change_history: []
  },
  {
    id: 2,
    module: 'pilot',
    name: 'Recovery plans',
    path: '/api/internal/pilot/recovery-plans/',
    method: 'GET',
    owner: 'architecture',
    status: 'mock',
    version: 'ui-p7-v1',
    permission: 'pilot.recovery.view',
    scope_keys: ['environment_ids', 'recovery_plan_ids'],
    response_schema_version: 'ui-p7-v1',
    evidence_status: 'valid',
    updated_at: '2026-07-17T00:00:00Z',
    request_fields: emptyRequestFields,
    response_fields: [],
    error_codes: [],
    change_history: []
  }
];

const assistants = [
  {
    id: 1,
    code: 'pilot-readiness-assistant',
    name: 'Pilot readiness assistant',
    status: 'mock',
    capability_declarations: ['checklist', 'risk_summary'],
    data_classes: ['internal_demo'],
    tool_allowlist: [],
    human_confirmation_required: true,
    updated_at: '2026-07-17T00:00:00Z',
    input_policy: 'Demo references only; credentials and raw business data are forbidden.',
    output_policy: 'Advisory output only; human confirmation is required.',
    limitations: ['No shell', 'No deployment', 'No credential access', 'No business writes'],
    review_owner: 'architecture',
    reviewed_at: null
  }
];

const page = (items) => ({ count: items.length, next: null, previous: null, results: items, api_status: 'mock' });
export const mockApiContracts = () => successResponse(page(contracts));
export const mockApiContractDetail = (id = 1) => successResponse({ ...(contracts.find((item) => item.id === Number(id)) || contracts[0]), api_status: 'mock' });
export const mockApiContractCheck = () => successResponse({ checked_count: contracts.length, passed_count: contracts.length, violations: [], evidence_status: 'fixed_demo', api_status: 'mock' });
export const mockAssistants = () => successResponse(page(assistants));
export const mockAssistantDetail = (id = 1) => successResponse({ ...(assistants.find((item) => item.id === Number(id)) || assistants[0]), api_status: 'mock' });
export const mockAssistantEvaluation = () => successResponse({
  assistant_id: 1,
  recommendation: 'Demo-only governance recommendation; human review is required.',
  limitations: assistants[0].limitations,
  confidence: 0.5,
  human_confirmation_required: true,
  tool_calls: [],
  business_writes: [],
  api_status: 'mock'
});
