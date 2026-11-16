import { mount, flushPromises } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ fetchOrderWarehouse: vi.fn(), retryOrderWarehouse: vi.fn() }));
const access = vi.hoisted(() => ({ allowed: true }));
vi.mock('../src/api/salesManagement', () => api);
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: code => access.allowed && code === 'sales_management.orders.view' }) }));
import OrderWarehouseInfo from '../src/components/OrderWarehouseInfo.vue';

let wrapper;
const reply = data => ({ success: true, data });
const matched = { status: 'matched', status_label: '已关联仓库', can_retry: true,
  snapshot_at: '2026-09-11T03:00:00Z', snapshot: { warehouse_code: 'PH001', warehouse_name: '测试仓库', packages: [
    { erp_no: 'ERP-1', warehouse_order_no: 'WH-1', status: 2, status_label: '已发货',
      shipped_at_utc: '2026-09-11T03:00:00Z', items: [{ sku: 'SKU-A', quantity: 2 }] }
  ] } };
const mountPanel = async () => {
  wrapper = mount(OrderWarehouseInfo, { props: { orderId: 1 }, global: { plugins: [ElementPlus] } });
  await flushPromises();
};
beforeEach(() => { vi.resetAllMocks(); vi.useFakeTimers(); access.allowed = true; api.fetchOrderWarehouse.mockResolvedValue(reply(matched)); });
afterEach(() => { wrapper?.unmount(); vi.useRealTimers(); });

describe('订单仓库信息', () => {
  it('读取详情不发起真实查询，显示原始明细和北京时间，缺失值明确标识', async () => {
    await mountPanel();
    expect(api.fetchOrderWarehouse).toHaveBeenCalledWith(1);
    expect(api.retryOrderWarehouse).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('PH001');
    expect(wrapper.text()).toContain('11:00:00');
    expect(wrapper.text()).toContain('SKU-A × 2');
    expect(wrapper.text()).toContain('未提供');
  });
  it('待处理自动刷新，完成停止轮询', async () => {
    api.fetchOrderWarehouse.mockResolvedValueOnce(reply({ status: 'pending', status_label: '等待查询', can_retry: true }))
      .mockResolvedValueOnce(reply(matched));
    await mountPanel();
    expect(wrapper.findAll('button')[1].attributes('disabled')).toBeDefined();
    await vi.advanceTimersByTimeAsync(5000);
    await flushPromises();
    expect(api.fetchOrderWarehouse).toHaveBeenCalledTimes(2);
    expect(wrapper.emitted('updated').map(args => args[0].summary.status)).toEqual(['pending', 'matched']);
    expect(wrapper.emitted('updated')[1][0].orderId).toBe(1);
    await vi.advanceTimersByTimeAsync(10000);
    expect(api.fetchOrderWarehouse).toHaveBeenCalledTimes(2);
  });
  it('重试只提交一次，失败保留快照并提示，不假报成功', async () => {
    api.retryOrderWarehouse.mockResolvedValue({ success: false });
    await mountPanel();
    await wrapper.findAll('button')[1].trigger('click');
    await flushPromises();
    expect(api.retryOrderWarehouse).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[role="alert"]').text()).toContain('未能提交');
    expect(wrapper.text()).toContain('ERP-1');
  });
  it('部分失败保留旧快照并展开各仓库原因', async () => {
    api.fetchOrderWarehouse.mockResolvedValue(reply({ ...matched, status: 'partial', status_label: '查询未完成', stale: true,
      checks: [{ warehouse_id: 2, warehouse: 'PH002', status: 'blocked', message: '网络审批未就绪' }] }));
    await mountPanel();
    expect(wrapper.text()).toContain('不能作为当前仓库状态');
    expect(wrapper.get('details').text()).toContain('PH002：条件未就绪');
    expect(wrapper.text()).toContain('网络审批未就绪');
  });
  it('无订单查看权限时不展示也不请求', async () => {
    access.allowed = false;
    await mountPanel();
    expect(wrapper.find('section').exists()).toBe(false);
    expect(api.fetchOrderWarehouse).not.toHaveBeenCalled();
  });
  it('业务查看用户可以看快照，后端未授权执行时不显示重试按钮', async () => {
    api.fetchOrderWarehouse.mockResolvedValue(reply({ ...matched, can_retry: false }));
    await mountPanel();
    expect(wrapper.text()).toContain('ERP-1');
    expect(wrapper.findAll('button')).toHaveLength(1);
    expect(wrapper.get('button').text()).toContain('刷新查询状态');
  });
  it('切换订单后旧响应不能覆盖新订单，关闭后停止轮询', async () => {
    let resolveOld;
    api.fetchOrderWarehouse.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
      .mockResolvedValueOnce(reply({ status: 'pending', status_label: '新订单等待查询' }));
    await mountPanel();
    await wrapper.setProps({ orderId: 2 });
    await flushPromises();
    resolveOld(reply(matched));
    await flushPromises();
    expect(wrapper.text()).not.toContain('ERP-1');
    expect(wrapper.text()).toContain('新订单等待查询');
    expect(wrapper.emitted('updated')).toHaveLength(1);
    expect(wrapper.emitted('updated')[0][0].orderId).toBe(2);
    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(10000);
    expect(api.fetchOrderWarehouse).toHaveBeenCalledTimes(2);
  });
});
