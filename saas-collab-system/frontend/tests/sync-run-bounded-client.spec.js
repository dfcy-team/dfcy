import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, shallowMount } from '@vue/test-utils';

const requests = vi.hoisted(() => ({ requestWithMockFallback: vi.fn(), requestApi: vi.fn() }));
vi.mock('../src/api/request', () => ({ ...requests, useMock: false }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }));
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ query: {} }) }));
import { fetchSyncRuns, fetchApiSyncLogs } from '../src/api/integrations';
import PlatformDrillWorkbench from '../src/views/integrations/PlatformDrillWorkbench.vue';

const configs = [1, 2].map(id => ({ id, platform: 'shopee', api_type: 'marketplace',
  account_alias: `config-${id}`, environment: 'sandbox', status: 'verified', regions: [] }));
const success = data => ({ success: true, data });
const mountWorkbench = () => shallowMount(PlatformDrillWorkbench, {
  global: { stubs: { ElCard: { template: '<section><slot /></section>' } } },
});

function respond(config, pendingFirstRun) {
  if (config.url === '/api/internal/integrations/configs/') return success({ results: configs });
  const detail = config.url.match(/\/configs\/(\d+)\/$/);
  if (detail) return success(configs.find(row => row.id === Number(detail[1])));
  if (config.url === '/api/internal/integrations/sync-runs/') {
    if (pendingFirstRun && config.params.integration_config_id === 1) return pendingFirstRun;
    return success({ count: 1, results: [{ id: config.params.integration_config_id * 10, platform: 'shopee' }] });
  }
  return success({ results: [] });
}

describe('bounded sync run requests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requests.requestWithMockFallback.mockImplementation(config => Promise.resolve(respond(config)));
    requests.requestApi.mockImplementation(config => Promise.resolve(respond(config)));
  });
  it('forwards paging and server-side filters for both collection callers', async () => {
    const params = { page: 2, page_size: 8, integration_config_id: 34 };
    await fetchSyncRuns(params);
    await fetchApiSyncLogs(params);
    expect(requests.requestWithMockFallback).toHaveBeenCalledTimes(2);
    for (const [config] of requests.requestWithMockFallback.mock.calls) {
      expect(config).toMatchObject({ method: 'get', url: '/api/internal/integrations/sync-runs/', params });
    }
  });

  it('requests the latest eight runs for each selected configuration', async () => {
    const wrapper = mountWorkbench();
    await flushPromises();
    const selector = wrapper.findComponent({ name: 'ElSelect' });
    selector.vm.$emit('update:modelValue', 2);
    selector.vm.$emit('change', 2);
    await flushPromises();
    const calls = requests.requestWithMockFallback.mock.calls.map(([config]) => config)
      .filter(config => config.url === '/api/internal/integrations/sync-runs/');
    expect(calls.map(config => config.params)).toEqual([
      { integration_config_id: 1, page: 1, page_size: 8 },
      { integration_config_id: 2, page: 1, page_size: 8 },
    ]);
    expect(wrapper.vm.runs.map(row => row.id)).toEqual([20]);
    wrapper.unmount();
  });

  it('ignores an older run response after switching configuration', async () => {
    let completeFirst;
    const pending = new Promise(resolve => { completeFirst = resolve; });
    requests.requestWithMockFallback.mockImplementation(config => Promise.resolve(respond(config, pending)));
    const wrapper = mountWorkbench();
    await flushPromises();
    const selector = wrapper.findComponent({ name: 'ElSelect' });
    selector.vm.$emit('update:modelValue', 2);
    selector.vm.$emit('change', 2);
    await flushPromises();
    completeFirst(success({ count: 1, results: [{ id: 10, platform: 'shopee' }] }));
    await flushPromises();
    expect(wrapper.vm.runs.map(row => row.id)).toEqual([20]);
    wrapper.unmount();
  });
});
