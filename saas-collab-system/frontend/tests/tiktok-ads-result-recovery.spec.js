import { flushPromises, mount } from '@vue/test-utils';
import { reactive } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { completeAdsOAuth, getAdsSession } from '../src/api/tiktokAds';
import { takeAdsReceipt } from '../src/utils/tiktokAdsBridge';
import Result from '../src/views/integrations/TikTokAdsAuthorizationResult.vue';
const routing = vi.hoisted(() => ({ route: null, replace: vi.fn() }));
vi.mock('vue-router', () => ({ useRoute: () => routing.route, useRouter: () => ({ replace: routing.replace }) }));
vi.mock('../src/api/tiktokAds', () => ({ completeAdsOAuth: vi.fn(), getAdsSession: vi.fn() }));
vi.mock('../src/utils/tiktokAdsBridge', async original => ({ ...await original(), takeAdsReceipt: vi.fn() }));
const session = '11111111-2222-4333-8444-555555555555';
const another = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
const snapshot = { success: true, data: { session_id: session, status: 'authorized', candidates: [] } };
const render = () => mount(Result, { global: { stubs: {
  TikTokAdsSessionPanel: { props: ['sessionId'], template: '<div class="candidates">{{ sessionId }}</div>' },
  ElButton: { template: '<button><slot /></button>' },
} } });
describe('Ads result reload and bookmark recovery', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routing.route = reactive({ query: { session_id: session } });
    takeAdsReceipt.mockReturnValue(null);
    getAdsSession.mockResolvedValue(snapshot);
    completeAdsOAuth.mockResolvedValue(snapshot);
  });
  it('completes once, then refresh and bookmark navigation use GET only', async () => {
    takeAdsReceipt.mockReturnValueOnce({ session_id: session, receipt_id: 'a'.repeat(64) });
    const first = render(); await flushPromises();
    expect(completeAdsOAuth).toHaveBeenCalledExactlyOnceWith({ session_id: session, receipt_id: 'a'.repeat(64) });
    first.unmount();
    const refreshed = render(); await flushPromises();
    expect(refreshed.find('.candidates').text()).toBe(session);
    expect(getAdsSession).toHaveBeenCalledExactlyOnceWith(session);
    routing.route.query = { session_id: another }; await flushPromises();
    expect(getAdsSession).toHaveBeenLastCalledWith(another);
    expect(refreshed.find('.candidates').text()).toBe(another);
    expect(completeAdsOAuth).toHaveBeenCalledTimes(1);
    refreshed.unmount();
  });
  it('resumes an authorized bookmark without possessing or requesting a receipt', async () => {
    const wrapper = render(); await flushPromises();
    expect(getAdsSession).toHaveBeenCalledExactlyOnceWith(session);
    expect(completeAdsOAuth).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('可收藏此页');
    wrapper.unmount();
  });
  it.each([{ session_id: 'bad' }, { session_id: [session, another] }, { session_id: session, receipt_id: 'bad' }])('does not request malformed query %j', async query => {
    routing.route.query = query;
    const wrapper = render(); await flushPromises();
    expect(getAdsSession).not.toHaveBeenCalled();
    expect(completeAdsOAuth).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('does not reveal candidates when the authenticated session GET is denied', async () => {
    getAdsSession.mockResolvedValue({ success: false, http_status: 403 });
    const wrapper = render(); await flushPromises();
    expect(wrapper.find('.candidates').exists()).toBe(false);
    expect(completeAdsOAuth).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
