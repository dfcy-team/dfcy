import { mount, shallowMount } from '@vue/test-utils';
import { expect, it } from 'vitest';
import { platformPackages } from '../src/utils/orderPresentation';
import SalesOrderCards from '../src/components/SalesOrderCards.vue';
import SalesOrderDetailPanel from '../src/components/SalesOrderDetailPanel.vue';

const order = { id: 1, platform: 'lazada', items: [], order_observations: {
  packages: [{ package_id: 'LZ-PKG', tracking_number: 'LZ-TRACK', shipping_carrier: 'Carrier' }],
  platform_logistics: { packages: [] },
} };

it('shows Lazada order-item package details even when tracking is empty', () => {
  const cards = mount(SalesOrderCards, { props: { rows: [order] }, global: { stubs: { ElTag: true } } });
  const detail = shallowMount(SalesOrderDetailPanel, { props: { order } });
  expect(cards.text()).toContain('LZ-TRACK');
  expect(detail.text()).toContain('LZ-PKG');
  expect(detail.text()).toContain('LZ-TRACK');
  expect(detail.text()).toContain('Carrier');
  cards.unmount(); detail.unmount();
});

it('merges a unique parcel identity without mutating the source', () => {
  const original = JSON.stringify(order);
  const merged = platformPackages({ ...order, order_observations: {
    ...order.order_observations, platform_logistics: { packages: [
      { package_number: 'LZ-PKG', tracking_number: null, logistics_status: 'shipped' },
    ] },
  } });
  expect(merged).toHaveLength(1);
  expect(merged[0].tracking_number).toBe('LZ-TRACK');
  expect(merged[0].logistics_status).toBe('shipped');
  expect(JSON.stringify(order)).toBe(original);
});

it('does not invent a package for order-level TikTok events', () => {
  expect(platformPackages({ order_observations: { platform_logistics: {
    packages: [{ package_number: null, events: [{ description: 'Delivered' }] }],
  } } })).toEqual([]);
});
