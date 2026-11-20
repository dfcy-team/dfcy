import { shallowMount, flushPromises } from '@vue/test-utils';
import { expect, it, vi } from 'vitest';
import Page from '../src/views/masterdata/PlatformMasterList.vue';
import AdminResourcePage from '../src/components/AdminResourcePage.vue';
import { updateMasterData } from '../src/api/masterData';
vi.mock('../src/api/masterData',()=>({createMasterData:vi.fn(),deleteMasterData:vi.fn(),fetchPlatforms:vi.fn(),
 fetchPlatformCatalog:vi.fn().mockResolvedValue({success:true,data:{results:[]}}),updateMasterData:vi.fn().mockResolvedValue({success:true}),updateMasterDataStatus:vi.fn()}));
it('offers explicit warehouse connectors and submits the original edit version',async()=>{
 const wrapper=shallowMount(Page);await flushPromises();
 const page=wrapper.findComponent(AdminResourcePage);
 const fields=page.props('formFields');
 const state=fields.find(f=>f.key==='warehouse_connector_state');
 const connector=fields.find(f=>f.key==='warehouse_connector_key');
 expect(state.default).toBe('pending');
 expect(connector.visible({platform_type:'warehouse_third_party',warehouse_connector_state:'selected'})).toBe(true);
 expect(connector.visible({platform_type:'shopee',warehouse_connector_state:'selected'})).toBe(false);
 expect(connector.visible({platform_type:'warehouse_third_party',warehouse_connector_state:'pending'})).toBe(false);
 expect(connector.options.map(o=>o.value)).toEqual(['best_ecapi','jifeng_wms']);
 const payload={warehouse_connector_state:'selected',warehouse_connector_key:'best_ecapi'};
 await page.props('editHandler')(16,payload,{id:16,version:3});
 expect(updateMasterData).toHaveBeenCalledWith('platforms',16,{...payload,version:3});
 wrapper.unmount();
});
