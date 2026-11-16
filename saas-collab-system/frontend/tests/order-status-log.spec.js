import { mount, flushPromises } from '@vue/test-utils';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ fetchOrderEvents: vi.fn() }));
const access = vi.hoisted(() => ({ allowed: true }));
vi.mock('../src/api/salesManagement', () => api);
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => access.allowed }) }));
import OrderStatusLog from '../src/components/OrderStatusLog.vue';
let wrapper;
beforeEach(() => { vi.resetAllMocks(); access.allowed = true; });
afterEach(() => wrapper?.unmount());
const open = async () => { wrapper = mount(OrderStatusLog, { props: { orderId: 1 } }); await flushPromises(); };
it('does not fabricate missing history', async () => {
  api.fetchOrderEvents.mockResolvedValue({ success: true, data: { events: [], message: '历史时间不推算' } });
  await open(); expect(wrapper.text()).toContain('暂无已保存'); expect(wrapper.findAll('li')).toHaveLength(0);
});
it('keeps collapse below expanded records and distinguishes aftersale completion', async () => {
  api.fetchOrderEvents.mockResolvedValue({ success: true, data: { events: Array.from({ length: 8 }, (_, id) => ({ id, event_at: '2026-10-02T14:02:12Z', status: 'COMPLETED', completed_scenario: id ? 'NORMAL' : 'RRAOC' })) } });
  await open(); expect(wrapper.findAll('li')).toHaveLength(6); expect(wrapper.text()).toContain('完成后售后流程结束');
  expect(wrapper.text()).toContain('22:02:12'); await wrapper.get('.toggle').trigger('click');
  expect(wrapper.findAll('li')).toHaveLength(8); expect(wrapper.get('ol').element.nextElementSibling.textContent).toContain('收起');
  await wrapper.get('.toggle').trigger('click'); expect(wrapper.findAll('li')).toHaveLength(6);
});
it('does not request without view permission', async () => { access.allowed = false; await open(); expect(api.fetchOrderEvents).not.toHaveBeenCalled(); });
it('shows failure instead of empty success', async () => { api.fetchOrderEvents.mockRejectedValue(new Error('test')); await open(); expect(wrapper.get('[role="alert"]').text()).toContain('读取失败'); });
it('discards a previous order response', async () => {
  let resolve;
  api.fetchOrderEvents.mockReturnValueOnce(new Promise(r => { resolve = r; })).mockResolvedValueOnce({ success: true, data: { events: [], message: 'new-order' } });
  await open(); await wrapper.setProps({ orderId: 2 }); await flushPromises();
  resolve({ success: true, data: { events: [], message: 'old-order' } }); await flushPromises();
  expect(wrapper.text()).toContain('new-order'); expect(wrapper.text()).not.toContain('old-order');
});

it('localizes known logistics descriptions and shows markup only as plain original text', async () => {
 api.fetchOrderEvents.mockResolvedValue({ success: true, data: { events: [
  { id: 1, source: '平台物流', status: '1400', title: 'Your package has been delivered!' },
  { id: 2, source: '平台物流', status: '100100', title: 'Your package has been picked up by LEX PH. Kindly share feedback <a href="https://example.invalid">here</a><script>alert(1)</script>' },
  { id: 3, source: '平台物流', title: 'Unknown provider event' }
 ] } });
 await open();
 expect(wrapper.findAll('li strong').map(node => node.text())).toEqual(['包裹已妥投', '物流商已揽收', '物流节点更新']);
 expect(wrapper.text()).not.toContain('订单完成');
 expect(wrapper.findAll('a,script')).toHaveLength(0);
 expect(wrapper.findAll('.original')[1].text()).toContain('feedback here');
 expect(wrapper.text()).not.toContain('href=');
 expect(wrapper.text()).not.toContain('alert(1)');
 expect(wrapper.findAll('.original')[2].text()).toBe('Unknown provider event');
});
