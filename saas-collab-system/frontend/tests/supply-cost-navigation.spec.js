import {beforeEach,describe,it,expect,vi} from 'vitest';
import {flushPromises,mount,shallowMount} from '@vue/test-utils';
import {reactive} from 'vue';
const mocks=vi.hoisted(()=>({context:vi.fn(),payments:vi.fn(),targets:vi.fn(),query:{},stale:false}));
vi.mock('../src/api/supplyCostsV2',()=>({fetchPayments:mocks.payments,fetchCostContext:mocks.context,fetchCostTargets:mocks.targets}));
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>({get authorizationStale(){return mocks.stale;},hasPermission:()=>true})}));
vi.mock('vue-router',async original=>({...await original(),useRoute:()=>({query:mocks.query})}));
import CostSettlementLinkV2 from '../src/components/supply-chain/CostSettlementLinkV2.vue';
import SupplyCostsV2 from '../src/views/purchasing/SupplyCostsV2.vue';
const ok=(data)=>({success:true,data});
const result=(kind,id)=>({target:{kind,id,number:`DOC-${id}`,version:2},fee:{amount:'12.0000',state:'confirmed'},settlement_supported:true,settlement:{recorded_amount:'5.0000',unsettled_amount:'7.0000'},latest_cost:{status:'confirmed'}});
beforeEach(()=>{mocks.payments.mockReset().mockImplementation(async(kind,id)=>ok({target:{kind,id,number:`PAY-${id}`},summary:{}}));mocks.context.mockReset().mockImplementation(async(kind,id)=>ok(result(kind,id)));mocks.targets.mockReset().mockResolvedValue({...ok([]),count:0});mocks.query={};mocks.stale=false;});

describe('cost and settlement single entry',()=>{
  it('business documents show a read-only summary and source-aware link',async()=>{
    const wrapper=mount(CostSettlementLinkV2,{props:{kind:'shipment',id:7,version:2},global:{stubs:{'router-link':{props:['to'],template:'<a :data-target="JSON.stringify(to)"><slot/></a>'},'el-button':{template:'<button><slot/></button>'}}}});
    await flushPromises();
    expect(wrapper.text()).toContain('12.0000');expect(wrapper.text()).toContain('5.0000');
    expect(wrapper.find('a').attributes('data-target')).toBe(JSON.stringify({path:'/supply-chain/costs',query:{kind:'shipment',id:'7'}}));
    expect(wrapper.findAll('input,textarea,select')).toHaveLength(0);wrapper.unmount();
  });
  it('does not retain a previous source response after source changes',async()=>{
    let finish;
    mocks.context.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
    const wrapper=shallowMount(CostSettlementLinkV2,{props:{kind:'shipment',id:7},global:{stubs:{'router-link':true}}});
    await wrapper.setProps({kind:'batch',id:8});await flushPromises();
    finish(ok(result('shipment',7)));await flushPromises();
    expect(wrapper.emitted('updated').map(([data])=>data.id)).toEqual([8]);wrapper.unmount();
  });
  it('opens the exact linked source in the unified menu',async()=>{
    mocks.query=reactive({kind:'inbound',id:'11'});
    const wrapper=shallowMount(SupplyCostsV2,{global:{directives:{loading:()=>{}}}});await flushPromises();
    expect(wrapper.vm.kind).toBe('inbound');expect(wrapper.vm.selected).toMatchObject({kind:'inbound',id:11});wrapper.unmount();
  });
  it('rejects invalid linked IDs without fetching a detail',async()=>{
    mocks.query={kind:'batch',id:'oops'};
    const wrapper=shallowMount(SupplyCostsV2,{global:{directives:{loading:()=>{}}}});await flushPromises();
    expect(mocks.context).not.toHaveBeenCalled();expect(wrapper.vm.selected).toBeNull();wrapper.unmount();
  });
  it.each(['purchase','domestic_freight'])('opens %s payment process through a direct link',async(kind)=>{
    mocks.query={kind,id:'12'};const w=shallowMount(SupplyCostsV2,{global:{directives:{loading:()=>{}}}});await flushPromises();
    expect(mocks.payments).toHaveBeenCalledWith(kind,12);expect(mocks.context).not.toHaveBeenCalled();expect(w.vm.selected).toMatchObject({kind,id:12});w.unmount();
  });
});
