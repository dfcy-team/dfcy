<template>
  <section class="supply-cost-ledger">
    <p>按商品、国家、仓库和发运批次查看供应链成本。默认显示各来源的最新版本；输入变化后显示待复算，历史金额保留。</p>
    <el-alert v-if="!allowed" title="需要供应链查看权限及对应数据范围。" type="info" :closable="false" />
    <template v-else>
      <el-form class="ledger-filters" inline @submit.prevent="search">
        <el-form-item label="SKU / 商品"><el-input v-model="draft.search" clearable placeholder="SKU 或商品名称" @input="draft.sku_id=''" @keyup.enter="search" /></el-form-item>
        <el-form-item label="国家"><el-select v-model="draft.country_id" clearable filterable remote :remote-method="v=>loadOptions('countries',v)" placeholder="全部国家"><el-option v-for="o in options.countries" :key="o.id" :value="o.id" :label="`${o.name} (${o.country_code})`" /></el-select></el-form-item>
        <el-form-item label="仓库"><el-select v-model="draft.warehouse_id" clearable filterable remote :remote-method="v=>loadOptions('warehouses',v)" placeholder="全部仓库"><el-option v-for="o in options.warehouses" :key="o.id" :value="o.id" :label="`${o.name} (${o.country_code})`" /></el-select></el-form-item>
        <el-form-item label="发运批次"><el-select v-model="draft.batch_id" clearable filterable remote :remote-method="v=>loadOptions('batches',v)" placeholder="全部批次"><el-option v-for="o in options.batches" :key="o.id" :value="o.id" :label="o.name" /></el-select></el-form-item>
        <el-form-item label="版本"><el-select v-model="draft.versions"><el-option label="最新版本" value="latest" /><el-option label="包含历史" value="all" /></el-select></el-form-item>
        <el-form-item><el-button type="primary" :disabled="loading" @click="search">查询</el-button><el-button :disabled="loading" @click="reset">重置</el-button></el-form-item>
      </el-form>
      <el-alert v-if="error || optionError" :title="error || optionError" type="error" :closable="false" />
      <div class="ledger-table">
        <el-table v-loading="loading" :data="rows" border row-key="id" empty-text="查询范围内尚无已计算的供应链成本">
          <el-table-column label="商品图片" width="112"><template #default="{row}"><DocumentProductImageV2 :image-path="row.image_preview_url || ''" :alt="`${row.sku || ''} 商品图片`"/></template></el-table-column><el-table-column label="SKU" min-width="190"><template #default="{row}"><DocumentSkuV2 :sku="row.sku" :legacy-sku-code="row.legacy_sku_code"/></template></el-table-column>
          <el-table-column label="入库单件成本" min-width="140"><template #default="{row}">{{ value(row.received_unit_cost) }}</template></el-table-column>
          <el-table-column label="发货单件成本" min-width="140"><template #default="{row}">{{ value(row.shipped_unit_cost) }}</template></el-table-column>
          <el-table-column label="状态 / 版本" min-width="165"><template #default="{row}">{{ stateLabel(row.status) }} · v{{ row.sequence }}{{ row.is_latest ? '' : ' · 历史' }}</template></el-table-column>
          <el-table-column prop="product_name" label="商品" min-width="170" />
          <el-table-column prop="country_code" label="国家" width="80" /><el-table-column label="仓库" min-width="140"><template #default="{row}">{{ row.warehouse_name || '未入库' }}</template></el-table-column>
          <el-table-column label="发运批次" min-width="200"><template #default="{row}">{{ row.batch_number || '集货前' }}</template></el-table-column>
          <el-table-column prop="shipment_number" label="发货单" min-width="180" />
          <el-table-column label="发货 / 实收" width="120"><template #default="{row}">{{ row.quantity }} / {{ row.received_quantity ?? '未核对' }}</template></el-table-column>
          <el-table-column label="操作" width="170"><template #default="{row}"><el-button link type="primary" @click="detail=row">构成</el-button><el-button link type="primary" @click="history(row)">历史版本</el-button></template></el-table-column>
        </el-table>
      </div>
      <el-pagination layout="total,prev,pager,next" :current-page="page" :page-size="20" :total="total" @current-change="changePage" />
      <el-drawer :model-value="!!detail" title="供应链商品成本构成" size="min(600px,96vw)" @close="detail=null" @update:model-value="v=>{if(!v)detail=null}">
        <el-descriptions v-if="detail" :column="1" border>
          <el-descriptions-item label="商品图片"><DocumentProductImageV2 :image-path="detail.image_preview_url || ''" :alt="`${detail.sku} 商品图片`"/></el-descriptions-item><el-descriptions-item label="商品"><DocumentSkuV2 :sku="detail.sku" :legacy-sku-code="detail.legacy_sku_code"/>{{ detail.product_name }}</el-descriptions-item>
          <el-descriptions-item label="来源">{{ detail.order_number }} / {{ detail.shipment_number }} / {{ detail.batch_number || '集货前' }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ stateLabel(detail.status) }} · v{{ detail.sequence }}{{ detail.is_latest ? '' : ' · 历史' }}</el-descriptions-item>
          <el-descriptions-item v-for="(label,key) in amounts" :key="key" :label="label">{{ value(detail[key]) }}</el-descriptions-item>
        </el-descriptions>
      </el-drawer>
    </template>
  </section>
</template>

<script setup>
import DocumentSkuV2 from './DocumentSkuV2.vue';
import DocumentProductImageV2 from './DocumentProductImageV2.vue';
import {computed, onMounted, onUnmounted, reactive, ref, watch} from 'vue';
import {useAuthStore} from '../../stores/auth';
import {fetchSupplyProductCosts, fetchSupplyCostOptions} from '../../api/supplyCostsV2';

const auth=useAuthStore();
const allowed=computed(()=>!auth.authorizationStale && auth.hasPermission('supply.v2.view'));
const empty=()=>({search:'',sku_id:'',country_id:'',warehouse_id:'',batch_id:'',versions:'latest'});
const draft=reactive(empty()), applied=ref(empty()), options=reactive({countries:[],warehouses:[],batches:[]});
const rows=ref([]),total=ref(0),page=ref(1),loading=ref(false),error=ref(''),optionError=ref(''),detail=ref(null);
let sequence=0;
const optionSequences={countries:0,warehouses:0,batches:0};
const amounts={goods_amount:'发货货值',collection_fee:'到集货点费用',freight_fee:'货运费用',clearance_fee:'实收清货费用',shipped_total:'发货总成本',received_goods_amount:'实收货值',received_collection_fee:'实收到仓费',received_freight_fee:'实收运费',received_total:'实收总成本',pending_total:'待处理成本'};
const value=v=>v===null||v===undefined?'未确定':v;
const stateLabel=v=>({confirmed:'已确认',estimated:'暂估',recalculation_required:'待复算'})[v]||v;

async function load(){
  const current=++sequence;
  if(!allowed.value){rows.value=[];total.value=0;return;}
  loading.value=true;error.value='';detail.value=null;
  try{
    const params=Object.fromEntries(Object.entries(applied.value).filter(([,v])=>v!==''&&v!==null&&v!==undefined));
    const result=await fetchSupplyProductCosts({...params,limit:20,offset:(page.value-1)*20});
    if(current!==sequence||!allowed.value)return;
    if(!result?.success)throw new Error(result?.message||'商品成本查询失败');
    rows.value=Array.isArray(result.data)?result.data:[];total.value=Number(result.count||0);
  }catch(e){if(current===sequence){rows.value=[];total.value=0;error.value=e?.message||'商品成本查询失败';}}
  finally{if(current===sequence)loading.value=false;}
}
async function loadOptions(kind,search=''){
  const current=++optionSequences[kind];
  if(!allowed.value)return;
  try{
    const result=await fetchSupplyCostOptions({kind,search,limit:50});
    if(current!==optionSequences[kind]||!allowed.value)return;
    if(!result?.success)throw new Error(result?.message||'筛选项加载失败');
    options[kind]=Array.isArray(result.data)?result.data:[];
  }catch(e){if(current===optionSequences[kind])optionError.value=e?.message||'筛选项加载失败';}
}
function search(){applied.value={...draft};page.value=1;return load();}
function reset(){Object.assign(draft,empty());return search();}
function changePage(v){page.value=v;return load();}
function history(row){Object.assign(draft,{...empty(),sku_id:row.sku_id,search:row.sku,country_id:row.country_id,versions:'all'});return search();}
function clear(){sequence++;rows.value=[];total.value=0;detail.value=null;loading.value=false;for(const kind of Object.keys(options)){optionSequences[kind]++;options[kind]=[];}}
watch(allowed,v=>{if(!v)clear();});
onMounted(()=>{load();for(const kind of Object.keys(options))loadOptions(kind);});
onUnmounted(clear);
defineExpose({draft,applied,rows,total,load,search,reset,history,changePage,detail});
</script>

<style scoped>
.supply-cost-ledger{min-width:0}.supply-cost-ledger>p{line-height:1.7;color:#64748b}.ledger-filters{display:flex;flex-wrap:wrap;gap:0 8px}.ledger-filters :deep(.el-input),.ledger-filters :deep(.el-select){width:200px}.ledger-table{max-width:100%;overflow-x:auto;margin:12px 0}.supply-cost-ledger :deep(.el-pagination){max-width:100%;flex-wrap:wrap}@media(max-width:680px){.ledger-filters :deep(.el-form-item){width:100%;margin-right:0}.ledger-filters :deep(.el-input),.ledger-filters :deep(.el-select){width:100%}}
</style>
