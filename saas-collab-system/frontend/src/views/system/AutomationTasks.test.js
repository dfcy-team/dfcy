import { mount, flushPromises } from '@vue/test-utils';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ElPagination } from 'element-plus';
import ElementPlus from 'element-plus';
import Page from './AutomationTasks.vue';
import { getAutomation } from '../../api/automation';
vi.mock('../../api/automation', () => ({ getAutomation: vi.fn() }));
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }));
describe('automation tasks', () => {
  beforeEach(() => { getAutomation.mockReset(); });
  it('loads list, displays unknown observations and fetches details', async () => {
    getAutomation.mockImplementation(async (path = "") => ({ data: path.includes('overview') ? { total:1 } : path === 'tasks/' ? { results:[{ id:'cron:abc', name:'商品ABC', source:'cron', state:'unknown', observed_at:null }], count:1 } : { name:'商品ABC', state:'unknown' } }));
    const wrapper = mount(Page, { global:{ plugins:[ElementPlus] } });
    await flushPromises();
    await wrapper.findAll('.el-tabs__item')[1].trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('商品ABC');
    expect(wrapper.text()).toContain('未采集');
    await wrapper.find('.el-table button').trigger('click'); await flushPromises();
    expect(getAutomation).toHaveBeenCalledWith('tasks/cron%3Aabc/');
    wrapper.unmount();
  });
  it('paginates run records and filters from task details', async () => {
    getAutomation.mockImplementation(async (path = '') => ({ data: path.includes('overview') ? {} : path === 'tasks/' ? { results:[{ id:'sync:1', name:'订单同步' }], count:1 } : path.startsWith('tasks/sync') ? { id:'sync:1', name:'订单同步' } : { results:[{ task_id:'sync:1', name:'订单同步', status:'success' }], count:45 } }));
    const wrapper = mount(Page, { global:{ plugins:[ElementPlus] } });
    await flushPromises();
    await wrapper.findAll('.el-tabs__item')[1].trigger('click'); await flushPromises();
    await wrapper.find('.el-table button').trigger('click'); await flushPromises();
    await wrapper.findAll('button').find(button => button.text() === '查看运行记录').trigger('click'); await flushPromises();
    expect(getAutomation).toHaveBeenLastCalledWith('runs/', expect.objectContaining({ task_id:'sync:1', page:1 }));
    wrapper.findComponent(ElPagination).vm.$emit('update:current-page', 2);
    wrapper.findComponent(ElPagination).vm.$emit('current-change', 2);
    await flushPromises();
    expect(getAutomation).toHaveBeenLastCalledWith('runs/', expect.objectContaining({ task_id:'sync:1', page:2 }));
    wrapper.unmount();
  });
  it('renders API failure and recovers when refreshed', async () => {
    getAutomation.mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ data:{ total:2 } });
    const wrapper = mount(Page, { global:{ plugins:[ElementPlus] } });
    await flushPromises(); expect(wrapper.text()).toContain('读取自动化任务失败');
    await wrapper.findAll('button').find(button => button.text() === '刷新').trigger('click'); await flushPromises();
    expect(wrapper.text()).not.toContain('读取自动化任务失败');
    wrapper.unmount();
  });
  it('keeps the latest selected task when detail responses arrive out of order', async () => {
    const pending = {};
    getAutomation.mockImplementation((path = '') => {
      if (path.includes('overview')) return Promise.resolve({ data:{} });
      if (path === 'tasks/') return Promise.resolve({ data:{ results:[
        { id:'sync:1', name:'甲任务' }, { id:'sync:2', name:'乙任务' }
      ], count:2 } });
      return new Promise(resolve => { pending[path] = resolve; });
    });
    const wrapper = mount(Page, { global:{ plugins:[ElementPlus] } });
    await flushPromises();
    await wrapper.findAll('.el-tabs__item')[1].trigger('click');
    await flushPromises();
    const buttons = wrapper.findAll('.el-table button');
    await buttons[0].trigger('click');
    await buttons[1].trigger('click');
    pending['tasks/sync%3A2/']({ data:{ id:'sync:2', name:'乙任务详情' } });
    await flushPromises();
    pending['tasks/sync%3A1/']({ data:{ id:'sync:1', name:'甲任务详情' } });
    await flushPromises();
    expect(wrapper.text()).toContain('乙任务详情');
    expect(wrapper.text()).not.toContain('甲任务详情');
    wrapper.unmount();
  });

});
