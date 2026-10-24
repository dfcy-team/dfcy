import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ complete: vi.fn(), fetch: vi.fn(), confirm: vi.fn(), cancel: vi.fn(),
  direct: vi.fn(), replace: vi.fn(), query: {} }));
vi.mock('../src/api/integrations', () => ({ completeTikTokDirectAuthorization: mocks.complete,
  fetchTikTokShopBinding: mocks.fetch, confirmTikTokShopBinding: mocks.confirm, cancelTikTokShopBinding: mocks.cancel }));
vi.mock('../src/utils/tiktokBrowserBridge', async original => ({ ...await original(), takeTikTokReceipt: () => '', takeTikTokDirectCallback: mocks.direct }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ isAuthenticated: true }) }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: mocks.query }), useRouter: () => ({ replace: mocks.replace }) }));
import Result from '../src/views/integrations/TikTokAuthorizationResult.vue';
const id = '12345678-1234-1234-1234-123456789abc';
const pending = () => ({ success: true, data: { status: 'pending_confirmation', binding_id: id,
  store_id: 12, store_code: 'DEMO', store_name: 'Intended SaaS store', region: 'PH',
  expires_at: new Date(Date.now() + 60000).toISOString(), candidates: [{ platform_store_id: 'shop-demo', name: 'Candidate', region: 'PH' }] } });
const render = () => mount(Result, { global: { stubs: { ElButton: { props: ['disabled'], template: '<button :disabled="disabled"><slot /></button>' } } } });
describe('direct Shop explicit confirmation', () => {
  beforeEach(() => {
    vi.clearAllMocks(); mocks.query = {};
    mocks.direct.mockReturnValue({ browser_token: 'DEMO_TOKEN', browser_verifier: 'a'.repeat(43), callback_params: { code: 'DEMO_CODE', state: 'demo' } });
    mocks.complete.mockResolvedValue(pending()); mocks.fetch.mockResolvedValue(pending());
    mocks.confirm.mockResolvedValue({ success: true, data: { status: 'bound', authorization: { status: 'active' } } });
    mocks.cancel.mockResolvedValue({ success: true, data: { status: 'cancelled' } });
  });
  it('requires a radio choice even for one candidate and confirms only on click', async () => {
    const wrapper = render(); await flushPromises();
    expect(wrapper.text()).toContain('Intended SaaS store');
    expect(wrapper.text()).toContain('Candidate / shop-demo / PH');
    expect(wrapper.text()).not.toContain('DEMO_TOKEN');
    expect(wrapper.text()).not.toContain('DEMO_CODE');
    expect(wrapper.find('input[type="radio"]').element.checked).toBe(false);
    expect(wrapper.findAll('button')[0].element.disabled).toBe(true);
    expect(mocks.confirm).not.toHaveBeenCalled();
    expect(mocks.replace).toHaveBeenCalledWith({ path: '/integrations/tiktok/authorization-result', query: { binding_id: id } });
    await wrapper.find('input[type="radio"]').setValue(true);
    await wrapper.findAll('button')[0].trigger('click'); await flushPromises();
    expect(mocks.confirm).toHaveBeenCalledExactlyOnceWith(id, 'shop-demo');
    expect(wrapper.text()).toContain('尚未执行数据同步');
  });
  it('resumes only with GET and explicit cancellation never confirms', async () => {
    mocks.direct.mockReturnValue(null); mocks.query = { binding_id: id };
    const wrapper = render(); await flushPromises();
    expect(mocks.fetch).toHaveBeenCalledExactlyOnceWith(id);
    expect(mocks.complete).not.toHaveBeenCalled();
    await wrapper.findAll('button')[1].trigger('click'); await flushPromises();
    expect(mocks.cancel).toHaveBeenCalledExactlyOnceWith(id);
    expect(mocks.confirm).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('已取消');
  });
  it('does not retry uncertain completion or expose raw errors', async () => {
    mocks.complete.mockRejectedValue(new Error('DEMO_SECRET'));
    const wrapper = render(); await flushPromises();
    expect(mocks.complete).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain('结果尚未确认');
    expect(wrapper.text()).not.toContain('DEMO_SECRET');
  });
  it('refreshes pending bindings via GET without consuming authorization again', async () => {
    const first = render(); await flushPromises(); first.unmount();
    mocks.direct.mockReturnValue(null); mocks.query = { binding_id: id };
    const refreshed = render(); await flushPromises();
    expect(mocks.complete).toHaveBeenCalledOnce();
    expect(mocks.fetch).toHaveBeenCalledExactlyOnceWith(id);
    expect(refreshed.find('input[type="radio"]').element.checked).toBe(false);
    expect(mocks.confirm).not.toHaveBeenCalled();
    expect(mocks.replace).toHaveBeenLastCalledWith({ path: '/integrations/tiktok/authorization-result', query: { binding_id: id } });
  });
  it('does not claim success for unknown status or missing-state backend rejection', async () => {
    mocks.complete.mockResolvedValue({ success: false, data: { reason_code: 'OAUTH_STATE_MISSING' } });
    const rejected = render(); await flushPromises();
    expect(rejected.text()).not.toContain('授权已保存');
    expect(rejected.find('input[type="radio"]').exists()).toBe(false);
    expect(mocks.confirm).not.toHaveBeenCalled();
    rejected.unmount();
    mocks.complete.mockResolvedValue({ success: true, data: { status: 'unknown' } });
    const unknown = render(); await flushPromises();
    expect(unknown.text()).toContain('回填未完成');
    expect(unknown.text()).not.toContain('授权已保存');
    expect(unknown.find('input[type="radio"]').exists()).toBe(false);
    expect(mocks.complete).toHaveBeenCalledTimes(2);
    expect(mocks.confirm).not.toHaveBeenCalled();
  });
});
