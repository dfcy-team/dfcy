// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { reactive, nextTick } from 'vue';
import Settings from '../src/components/inventory/InventoryAbcSettings.vue';
import Badge from '../src/components/inventory/InventoryAbcBadges.js';
const mocks = vi.hoisted(() => ({ request: vi.fn(), auth: null }));
vi.mock('../src/api/request', () => ({requestApi: mocks.request}));
vi.mock('../src/stores/auth', () => ({useAuthStore: () => mocks.auth}));
const data = {abc_enabled:true, abc_window_days:90, abc_a_percent:'80', abc_b_percent:'95', abc_stability_days:3, new_product_observation_days:30};
const mountSettings = () => mount(Settings, {global:{stubs:{'el-card':{template:'<div><slot name="header"/><slot/></div>'},'el-select':true,'el-option':true,'el-input-number':true,'el-button':{template:'<button :disabled="disabled" @click="$emit(\'click\')"><slot/></button>',props:['disabled','loading']}}}});
const defer = () => { let resolve; const promise = new Promise(r => resolve = r); return {promise,resolve}; };
beforeEach(() => { mocks.request.mockReset(); mocks.auth = reactive({authorizationStale:false, currentUser:{id:1,tenant_id:1}, hasPermission: () => true, hasAllDataScopeFor: () => true}); });
describe('composite ABC settings', () => {
 it('loads read-only and saves only ABC fields after valid edits', async () => {
  mocks.request.mockResolvedValue({success:true,data}); const w=mountSettings(); await flushPromises();
  expect(mocks.request.mock.calls).toHaveLength(1); expect(mocks.request.mock.calls[0][0].method).toBe('get');
  w.vm.state.abc_a_percent=70; await nextTick(); await w.vm.save();
  expect(mocks.request.mock.calls[1][0]).toMatchObject({method:'put',data:{abc_a_percent:70}});
  expect(mocks.request.mock.calls[1][0].data).not.toHaveProperty('new_product_observation_days');
 });
 it('blocks failed load, invalid thresholds and stale authorization', async () => {
  mocks.request.mockRejectedValueOnce(Error('failed')); const w=mountSettings(); await flushPromises(); await w.vm.save(); expect(mocks.request).toHaveBeenCalledTimes(1); w.unmount();
  mocks.request.mockReset(); mocks.request.mockResolvedValue({success:true,data}); const x=mountSettings(); await flushPromises(); x.vm.state.abc_a_percent=99; await x.vm.save(); expect(mocks.request).toHaveBeenCalledTimes(1);
  mocks.auth.authorizationStale=true; await nextTick(); await x.vm.save(); expect(mocks.request).toHaveBeenCalledTimes(1);
 });
 it('invalidates old tenant GET and PUT responses immediately on identity changes', async () => {
  const oldGet=defer(), oldPut=defer(), newGet=defer();
  mocks.request.mockReturnValueOnce(oldGet.promise).mockResolvedValueOnce({success:true,data}).mockReturnValueOnce(oldPut.promise).mockReturnValueOnce(newGet.promise);
  const w=mountSettings();
  const oldGetSignal=mocks.request.mock.calls[0][0].signal;
  mocks.auth.currentUser={id:2,tenant_id:2};
  expect(oldGetSignal.aborted).toBe(true); expect(w.vm.loaded).toBe(false); await flushPromises();
  oldGet.resolve({success:true,data:{...data,abc_window_days:111}}); await flushPromises();
  expect(w.vm.state.abc_window_days).toBe(90);
  w.vm.state.abc_window_days=120; const pending=w.vm.save();
  const oldPutSignal=mocks.request.mock.calls[2][0].signal;
  mocks.auth.currentUser.tenant_id=3;
  expect(oldPutSignal.aborted).toBe(true);
  expect(w.vm.loaded).toBe(false); expect(w.vm.state).toEqual({});
  oldPut.resolve({success:true,data:{...data,abc_window_days:120}}); await pending;
  expect(w.vm.loaded).toBe(false); expect(w.vm.state).toEqual({});
  newGet.resolve({success:true,data:{...data,abc_window_days:60}}); await flushPromises();
  expect(w.vm.state.abc_window_days).toBe(60); expect(w.vm.loaded).toBe(true);
 });
 it('ignores obsolete load and freezes duplicate save', async () => {
  const first=defer(), save=defer(); mocks.request.mockReturnValueOnce(first.promise).mockResolvedValueOnce({success:true,data}).mockReturnValueOnce(save.promise);
  const w=mountSettings(); mocks.auth.authorizationStale=true; await nextTick(); mocks.auth.authorizationStale=false; await nextTick(); await flushPromises(); first.resolve({success:true,data:{...data,abc_window_days:100}}); await flushPromises(); expect(w.vm.state.abc_window_days).toBe(90);
  w.vm.state.abc_window_days=100; const pending=w.vm.save(); await w.vm.save(); expect(mocks.request).toHaveBeenCalledTimes(3); expect(w.vm.disabled).toBe(true); save.resolve({success:true,data:{...data,abc_window_days:100}}); await pending;
 });
});
describe('composite badge', () => {
 const abc={classification_basis:'composite',policy_version:'composite_revenue_units_v1_20261120',status:'partial',spu_grade:'A',spu_reference_grade:'B',sku_grade:'A',sku_reference_grade:'C',sku_evidence:{revenue_grade:'A',units_grade:'B',continuity_label:'sustained'}};
 it('shows references and evidence for SKU and only SPU for parent', () => {
  const sku=mount(Badge,{props:{row:{abc},entityType:'sku'}}); expect(sku.text()).toContain('参考 C'); expect(sku.text()).toContain('销售额 A'); expect(sku.text()).toContain('持续销售');
  const spu=mount(Badge,{props:{row:{abc},entityType:'spu'}}); expect(spu.text()).toContain('参考 B'); expect(spu.text()).not.toContain('SKU');
 });
 it('rejects old policy',()=>{const w=mount(Badge,{props:{row:{abc:{...abc,policy_version:'old'}},entityType:'sku'}}); expect(w.text()).toContain('更新中');});
});
