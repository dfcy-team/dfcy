// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import Page from '../src/views/products/MonthlyCostLedger.vue';
const api=vi.hoisted(()=>vi.fn());
vi.mock('../src/api/request',()=>({requestApi:api}));
const slot={template:'<div><slot /></div>'};
const components=Object.fromEntries(['ElForm','ElFormItem','ElSelect','ElTable','ElPagination','ElDatePicker','ElOption','ElTableColumn'].map(k=>[k,slot]));
components.ElButton={template:'<button @click="$emit(\'click\')"><slot /></button>'};
components.ElAlert={props:['title'],template:'<div>{{title}}</div>'};
const mountPage=()=>mount(Page,{global:{stubs:components,directives:{loading:()=>{}}}});
describe('monthly cost errors',()=>{
 it('shows denied responses without rendering rows or exporting undefined CSV',async()=>{
  api.mockResolvedValue({success:false,message:'无权访问'});
  const wrapper=mountPage();await flushPromises();
  expect(wrapper.text()).toContain('无权访问');
  const button=wrapper.findAll('button').find(b=>b.text().includes('下载'));
  await button.trigger('click');await flushPromises();
  expect(wrapper.text()).toContain('无权访问');
  wrapper.unmount();
 });
 it('renders authorized empty ledger',async()=>{
  api.mockImplementation(({url})=>Promise.resolve({success:true,data:url.includes('warehouses')?[]:{items:[],total:0}}));
  const wrapper=mountPage();await flushPromises();
  expect(wrapper.text()).toContain('尚无月度记录');wrapper.unmount();
 });
});
