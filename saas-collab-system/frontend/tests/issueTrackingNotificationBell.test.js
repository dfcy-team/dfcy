import {mount,flushPromises} from '@vue/test-utils';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import NotificationBell from '../src/components/issueTracking/NotificationBell.vue';
import {tracking} from '../src/api/issueTracking';
vi.mock('../src/api/issueTracking',()=>({tracking:vi.fn(),actions:{remind:'催办'}}));
let wrapper,poll,interval,clear;
const data=(count=107)=>({unread_count:count,count:count,page:1,results:count?[{id:7,issue:17,issue_title:'需补充凭证',action:'remind',read_at:null,created_at:'2026-11-26T02:00:00Z'}]:[]});
function mountBell(){wrapper=mount(NotificationBell,{global:{stubs:{ElBadge:{name:'BadgeStub',props:['value','max','hidden'],template:'<div><slot/><sup v-if="!hidden">{{value}}</sup></div>'},ElButton:{props:['disabled'],template:'<button :disabled="disabled"><slot/></button>'},ElDrawer:{props:['modelValue'],template:'<aside v-if="modelValue"><slot/><slot name="footer"/></aside>'},ElTabs:{template:'<div><slot/></div>'},ElTabPane:true,ElEmpty:{props:['description'],template:'<p>{{description}}</p>'},ElAlert:{props:['title'],template:'<p role="alert">{{title}}</p>'},ElSkeleton:true,ElPagination:true}}});return wrapper;}
beforeEach(()=>{tracking.mockReset();tracking.mockResolvedValue(data());interval=vi.spyOn(window,'setInterval').mockImplementation(fn=>{poll=fn;return 321;});clear=vi.spyOn(window,'clearInterval');});
afterEach(()=>{wrapper?.unmount();wrapper=null;vi.restoreAllMocks();});
describe('用户消息铃铛',()=>{
 it('展示精确未读数并使用99上限，点击可看标题、类型及北京时间',async()=>{
  const w=mountBell();await flushPromises();expect(w.findComponent({name:'BadgeStub'}).props()).toMatchObject({value:107,max:99,hidden:false});
  await w.get('button').trigger('click');await flushPromises();expect(w.get('aside').text()).toContain('需补充凭证');expect(w.text()).toContain('催办');expect(w.text()).toContain('10:00:00');
 });
 it('单条已读后打开对应个人事件详情，并刷新角标',async()=>{
  const opened=vi.fn();window.addEventListener('open-event-tracking',opened);
  tracking.mockImplementation((path,method)=>Promise.resolve(method==='post'?{unread_count:0,updated_count:1}:data(0)));
  const w=mountBell();await flushPromises();tracking.mockResolvedValueOnce(data(1));await w.get('button').trigger('click');await flushPromises();
  await w.get('.message-item').trigger('click');await flushPromises();
  expect(tracking).toHaveBeenCalledWith('notification-center/','post',{id:7});expect(opened.mock.calls[0][0].detail.issueId).toBe(17);expect(w.find('aside').exists()).toBe(false);expect(w.findComponent({name:'BadgeStub'}).props('hidden')).toBe(true);
  window.removeEventListener('open-event-tracking',opened);
 });
 it('全部已读只在服务端成功后清除角标和未读列表',async()=>{
  const w=mountBell();await flushPromises();await w.get('button').trigger('click');await flushPromises();
  tracking.mockImplementation((path,method)=>Promise.resolve(method==='post'?{updated_count:107,unread_count:0}:data(0)));
  await w.findAll('button').find(b=>b.text()==='全部标为已读').trigger('click');await flushPromises();
  expect(tracking).toHaveBeenCalledWith('notification-center/','post',{all:true});expect(w.findComponent({name:'BadgeStub'}).props('hidden')).toBe(true);expect(w.text()).toContain('暂无未读消息');
 });
 it('标记失败不清除未读数，也不打开错误事项',async()=>{
  const w=mountBell();await flushPromises();await w.get('button').trigger('click');await flushPromises();
  tracking.mockRejectedValueOnce(new Error('无权访问该消息'));
  await w.get('.message-item').trigger('click');await flushPromises();
  expect(w.get('[role="alert"]').text()).toContain('无权访问');expect(w.find('aside').exists()).toBe(true);expect(w.findComponent({name:'BadgeStub'}).props('value')).toBe(107);
 });
 it('失败保留已知数量；轮询与可见性更新，卸载清理监听',async()=>{
  const w=mountBell();await flushPromises();tracking.mockRejectedValueOnce(new Error('网络不可用'));await w.get('button').trigger('click');await flushPromises();
  expect(w.get('[role="alert"]').text()).toContain('网络不可用');expect(w.findComponent({name:'BadgeStub'}).props('value')).toBe(107);
  await poll();await flushPromises();expect(w.find('[role="alert"]').exists()).toBe(false);
  const count=tracking.mock.calls.length;w.unmount();wrapper=null;window.dispatchEvent(new Event('issue-tracking-updated'));document.dispatchEvent(new Event('visibilitychange'));expect(tracking.mock.calls.length).toBe(count);expect(clear).toHaveBeenCalledWith(321);
 });
});
