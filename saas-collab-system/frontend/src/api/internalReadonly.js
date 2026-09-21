import { requestWithMockFallback } from './request';
import {
  mockCreateInternalReadonlyClient,
  mockInternalReadonlyAudit,
  mockInternalReadonlyClients,
  mockRotateInternalReadonlyCredential,
  mockSetInternalReadonlyClientStatus,
  mockUpdateInternalReadonlyClient
} from '../mock/internalReadonly';

const root = '/api/internal/integrations/internal-api-clients/';
export const fetchInternalReadonlyClients = (params = {}) => requestWithMockFallback({ method: 'get', url: root, params }, mockInternalReadonlyClients, 'internal_readonly.clients');
export const createInternalReadonlyClient = (data) => requestWithMockFallback({ method: 'post', url: root, data }, () => mockCreateInternalReadonlyClient(data), 'internal_readonly.create');
export const updateInternalReadonlyClient = (id, data) => requestWithMockFallback({ method: 'patch', url: `${root}${id}/`, data }, () => mockUpdateInternalReadonlyClient(id, data), 'internal_readonly.update');
export const setInternalReadonlyClientStatus = (id, status) => requestWithMockFallback({ method: 'post', url: `${root}${id}/status/`, data: { status } }, () => mockSetInternalReadonlyClientStatus(id, status), 'internal_readonly.status');
export const rotateInternalReadonlyCredential = (id, idempotencyKey) => requestWithMockFallback({ method: 'post', url: `${root}${id}/rotate/`, headers: { 'Idempotency-Key': idempotencyKey } }, () => mockRotateInternalReadonlyCredential(id), 'internal_readonly.rotate');
export const fetchInternalReadonlyAudit = (id) => requestWithMockFallback({ method: 'get', url: `${root}${id}/audit/` }, () => mockInternalReadonlyAudit(id), 'internal_readonly.audit');
