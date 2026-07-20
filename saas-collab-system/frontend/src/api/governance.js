import { requestWithMockFallback, withApiStatus } from './request';
import { mockApiContractCheck, mockApiContractDetail, mockApiContracts, mockAssistantDetail, mockAssistantEvaluation, mockAssistants } from '../mock/governance';

const sandbox = async (request) => {
  const response = withApiStatus(await request, 'sandbox');
  if (response?.success && response.data?.api_status === 'connected') response.data.api_status = 'sandbox';
  return response;
};
const idempotency = () => `ui-p7-governance-${Date.now()}-${Math.random().toString(16).slice(2)}`;

export const fetchApiContracts = (params = {}) => sandbox(requestWithMockFallback({ method: 'get', url: '/api/internal/governance/api-contracts/', params }, mockApiContracts, 'governance.api'));
export const fetchApiContract = (id) => sandbox(requestWithMockFallback({ method: 'get', url: `/api/internal/governance/api-contracts/${id}/` }, () => mockApiContractDetail(id), 'governance.api.detail'));
export const checkApiContractMock = (payload) => requestWithMockFallback({ method: 'post', url: '/api/internal/governance/api-contracts/check-mock/', data: payload, headers: { 'Idempotency-Key': idempotency() } }, mockApiContractCheck, 'governance.api.check');
export const fetchAssistants = (params = {}) => sandbox(requestWithMockFallback({ method: 'get', url: '/api/internal/governance/assistants/', params }, mockAssistants, 'governance.assistants'));
export const fetchAssistant = (id) => sandbox(requestWithMockFallback({ method: 'get', url: `/api/internal/governance/assistants/${id}/` }, () => mockAssistantDetail(id), 'governance.assistants.detail'));
export const evaluateAssistantMock = (id, payload) => requestWithMockFallback({ method: 'post', url: `/api/internal/governance/assistants/${id}/evaluate-mock/`, data: payload, headers: { 'Idempotency-Key': idempotency() } }, mockAssistantEvaluation, 'governance.assistants.evaluate');
