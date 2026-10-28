import { mount, flushPromises } from '@vue/test-utils';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { reactive } from 'vue';
import SalesCurrentOperations from '../src/views/sales-management/SalesCurrentOperations.vue';
import { fetchSalesOperations } from '../src/api/salesOperations';
const query = reactive({ view: 'operations', period: 'current' });
vi.mock('vue-router', () => ({ useRoute: () => ({ query }) }));
vi.mock('../src/api/salesOperations', () => ({ fetchSalesOperations: vi.fn() }));
let wrapper;
beforeEach(() => {
  Object.keys(query).forEach(key => delete query[key]); Object.assign(query, { view: 'operations', period: 'current' });
  fetchSalesOperations.mockReset().mockResolvedValue({ success: true, data: { generated_at: '2026-10-26T08:00:00Z', rows: [{ store_id: 1, store_name: '测试店铺', country: 'PH', currency: 'PHP', sales_amount: '123.45', roi: '2', order_count: 3 }], currency_groups: [], has_next: true } });
});
afterEach(() => wrapper?.unmount());
describe('今日累计明细', () => {
  it('只请求current数据且保留筛选和分页，不伪造涨跌', async () => {
    query.store_id = '12'; query.currency = 'PHP';
    wrapper = mount(SalesCurrentOperations); await flushPromises();
    expect(fetchSalesOperations.mock.calls[0][0]).toMatchObject({ period: 'current', view: 'stores', store_id: '12', currency: 'PHP', page: 1 });
    expect(fetchSalesOperations.mock.calls[0][0]).not.toHaveProperty('date_from');
    expect(wrapper.text()).toContain('123.45');
    expect(wrapper.text()).toContain('不显示涨跌幅');
    await wrapper.find('footer button:last-child').trigger('click'); await flushPromises();
    expect(fetchSalesOperations.mock.calls.at(-1)[0].page).toBe(2);
  });
  it('参数异常时停止查询而不是扩大范围', async () => {
    query.store_id = ['1', '2'];
    wrapper = mount(SalesCurrentOperations); await flushPromises();
    expect(fetchSalesOperations).not.toHaveBeenCalled();
    expect(wrapper.find('[role="alert"]').text()).toContain('参数无效');
  });
});
