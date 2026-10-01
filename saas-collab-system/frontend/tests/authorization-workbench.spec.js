import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const apiMocks = vi.hoisted(() => ({ getCurrentUser: vi.fn(), login: vi.fn() }));
vi.mock('../src/api/auth', () => apiMocks);
vi.mock('../src/api/request', () => ({ useMock: false }));
vi.mock('../src/utils/authSession', () => ({ clearAuthSession: vi.fn(), readAuthSession: vi.fn(), writeAuthSession: vi.fn() }));
vi.mock('../src/mock/auth', () => ({ mockAuthUser: { id: 'mock-user' } }));
import { useAuthStore } from '../src/stores/auth';
import { authorizationPreviewSignature, canApplyAuthorizationPreview } from '../src/utils/authorizationPreview';
import { buildResourcePoliciesForSave, splitResourcePolicies } from '../src/utils/authorizationPreview';

describe('authorization stale fail-closed behavior', () => {
  beforeEach(() => { setActivePinia(createPinia()); apiMocks.getCurrentUser.mockReset(); });

  it('retains display data but blocks actions after refresh failure, then reopens them on success', async () => {
    const auth = useAuthStore();
    const snapshot = { id: 7, username: 'operator', action_permission_codes: ['system.users.manage'] };
    auth.setCurrentUser(snapshot);
    apiMocks.getCurrentUser.mockResolvedValueOnce({ success: false, message: 'offline' });

    await auth.refreshCurrentUser();

    expect(auth.currentUser).toEqual(snapshot);
    expect(auth.isAuthenticated).toBe(true);
    expect(auth.authorizationStale).toBe(true);
    expect(auth.hasActionPermission('system.users.manage')).toBe(false);

    apiMocks.getCurrentUser.mockResolvedValueOnce({ success: true, data: snapshot });
    await auth.refreshCurrentUser();

    expect(auth.authorizationStale).toBe(false);
    expect(auth.hasActionPermission('system.users.manage')).toBe(true);
  });

  it('invalidates a preview when any batch input changes and blocks it while stale', () => {
    const input = { userIds: [2, 1], roleCodes: ['sales', 'ops'], operation: 'transfer', replaceSource: 'position', reason: '岗位调动' };
    const previewSignature = authorizationPreviewSignature(input);
    const preview = { preview_token: 'signed-test-token' };
    expect(canApplyAuthorizationPreview(preview, previewSignature, authorizationPreviewSignature(input))).toBe(true);
    for (const changed of [
      { ...input, userIds: [1] },
      { ...input, roleCodes: ['sales'] },
      { ...input, operation: 'offboard' },
      { ...input, replaceSource: 'legacy' },
      { ...input, reason: '其他原因' },
    ]) {
      expect(canApplyAuthorizationPreview(preview, previewSignature, authorizationPreviewSignature(changed))).toBe(false);
    }
    expect(canApplyAuthorizationPreview(preview, previewSignature, authorizationPreviewSignature(input), true)).toBe(false);
  });

  it('preserves operation-specific policies and nonempty custom dimensions in a wildcard edit', () => {
    const exact = { resource_code: 'platform_product_details', permission_code: 'listings.product_detail.export', scope_type: 'custom', config: { store_ids: [4] } };
    const unknown = { resource_code: 'future.resource', permission_code: '*', scope_type: 'custom', config: { future_ids: [8] } };
    const definitions = [{ resource_code: 'platform_product_details' }];
    const { wildcardByResource, operationPolicies } = splitResourcePolicies(definitions, [exact, unknown, {
      resource_code: 'platform_product_details', permission_code: '*', scope_type: 'custom', config: { platform_ids: [2] },
    }]);
    const result = buildResourcePoliciesForSave(definitions, { platform_product_details: true }, {
      platform_product_details: { scope_type: 'custom', config: { platform_ids: [3], store_ids: [], custom_ids: [9] } },
    }, operationPolicies);
    expect(wildcardByResource.platform_product_details.config.platform_ids).toEqual([2]);
    expect(result).toEqual([exact, unknown, {
      resource_code: 'platform_product_details', permission_code: '*', scope_type: 'custom', config: { platform_ids: [3], custom_ids: [9] },
    }]);
  });

  it('denies explicitly inactive capabilities even to a superuser', () => {
    const auth = useAuthStore();
    auth.setCurrentUser({
      id: 1, is_superuser: true,
      inactive_permission_codes: ['system.users.manage', 'field.system.users.department.view'],
      hidden_menu_permission_codes: ['menu.system.users.view'],
    });
    expect(auth.hasPermission('system.users.manage')).toBe(false);
    expect(auth.hasActionPermission('system.users.manage')).toBe(false);
    expect(auth.hasFieldPermission('field.system.users.department.view')).toBe(false);
    expect(auth.hasMenuPermission('menu.system.users.view')).toBe(false);
  });
});
