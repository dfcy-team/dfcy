import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ fetchFreightChannels: vi.fn(), fetchFreightQuotes: vi.fn() }));
const auth = vi.hoisted(() => ({ hasPermission: vi.fn(() => true) }));
vi.mock('../src/api/supplyFreightChannelsV2', () => api);
vi.mock('../src/api/supplyChainV2', () => ({
  createIdempotencyKey: () => 'test-key',
  fetchSupplyOptions: vi.fn(async () => ({ success: true, data: [] }))
}));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => auth }));

import FreightChannelsV2 from '../src/components/supply-chain/FreightChannelsV2.vue';

const row = {
  id: 7, version: 3, name: 'Shanghai to US', current_quote: null,
  current_quotes: [
    { id: 10, sequence: 2, billing_basis: 'cbm', fee_per_cbm: '9.00', tax_percent: '0', prices_include_tax: false },
    { id: 12, sequence: 4, billing_basis: 'container', container_type: '40HQ', container_fee: '1850.00', tax_percent: '0', prices_include_tax: false },
    { id: 13, sequence: 5, billing_basis: 'container', container_type: '20GP', container_fee: '1000.00', tax_percent: '0', prices_include_tax: false }
  ]
};

describe('FreightChannels multi-quote contract', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.fetchFreightChannels.mockResolvedValue({ success: true, data: [row], count: 1, business_date: '2026-10-16' });
    api.fetchFreightQuotes.mockResolvedValue({ success: true, data: row.current_quotes, count: 3 });
  });

  it('loads all current schemes without treating the compatibility quote as a selection', async () => {
    const wrapper = mount(FreightChannelsV2, { props: { company: { id: 3, name: 'Carrier', is_active: true } } });
    await flushPromises();
    expect(wrapper.vm.channels[0].current_quotes.map(q => q.id)).toEqual([10, 12, 13]);
    expect(wrapper.vm.channels[0].current_quote).toBeNull();
    await wrapper.vm.openQuote(row);
    expect(wrapper.vm.quoteForm).toMatchObject({ billing_basis: 'cbm', fee_per_cbm: '9.00' });
    await wrapper.vm.showHistory(row);
    expect(wrapper.vm.history).toHaveLength(3);
    wrapper.unmount();
  });

  it('renders each current scheme and shows billing basis and container type in history', async () => {
    const wrapper = mount(FreightChannelsV2, { props: { company: { id: 3, name: 'Carrier', is_active: true } } });
    await flushPromises();
    expect(wrapper.text()).toContain('40HQ');
    expect(wrapper.text()).toContain('20GP');
    expect(wrapper.text()).toContain('9.00');
    await wrapper.vm.showHistory(row);
    await flushPromises();
    expect(wrapper.vm.history.map(q => q.billing_basis)).toEqual(['cbm', 'container', 'container']);
    wrapper.unmount();
  });
});
