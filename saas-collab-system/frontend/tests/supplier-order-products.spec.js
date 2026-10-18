import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
const mocks=vi.hoisted(()=>({requestApi:vi.fn(),downloadApiFile:vi.fn(),push:vi.fn()}));
vi.mock('../src/api/request',()=>({requestApi:mocks.requestApi,downloadApiFile:mocks.downloadApiFile,formatApiError:r=>r.message||'无权访问'}));
vi.mock('vue-router',()=>({useRoute:()=>({params:{id:'12'}}),useRouter:()=>({push:mocks.push})}));
import SupplierOrdersV2 from '../src/views/suppliers/SupplierOrdersV2.vue';
const pass={template:'<div><slot/></div>'};
const stubs={
  SupplierProductImageV2:{props:['source'],template:'<img v-if="source" :src="source"/>'},
  'el-dialog':{props:['modelValue'],template:'<section v-if="modelValue"><slot/><slot name="footer"/></section>'},
  'el-image':{props:['src'],template:'<img v-if="src" :src="src"/><span v-else><slot name="error"/></span>'},
  'el-table':pass,'el-table-column':true,'el-pagination':true,'el-skeleton':true,
  'router-link':{props:['to'],template:'<a :href="to"><slot/></a>'},
  'el-alert':{props:['title'],template:'<p role="alert">{{title}}</p>'},
  'el-button':{emits:['click'],template:'<button @click="$emit(\'click\')"><slot/></button>'}
};
const detail={id:12,number:'TEST-PO',country_code:'US',total_quantity:2,total_amount:'20',lines:[
  {id:1,sku_id:6,sku:'SKU-6',name:'蓝色收纳箱',quantity:2,unit_price:'10',product_details_source:'confirmation',
   label_pdf_url:'/api/external/supplier/supply-chain/v2/purchase-orders/12/skus/6/labels/',
   product_details:{image_url:'https://example.test/product.png',specification:'15L',material:'PP',color:'蓝色',unit:'个',package_weight_g:'500',package_volume_cbm:'0.02',spec_values:{容量:'15L'},product_description:'<script>literal</script>'}}
]};
const page=()=>mount(SupplierOrdersV2,{global:{stubs,directives:{loading:()=>{}}}});
beforeEach(()=>{vi.clearAllMocks();mocks.requestApi.mockImplementation(async r=>r.url.endsWith('/12/')?{success:true,data:detail}:{success:true,data:[],count:0});mocks.downloadApiFile.mockResolvedValue({success:true});});
describe('supplier order product detail',()=>{
  it('renders mobile order cards with flow, totals and both actions while retaining the desktop table',async()=>{
    mocks.requestApi.mockImplementation(async r=>r.url.endsWith('/12/')?{success:true,data:detail}:{success:true,data:[{id:12,number:'TEST-PO',country_code:'PH',total_quantity:2,total_amount:'20',fulfillment:{label:'分批发货',ordered_quantity:2,shipped_quantity:1,unshipped_quantity:1}}],count:1});
    const wrapper=page();await flushPromises();await wrapper.vm.$nextTick();
    expect(wrapper.find('.table-wrap').exists()).toBe(true);
    const cards=wrapper.text();
    expect(cards).toContain('TEST-PO');expect(cards).toContain('菲律宾');expect(cards).toContain('分批发货');
    expect(cards).toContain('查看采购单');expect(cards).toContain('登记发货');wrapper.unmount();
  });
  it('opens the order deep link with pictures, full descriptions and safe literal text',async()=>{
    const wrapper=page();await flushPromises();
    expect(wrapper.find('img').attributes('src')).toBe('https://example.test/product.png');
    expect(wrapper.text()).toContain('蓝色收纳箱');expect(wrapper.text()).toContain('15L');expect(wrapper.text()).toContain('PP');
    expect(wrapper.text()).not.toContain('约定采购价');expect(wrapper.find('details.all-product-details').exists()).toBe(true);expect(wrapper.find('details.all-product-details').element.open).toBe(false);
    expect(wrapper.text()).toContain('登记发货');expect(wrapper.text()).toContain('下载 Excel');
    expect(wrapper.text()).toContain('包装重量（g）');expect(wrapper.text()).toContain('500');
    expect(wrapper.text()).toContain('下单确认时快照');expect(wrapper.text()).toContain('<script>literal</script>');
    expect(wrapper.find('script').exists()).toBe(false);expect(wrapper.text()).toContain('未维护');wrapper.unmount();
  });
  it('downloads the selected SKU label with authentication and keeps full-order Excel available',async()=>{
    const wrapper=page();await flushPromises();
    const link=wrapper.find('a.pdf-link');expect(link.attributes('href')).toBe(detail.lines[0].label_pdf_url);
    await link.trigger('click');await flushPromises();
    expect(mocks.downloadApiFile).toHaveBeenCalledWith(detail.lines[0].label_pdf_url,'TEST-PO-sku-6.pdf');
    await wrapper.findAll('button').find(b=>b.text()==='下载 Excel').trigger('click');await flushPromises();
    expect(mocks.downloadApiFile).toHaveBeenLastCalledWith('/api/external/supplier/supply-chain/v2/purchase-orders/12/excel/','TEST-PO.xlsx');wrapper.unmount();
  });
  it('does not reveal detail or document links when the order is inaccessible',async()=>{
    mocks.requestApi.mockImplementation(async r=>r.url.endsWith('/12/')?{success:false,message:'订单不可访问'}:{success:true,data:[],count:0});
    const wrapper=page();await flushPromises();expect(wrapper.text()).toContain('订单不可访问');expect(wrapper.find('.pdf-link').exists()).toBe(false);expect(wrapper.find('img').exists()).toBe(false);wrapper.unmount();
  });
});
