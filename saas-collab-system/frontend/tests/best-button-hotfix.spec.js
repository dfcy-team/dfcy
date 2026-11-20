import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import BestWarehouseAccess from '../src/components/BestWarehouseAccess.vue';
import { requestApi } from '../src/api/request';
vi.mock('../src/api/request', () => ({ requestApi: vi.fn() }));
vi.mock('../src/components/BestWarehouseOperations.vue', () => ({ default: { template: '<div />' } }));
describe('BEST warehouse verification button', () => {
  beforeEach(() => {
    requestApi.mockReset();
    const base = { authorization_id: 5, execution_enabled: true, version: 7, status: 'pending', key_configured: true, customer_code: 'TEST-CUSTOMER', partner_id: 'TEST-PARTNER' };
    requestApi.mockImplementation(async ({ method }) => ({ success: true, data: method === 'get' ? base : {
      ...base, selection_required: true, country_confirmation_required: true, local_country: 'MY',
      warehouses: [{ code: 'SA_01', name: 'Test warehouse', country: 'CN' }]
    } }));
  });
  it('queries without SKU and sends warehouse plus explicit country confirmation', async () => {
    const wrapper = mount(BestWarehouseAccess, { props: { warehouseId: 6, canCheck: true, canManage: true }, global: { plugins: [ElementPlus] } });
    await flushPromises();
    await wrapper.findAll('form')[1].trigger('submit');
    await flushPromises();
    expect(requestApi.mock.calls[1][0].data).toEqual({ warehouse_code: '' });
    await wrapper.get('select').setValue('SA_01');
    await wrapper.findAll('form')[1].trigger('submit');
    await flushPromises();
    expect(requestApi).toHaveBeenCalledTimes(2);
    await wrapper.get('input[type="checkbox"]').setValue(true);
    await wrapper.findAll('form')[1].trigger('submit');
    await flushPromises();
    expect(requestApi.mock.calls[2][0]).toMatchObject({ method: 'post', url: '/api/internal/integrations/warehouses/6/best-access/check/', data: {
      warehouse_code: 'SA_01', confirm_country_mismatch: true, version: 7, confirmed_country: 'CN'
    } });
    wrapper.unmount();
  });
  it('does not submit without management permission', async () => {
    const wrapper = mount(BestWarehouseAccess, { props: { warehouseId: 6, canCheck: true, canManage: false }, global: { plugins: [ElementPlus] } });
    await flushPromises();
    await wrapper.findAll('form')[1].trigger('submit');
    await flushPromises();
    expect(requestApi).toHaveBeenCalledTimes(1);
    expect(wrapper.findAll('form')[1].get('button').attributes('disabled')).toBeDefined();
    wrapper.unmount();
  });
});
