import {mount,flushPromises} from '@vue/test-utils';
import {afterEach,describe,it,expect,vi} from 'vitest';
import Summary from '../src/components/issueTracking/TrackingSummary.vue';
import {tracking} from '../src/api/issueTracking';
import {trackingTime} from '../src/components/issueTracking/display';
vi.mock('../src/api/issueTracking',()=>({tracking:vi.fn(),states:{pending:'待办理'}}));
afterEach(()=>vi.clearAllMocks());
describe('个人跟踪摘要',()=>{
 it('完成操作事件触发摘要刷新；点击事项打开个人设置详情',async()=>{
  tracking.mockResolvedValue({pending:1,processing:0,confirming:0,overdue:0,items:[{id:17,title:'验收事项',status:'pending'}]});
  const w=mount(Summary,{global:{stubs:{ElButton:{template:'<button><slot/></button>'},ElEmpty:true}}});await flushPromises();
  const open=vi.fn();window.addEventListener('open-event-tracking',open);
  await w.findAll('button').at(-1).trigger('click');expect(open.mock.calls[0][0].detail.issueId).toBe(17);
  window.dispatchEvent(new Event('issue-tracking-updated'));await flushPromises();expect(tracking).toHaveBeenCalledTimes(2);
  w.unmount();window.dispatchEvent(new Event('issue-tracking-updated'));expect(tracking).toHaveBeenCalledTimes(2);
  window.removeEventListener('open-event-tracking',open);
 });
 it('日期固定以北京时间展示',()=>{expect(trackingTime('2026-11-26T02:00:00Z')).toContain('10:00:00');expect(trackingTime(null)).toBe('—');});
});
