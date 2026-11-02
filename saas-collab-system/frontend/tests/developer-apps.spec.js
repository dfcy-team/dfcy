import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { useAuthStore } from '../src/stores/auth';
import ElementPlus from 'element-plus';
import DeveloperApps from '../src/views/integrations/DeveloperApps.vue';
import { developerRequest } from '../src/api/developerApps';
import { canAccessPath } from '../src/router/menu';
import { buildIntegrationSidebar } from '../src/router/integrationNavigation';
vi.mock('../src/api/developerApps', () => ({ developerRequest: vi.fn(), downloadDeveloperDocs: vi.fn() }));
describe('developer application flow', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().currentUser = {user_id:1,user_type:"internal",tenant_id:1,permissions:["integrations.developer_app.manage"]};
    developerRequest.mockImplementation(async path => ({success:true,data:path==='developer-apps/'?{items:[]}:{connections:[],accounts:[],endpoints:[{id:1,name:'订单',code:'orders',connection_id:2,account_id:3,method:'GET'}]}}));
  });
  it('loads live resources and opens a single application form', async () => {
    const wrapper = mount(DeveloperApps, {global:{plugins:[ElementPlus]}});
    await flushPromises();
    expect(developerRequest).toHaveBeenCalledWith('developer-catalog/', undefined, undefined);
    const button = wrapper.findAll('button').find(b=>b.text()==='新建应用');
    await button.trigger('click'); await flushPromises();
    expect(document.body.textContent + wrapper.text()).toContain('创建并申请');
    expect(document.body.textContent + wrapper.text()).toContain('提交申请');
    wrapper.unmount();
  });
  it('shows only developer entry to a granted internal developer', () => {
    const user={user_type:'internal',tenant_id:1,roles:['operator'],permissions:['integrations.developer_app.view']};
    expect(canAccessPath(user,'/integrations/developer-apps')).toBe(true);
    expect(canAccessPath(user,'/integrations/configs')).toBe(false);
    const section=buildIntegrationSidebar(user).find(item=>item.label==='授权中心');
    expect(section.children.map(item=>item.label)).toEqual(['开发者中心']);
    expect(section.children[0].children.map(item=>item.path)).toEqual(['/integrations/developer-apps']);
    expect(canAccessPath({...user,user_type:'supplier'},'/integrations/developer-apps')).toBe(false);
  });
  it('uses the auth user_id to expose owner actions only on owned apps', async () => {
    developerRequest.mockImplementation(async path => ({success:true,data:path==='developer-apps/'?{items:[{id:7,owner_id:1,name:'Owned',status:'active',approved_endpoint_ids:[1]}]}:{connections:[],accounts:[],endpoints:[]}}));
    const wrapper = mount(DeveloperApps, {global:{plugins:[ElementPlus]}});
    await flushPromises();
    expect(wrapper.text()).toContain('领取令牌');
    expect(wrapper.text()).toContain('申请扩权／延期');
    useAuthStore().currentUser = {user_id:2,user_type:'internal',tenant_id:1,permissions:['integrations.developer_app.manage']};
    await flushPromises();
    expect(wrapper.text()).not.toContain('领取令牌');
    expect(wrapper.text()).not.toContain('调用调试');
    wrapper.unmount();
  });
});
