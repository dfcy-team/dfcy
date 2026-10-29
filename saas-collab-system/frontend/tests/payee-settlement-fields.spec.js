import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
const mocks=vi.hoisted(()=>({fetch:vi.fn(),create:vi.fn(),update:vi.fn()}));
vi.mock('../src/api/supplyCostsV2',()=>({fetchPayeeAccounts:mocks.fetch,createPayeeAccount:mocks.create,updatePayeeAccount:mocks.update,createIdempotencyKey:()=> 'stable-key'}));
import Fields from '../src/components/supply-chain/PayeeSettlementFieldsV2.vue';
const mountFields=()=>mount(Fields,{props:{kind:'shipment',id:1,total:'120.0000',editable:true,modelValue:[]},global:{stubs:{'el-select':true,'el-option':true,'el-input':true,'el-button':true,'el-dialog':true,'el-alert':true}}});
describe('收款账户按需加载',()=>{
 beforeEach(()=>{mocks.fetch.mockReset().mockResolvedValue({success:true,data:{accounts:[]}});mocks.create.mockReset();mocks.update.mockReset();});
 it('does not request accounts on mount and loads once on demand',async()=>{
  const w=mountFields();expect(mocks.fetch).not.toHaveBeenCalled();w.vm.add();await flushPromises();
  expect(mocks.fetch).toHaveBeenCalledWith('shipment',1);
  expect(w.emitted('update:modelValue')[0][0][0].amount).toBe('120.0000');
  await w.vm.loadAccounts();expect(mocks.fetch).toHaveBeenCalledTimes(1);w.unmount();
 });
 it('discards a previous document response after switching documents',async()=>{
  let resolve;mocks.fetch.mockReturnValue(new Promise(r=>resolve=r));const w=mountFields();w.vm.loadAccounts();await w.setProps({id:2});
  resolve({success:true,data:{accounts:[{id:99,account_name:'旧单据账户'}]}});await flushPromises();expect(w.vm.accounts).toEqual([]);w.unmount();
 });
 it('reuses account creation idempotency key after a transport failure',async()=>{
  const w=mountFields();Object.assign(w.vm.form,{account_name:'公司收款',account_holder:'收款公司',bank_name:'银行',account_number:'1234'});
  mocks.create.mockRejectedValueOnce(new Error('网络失败')).mockResolvedValueOnce({success:true,data:{account:{id:3}}});
  await w.vm.saveAccount();await w.vm.saveAccount();expect(mocks.create).toHaveBeenCalledTimes(2);
  expect(mocks.create.mock.calls[0][3]).toBe(mocks.create.mock.calls[1][3]);w.unmount();
 });
 it('force refresh supersedes a stale in-flight account response',async()=>{
  let resolveOld;mocks.fetch.mockReturnValueOnce(new Promise(r=>resolveOld=r)).mockResolvedValueOnce({success:true,data:{accounts:[{id:2}]}});
  const w=mountFields();w.vm.loadAccounts();await w.vm.loadAccounts(true);expect(w.vm.accounts).toEqual([{id:2}]);
  resolveOld({success:true,data:{accounts:[{id:1}]}});await flushPromises();expect(w.vm.accounts).toEqual([{id:2}]);w.unmount();
 });
 it('shows the historical nature after the account master changes',async()=>{
  const w=mountFields();w.vm.accounts.push({id:1,nature:'personal',active:true});const row={account_id:1,account_snapshot:{nature:'corporate',account_name:'历史公司户'}};
  expect(w.vm.selectedAccount(row).nature).toBe('corporate');expect(w.vm.rowOptions(row)[0].nature).toBe('corporate');w.unmount();
 });
});
