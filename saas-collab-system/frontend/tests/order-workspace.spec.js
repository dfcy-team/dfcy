import { mount } from '@vue/test-utils';
import { describe, it, expect } from 'vitest';
import SalesOrderCards from '../src/components/SalesOrderCards.vue';
import SalesOrderDetailPanel from '../src/components/SalesOrderDetailPanel.vue';
import { warehouseItemPairs, extraOrderTimes, matchWarehouseItem, primaryOrderTime, orderMoney, orderTime } from '../src/utils/orderPresentation';

const order = { id: 1, external_order_id: 'TEST-ORDER', platform: 'shopee', normalized_status: 'cancelled',
  created_at_utc: '2026-09-30T09:31:00Z', paid_at_utc: '2026-09-30T09:31:00Z',
  store: { code: 'TEST', region: 'PH' }, order_total_amount: '606.0000', currency: 'PHP',
  items: [{ id: 1, seller_sku: 'TEST-SKU', quantity: 2 }] };

describe('order workspace', () => {
  it('keeps cancellation, completion and payment semantics separate', () => {
    expect(primaryOrderTime(order)).toEqual(['取消', undefined]);
    expect(primaryOrderTime({ ...order, normalized_status: 'completed' })).toEqual(['完成', undefined]);
    expect(orderTime(order.created_at_utc)).toContain('17:31');
    expect(primaryOrderTime({ ...order, normalized_status: 'processing', raw_status: 'IN_CANCEL', cancel_requested_at_utc: '2026-10-01T01:00:00Z' })).toEqual(['申请取消', '2026-10-01T01:00:00Z']);
    expect(primaryOrderTime({ ...order, raw_status: 'IN_CANCEL' })).toEqual(['取消', undefined]);
    expect(orderMoney(null)).toBe('未提供');
    expect(orderMoney('0.0000')).toBe('0.00');
  });
  it('matches only a unique platform and warehouse SKU with a current snapshot', () => {
    const data = { ...order, warehouse_summary: { snapshot: { packages: [{ items: [{ sku: 'TEST-SKU', quantity: 2 }] }] } } };
    expect(matchWarehouseItem(data, order.items[0]).quantity).toBe(2);
    expect(matchWarehouseItem({ ...data, items: [...order.items, ...order.items] }, order.items[0])).toBeNull();
    expect(matchWarehouseItem({ ...data, warehouse_summary: { ...data.warehouse_summary, stale: true } }, order.items[0])).toBeNull();
    data.warehouse_summary.snapshot.packages.push({ items: [{ sku: 'TEST-SKU', quantity: 1 }] });
    expect(matchWarehouseItem(data, order.items[0])).toBeNull();
  });
  it('puts collapse after expanded times and preserves order actions', async () => {
    const wrapper = mount(SalesOrderCards, { props: { rows: [order], selectable: true }, global: { stubs: { ElTag: { template: '<span><slot /></span>' } } } });
    expect(wrapper.text()).not.toContain('订单完成');
    await wrapper.findAll('button').find(button => button.text() === '更多时间 ↓').trigger('click');
    const html = wrapper.html();
    expect(html.indexOf('买家支付')).toBeLessThan(html.indexOf('收起时间'));
    await wrapper.find('input[type=checkbox]').setValue(true);
    expect(wrapper.emitted('selection')[0][0][0].id).toBe(1);
    await wrapper.findAll('button').find(button => button.text() === '查看详情').trigger('click');
    expect(wrapper.emitted('open')[0][0].id).toBe(1);
    wrapper.unmount();
  });
  it('retains original amount evidence without conversion and never invents missing converted source values', () => {
    const stubs = { ElTag: true, ElButton: true, OrderWarehouseInfo: true, OrderStatusLog: true, OrderRegistrationLinks: true };
    const detail = mount(SalesOrderDetailPanel, { props: { order: { ...order, currency: 'PHP', subtotal_amount: '128.0000', order_total_amount: '130.0000' } }, global: { stubs } });
    expect(detail.text()).toContain('商品小计：128.0000 PHP');
    expect(detail.text()).toContain('订单金额：130.0000 PHP');
    detail.unmount();
    const converted = mount(SalesOrderDetailPanel, { props: { order: { ...order, currency: 'CNY', source_currency: 'PHP', order_total_amount: '13.00', source_amounts: {} } }, global: { stubs } });
    expect(converted.text()).toContain('订单金额：未提供 PHP');
    expect(converted.text()).not.toContain('订单金额：13.00 PHP');
    converted.unmount();
  });
  it('labels converted amounts as display currency and shows supplied source amounts in detail', () => {
    const converted = { ...order, currency: 'CNY', order_total_amount: '303.00', source_currency: 'PHP', source_amounts: { order_total_amount: '606.0000' } };
    const cards = mount(SalesOrderCards, { props: { rows: [converted] }, global: { stubs: { ElTag: { template: '<span><slot /></span>' } } } });
    expect(cards.text()).toContain('金额按当前展示币种');
    expect(cards.text()).not.toContain('金额按原币种');
    expect(cards.get('.order-money').text()).toContain('CNY');
    const detail = mount(SalesOrderDetailPanel, { props: { order: converted }, global: { stubs: { ElTag: true, ElButton: true, OrderWarehouseInfo: true, OrderStatusLog: true, OrderRegistrationLinks: true } } });
    expect(detail.text()).toContain('本页金额为 CNY 展示金额');
    expect(detail.text()).toContain('订单金额：606.0000 PHP');
    cards.unmount(); detail.unmount();
  });
});

describe('workspace completeness', () => {
 it('keeps split warehouse lines, flags quantities and excludes stale matches', () => {
  const data = { ...order, warehouse_summary: { snapshot: { packages: [{ items: [{ sku: 'TEST-SKU', quantity: 1 }, { warehouse_sku: 'TEST-SKU', quantity: 2 }, { sku: 'OTHER', quantity: 1 }] }] } } };
  const pairs = warehouseItemPairs(data);
  expect(pairs[0].matches).toHaveLength(2); expect(pairs[0].mismatch).toBe(true); expect(pairs[1].line).toBeNull();
  data.warehouse_summary.stale = true; expect(warehouseItemPairs(data)[0].matches).toHaveLength(0);
 });
 it('folds extra products and separates delivery from completion', async () => {
  const data = { ...order, items: [1,2,3].map(id => ({ id, seller_sku: `SKU-${id}`, quantity: 1 })), order_observations: { platform_delivered_at_utc: '2026-10-02T04:34:00Z' } };
  const wrapper = mount(SalesOrderCards, { props: { rows: [data] }, global: { stubs: { ElTag: { template: '<span><slot /></span>' } } } });
  expect(wrapper.findAll('.product')).toHaveLength(2);
  await wrapper.findAll('button').find(button => button.text().includes('另 1 项')).trigger('click');
  expect(wrapper.findAll('.product')).toHaveLength(3);
  expect(extraOrderTimes(data).map(row => row[0])).toContain('平台妥投（非订单完成）');
  expect(primaryOrderTime(data)[0]).toBe('取消');
 });
});

it('uses explicit pickup events and warehouse shipment without inventing completion', () => {
 const data = { ...order, normalized_status: 'confirmed', order_observations: { platform_logistics: { packages: [{ events: [
  { description: 'Your package has been picked up by LEX PH.', occurred_at_utc: '2026-10-01T08:09:13Z' },
  { description: 'Your package has been delivered!', occurred_at_utc: '2026-10-03T03:43:01Z' }
 ] }] } }, warehouse_summary: { snapshot: { packages: [{ shipped_at_utc: '2026-10-01T07:30:24Z' }] } } };
 expect(primaryOrderTime(data)).toEqual(['平台揽收（轨迹）', '2026-10-01T08:09:13Z']);
 expect(extraOrderTimes(data).map(row => row[0])).toContain('仓库发货');
 expect(primaryOrderTime({ ...data, normalized_status: 'completed' })).toEqual(['完成', undefined]);
 data.warehouse_summary.stale = true;
 expect(extraOrderTimes(data).map(row => row[0])).not.toContain('仓库发货');
 data.order_observations.platform_logistics.packages.push({ events: [] });
 expect(primaryOrderTime(data)).toEqual(['揽收', null]);
});

it('separates order and warehouse status and folds raw provider values', () => {
 const data = { ...order, normalized_status: 'confirmed', raw_status: 'confirmed', warehouse_summary: { status: 'matched', status_label: '已关联仓库', snapshot: { packages: [{ status_label: '未提供或未知状态' }] } } };
 const wrapper = mount(SalesOrderCards, { props: { rows: [data] }, global: { stubs: { ElTag: { template: '<span><slot /></span>' } } } });
 const progress = wrapper.get('.order-progress');
 expect(progress.findAll('.progress-label').map(node => node.text())).toEqual(['订单', '仓库']);
 expect(progress.text()).toContain('状态待确认');
 expect(progress.text()).not.toContain('未提供或未知状态');
 expect(progress.text()).toContain('已匹配仓库');
 expect(progress.get('details').attributes('open')).toBeUndefined();
 expect(progress.get('details small').text()).toBe('confirmed');
 wrapper.unmount();
});
