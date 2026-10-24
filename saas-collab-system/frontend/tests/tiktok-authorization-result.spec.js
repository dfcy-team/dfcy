import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ complete: vi.fn(), fetch: vi.fn(), confirm: vi.fn(), cancel: vi.fn(), take: vi.fn(), direct: vi.fn(), replace: vi.fn(), authenticated: true, query: {} }));
vi.mock('../src/api/integrations', () => ({ completeTikTokDirectAuthorization: mocks.complete, fetchTikTokShopBinding: mocks.fetch, confirmTikTokShopBinding: mocks.confirm, cancelTikTokShopBinding: mocks.cancel }));
vi.mock('../src/utils/tiktokBrowserBridge', async original => ({ ...await original(), takeTikTokReceipt: mocks.take, takeTikTokDirectCallback: mocks.direct }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ isAuthenticated: mocks.authenticated }) }));
vi.mock('vue-router', () => ({ useRouter: () => ({ replace: mocks.replace }), useRoute: () => ({ query: mocks.query }) }));
import Result from '../src/views/integrations/TikTokAuthorizationResult.vue';

describe('TK automatic authorization result', () => {
  const payload = { browser_token: 'DEMO', browser_verifier: 'a'.repeat(43), callback_params: { code: 'DEMO_CODE', state: 'demo' } };
  beforeEach(() => { vi.clearAllMocks(); mocks.authenticated = true; mocks.query = {}; mocks.take.mockReturnValue(''); mocks.direct.mockReturnValue(payload); });
  const mountResult = () => mount(Result, { global: { stubs: { 'el-button': { inheritAttrs: true, template: '<button v-bind="$attrs"><slot /></button>' } } } });
  it('saves exactly once without displaying the receipt and does not claim synchronization', async () => {
    mocks.complete.mockResolvedValue({ success: true, data: { status: 'active' } });
    const wrapper = mountResult();
    await flushPromises();
    expect(mocks.complete).toHaveBeenCalledExactlyOnceWith(payload);
    expect(wrapper.text()).toContain('授权已保存');
    expect(wrapper.text()).toContain('尚未执行数据同步');
    expect(wrapper.text()).not.toContain('TEST_RECEIPT');
  });
  it.each(['missing-receipt', 'logged-out'])('does not send an unusable callback: %s', async (condition) => {
    if (condition === 'missing-receipt') mocks.direct.mockReturnValue(null);
    else mocks.authenticated = false;
    const wrapper = mountResult();
    await flushPromises();
    expect(mocks.complete).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('重新发起');
  });
  it('rejects old relay receipts without exchanging them', async () => {
    mocks.direct.mockReturnValue(null);
    mocks.take.mockReturnValue('TEST_RECEIPT');
    const wrapper = mountResult();
    await flushPromises();
    expect(mocks.complete).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('旧版中转回执已停用');
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
  it('shows the server-returned SaaS target and platform store ID after binding', async () => {
    mocks.complete.mockResolvedValue({ success: true, data: { status: 'bound', store_code: 'SHOP-7', store_name: 'North Shop', authorization: { platform_store_id: 'tt-91' } } });
    const wrapper = mountResult();
    await flushPromises();
    expect(wrapper.text()).toContain('已保存到发起店铺');
    expect(wrapper.text()).toContain('North Shop / SHOP-7');
    expect(wrapper.text()).toContain('tt-91');
    expect(wrapper.text()).not.toContain('state');
  });
  it('requires explicit selection and confirmation for a single candidate', async () => {
    mocks.direct.mockReturnValue(null);
    const bindingId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
    mocks.query = { binding_id: bindingId };
    mocks.fetch.mockResolvedValue({ success: true, data: { status: 'pending_confirmation', binding_id: bindingId, store_code: 'SHOP-7', store_name: 'North Shop', store_id: 7, region: 'MY', expires_at: new Date(Date.now() + 60000).toISOString(), candidates: [{ platform_store_id: 'tt-91', name: 'North TikTok', region: 'MY' }] } });
    mocks.confirm.mockResolvedValue({ success: true, data: { status: 'bound', store_code: 'SHOP-7', store_name: 'North Shop', authorization: { platform_store_id: 'tt-91' } } });
    const wrapper = mountResult();
    await flushPromises();
    const confirm = wrapper.findAll('button').find(button => button.text().includes('确认绑定所选店铺'));
    expect(confirm.attributes('disabled')).toBeDefined();
    expect(mocks.confirm).not.toHaveBeenCalled();
    await wrapper.get('input[type="radio"]').setValue('tt-91');
    expect(confirm.attributes('disabled')).toBeUndefined();
    await confirm.trigger('click');
    await flushPromises();
    expect(mocks.confirm).toHaveBeenCalledExactlyOnceWith(bindingId, 'tt-91');
    expect(wrapper.text()).toContain('North Shop / SHOP-7');
    expect(wrapper.text()).not.toContain('state');
  });
  it('does not render unrecognized diagnostic fields or raw server messages', async () => {
    mocks.complete.mockResolvedValue({ success: false, message: 'SECRET_MESSAGE', data: { diagnostic: {
      platform: 'tiktok', stage: 'constructor', category: '__proto__', diagnostic_id: 'c'.repeat(32),
    } } });
    const wrapper = mountResult();
    await flushPromises();
    expect(wrapper.text()).not.toContain('SECRET_MESSAGE');
    expect(wrapper.text()).not.toContain('constructor');
    expect(wrapper.text()).not.toContain('c'.repeat(32));
    expect(wrapper.text()).not.toContain('state');
  });
});
