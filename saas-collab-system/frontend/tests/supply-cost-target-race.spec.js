import {describe,it,expect,vi} from 'vitest';
import {shallowMount,flushPromises} from '@vue/test-utils';
const mocks=vi.hoisted(()=>({targets:vi.fn()}));
vi.mock('../src/api/supplyCostsV2',()=>({fetchCostTargets:mocks.targets}));
vi.mock('vue-router',async original=>({...await original(),useRoute:()=>({query:{}})}));
import SupplyCostsV2 from '../src/views/purchasing/SupplyCostsV2.vue';

describe('cost target type changes',()=>{
  it.each(['success','failure'])('ignores an old shipment %s after batch results arrive',async(outcome)=>{
    let resolveOld,rejectOld;
    mocks.targets.mockReset()
      .mockImplementationOnce(()=>new Promise((resolve,reject)=>{resolveOld=resolve;rejectOld=reject;}))
      .mockResolvedValueOnce({success:true,count:1,data:[{id:1,number:'BATCH-1'}]});
    const wrapper=shallowMount(SupplyCostsV2,{global:{directives:{loading:()=>{}}}});
    wrapper.vm.kind='batch';
    await wrapper.vm.loadTargets();
    expect(wrapper.vm.targets[0]).toMatchObject({id:1,number:'BATCH-1',kind:'batch'});
    if(outcome==='success')resolveOld({success:true,count:1,data:[{id:1,number:'SHIPMENT-1'}]});
    else rejectOld(new Error('old failure'));
    await flushPromises();
    expect(wrapper.vm.targets[0].number).toBe('BATCH-1');
    wrapper.vm.openTarget(wrapper.vm.targets[0]);
    wrapper.vm.kind='shipment';
    expect(wrapper.vm.selected.kind).toBe('batch');
    wrapper.unmount();
  });
});
