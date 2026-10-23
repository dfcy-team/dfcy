import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, expect, it, vi } from 'vitest';
const api=vi.hoisted(()=>({fetchIntegrationAudit:vi.fn()}));
vi.mock('../src/api/integrations',()=>api);
vi.mock('../src/api/request',()=>({useMock:false}));
import Page from '../src/views/integrations/IntegrationAuditList.vue';
const render=()=>mount(Page,{global:{directives:{loading:()=>{}},stubs:{
  AppPage:{props:['capability'],template:'<section>{{capability}}<slot name="action"/><slot/></section>'},
  'el-button':{template:'<button><slot/></button>'},'el-alert':{props:['title'],template:'<p>{{title}}</p>'},
  'el-table':{props:['data','emptyText'],template:'<div>{{data.length ? data[0].id : emptyText}}</div>'},
  'el-input':true,'el-select':true,'el-option':true,'el-table-column':true,'el-pagination':true,'el-drawer':true
}}});
beforeEach(()=>vi.clearAllMocks());
it('clears failed audit rows, does not claim zero records, and recovers on refresh',async()=>{
  api.fetchIntegrationAudit.mockRejectedValueOnce(new Error('Network Error'));
  const w=render();await flushPromises();
  expect(w.text()).toContain('无法判断是否有审计记录');
  expect(w.text()).not.toContain('共 0 条');expect(w.text()).not.toContain('Network Error');
  api.fetchIntegrationAudit.mockResolvedValue({success:true,data:{api_status:'connected',results:[{id:9}],count:1}});
  await w.find('button').trigger('click');await flushPromises();
  expect(w.text()).toContain('共 1 条');expect(w.text()).not.toContain('读取失败');w.unmount();
});
it('rejects a degraded fixture response in production instead of displaying it',async()=>{
  api.fetchIntegrationAudit.mockResolvedValue({success:true,data:{api_status:'degraded',results:[{id:501}],count:1}});
  const w=render();await flushPromises();
  expect(w.text()).not.toContain('501');expect(w.text()).toContain('无法判断是否有审计记录');w.unmount();
});
