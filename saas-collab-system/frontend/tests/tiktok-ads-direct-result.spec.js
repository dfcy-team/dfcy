import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ complete: vi.fn(), get: vi.fn(), take: vi.fn(), replace: vi.fn() }));
vi.mock('../src/api/tiktokAds', () => ({ completeAdsDirectOAuth: mocks.complete, getAdsSession: mocks.get }));
vi.mock('../src/utils/tiktokAdsDirect', async original => ({ ...await original(), takeAdsDirectCallback: mocks.take }));
vi.mock('../src/utils/tiktokAdsBridge', async original => ({ ...await original(), takeAdsReceipt: () => null }));
vi.mock('vue-router', () => ({ useRoute: () => ({ path: '/integrations/tiktok-ads/direct-callback', query: {} }),
  useRouter: () => ({ replace: mocks.replace }) }));
import Result from '../src/views/integrations/TikTokAdsAuthorizationResult.vue';
const id = '12345678-1234-1234-1234-123456789abc';
const payload = { browser_token: 'DEMO_TOKEN', browser_verifier: 'a'.repeat(43), callback_params: { auth_code: 'DEMO_CODE', state: 'demo' } };
const render = () => mount(Result, { global: { stubs: {
  TikTokAdsSessionPanel: { props: ['sessionId'], template: '<div class="session">{{ sessionId }}</div>' },
  ElButton: { template: '<button><slot /></button>' },
} } });
describe('direct-only Ads result', () => {
  beforeEach(() => {
    vi.clearAllMocks(); mocks.take.mockReturnValue(payload);
    mocks.complete.mockResolvedValue({ success: true, data: { session_id: id, status: 'authorized' } });
  });
  it('completes once and replaces URL with only a safe session ID', async () => {
    const wrapper = render(); await flushPromises();
    expect(mocks.complete).toHaveBeenCalledExactlyOnceWith(payload);
    expect(mocks.replace).toHaveBeenCalledWith('/integrations/tiktok-ads/authorization-result?session_id=' + id);
    expect(wrapper.find('.session').text()).toBe(id);
    expect(wrapper.text()).toContain('尚未同步任何报表');
    expect(wrapper.text()).not.toContain('DEMO_TOKEN');
    expect(wrapper.text()).not.toContain('DEMO_CODE');
  });
  it('rejects a stale direct page without requests', async () => {
    mocks.take.mockReturnValue(null);
    const wrapper = render(); await flushPromises();
    expect(mocks.complete).not.toHaveBeenCalled();
    expect(mocks.get).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('不要重复提交');
  });
  it('never repeats an uncertain callback', async () => {
    mocks.complete.mockRejectedValue(new Error('DEMO_SECRET'));
    const wrapper = render(); await flushPromises();
    expect(mocks.complete).toHaveBeenCalledOnce();
    expect(mocks.get).not.toHaveBeenCalled();
    expect(wrapper.text()).not.toContain('DEMO_SECRET');
    expect(wrapper.text()).toContain('结果尚未确认');
  });
});
