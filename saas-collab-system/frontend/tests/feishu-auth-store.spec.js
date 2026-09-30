import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const mocks = vi.hoisted(() => ({ login: vi.fn(), complete: vi.fn(), me: vi.fn(), write: vi.fn(), clear: vi.fn() }));
vi.mock('../src/api/auth', () => ({ login: mocks.login, completeFeishuLogin: mocks.complete, getCurrentUser: mocks.me }));
vi.mock('../src/api/request', () => ({ useMock: false }));
vi.mock('../src/utils/authSession', () => ({ readAuthSession: vi.fn(() => null), writeAuthSession: mocks.write, clearAuthSession: mocks.clear }));
import { useAuthStore } from '../src/stores/auth';

describe('auth store login actions', () => {
  beforeEach(() => { vi.clearAllMocks(); setActivePinia(createPinia()); });

  it('authenticates through password login after the Feishu path fails', async () => {
    mocks.complete.mockResolvedValue({ success: false, code: 'unbound' });
    mocks.login.mockResolvedValue({ success: true, data: { access: 'synthetic-access', refresh: 'synthetic-refresh' } });
    mocks.me.mockResolvedValue({ success: true, data: { id: 17, username: 'synthetic-user' } });
    const auth = useAuthStore();
    const feishu = await auth.completeFeishuLogin();
    expect(feishu.success).toBe(false);
    const password = await auth.login({ username: 'synthetic-user', password: 'synthetic-password' });
    expect(password.success).toBe(true);
    expect(auth.isAuthenticated).toBe(true);
    expect(auth.currentUser.username).toBe('synthetic-user');
    expect(mocks.login).toHaveBeenCalledOnce();
  });

  it('clears tokens and authentication if profile loading fails after a successful provider response', async () => {
    mocks.complete.mockResolvedValue({ success: true, data: { access: 'synthetic-access', refresh: 'synthetic-refresh' } });
    mocks.me.mockResolvedValue({ success: false, message: 'profile unavailable' });
    const auth = useAuthStore();
    const result = await auth.completeFeishuLogin();
    expect(result.success).toBe(false);
    expect(mocks.write).toHaveBeenCalledWith({ access: 'synthetic-access', refresh: 'synthetic-refresh' });
    expect(mocks.clear).toHaveBeenCalledOnce();
    expect(auth.isAuthenticated).toBe(false);
  });

  it('rejects success responses without both tokens', async () => {
    mocks.complete.mockResolvedValue({ success: true, data: { access: 'synthetic-access' } });
    const auth = useAuthStore();
    const result = await auth.completeFeishuLogin();
    expect(result.success).toBe(false);
    expect(mocks.me).not.toHaveBeenCalled();
    expect(mocks.write).not.toHaveBeenCalled();
    expect(auth.isAuthenticated).toBe(false);
  });
});
