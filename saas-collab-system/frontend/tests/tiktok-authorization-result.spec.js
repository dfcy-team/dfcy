import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ complete: vi.fn(), take: vi.fn(), replace: vi.fn(), authenticated: true }));
vi.mock('../src/api/integrations', () => ({ completeTikTokBrowserAuthorization: mocks.complete }));
vi.mock('../src/utils/tiktokBrowserBridge', () => ({ takeTikTokReceipt: mocks.take }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ isAuthenticated: mocks.authenticated }) }));
vi.mock('vue-router', () => ({ useRouter: () => ({ replace: mocks.replace }) }));
import Result from '../src/views/integrations/TikTokAuthorizationResult.vue';

describe('TK automatic authorization result', () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.authenticated = true; mocks.take.mockReturnValue('FAKE_RECEIPT'); });
  const mountResult = () => mount(Result, { global: { stubs: { 'el-button': { template: '<button><slot /></button>' } } } });
  it('saves exactly once without displaying the receipt and does not claim synchronization', async () => {
    mocks.complete.mockResolvedValue({ success: true });
    const wrapper = mountResult();
    await flushPromises();
    expect(mocks.complete).toHaveBeenCalledExactlyOnceWith({ receipt_token: 'FAKE_RECEIPT' });
    expect(wrapper.text()).toContain('授权已保存');
    expect(wrapper.text()).toContain('尚未执行数据同步');
    expect(wrapper.text()).not.toContain('FAKE_RECEIPT');
  });
  it.each(['missing-receipt', 'logged-out'])('does not send an unusable callback: %s', async (condition) => {
    if (condition === 'missing-receipt') mocks.take.mockReturnValue('');
    else mocks.authenticated = false;
    const wrapper = mountResult();
    await flushPromises();
    expect(mocks.complete).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('重新发起');
  });
  it('never retries uncertain network results or displays raw errors', async () => {
    mocks.complete.mockRejectedValue(new Error('FAKE_SECRET_MUST_NOT_DISPLAY'));
    const wrapper = mountResult();
    await flushPromises();
    expect(mocks.complete).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain('结果尚未确认');
    expect(wrapper.text()).not.toContain('FAKE_SECRET');
  });
  it('shows invalid-code recovery guidance without automatically repeating the exchange', async () => {
    mocks.complete.mockResolvedValue({ success: false, message: 'FAKE_SECRET', data: { diagnostic: {
      platform: 'tiktok', stage: 'exchange_token', category: 'platform_error',
      platform_error_code: '36004004', diagnostic_id: 'b'.repeat(32),
    } } });
    const wrapper = mountResult();
    await flushPromises();
    expect(wrapper.text()).toContain('36004004');
    expect(wrapper.text()).toContain('重新发起授权');
    expect(wrapper.text()).not.toContain('FAKE_SECRET');
    expect(mocks.complete).toHaveBeenCalledOnce();
  });
});
