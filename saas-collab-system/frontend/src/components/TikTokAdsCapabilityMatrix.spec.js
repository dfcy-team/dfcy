import { shallowMount, flushPromises } from '@vue/test-utils';
import { beforeEach, expect, it, vi } from 'vitest';
import Matrix from './TikTokAdsCapabilityMatrix.vue';

const { fetchAdsCapabilities } = vi.hoisted(() => ({ fetchAdsCapabilities: vi.fn() }));
vi.mock('../api/tiktokAds', () => ({ fetchAdsCapabilities, updateAdsReadCapability: vi.fn() }));
vi.mock('../api/integrations', () => ({ createSyncJob: vi.fn() }));
vi.mock('../stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ push: vi.fn() }) }));
const mount = () => shallowMount(Matrix, { global: { directives: { loading: () => {} } } });
const timeout = () => Object.assign(new Error('timeout of 10000ms exceeded'), { code: 'ECONNABORTED' });
beforeEach(() => fetchAdsCapabilities.mockReset());

it('distinguishes timeout from an empty account list and recovers on retry', async () => {
  fetchAdsCapabilities.mockRejectedValueOnce(timeout());
  const wrapper = mount();
  await flushPromises();
  expect(wrapper.findComponent({ name: 'ElTable' }).props('emptyText')).toContain('读取失败');
  expect(wrapper.html()).toContain('不代表广告授权失效');
  fetchAdsCapabilities.mockResolvedValueOnce({ success: true, data: { items: [] } });
  await wrapper.vm.load();
  expect(wrapper.findComponent({ name: 'ElTable' }).props('emptyText')).toContain('暂无广告户');
  expect(wrapper.html()).not.toContain('不代表广告授权失效');
});

it('retains previous rows after refresh failure and marks them stale', async () => {
  const rows = [{ mapping_id: 1, store_id: 1, store_code: 'TK1PH', store_name: 'Test' }];
  fetchAdsCapabilities.mockResolvedValueOnce({ success: true, data: { items: rows } });
  const wrapper = mount();
  await flushPromises();
  fetchAdsCapabilities.mockRejectedValueOnce(timeout());
  await wrapper.vm.load();
  expect(wrapper.findComponent({ name: 'ElTable' }).props('data')).toEqual(rows);
  expect(wrapper.html()).toContain('当前保留上次查询结果，操作已暂停');
});
