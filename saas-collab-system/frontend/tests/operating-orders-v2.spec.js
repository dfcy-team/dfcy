import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks=vi.hoisted(()=>({requestApi:vi.fn(),permission:true}));
vi.mock('../src/api/request',()=>({requestApi:mocks.requestApi}));
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>({authorizationStale:false,hasPermission:p=>mocks.permission&&(p==='sales_management.operating_orders.view'||p==='sales_management.operating_orders.manage'||p==='supply.v2.manage')})}));
import * as api from '../src/api/operatingOrdersV2';
import OperatingOrdersV2 from '../src/views/sales-management/OperatingOrdersV2.vue';
import OperatingSplitV2 from '../src/components/supply-chain/OperatingSplitV2.vue';
import { describe as d, expect as e, it as test, vi as v } from 'vitest';

describe('operating orders API contracts',()=>{
  beforeEach(()=>mocks.requestApi.mockReset().mockResolvedValue({success:true,data:[]}));
  it('uses the real sales routes and sends idempotency keys for writes',async()=>{
    await api.fetchOperatingOptions({kind:'skus',search:'ABC',limit:100,offset:0});
    await api.fetchOperatingOrders({status:'draft',limit:20,offset:0});
    await api.fetchOperatingOrder(12);
    await api.previewOperatingOrder({country_id:3,sku_ids:[4],sales_start:'2026-09-01',sales_end:'2026-09-30',target_stock_sales_ratio:1.2,include_in_transit:true},'preview-key');
    await api.createOperatingOrder({country_id:3,source_kind:'new_goods',lines:[{sku_id:4,quantity:2}]},'retry-key');
    await api.updateOperatingOrder(12,{expected_version:2,lines:[{sku_id:4,quantity:3}]},'patch-key');
    await api.submitOperatingOrder(12,{expected_version:3},'submit-key');
    expect(mocks.requestApi.mock.calls.map(([r])=>[r.method,r.url])).toEqual([
      ['get','/api/internal/commerce/operating-options/'],['get','/api/internal/commerce/operating-orders/'],['get','/api/internal/commerce/operating-orders/12/'],['post','/api/internal/commerce/operating-orders/preview/'],['post','/api/internal/commerce/operating-orders/'],['patch','/api/internal/commerce/operating-orders/12/'],['post','/api/internal/commerce/operating-orders/12/submit/']
    ]);
    expect(mocks.requestApi.mock.calls[4][0].headers['Idempotency-Key']).toBe('retry-key');
    expect(mocks.requestApi.mock.calls[3][0].headers['Idempotency-Key']).toBe('preview-key');
    expect(mocks.requestApi.mock.calls[5][0].data.expected_version).toBe(2);
  });
  it('uses procurement read and split routes with versioned idempotent split',async()=>{
    await api.fetchSubmittedProcurementOrders({limit:20,offset:0});await api.fetchSubmittedProcurementOrder(8);
    await api.splitOperatingOrder(8,{expected_version:4,supplier_id:7,lines:[{operating_line_id:6,quantity:2,unit_price:null}]},'split-key');
    expect(mocks.requestApi.mock.calls.map(([r])=>[r.method,r.url])).toEqual([
      ['get','/api/internal/supply-chain/v2/operating-orders/'],['get','/api/internal/supply-chain/v2/operating-orders/8/'],['post','/api/internal/supply-chain/v2/operating-orders/8/split/']
    ]);
    expect(mocks.requestApi.mock.calls[2][0].data.expected_version).toBe(4);
    expect(mocks.requestApi.mock.calls[2][0].headers['Idempotency-Key']).toBe('split-key');
  });
});

const ok=(data,extra={})=>({success:true,data,...extra});
const uiStubs={AppPage:{template:'<main><slot name="action"/><slot/></main>'},'el-button':{props:['disabled','loading'],emits:['click'],template:'<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot/></button>'},'el-alert':{props:['title'],template:'<p role="alert">{{title}}</p>'},'el-input':{template:'<input/>'},'el-input-number':{template:'<input/>'},'el-select':{template:'<div><slot/></div>'},'el-option':{template:'<option/>'},'el-table':{props:['data'],template:'<section><div v-for="row in data" :key="row.sku_id">{{row.sku}} · 建议 {{row.suggested_quantity ?? "—"}} · {{row.issues?.map(i=>({collection_coverage_unproven:"采集完整性待复核",refunds_not_deducted:"尚未扣除退款",no_sales_facts:"缺少销量事实"}[i]||i)).join("；")}}</div><slot/></section>'},'el-table-column':{template:'<div><slot :row="{}" :$index="0"/></div>'},'el-drawer':{props:['modelValue'],template:'<aside v-if="modelValue"><slot/><slot name="footer"/></aside>'},'el-form-item':{template:'<label><slot/></label>'},'el-date-picker':{template:'<input/>'},'el-switch':{template:'<input/>'},'el-pagination':true};
const createOperatingPage=()=>mount(OperatingOrdersV2,{global:{stubs:uiStubs,directives:{loading:()=>{}}}});
const validPreview=()=>({preview_token:'test-token-1',formula:'f',needs_review:true,generated_at:'2026-10-13T10:00:00Z',parameters:{country_id:3,sku_ids:[4],sales_start:'2026-10-01',sales_end:'2026-10-10',target_stock_sales_ratio:1,include_in_transit:true},lines:[{sku_id:4,sku:'SKU-A',sales_quantity:null,available_stock:null,in_transit_stock:null,suggested_quantity:null,source_snapshot_ids:[41],source_run_ids:[51],issues:['no_sales_facts','collection_coverage_unproven','refunds_not_deducted']}]});
describe('operating suggestion component',()=>{
  beforeEach(()=>mocks.requestApi.mockReset().mockImplementation(async r=>r?.url?.endsWith('/preview/')?ok(validPreview()):ok([], {count:0})));
  it('retains old SKU and image metadata when selecting, previewing and reopening an operating order',async()=>{
    const product={id:4,sku_code:'NEW-4',legacy_sku_code:'OLD-4',product_name:'测试收纳箱',product_details:{image_url:'/media/test-4.jpg',specification:'15L'}};
    const line={sku_id:4,sku:product.sku_code,legacy_sku_code:product.legacy_sku_code,product_name:product.product_name,product_details:product.product_details,quantity:6};
    const detail={id:8,number:'OP-8',status:'draft',version:1,country_id:3,source_kind:'new_goods',order_date:'2026-10-12',lines:[line]};
    mocks.requestApi.mockReset().mockImplementation(async r=>r?.url?.endsWith('/operating-options/')?ok(r.params.kind==='skus'?[product]:[]):r?.url?.endsWith('/operating-orders/8/')?ok(detail):r?.url?.endsWith('/preview/')?ok({...validPreview(),lines:[{...validPreview().lines[0],suggested_quantity:6}]}):ok([], {count:0}));
    const w=createOperatingPage();await flushPromises();w.vm.openNew();await w.vm.loadOptions('skus','OLD-4');w.vm.addLine();w.vm.form.lines[0].sku_id=4;w.vm.selectSku(w.vm.form.lines[0]);
    expect(w.vm.form.lines[0]).toMatchObject({sku:'NEW-4',legacy_sku_code:'OLD-4',product_details:product.product_details});expect(w.vm.skuLabel(product)).toContain('旧 OLD-4');
    Object.assign(w.vm.form,{country_id:3,source_kind:'cycle'});Object.assign(w.vm.previewForm,{sales_start:'2026-10-01',sales_end:'2026-10-10'});await flushPromises();await w.vm.makePreview();
    expect(w.vm.form.lines[0]).toMatchObject({legacy_sku_code:'OLD-4',product_details:product.product_details,quantity:6});
    await w.vm.openDetail({id:8});expect(w.vm.form.lines[0]).toMatchObject(line);w.unmount();
  });
  it('reuses the preview idempotency key after an uncertain response',async()=>{
    let n=0;mocks.requestApi.mockImplementation(async r=>r?.url?.endsWith('/preview/')?(++n===1?{success:false,message:'timeout',http_status:null}:ok(validPreview())):ok([], {count:0}));
    const w=createOperatingPage();await flushPromises();w.vm.openNew();await flushPromises();Object.assign(w.vm.form,{country_id:3,source_kind:'cycle',lines:[{sku_id:4,quantity:1,sku:'SKU-A'}]});Object.assign(w.vm.previewForm,{sales_start:'2026-10-01',sales_end:'2026-10-10'});
    await flushPromises();await w.vm.makePreview();await w.vm.makePreview();const req=mocks.requestApi.mock.calls.map(([x])=>x).filter(x=>x.url.endsWith('/preview/'));
    expect(req).toHaveLength(2);expect(req[0].headers['Idempotency-Key']).toBe(req[1].headers['Idempotency-Key']);expect(req[0].data).toMatchObject({country_id:3,sku_ids:[4]});w.unmount();
  });
  it('keeps missing suggestions visible with source IDs and issues, then blocks saving',async()=>{
    const w=createOperatingPage();await flushPromises();w.vm.openNew();await flushPromises();Object.assign(w.vm.form,{country_id:3,source_kind:'cycle',lines:[{sku_id:4,quantity:1,sku:'SKU-A'}]});Object.assign(w.vm.previewForm,{sales_start:'2026-10-01',sales_end:'2026-10-10'});await w.vm.makePreview();await flushPromises();
    expect(w.text()).toContain('SKU-A · 建议 —');expect(w.text()).toContain('采集完整性待复核');expect(w.text()).toContain('尚未扣除退款');expect(w.text()).toContain('41');expect(w.text()).toContain('51');
    mocks.requestApi.mockClear();await w.vm.save();expect(w.vm.formError).toContain('建议缺失或为 0');expect(mocks.requestApi).not.toHaveBeenCalled();w.unmount();
  });
  it('invalidates a displayed preview when its inputs change',async()=>{
    const w=createOperatingPage();await flushPromises();w.vm.openNew();await flushPromises();Object.assign(w.vm.form,{country_id:3,source_kind:'cycle',lines:[{sku_id:4,quantity:1,sku:'SKU-A'}]});Object.assign(w.vm.previewForm,{sales_start:'2026-10-01',sales_end:'2026-10-10'});await flushPromises();await w.vm.makePreview();expect(w.vm.preview).toBeTruthy();w.vm.previewForm.include_in_transit=false;await flushPromises();expect(w.vm.preview).toBeNull();w.unmount();
  });
  it('accepts 4 digit ratios, rejects a sales end date of today, and prefills a positive suggestion',async()=>{
    const today=new Intl.DateTimeFormat('en',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()),todayText=`${today.find(p=>p.type==='year').value}-${today.find(p=>p.type==='month').value}-${today.find(p=>p.type==='day').value}`;
    mocks.requestApi.mockReset().mockImplementation(async r=>r?.url?.endsWith('/preview/')?ok({...validPreview(),lines:[{...validPreview().lines[0],suggested_quantity:7}]}):ok([], {count:0}));
    const w=createOperatingPage();await flushPromises();w.vm.openNew();await flushPromises();Object.assign(w.vm.form,{country_id:3,source_kind:'cycle',lines:[{sku_id:4,quantity:1,sku:'SKU-A'}]});Object.assign(w.vm.previewForm,{sales_start:'2026-10-01',sales_end:todayText,target_stock_sales_ratio:1.2345});await flushPromises();await w.vm.makePreview();
    expect(w.vm.formError).toContain('最晚到昨天');expect(mocks.requestApi.mock.calls.filter(([r])=>r?.url?.endsWith('/preview/'))).toHaveLength(0);
    w.vm.previewForm.sales_end='2026-10-10';await flushPromises();await w.vm.makePreview();expect(mocks.requestApi.mock.calls.filter(([r])=>r?.url?.endsWith('/preview/'))).toHaveLength(1);expect(w.vm.form.lines[0].quantity).toBe(7);w.unmount();
  });
  it('reopens the saved calculation snapshot without invalidating it and shows reviewed quantities',async()=>{
    const snapshot={...validPreview(),operator_reviewed_quantities:[{sku_id:4,quantity:6}]},detail={id:8,number:'OP-8',status:'submitted',version:3,country_id:3,source_kind:'cycle',order_date:'2026-10-12',lines:[{sku_id:4,sku:'SKU-A',product_name:'商品甲',quantity:6}],calculation_snapshot:snapshot};
    mocks.requestApi.mockReset().mockImplementation(async r=>r?.url?.endsWith('/operating-orders/8/')?ok(detail):ok([], {count:0}));
    const w=createOperatingPage();await flushPromises();await w.vm.openDetail({id:8});await flushPromises();
    expect(w.vm.preview).toEqual(snapshot);expect(w.vm.form.lines[0]).toMatchObject({quantity:6,suggested_quantity:null,source_snapshot_ids:[41]});expect(w.text()).toContain('41');expect(w.text()).toContain('2026-10-13T10:00:00Z');w.unmount();
  });
  it('excludes the current draft reservation when refreshing its suggestion',async()=>{
    const detail={id:8,number:'OP-8',status:'draft',version:2,country_id:3,source_kind:'cycle',order_date:'2026-10-12',lines:[{sku_id:4,sku:'SKU-A',quantity:7}],calculation_snapshot:validPreview()};
    mocks.requestApi.mockReset().mockImplementation(async r=>r?.url?.endsWith('/operating-orders/8/')?ok(detail):r?.url?.endsWith('/preview/')?ok(validPreview()):ok([],{count:0}));
    const w=createOperatingPage();await flushPromises();await w.vm.openDetail({id:8});await flushPromises();await w.vm.makePreview();
    const request=mocks.requestApi.mock.calls.map(([r])=>r).find(r=>r.url.endsWith('/preview/'));
    expect(request.data.exclude_operating_order_id).toBe(8);expect(request.data.sku_ids).toEqual([4]);w.unmount();
  });
  it('allows cancelling a submitted order while keeping submission draft-only',async()=>{
    const detail={id:8,number:'OP-8',status:'submitted',version:4,country_id:3,source_kind:'new_goods',order_date:'2026-10-12',lines:[{sku_id:4,sku:'SKU-A',product_name:'商品甲',quantity:2}]};
    mocks.requestApi.mockReset().mockImplementation(async r=>r?.url?.endsWith('/operating-orders/8/')&&r.method==='get'?ok(detail):r?.url?.endsWith('/cancel/')?ok({...detail,status:'cancelled',version:5}):ok([], {count:0}));
    const w=createOperatingPage();await flushPromises();await w.vm.openDetail({id:8});await w.vm.transition('submit');expect(mocks.requestApi.mock.calls.some(([r])=>r?.url?.endsWith('/submit/'))).toBe(false);await w.vm.transition('cancel');expect(mocks.requestApi.mock.calls.some(([r])=>r?.url?.endsWith('/cancel/'))).toBe(true);w.unmount();
  });
});

describe('operating split component',()=>{
  it('omits an empty unit price so the server can use the supplier quote',async()=>{
    mocks.requestApi.mockReset().mockImplementation(async r=>r?.url?.endsWith('/operating-orders/8/')?ok({id:8,status:'submitted',version:4,lines:[{id:6,sku:'SKU-A',product_name:'商品甲',quantity:4,remaining_quantity:4,allocated_quantity:0}]}):ok([], {count:0}));
    const w=mount(OperatingSplitV2,{props:{canView:true,canManage:true},global:{stubs:uiStubs,directives:{loading:()=>{}}}});await flushPromises();await w.vm.open({id:8});Object.assign(w.vm.form,{supplier_id:7});Object.assign(w.vm.lines[0],{split_quantity:2,unit_price:null});await w.vm.split();
    const req=mocks.requestApi.mock.calls.map(([x])=>x).find(x=>x?.url?.endsWith('/split/'));expect(req.data.lines).toEqual([{operating_line_id:6,quantity:2}]);w.unmount();
  });
});
