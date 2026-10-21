import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks=vi.hoisted(()=>({requestApi:vi.fn()}));
vi.mock('../src/api/request',()=>mocks);
import Reference from '../src/components/supply-chain/OperatingReferenceV2.vue';
const parameters={country_id:3,source_kind:'cycle',sales_start:'2026-09-01',sales_end:'2026-09-30',target_stock_sales_ratio:1,include_in_transit:true};
const row=(id,qty)=>({sku_id:id,sku:`SKU-${id}`,suggested_quantity:qty});
const response=lines=>({success:true,data:{lines,count:40,candidate_count:40,scanned_count:20,next_offset:20,has_more:true,generated_at:'2026-10-20'}});
const stubs={
  'el-table':{template:'<div><slot/></div>'},
  'el-table-column':{template:'<div/>'},
  'el-input':true,'el-select':true,'el-option':true,'el-pagination':true,
  'el-alert':{props:['title'],template:'<p>{{title}}</p>'},
  'el-button':{props:['disabled'],emits:['click'],template:'<button :disabled="disabled" @click="$emit(\'click\')"><slot/></button>'},
};
const create=()=>mount(Reference,{props:{parameters,validate:()=>true},global:{stubs,directives:{loading:()=>{}}}});
describe('country-first operating references',()=>{
  beforeEach(()=>{mocks.requestApi.mockReset().mockResolvedValue(response([row(1,5),row(2,0),row(3,null)]));});
  it('does no initial calculation, calculates one requested page, and keeps valid selections across pages',async()=>{
    const w=create();await flushPromises();expect(mocks.requestApi).not.toHaveBeenCalled();
    await w.vm.generate();
    expect(mocks.requestApi).toHaveBeenCalledWith(expect.objectContaining({method:'post',url:'/api/internal/commerce/operating-orders/references/',data:{...parameters,analysis_mode:'country',search:'',quantity_filter:'positive',limit:20,offset:0}}));
    w.vm.selectPage();expect(w.vm.selectedRows.map(r=>r.sku_id)).toEqual([1]);
    mocks.requestApi.mockResolvedValue(response([row(4,8)]));await w.vm.continueSearch();w.vm.selectPage();
    expect(mocks.requestApi.mock.lastCall[0].data.offset).toBe(20);
    expect(w.vm.selectedRows.map(r=>r.sku_id)).toEqual([1,4]);
    const apply=w.findAll('button').find(b=>b.text().includes('加入订货明细'));
    await apply.trigger('click');expect(w.emitted('select')[0][0].map(r=>r.sku_id)).toEqual([1,4]);
    expect(mocks.requestApi.mock.calls.every(([r])=>r.url.endsWith('/references/'))).toBe(true);
    w.unmount();
  });
  it('discards stale responses and clears selection on country or model changes',async()=>{
    const w=create();await w.vm.generate();w.vm.selectPage();
    let finish;mocks.requestApi.mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
    const pending=w.vm.continueSearch();
    await w.setProps({parameters:{...parameters,country_id:9,source_kind:'season'}});
    finish(response([row(99,100)]));await pending;
    expect(w.vm.rows).toEqual([]);expect(w.vm.selectedRows).toEqual([]);expect(w.vm.generated).toBe(false);
    w.unmount();
  });
  it('keeps unknown and zero distinct and enforces a bounded selection',async()=>{
    const w=create();await w.vm.generate();
    mocks.requestApi.mockResolvedValue(response([row(3,null)]));w.vm.filter='unknown';await w.vm.changeFilter();expect(w.vm.rows.map(r=>r.sku_id)).toEqual([3]);expect(mocks.requestApi.mock.lastCall[0].data.quantity_filter).toBe('unknown');
    mocks.requestApi.mockResolvedValue(response([row(2,0)]));w.vm.filter='zero';await w.vm.changeFilter();expect(w.vm.rows.map(r=>r.sku_id)).toEqual([2]);expect(mocks.requestApi.mock.lastCall[0].data.quantity_filter).toBe('zero');
    for(let i=1;i<=101;i++)w.vm.toggle(row(i,1),true);
    expect(w.vm.selectedRows).toHaveLength(100);expect(w.vm.error).toContain('100');
    w.vm.toggle(row(1,1),false);expect(w.vm.error).toBe('');expect(w.vm.selectedRows).toHaveLength(99);
    w.unmount();
  });
  it('only requests platform analysis explicitly and never substitutes it for country suggestions',async()=>{
    const w=create();await w.vm.generate();
    w.vm.analysisMode='platform';w.vm.resetAnalysis();await w.vm.generate();
    expect(w.vm.error).toContain('请选择');expect(mocks.requestApi).toHaveBeenCalledTimes(1);
    w.vm.platformType='shopee';w.vm.resetAnalysis();
    mocks.requestApi.mockResolvedValue(response([{...row(1,12),platform_analysis:{sales_quantity:5,daily_sales:'0.2',country_sales_share:'0.25'}}]));
    await w.vm.generate();w.vm.selectPage();
    expect(mocks.requestApi.mock.lastCall[0].data).toMatchObject({analysis_mode:'platform',platform_type:'shopee'});
    expect(w.vm.selectedRows[0].suggested_quantity).toBe(12);
    expect(w.vm.share('0.25')).toBe('25.0%');
    w.vm.analysisMode='country';w.vm.resetAnalysis();await w.vm.generate();
    expect(mocks.requestApi.mock.lastCall[0].data).not.toHaveProperty('platform_type');
    expect(w.vm.selectedRows).toEqual([]);
    w.unmount();
  });
});
