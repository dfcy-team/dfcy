import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
const route = vi.hoisted(() => ({ query: {} }));
const api = vi.hoisted(() => ({ fetchAdvertisingOverview: vi.fn(), fetchAdvertisingPerformance: vi.fn() }));
vi.mock('vue-router', () => ({ useRoute: () => route }));
vi.mock('../src/api/advertising', () => api);
import ShopeeAdvertisingReport from '../src/components/ShopeeAdvertisingReport.vue';
import { drillQuery } from '../src/views/reports/reportPresentation';
import { rawDetailRoute } from '../src/views/reports/periodAnalysis';

const filters = { date_from: '2026-10-01', date_to: '2026-10-02', currency: 'PHP',
  store_ids: '7,8', platforms: 'shopee,lazada', storecountry: 'PH' };
const stubs = Object.fromEntries(['el-form', 'el-form-item', 'el-select', 'el-option', 'el-date-picker',
  'el-table', 'el-table-column', 'el-pagination', 'el-button', 'el-skeleton', 'el-alert', 'el-empty'].map(key => [key, true]));

describe('V243 advertising scoped drill contract', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    route.query = {};
    api.fetchAdvertisingOverview.mockResolvedValue({ success: true, data: { results: [], count: 0, stores: [] } });
  });
  it('keeps aggregate multi-store/platform/country constraints through the actual records component', async () => {
    route.query = drillQuery('advertising', { date: '2026-10-01', currency: 'PHP' }, {
      dataset: 'advertising', dimensions: ['date', 'currency'], filters,
    });
    const wrapper = mount(ShopeeAdvertisingReport, { global: { stubs } });
    await flushPromises();
    expect(api.fetchAdvertisingOverview).toHaveBeenLastCalledWith(expect.objectContaining({
      store_ids: '7,8', platforms: 'shopee,lazada', storecountry: 'PH', region: 'PH', currency: 'PHP',
      period_start: '2026-10-01', period_end: '2026-10-01', kind: 'shop_daily',
    }));
    wrapper.unmount();
  });
  it('keeps period analysis multivalue filters when opening original daily facts', async () => {
    route.query = rawDetailRoute('advertising', filters).query;
    const wrapper = mount(ShopeeAdvertisingReport, { global: { stubs } });
    await flushPromises();
    expect(api.fetchAdvertisingOverview).toHaveBeenLastCalledWith(expect.objectContaining({
      store_ids: '7,8', platforms: 'shopee,lazada', storecountry: 'PH', region: 'PH',
      period_start: '2026-10-01', period_end: '2026-10-02',
    }));
    wrapper.unmount();
  });
  it('narrows to a grouped store/platform instead of retaining unrelated multiselections', () => {
    const query = drillQuery('advertising', { store_id: 7, platform: 'shopee', storecountry: 'PH' }, {
      dataset: 'advertising', dimensions: ['store_id', 'platform', 'storecountry'], filters,
    });
    expect(query.store_id).toBe(7);
    expect(query.platform).toBe('shopee');
    expect(query.region).toBe('PH');
    expect(query.store_ids).toBeUndefined();
    expect(query.platforms).toBeUndefined();
  });
});
