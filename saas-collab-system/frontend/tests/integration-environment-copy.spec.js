import { shallowMount, flushPromises } from '@vue/test-utils';
import { beforeEach, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ create: vi.fn(), fetch: vi.fn(), allowed: true }));
vi.mock('../src/api/integrations', async original => ({ ...(await original()), createIntegrationConfig: mocks.create, fetchIntegrationWorkspace: mocks.fetch }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => mocks.allowed }) }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {}, fullPath: '/integrations/configs' }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
import Workspace from '../src/views/integrations/IntegrationWorkspace.vue';
const row = { id: 7, platform: 'shopee', account_alias: '原试运行配置', environment: 'pilot', api_type: 'marketplace', regions: ['PH'], credential_id: 'synthetic-reference' };
beforeEach(() => {
  mocks.allowed = true; mocks.create.mockReset().mockResolvedValue({success:true});
  mocks.fetch.mockResolvedValue({ success:true, data:{summary:{},options:{},pagination:{},results:[row],reference_options:{
    platforms:[{value:'shopee',enabled:true,api_types:[{value:'marketplace'}]}],
    environments:[{value:'pilot',label:'试运行'},{value:'production',label:'生产'}],countries:[{country_code:'PH'}]
  }}});
});
async function setup() {
  const wrapper=shallowMount(Workspace,{props:{mode:'configs'},global:{config:{warnHandler:()=>{}},stubs:{'el-table':true,'el-dialog':true}}});
  await flushPromises();return wrapper;
}
it('creates a different environment using only public fields and leaves the source intact',async()=>{
  const w=await setup(), state=w.vm.$.setupState;
  state.openEnvironmentConfig(row);
  expect(state.configForm.environment).toBe('');
  expect(state.configForm.regions).toEqual(['PH']);
  state.configForm.environment='pilot';await state.prepareConfig();expect(mocks.create).not.toHaveBeenCalled();
  state.configForm.environment='production';await state.prepareConfig();
  expect(mocks.create).toHaveBeenCalledExactlyOnceWith({account_alias:row.account_alias,platform:'shopee',api_type:'marketplace',environment:'production',regions:['PH']});
  expect(row.environment).toBe('pilot');expect(row.regions).toEqual(['PH']);w.unmount();
});
it('requires create permission and clears the source constraint for ordinary new configurations',async()=>{
  mocks.allowed=false;const w=await setup(), state=w.vm.$.setupState;
  state.openEnvironmentConfig(row);expect(state.configDialog).toBe(false);w.unmount();
  mocks.allowed=true;const next=await setup(), other=next.vm.$.setupState;
  other.openEnvironmentConfig(row);other.openCreateConfig();
  other.configForm.account_alias='另一个配置';other.configForm.environment='pilot';other.configForm.regions=['PH'];
  await other.prepareConfig();expect(mocks.create).toHaveBeenCalledOnce();next.unmount();
});
