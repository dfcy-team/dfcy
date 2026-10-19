import { shallowMount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => Object.fromEntries(['confirmProductCostImport', 'confirmProductCostVersion', 'createProductCostVersion', 'executeProductCostBackfill', 'fetchCostWarehouses', 'fetchProductCosts', 'previewProductCostBackfill', 'previewProductCostImport'].map((key) => [key, vi.fn()])));
vi.mock('../src/api/productCosts', () => api);
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }));
import ProductCostLedger from '../src/views/products/ProductCostLedger.vue';

describe('cost version decimal payload', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.fetchProductCosts.mockResolvedValue({ success: true, data: { items: [], total: 0 } });
    api.fetchCostWarehouses.mockResolvedValue({ success: true, data: [] });
    api.createProductCostVersion.mockResolvedValue({ success: true });
  });
  it.each([
    [0.1, 0.2, '0.3000'],
    ['0.0001', '0.0002', '0.0003'],
    [0, 0, '0.0000'],
    [null, 0, null],
  ])('submits bounded decimal precision for %s plus %s', async (purchase, freight, expected) => {
    const wrapper = shallowMount(ProductCostLedger);
    await flushPromises();
    wrapper.vm.edit({ sku_id: 1, warehouse: 2, status: 'confirmed', effective_from: '2026-10-19', purchase_price: purchase, freight_cost: freight, duty_cost: 0, packaging_cost: 0, other_cost: 0, confirmed_cost: '0.3000' });
    wrapper.vm.form.reason = 'decimal regression';
    await wrapper.vm.save();
    expect(api.createProductCostVersion).toHaveBeenCalledOnce();
    expect(api.createProductCostVersion.mock.calls[0][0].system_cost).toBe(expected);
    wrapper.unmount();
  });
});
