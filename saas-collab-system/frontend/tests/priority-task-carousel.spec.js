import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import PriorityTaskCarousel from '../src/views/influencers/PriorityTaskCarousel.vue';

describe('priority task carousel', () => {
  it('shows one task and wraps through both priority groups', async () => {
    const wrapper = mount(PriorityTaskCarousel, { props: { groups: {
      urgent: [{ id: 1, task_no: 'A', task_name: 'First' }],
      high: [{ id: 2, task_no: 'B', task_name: 'Second' }],
    } } });
    expect(wrapper.findAll('.task')).toHaveLength(1);
    expect(wrapper.find('.task').text()).toContain('First');
    await wrapper.get('[aria-label="下一条重点任务"]').trigger('click');
    expect(wrapper.find('.task').text()).toContain('Second');
    await wrapper.get('[aria-label="下一条重点任务"]').trigger('click');
    expect(wrapper.find('.task').text()).toContain('First');
    await wrapper.get('[aria-label="上一条重点任务"]').trigger('click');
    expect(wrapper.find('.task').text()).toContain('Second');
    await wrapper.setProps({ groups: { urgent: [], high: [] } });
    expect(wrapper.findAll('.task')).toHaveLength(0);
    expect(wrapper.text()).toContain('暂无紧急');
    wrapper.unmount();
  });
});
