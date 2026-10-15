<template>
  <main class="orders" v-loading="loading">
    <h1>我的采购订单</h1><p>点击查看订单附件或登记分批发货。仅显示本供应商已下单的采购单。</p>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-button @click="load">刷新</el-button>
    <div class="table-wrap"><el-table :data="rows">
      <el-table-column prop="number" label="采购单号" min-width="210" />
      <el-table-column prop="country_code" label="国家" width="90" />
      <el-table-column prop="total_quantity" label="总数量" width="110" />
      <el-table-column prop="total_amount" label="总金额" width="130" />
      <el-table-column label="操作" width="250"><template #default="{row}"><el-button link type="primary" @click="open(row.id)">查看采购单</el-button><router-link :to="`/supplier/shipments?order_id=${row.id}`">登记发货</router-link></template></el-table-column>
    </el-table></div>
    <el-pagination layout="prev,pager,next,total" :total="count" :page-size="50" v-model:current-page="page" @current-change="load" />
    <el-dialog v-model="visible" title="采购单详情" width="min(1040px,95vw)">
      <el-skeleton v-if="detailLoading" :rows="6" animated />
      <template v-if="detail"><h2>{{ detail.number }}</h2><p>{{ detail.country_code }} · 总数量 {{ detail.total_quantity }} · 总金额 {{ detail.total_amount }}</p>
        <p v-if="detail.reference_number">备注单号：{{ detail.reference_number }}</p><p>{{ detail.notes }}</p>
        <section class="product-list" aria-label="采购商品明细">
          <article v-for="line in detail.lines" :key="line.id" class="product-card">
            <div class="product-heading">
              <SupplierProductImageV2 :order-id="detail.id" :sku-id="line.sku_id" :source="line.product_details?.image_url || ''" />
              <div class="product-title"><h3>{{line.name || line.sku}}</h3><DocumentSkuV2 :sku="line.sku" :legacy-sku-code="line.legacy_sku_code"/><p>采购数量 {{line.quantity}} {{line.product_details?.unit || '件'}} · 约定采购价 {{line.unit_price}}</p><small>{{line.product_details_source === 'confirmation' ? '商品资料：下单确认时快照' : '商品资料：当前档案（历史订单未保存资料快照）'}}</small></div>
              <a v-if="line.label_pdf_url" class="pdf-link" :href="line.label_pdf_url" :aria-disabled="downloading" @click.prevent="downloadProductPdf(line)">下载本商品 PDF 标签</a>
            </div>
            <dl class="product-details">
              <div v-for="field in productFields" :key="field.key"><dt>{{field.label}}</dt><dd>{{display(line.product_details?.[field.key])}}</dd></div>
              <div class="full"><dt>规格属性</dt><dd>{{specifications(line.product_details?.spec_values)}}</dd></div>
              <div class="full"><dt>商品卖点</dt><dd>{{display(line.product_details?.selling_points)}}</dd></div>
              <div class="full"><dt>商品说明</dt><dd>{{display(line.product_details?.product_description)}}</dd></div>
            </dl>
          </article>
        </section>
        <div class="document-actions"><el-button :loading="downloading" @click="download('excel')">下载图文采购订单 Excel</el-button><el-button :loading="downloading" @click="download('labels')">下载全部 SKU 标签 PDF</el-button><el-button type="primary" @click="router.push(`/supplier/shipments?order_id=${detail.id}`)">登记本单发货</el-button></div>
      </template>
    </el-dialog>
  </main>
</template>
<script setup>
import { ref, onMounted, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import SupplierProductImageV2 from '../../components/supply-chain/SupplierProductImageV2.vue';
import DocumentSkuV2 from '../../components/supply-chain/DocumentSkuV2.vue';
import { requestApi, downloadApiFile, formatApiError } from '../../api/request';
const base = '/api/external/supplier/supply-chain/v2/', route = useRoute(), router = useRouter();
const rows=ref([]),count=ref(0),page=ref(1),loading=ref(false),error=ref(''),visible=ref(false),detail=ref(null);
const detailLoading=ref(false),downloading=ref(false);let detailRequest=0;
const productFields=[
  {key:'spu',label:'SPU'},{key:'brand',label:'品牌'},{key:'category',label:'商品分类'},
  {key:'specification',label:'规格'},{key:'color',label:'颜色'},{key:'size',label:'尺码'},
  {key:'material',label:'材质'},{key:'unit',label:'单位'},
  {key:'package_length_cm',label:'包装长（cm）'},{key:'package_width_cm',label:'包装宽（cm）'},
  {key:'package_height_cm',label:'包装高（cm）'},{key:'package_weight_g',label:'包装重量（g）'},
  {key:'package_volume_cbm',label:'包装体积（m³）'},{key:'origin_country',label:'原产国'},
  {key:'hs_code',label:'海关编码'},{key:'inventory_type',label:'商品形态'},{key:'product_type',label:'商品类型'}
];
function display(value){if(value==null||value==='')return '未维护';if(Array.isArray(value))return value.length?value.map(item=>typeof item==='object'?JSON.stringify(item):String(item)).join('；'):'未维护';return ({physical:'实体商品',virtual:'虚拟商品',standard:'标准商品',bundle:'组合商品'})[value]||String(value);}
function specifications(value){if(!value||!Object.keys(value).length)return '未维护';return Object.entries(value).map(([key,item])=>`${key}：${display(item)}`).join('；');}
async function load() { loading.value=true; const r=await requestApi({method:'get',url:`${base}purchase-orders/`,params:{limit:50,offset:(page.value-1)*50}}); loading.value=false; if(!r.success){error.value=formatApiError(r);return;} rows.value=r.data;count.value=r.count;error.value=''; }
async function open(id) { const request=++detailRequest; detailLoading.value=true; detail.value=null;visible.value=true;const r=await requestApi({method:'get',url:`${base}purchase-orders/${encodeURIComponent(id)}/`});if(request!==detailRequest)return;detailLoading.value=false;if(!r.success){error.value=formatApiError(r);visible.value=false;return;}detail.value=r.data;error.value=''; }
async function downloadFile(url,filename){if(downloading.value)return;downloading.value=true;try{const r=await downloadApiFile(url,filename);if(!r.success)error.value=formatApiError(r);}finally{downloading.value=false;}}
async function download(kind) { if(detail.value)await downloadFile(`${base}purchase-orders/${detail.value.id}/${kind}/`,`${detail.value.number}.${kind==='excel'?'xlsx':'pdf'}`); }
async function downloadProductPdf(line){if(!detail.value||!line.label_pdf_url)return;await downloadFile(line.label_pdf_url,`${detail.value.number}-sku-${line.sku_id}.pdf`);}
onMounted(async()=>{ await load(); if(route.params.id)await open(route.params.id); });
watch(()=>route.params.id,(id,previous)=>{if(id&&id!==previous)open(id);});
</script>
<style scoped>
.orders{padding:24px;max-width:1200px;margin:auto;}h1{font-size:24px;}p{color:#667085;line-height:1.6;}.table-wrap{overflow-x:auto;margin:16px 0;}.el-table{min-width:740px;}a{font-size:14px;color:#2563eb;text-decoration:none;margin-left:12px;}@media(max-width:600px){.orders{padding:16px;}}
.product-list{display:grid;gap:16px;margin:20px 0}.product-card{border:1px solid #dce3ed;border-radius:10px;padding:16px;min-width:0}.product-heading{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap}.product-image{width:112px;height:112px;border:1px solid #e5e7eb;border-radius:8px;flex-shrink:0}.image-empty{display:flex;align-items:center;justify-content:center;height:100%;font-size:12px;color:#667085}.product-title{flex:1;min-width:150px;overflow-wrap:anywhere}.product-title h3{margin:0 0 8px}.product-title p{margin:8px 0}.product-title small{color:#667085}.pdf-link{display:block;line-height:1.8;margin:0}.product-details{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px 20px;margin:18px 0 0}.product-details div{min-width:0}.product-details dt{font-size:12px;color:#667085;margin-bottom:4px}.product-details dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}.product-details .full{grid-column:1/-1}.document-actions{display:flex;gap:10px;flex-wrap:wrap}.document-actions .el-button{margin:0}@media(max-width:650px){.product-details{grid-template-columns:repeat(2,minmax(0,1fr))}.product-card{padding:12px}.product-image{width:88px;height:88px}.pdf-link{flex-basis:100%}}
</style>
