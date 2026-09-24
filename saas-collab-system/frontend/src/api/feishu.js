import { requestWithMockFallback } from './request';

const base = '/api/internal/integrations/feishu';

const ok = (data) => ({ success: true, code: 'OK', message: '请求成功', data });
const emptyList = () => ok({ items: [], count: 0 });
const mockConnection = () => ok({
  app_id: '', domain: 'feishu', enabled: false, status: 'not_configured',
  credential_configured: false, verification_token_configured: false,
  encrypt_key_configured: false, callback_url: '', updated_at: null
});

export const fetchFeishuConnection = () => requestWithMockFallback(
  { method: 'get', url: `${base}/connection/` }, mockConnection, 'integrations.feishu.connection'
);

export const updateFeishuConnection = (data) => requestWithMockFallback(
  { method: 'put', url: `${base}/connection/`, data },
  () => ok({ ...mockConnection().data, ...data, app_secret: undefined, verification_token: undefined, encrypt_key: undefined }),
  'integrations.feishu.connection.update'
);

const resources = {
  identities: 'identities', notifications: 'notifications', reports: 'reports', approvals: 'approvals'
};

export const fetchFeishuResources = (resource, params = {}) => requestWithMockFallback(
  { method: 'get', url: `${base}/${resources[resource]}/`, params }, emptyList, `integrations.feishu.${resource}`
);

export const fetchFeishuIdentityCandidates = (systemUserId) => requestWithMockFallback(
  { method: 'post', url: `${base}/identities/system-users/${systemUserId}/candidates/` },
  () => ok({ system_user_id: systemUserId, candidates: [] }), 'integrations.feishu.identities.candidates'
);

export const bindFeishuIdentity = (systemUserId, data) => requestWithMockFallback(
  { method: 'put', url: `${base}/identities/system-users/${systemUserId}/binding/`, data },
  () => ok({ ...data, system_user_id: systemUserId }), 'integrations.feishu.identities.bind'
);

export const createFeishuResource = (resource, data) => requestWithMockFallback(
  { method: 'post', url: `${base}/${resources[resource]}/`, data },
  () => ok({ ...data, id: `mock-${Date.now()}` }), `integrations.feishu.${resource}.create`
);

export const updateFeishuResource = (resource, id, data) => requestWithMockFallback(
  { method: 'patch', url: `${base}/${resources[resource]}/${id}/`, data },
  () => ok({ ...data, id }), `integrations.feishu.${resource}.update`
);

export const deleteFeishuResource = (resource, id) => requestWithMockFallback(
  { method: 'delete', url: `${base}/${resources[resource]}/${id}/` },
  () => ok({ id }), `integrations.feishu.${resource}.delete`
);

export const fetchFeishuOperations = (params = {}) => requestWithMockFallback(
  { method: 'get', url: `${base}/operations/`, params }, emptyList, 'integrations.feishu.operations'
);
