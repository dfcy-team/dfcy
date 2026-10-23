import { mount, flushPromises } from '@vue/test-utils';
import { describe, it, expect, vi, afterEach } from 'vitest';
import BoardDeclines from '../src/views/sales-management/BoardDeclines.vue';
import { fetchBoardDeclines } from '../src/api/realtimeBoard';
vi.mock('../src/api/realtimeBoard', () => ({ fetchBoardDeclines: vi.fn() }));
const filters = {date_from:'2025-01-02',date_to:'2025-01-02',region:'PH',store_id:'2',currency:'PHP'};
const response = name => ({success:true,data:{filters:{...filters,previous_from:'2025-01-01',previous_to:'2025-01-01'},rows:[{store_id:2,currency:'PHP',product_id:'A',product_name:name,store_name:'店铺',country:'PH',sales_amount:'50',previous_sales_amount:'100',decline_amount:'50',change_percent:'-50',diagnosis:null}]}});
let wrapper;
afterEach(() => {wrapper?.unmount();wrapper=null;vi.resetAllMocks();});
describe('按需下降排行',()=>{
 it('does not fetch incomplete days or missing currency',async()=>{
  wrapper=mount(BoardDeclines,{props:{filters:{...filters,date_to:'2999-01-01'}}});await flushPromises();
  expect(fetchBoardDeclines).not.toHaveBeenCalled();expect(wrapper.text()).toContain('已结束');
  await wrapper.setProps({filters:{...filters,currency:''}});expect(fetchBoardDeclines).not.toHaveBeenCalled();
 });
 it('preserves scope, requests new rank metric and shows evidence only',async()=>{
  fetchBoardDeclines.mockResolvedValue(response('商品A'));wrapper=mount(BoardDeclines,{props:{filters}});await flushPromises();
  expect(fetchBoardDeclines.mock.calls[0][0]).toEqual({...filters,metric:'amount'});
  await wrapper.find('select').setValue('percent');await flushPromises();
  expect(fetchBoardDeclines.mock.calls.at(-1)[0]).toEqual({...filters,metric:'percent'});
  await wrapper.find('tbody button').trigger('click');expect(wrapper.text()).toContain('原因待核查');expect(wrapper.text()).toContain('未触发昨日');
 });
 it('aborts replaced scope and ignores its late response',async()=>{
  let finish;fetchBoardDeclines.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve})).mockResolvedValue(response('新范围'));
  wrapper=mount(BoardDeclines,{props:{filters}});await flushPromises();const signal=fetchBoardDeclines.mock.calls[0][1];
  await wrapper.setProps({filters:{...filters,store_id:'3'}});await flushPromises();expect(signal.aborted).toBe(true);
  finish(response('旧范围'));await flushPromises();expect(wrapper.text()).toContain('新范围');expect(wrapper.text()).not.toContain('旧范围');
 });
 it('clears old results on error and aborts on leave',async()=>{
  fetchBoardDeclines.mockResolvedValueOnce(response('商品A')).mockRejectedValueOnce(new Error('读取失败'));
  wrapper=mount(BoardDeclines,{props:{filters}});await flushPromises();await wrapper.find('select').setValue('percent');await flushPromises();
  expect(wrapper.text()).not.toContain('商品A');expect(wrapper.text()).toContain('读取失败');
  const signal=fetchBoardDeclines.mock.calls.at(-1)[1];wrapper.unmount();wrapper=null;expect(signal.aborted).toBe(true);
 });
});
