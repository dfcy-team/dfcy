import { shallowMount, flushPromises } from '@vue/test-utils';
import { beforeEach, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ create: vi.fn(), fetch: vi.fn(), rotate: vi.fn(), allowed: true }));
vi.mock('../src/api/integrations', async original => ({ ...(await original()), createIntegrationConfig: mocks.create, fetchIntegrationWorkspace: mocks.fetch, rotateIntegrationSecretValues: mocks.rotate }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => mocks.allowed }) }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {}, fullPath: '/integrations/configs' }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock('element-plus', async original => ({ ...(await original()), ElMessageBox: { confirm: vi.fn().mockResolvedValue('confirm') } }));
import Workspace from '../src/views/integrations/IntegrationWorkspace.vue';
const row = { id: 7, platform: 'shopee', account_alias: '原试运行配置', environment: 'pilot', api_type: 'marketplace', regions: ['PH'], credential_id: 'synthetic-reference' };
beforeEach(() => {
  mocks.rotate.mockReset().mockResolvedValue({success:true}); mocks.allowed = true; mocks.create.mockReset().mockResolvedValue({success:true});
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

it('creates BEST using only basic fields, then maintains credentials separately', async () => {
  const w = await setup(), state = w.vm.$.setupState;
  state.openCreateConfig();
  Object.assign(state.configForm, {account_alias:'BEST test',platform:'best_ecapi',api_type:'inventory',environment:'production',regions:['MY']});
  await state.prepareConfig();
  expect(mocks.create).toHaveBeenCalledExactlyOnceWith({...state.configForm});
  expect(mocks.create.mock.calls[0][0]).not.toHaveProperty('best_config');
  state.openCredential({id:8,platform:'best_ecapi',api_type:'inventory',regions:['MY'],config_version:1});
  Object.assign(state.credentialForm, {partner_id:'TEST_PARTNER',partner_key:'FAKE_TEST_KEY',customer_code:'TEST_CUSTOMER',api_host:'https://example.com/ecapi/api/process',site_code:'MY'});
  await state.saveCredential();
  expect(mocks.rotate.mock.calls[0][1].credentials).toEqual({partner_id:'TEST_PARTNER',partner_key:'FAKE_TEST_KEY',customer_code:'TEST_CUSTOMER',api_host:'https://example.com/ecapi/api/process',site_code:'MY'});
  expect(state.credentialForm.partner_key).toBe('');
  expect(state.credentialDialog).toBe(false);
  w.unmount();
});

it('shows BEST maintenance field errors and clears keys even after rejection', async () => {
  const w = await setup(), state = w.vm.$.setupState;
  state.openCredential({id:8,platform:'best_ecapi',api_type:'inventory',regions:['MY'],config_version:1});
  Object.assign(state.credentialForm,{partner_key:'FAKE_TEST_KEY',api_host:'http://example.com'});
  mocks.rotate.mockResolvedValueOnce({success:false,message:'请检查字段',data:{credentials:{api_host:['请填写 HTTPS 网关']}}});
  await state.saveCredential();
  expect(state.credentialErrors.api_host).toBe('请填写 HTTPS 网关');
  expect(state.credentialForm.partner_key).toBe('');
  expect(state.credentialDialog).toBe(true);
  state.openCredential(row);
  expect(state.credentialPayload()).toEqual({});
  expect(state.credentialErrors).toEqual({});
  w.unmount();
});
