import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { canAccessPath, filterMenuItems, flattenMenuItems } from '../src/router/menu';
import { getActionAccess } from '../src/utils/actionAccess';
import { masterDataMocks } from '../src/mock/masterData';
import { mockSecurityOperations } from '../src/mock/systemAdmin';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

const viewer = {
  user_type: 'internal',
  is_superuser: false,
  permissions: [
    'system.organization.view', 'system.users.view', 'system.roles.view', 'masterdata.view', 'security.operations.view'
  ]
};
const authFor = (user) => ({
  currentUser: user,
  hasPermission: (...codes) => Boolean(user.is_superuser) || codes.some((code) => user.permissions.includes(code))
});

describe('UI-P2 route and action contracts', () => {
  it('registers all system and master-data pages behind explicit permissions', () => {
    for (const path of [
      '/system/departments', '/system/users', '/system/roles', '/system/security-operations',
      '/master-data/platforms', '/master-data/stores', '/master-data/warehouses', '/master-data/suppliers'
    ]) {
      expect(canAccessPath(viewer, path), path).toBe(true);
    }
    expect(canAccessPath({ ...viewer, user_type: 'external' }, '/system/users')).toBe(false);
    expect(canAccessPath({ ...viewer, user_type: 'rpa' }, '/master-data/platforms')).toBe(false);
  });

  it('shows read pages but hides write actions from view-only users', () => {
    const paths = flattenMenuItems(filterMenuItems(viewer)).map((item) => item.path);
    expect(paths).toContain('/system/users');
    expect(paths).toContain('/master-data/suppliers');
    expect(getActionAccess(authFor(viewer), { permission: 'system.users.manage' }).visible).toBe(false);
    expect(getActionAccess(authFor(viewer), { permission: 'masterdata.manage' }).allowed).toBe(false);
  });

  it('allows write actions only with backend action permissions', () => {
    const manager = { ...viewer, permissions: [...viewer.permissions, 'system.users.manage', 'masterdata.manage'] };
    expect(getActionAccess(authFor(manager), { permission: 'system.users.manage' }).allowed).toBe(true);
    expect(getActionAccess(authFor(manager), { permission: 'masterdata.manage' }).allowed).toBe(true);
  });
});

describe('UI-P2 API and sensitive-field contracts', () => {
  it('uses only the frozen internal system and master-data API partitions', () => {
    const systemApi = read('src/api/systemAdmin.js');
    const masterApi = read('src/api/masterData.js');
    expect(systemApi).toContain('/api/internal/system/users/');
    expect(systemApi).toContain('/api/internal/system/user-role-options/');
    expect(systemApi).toContain('/api/internal/system/roles/');
    expect(systemApi).toContain('/api/internal/system/security-operations/');
    expect(masterApi).toContain('/api/internal/master-data/${resource}/');
    expect(systemApi + masterApi).not.toContain('/admin/');
    expect(systemApi + masterApi).not.toContain('/api/rpa/');
    expect(systemApi + masterApi).not.toContain('/api/finance/');
  });

  it('keeps mock supplier contacts and credential references masked', () => {
    const supplier = masterDataMocks.suppliers().data.results[0];
    const security = mockSecurityOperations().data;
    expect(supplier.contact_email_masked).toMatch(/\*\*\*/);
    expect(supplier.contact_phone_masked).toMatch(/\*\*\*/);
    expect(supplier).not.toHaveProperty('contact_email');
    expect(security.credential_references[0]).toHaveProperty('credential_fingerprint');
    expect(security.credential_references[0]).not.toHaveProperty('credential_ciphertext');
    expect(JSON.stringify(security)).not.toMatch(/api[_-]?secret|cookie|session/i);
  });

  it('renders the six trusted access layers and action double-check', () => {
    const rolePage = read('src/views/system/RolePermissionMatrix.vue');
    const userPage = read('src/views/system/UserDirectory.vue');
    const resourcePage = read('src/components/AdminResourcePage.vue');
    for (const label of ['Tenant', '用户类型', '角色', 'Permission', 'Data scope', '字段与流程']) {
      expect(rolePage).toContain(label);
    }
    expect(resourcePage).toContain("getActionAccess(auth, { permission: props.managePermission })");
    expect(resourcePage).toContain('if (!manageAccess.value.allowed');
    expect(resourcePage).toContain('凭据、Token、Cookie 和 Session 不在此表单采集');
    expect(resourcePage).toContain("ref(useMock ? 'mock' : 'pending')");
    expect(resourcePage).toContain("apiStatus === 'fallback' ? 'degraded' : apiStatus");
    expect(rolePage).toMatch(/async function submitRole\(\) \{\s+if \(!manageAccess\.value\.allowed\)/);
    expect(userPage).toContain('fetchAssignableRoles({ page: 1, page_size: 100 })');
    expect(userPage).toContain('updateUserRoles(selectedUser.value.id, selectedRoleCodes.value)');
    expect(userPage).toMatch(/async function saveRoleAssignment\(\) \{\s+if \(!roleAccess\.value\.allowed/);
  });

  it('consumes role pagination and never marks unresolved APIs connected', () => {
    const rolePage = read('src/views/system/RolePermissionMatrix.vue');
    const securityPage = read('src/views/system/SecurityOperations.vue');
    const resourcePage = read('src/components/AdminResourcePage.vue');
    expect(rolePage).toContain('v-model:current-page="page"');
    expect(rolePage).toContain('page: page.value, page_size: pageSize');
    expect(rolePage).toContain('state === \'ready\' || total > 0');
    expect(rolePage).toContain("ref(useMock ? 'mock' : 'pending')");
    expect(securityPage).toContain("ref(useMock ? 'mock' : 'pending')");
    expect(rolePage + securityPage + resourcePage).toContain("response.http_status ? 'pending' : 'degraded'");
    expect(rolePage).not.toContain("if (response?.success) return 'connected'");
    expect(resourcePage).not.toContain("payload.data.status || 'connected'");
    expect(securityPage).not.toContain("response.data.status || 'connected'");
  });

  it('declares tenant, reference protection, masking, and high-risk boundaries on pages', () => {
    const sources = [
      'src/views/system/DepartmentDirectory.vue', 'src/views/system/UserDirectory.vue',
      'src/views/masterdata/PlatformMasterList.vue', 'src/views/masterdata/SupplierMasterList.vue',
      'src/views/system/SecurityOperations.vue'
    ].map(read).join('\n');
    for (const phrase of ['跨租户', '脱敏', '引用', '凭据']) expect(sources).toContain(phrase);
    expect(sources).not.toContain('真实平台连接');
  });
});
