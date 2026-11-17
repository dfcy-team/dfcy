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
