import {afterEach,beforeEach,describe,it,expect,vi} from 'vitest';
import {mount,flushPromises} from '@vue/test-utils';
const mocks=vi.hoisted(()=>({fetchApiFile:vi.fn()}));
vi.mock('../src/api/request',()=>({fetchApiFile:mocks.fetchApiFile}));
import SupplierProductImageV2 from '../src/components/supply-chain/SupplierProductImageV2.vue';
const options={global:{stubs:{'el-image':{props:['src'],template:'<img :src="src"/>'}}}};
beforeEach(()=>{vi.clearAllMocks();vi.stubGlobal('URL',{createObjectURL:vi.fn(()=> 'blob:authenticated-image'),revokeObjectURL:vi.fn()});});
afterEach(()=>vi.unstubAllGlobals());
describe('private supplier product images',()=>{
  it('fetches through the order-authorized image endpoint and revokes the browser object URL',async()=>{
    mocks.fetchApiFile.mockResolvedValue({success:true,blob:new Blob(['test'],{type:'image/jpeg'})});
    const wrapper=mount(SupplierProductImageV2,{...options,props:{orderId:7,skuId:6,source:'/media/item.png'}});await flushPromises();
    expect(mocks.fetchApiFile).toHaveBeenCalledWith('/api/external/supplier/supply-chain/v2/purchase-orders/7/skus/6/image/');
    expect(wrapper.find('img').attributes('src')).toBe('blob:authenticated-image');wrapper.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:authenticated-image');
  });
  it('does not request an image when the product has no picture',async()=>{
    const wrapper=mount(SupplierProductImageV2,{...options,props:{orderId:7,skuId:6}});await flushPromises();
    expect(mocks.fetchApiFile).not.toHaveBeenCalled();wrapper.unmount();
  });
  it('keeps rejected or stale image responses out of the display',async()=>{
    let resolve; mocks.fetchApiFile.mockReturnValue(new Promise(r=>{resolve=r}));
    const wrapper=mount(SupplierProductImageV2,{...options,props:{orderId:7,skuId:6,source:'https://example.test/image.png'}});
    await wrapper.setProps({source:''});resolve({success:true,blob:new Blob(['test'])});await flushPromises();
    expect(URL.createObjectURL).not.toHaveBeenCalled();expect(wrapper.find('img').attributes('src')).toBe('');wrapper.unmount();
  });
});
