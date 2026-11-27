import { mount, flushPromises } from '@vue/test-utils';
import { describe, it, expect, vi } from 'vitest';
import UserSettingsDrawer from '../src/components/UserSettingsDrawer.vue';
import { menuItems, flattenMenuItems } from '../src/router/menu';
vi.mock('../src/api/auth', () => ({ getMyProfile: vi.fn(), updateMyProfile: vi.fn(), changeMyPassword: vi.fn() }));
const stubs = { EventTracking: { name: 'EventTrackingStub', props: ['initialIssueId'], template: '<div>跟踪工作区 {{initialIssueId}}</div>' }, ElDrawer: { props: ['modelValue', 'size'], template: '<aside v-if="modelValue" :data-size="size"><slot /></aside>' }, ElTabs: { template: '<div><slot /></div>' }, ElTabPane: { props: ['label'], template: '<section :aria-label="label"><slot /></section>' }, FeishuBindingPanel: true, ElForm: { template: '<form><slot /></form>' }, ElFormItem: { template: '<div><slot /></div>' }, ElInput: true, ElInputNumber: true, ElButton: true };
describe('事件跟踪个人入口', () => {
  it('位于个人设置内，显示跟踪事项并扩展工作区宽度', async () => {
    const w = mount(UserSettingsDrawer, { props: { modelValue: true, currentUser: { user_type: 'internal' }, initialTab: 'tracking', trackingIssueId: 17 }, global: { stubs } });
    await flushPromises(); expect(w.get('[aria-label="事件跟踪"]').text()).toContain('跟踪工作区 17');
    expect(w.get('aside').attributes('data-size')).toContain('1120px'); w.unmount();
  });
  it('重复点击同一事项也重新打开跟踪详情',async()=>{
    const w=mount(UserSettingsDrawer,{props:{modelValue:true,currentUser:{user_type:'internal'},initialTab:'tracking',trackingIssueId:17,trackingOpenKey:1},global:{stubs}});
    await flushPromises();const previous=w.findComponent({name:'EventTrackingStub'}).element;
    await w.setProps({trackingOpenKey:2});await flushPromises();
    expect(w.get('[aria-label="事件跟踪"]').text()).toContain('跟踪工作区 17');expect(w.findComponent({name:'EventTrackingStub'}).element).not.toBe(previous);w.unmount();
  });
  it('外部用户不显示个人跟踪入口；左侧不再有独立入口', () => {
    const w = mount(UserSettingsDrawer, { props: { modelValue: true, currentUser: { user_type: 'external' } }, global: { stubs } });
    expect(w.find('[aria-label="事件跟踪"]').exists()).toBe(false);
    expect(flattenMenuItems(menuItems).some(row => row.path === '/issue-tracking')).toBe(false); w.unmount();
  });
});
