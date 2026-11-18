import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import { createElementBlock, createVNode, defineComponent, nextTick, openBlock, ref } from 'vue';
import PriorityTaskCarousel from '../src/views/influencers/PriorityTaskCarousel.vue';
import { installPriorityCarousel } from '../scripts/priority-carousel-hotfix.mjs';

describe('priority task carousel', () => {
  it('updates live hotfix component props inside a compiled parent block', async () => {
    const groups = ref({ urgent: [], high: [] });
    const source = installPriorityCarousel('function renderPriority(){return null;}\nfunction renderActivity(){}', '/assets/PriorityTaskCarousel-abc123.js');
    const factory = new Function('u', 'PriorityTaskCarousel', 'priorityTasks', 'activityLoading', 'activityError', 'priorityLoadError', source.slice(source.indexOf('\n') + 1) + '\nreturn renderPriority;');
    const render = factory(createVNode, PriorityTaskCarousel, groups, ref(false), ref(false), ref(false));
    const wrapper = mount(defineComponent({ setup: () => () => { openBlock(); return createElementBlock('main', null, [render()]); } }));
    expect(wrapper.text()).toContain('暂无紧急');
    groups.value = { urgent: [{ id: 1, task_no: 'A', task_name: 'Loaded' }], high: [] };
    await nextTick();
    expect(wrapper.find('.task').text()).toContain('Loaded');
    wrapper.unmount();
  });
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
