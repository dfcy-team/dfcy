import {describe,it,expect,vi} from 'vitest';
import {mount,flushPromises} from '@vue/test-utils';
const mocks=vi.hoisted(()=>({fetch:vi.fn()}));
vi.mock('../src/api/paymentTermsV2',()=>({fetchPaymentReminders:mocks.fetch}));
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>({currentUser:{id:1},authorizationStale:false})}));
import Reminders from '../src/components/supply-chain/PaymentRemindersV2.vue';
const pagination={props:['total','currentPage','pageSize'],emits:['current-change'],template:'<nav />'};
describe('payment reminder pagination',()=>{
 it('retains total during same-scope page loading and preserves page offset',async()=>{
  let finish;mocks.fetch.mockReset().mockResolvedValueOnce({success:true,count:81,data:[]}).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  const w=mount(Reminders,{global:{stubs:{'el-button':true,'el-select':true,'el-option':true,'el-alert':true,'el-table':true,'el-table-column':true,'el-pagination':pagination}}});
  await w.vm.toggle();await flushPromises();w.vm.page=5;const pending=w.vm.load();
  expect(w.vm.total).toBe(81);expect(mocks.fetch.mock.lastCall[0].offset).toBe(80);
  finish({success:true,count:81,data:[]});await pending;w.unmount();
 });
});
