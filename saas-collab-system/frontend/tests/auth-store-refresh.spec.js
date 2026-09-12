import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const apiMocks = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  login: vi.fn(),
}));

vi.mock('../src/api/auth', () => apiMocks);
vi.mock('../src/api/request', () => ({ useMock: false }));
vi.mock('../src/utils/authSession', () => ({
  clearAuthSession: vi.fn(),
  readAuthSession: vi.fn(),
  writeAuthSession: vi.fn(),
}));
vi.mock('../src/mock/auth', () => ({ mockAuthUser: { id: 'mock-user' } }));

import { useAuthStore } from '../src/stores/auth';

describe('auth store permission refresh', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    apiMocks.getCurrentUser.mockReset();
  });

  it('replaces the current authorization snapshot after a successful refresh', async () => {
    const auth = useAuthStore();
    auth.setCurrentUser({
      id: 1,
      action_permission_codes: ['system.roles.manage'],
      all_scope_permission_codes: ['system.roles.manage'],
    });
    const refreshed = {
      id: 1,
      action_permission_codes: ['system.roles.view'],
      all_scope_permission_codes: [],
    };
    apiMocks.getCurrentUser.mockResolvedValue({ success: true, data: refreshed });

    const response = await auth.refreshCurrentUser();

    expect(response.success).toBe(true);
    expect(auth.currentUser).toEqual(refreshed);
    expect(auth.hasActionPermission('system.roles.manage')).toBe(false);
  });

  it('keeps the last usable authorization snapshot when refresh fails', async () => {
    const auth = useAuthStore();
    const previous = {
      id: 1,
      action_permission_codes: ['system.roles.manage'],
      all_scope_permission_codes: ['system.roles.manage'],
    };
    auth.setCurrentUser(previous);
    apiMocks.getCurrentUser.mockResolvedValue({ success: false, message: 'temporary failure' });

    const response = await auth.refreshCurrentUser();

    expect(response.success).toBe(false);
    expect(auth.currentUser).toEqual(previous);
    expect(auth.isAuthenticated).toBe(true);
  });
});
