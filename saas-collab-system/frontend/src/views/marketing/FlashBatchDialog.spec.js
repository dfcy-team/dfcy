// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import FlashBatchDialog from './FlashBatchDialog.vue';
import { flashRequest } from '../../api/flashSales';

vi.mock('../../api/flashSales', () => ({
  flashRequest: vi.fn(), flashTime: value => value, taskLabels: {},
  taskLabel: task => task.status, finished: task => task.status === 'succeeded',
}));

afterEach(() => {vi.useRealTimers();vi.clearAllMocks();});

it('ticks running time locally and stops adding time during retry waiting', async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-11-17T02:00:00Z'));
  const task = {id:1,store_name:'测试店铺',status:'running',queue_ms:5000,execution_ms:10000,
    execution_live_until:'2026-11-17T02:01:00Z',waiting_ms:0,intents:[],sync_progress:'本轮已读取 100 条活动'};
  const batch = {id:'batch',operation:'sync',source:'manual',server_now:'2026-11-17T02:00:00Z',tasks:[task],notifications:[]};
  flashRequest.mockResolvedValueOnce(batch).mockResolvedValue({...batch,server_now:'2026-11-17T02:00:05Z',tasks:[{...task,
    status:'waiting',execution_ms:15000,execution_live_until:null,sync_progress:''}]});
  const wrapper = mount(FlashBatchDialog,{props:{batchId:'batch'},global:{stubs:{
    ElDialog:{template:'<div><slot/><slot name="footer"/></div>'},ElButton:true,ElAlert:true,
  }}});
  await flushPromises();
  expect(wrapper.text()).toContain('启动等待 5 秒');
  expect(wrapper.text()).toContain('本轮已读取 100 条活动');
  await vi.advanceTimersByTimeAsync(2000);
  expect(wrapper.text()).toContain('执行 12 秒');
  await vi.advanceTimersByTimeAsync(3000);
  await flushPromises();
  await vi.advanceTimersByTimeAsync(1000);
  expect(wrapper.text()).toContain('执行 15 秒');
  expect(wrapper.text()).not.toContain('本轮已读取');
  wrapper.unmount();
  expect(vi.getTimerCount()).toBe(0);
});


it('continues the protected original task and polls its batch after recovery', async () => {
  vi.useFakeTimers();
  const failed = {id:512,store_name:'测试店铺',status:'failed',execution_ms:0,waiting_ms:0,intents:[]};
  const original = {...failed,id:486,status:'queued',message:'按原时段处理异常'};
  const batch = {id:'blocked',operation:'run',source:'manual',finished_at:'2026-11-19',tasks:[failed],notifications:[]};
  flashRequest.mockImplementation((path,method) => Promise.resolve(method === 'post' ? {id:'original',task_id:486}
    : path === 'batches/original/' ? {...batch,id:'original',finished_at:null,tasks:[original]} : batch));
  const wrapper = mount(FlashBatchDialog,{props:{batchId:'blocked',taskId:512,canExecute:true},global:{stubs:{
    ElDialog:{template:'<div><slot/><slot name="footer"/></div>'},
    ElButton:{template:'<button @click="$emit(\'click\')"><slot/></button>'},ElAlert:true,
  }}});
  await flushPromises();
  await wrapper.findAll('button').find(button => button.text() === '按原时段处理异常').trigger('click');
  await flushPromises();
  expect(flashRequest).toHaveBeenCalledWith('batches/blocked/','post',{action:'recover',task_id:512});
  expect(wrapper.text()).toContain('queued');
  expect(wrapper.text()).toContain('按原时段处理异常');
  await vi.advanceTimersByTimeAsync(5000);
  expect(flashRequest).toHaveBeenLastCalledWith('batches/original/');
  wrapper.unmount();
  expect(vi.getTimerCount()).toBe(0);
});
