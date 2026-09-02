import { requestApi } from './request';

const idempotency = (prefix = 'ui-governance') => `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;

// Governance reads and writes always use the authenticated API. A failed
// request is returned to the view unchanged; no client-side records are substituted.
export const fetchApiContracts = (params = {}) => requestApi({
  method: 'get',
  url: '/api/internal/governance/api-contracts/',
  params
});

export const fetchApiContract = (id) => requestApi({
  method: 'get',
  url: `/api/internal/governance/api-contracts/${id}/`
});

export const checkApiContract = (payload) => requestApi({
  method: 'post',
  url: '/api/internal/governance/api-contracts/check-mock/',
  data: payload,
  headers: { 'Idempotency-Key': idempotency('ui-governance-contract-check') }
});

export const fetchAssistants = (params = {}) => requestApi({
  method: 'get',
  url: '/api/internal/governance/assistants/',
  params
});

export const fetchAssistant = (id) => requestApi({
  method: 'get',
  url: `/api/internal/governance/assistants/${id}/`
});

/** Start a real, server-side assistant evaluation job. */
export const createAssistantEvaluation = (id, payload) => requestApi({
  method: 'post',
  url: `/api/internal/governance/assistants/${id}/evaluations/`,
  data: payload,
  headers: { 'Idempotency-Key': idempotency('ui-governance-assistant-evaluation') }
});

/** Read a single evaluation job, including status, result and audit details. */
export const fetchAssistantEvaluation = (id) => requestApi({
  method: 'get',
  url: `/api/internal/governance/assistant-evaluations/${id}/`
});
