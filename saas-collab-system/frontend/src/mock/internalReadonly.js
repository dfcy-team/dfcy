import { successResponse } from './index';
import { internalReadonlyResourceFields } from '../config/internalReadonlyResources';

let clients = [
  { id: 'client-001', name: '知识库同步服务', caller_type: 'knowledge_base', client_id: 'intapi_demo', status: 'active', resources: { products: ['id', 'name', 'updated_at'], suppliers: ['id', 'name', 'updated_at'] }, allowed_cidrs: ['10.20.0.0/16'], rate_limit_per_minute: 120, page_size_limit: 100, expires_at: '2027-09-21T23:59:59+08:00', last_rotated_at: '2026-09-21 10:18' }
];
const audits = [
  { id: 'audit-001', client_name: '知识库同步服务', action: '读取商品列表', method: 'GET', result: '成功', source_ip: '10.20.1.8', created_at: '2026-09-21 10:18' }
];
const ok = (data, message = '操作成功') => successResponse(data, message);
const normalizeResources = (value) => Array.isArray(value)
  ? Object.fromEntries(value.map((code) => [code, [...(internalReadonlyResourceFields[code] || [])]]))
  : value;

export const mockInternalReadonlyClients = () => ok({ items: clients.map((item) => ({ ...item })), api_status: 'mock' });
export const mockCreateInternalReadonlyClient = (payload = {}) => {
  const item = { ...payload, resources: normalizeResources(payload.resources), id: `client-${Date.now()}`, client_id: `intapi_${Date.now()}`, status: 'active', last_rotated_at: '--' };
  clients = [item, ...clients];
  return ok({ ...item, client_secret: `demo_${Date.now()}_only_once`, secret_display_once: true, api_status: 'mock' }, '调用系统已创建，密钥仅显示一次');
};
export const mockUpdateInternalReadonlyClient = (id, payload = {}) => {
  clients = clients.map((item) => item.id === id ? { ...item, ...payload, resources: normalizeResources(payload.resources || item.resources) } : item);
  return ok({ client: clients.find((item) => item.id === id), api_status: 'mock' });
};
export const mockSetInternalReadonlyClientStatus = (id, status) => {
  clients = clients.map((item) => item.id === id ? { ...item, status } : item);
  return ok({ client: clients.find((item) => item.id === id), api_status: 'mock' });
};
export const mockRotateInternalReadonlyCredential = (id) => ok({ client_id: id, client_secret: `demo_rotated_${Date.now()}_only_once`, api_status: 'mock' }, '密钥已轮换，仅显示一次');
export const mockInternalReadonlyAudit = () => ok({ items: audits, api_status: 'mock' });
