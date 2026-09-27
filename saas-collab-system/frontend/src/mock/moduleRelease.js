import { successResponse } from './index';

const moduleCodes = [
  'core', 'masterdata', 'product_development', 'supply_chain', 'inventory',
  'global_listing', 'sales', 'influencer', 'finance', 'analytics', 'decision',
  'reports', 'workflow', 'rpa', 'api_integrations', 'system', 'governance'
];

const clone = (value) => JSON.parse(JSON.stringify(value));
const initialModules = Object.fromEntries(moduleCodes.map((code) => [code, 'enabled']));
const state = { effective: clone(initialModules), versions: [], values: {}, nextId: 1 };

export const mockModuleRelease = () => successResponse({
  effective_config: { modules: clone(state.effective) },
  versions: clone(state.versions),
  api_status: 'mock'
});

export const mockCreateModuleReleaseVersion = (payload) => {
  const modules = payload?.value?.modules;
  if (!modules || typeof modules !== 'object') {
    return { success: false, code: 'INVALID_MODULES', message: '模块配置不能为空。', data: null };
  }
  const id = state.nextId++;
  const version = { id, version: id, status: 'pending_approval', created_at: new Date().toISOString(), created_by_id: 1 };
  state.values[id] = clone(modules);
  state.versions.unshift(version);
  return successResponse({ version: clone(version), api_status: 'mock' });
};

export const mockApproveModuleReleaseVersion = (id) => {
  const version = state.versions.find((item) => String(item.id) === String(id));
  if (!version || version.status !== 'pending_approval') {
    return { success: false, code: 'VERSION_NOT_PENDING', message: '只有待审批版本可以审批。', data: null };
  }
  for (const item of state.versions) if (item.status === 'effective') item.status = 'superseded';
  version.status = 'effective';
  state.effective = clone(state.values[version.id]);
  return successResponse({ version: clone(version), api_status: 'mock' });
};

export const mockRollbackModuleReleaseVersion = (id) => {
  const source = state.versions.find((item) => String(item.id) === String(id));
  if (!source) return { success: false, code: 'VERSION_NOT_FOUND', message: '目标版本不存在。', data: null };
  return mockCreateModuleReleaseVersion({ value: { modules: state.values[source.id] } });
};
