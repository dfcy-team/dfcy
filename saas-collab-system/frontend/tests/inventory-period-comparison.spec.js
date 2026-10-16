import { describe, expect, it, vi } from 'vitest';
import { flushPromises, shallowMount } from '@vue/test-utils';
const api=vi.hoisted(()=>({startAnalysisJob:vi.fn(),pollAnalysisJob:vi.fn(),cancelAnalysisJob:vi.fn(),isAccessFailure:()=>false}));
vi.mock('../src/views/reports/periodAnalysis',()=>api);
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>({currentUser:{is_superuser:true}})}));
vi.mock('../src/router/menu',()=>({canAccessPath:()=>true}));
vi.mock('vue-router',()=>({useRouter:()=>({push:vi.fn()})}));
import InventoryPeriodComparison from '../src/components/inventory/InventoryPeriodComparison.vue';
describe('inventory comparison recovery',()=>{
 it('keeps the submitted filters when resuming an older job after editing the form',async()=>{
  api.startAnalysisJob.mockResolvedValue({success:true,data:{id:9,status:'queued'}});
  api.pollAnalysisJob.mockResolvedValueOnce({success:false,message:'任务仍在运行'}).mockResolvedValueOnce({success:true,data:{status:'completed',result:{rows:[],date_from:'2026-01-01',date_to:'2026-02-01'}}});
  const wrapper=shallowMount(InventoryPeriodComparison);
  wrapper.vm.from='2026-01-01';wrapper.vm.to='2026-02-01';
  wrapper.vm.run();await flushPromises();
  wrapper.vm.from='2026-01-10';
  wrapper.vm.resume();await flushPromises();
  expect(wrapper.vm.result.date_from).toBe('2026-01-01');
  expect(wrapper.vm.dirty).toBe(true);
  expect(wrapper.vm.blocked).toBe(true);
  wrapper.unmount();
 });
});
