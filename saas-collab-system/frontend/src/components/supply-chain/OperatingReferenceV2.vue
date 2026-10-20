<template>
  <section class="reference-list" aria-label="国家订货参考清单">
    <p>先生成国家参考清单，再勾选需订货的商品。候选范围为当前国家有权查看的普通商品，缺少该国数据的商品会标为待核对。每页计算 20 个商品，翻页保留勾选，最多选择 100 个。</p>
    <p class="muted">{{ parameters.source_kind === 'season' ? '季节模式：请在上方选择历史参考季节的销售期间及目标库销比；当前按历史销量测算，不自动预测季节增长。' : '周期模式：按所选销售期间和目标库销比测算。' }}</p>
    <div class="reference-actions">
      <el-select v-model="analysisMode" aria-label="参考分析方式" @change="resetAnalysis"><el-option label="国家汇总（不区分平台）" value="country"/><el-option label="按平台分析" value="platform"/></el-select>
      <el-select v-if="analysisMode==='platform'" v-model="platformType" placeholder="选择平台" aria-label="参考分析平台" @change="resetAnalysis"><el-option v-for="option in platformOptions" :key="option.platform_type" :label="option.name" :value="option.platform_type"/></el-select>
      <small v-if="analysisMode==='platform' && !platformOptions.length">请先用国家汇总生成清单，获取当前国家有权限的平台。</small>
    </div>
    <p v-if="analysisMode==='platform'" class="muted">平台用于查看销售贡献；建议订货量仍按国家汇总计算，共享库存、在途及已有需求只扣减一次。</p>
    <div class="reference-actions">
      <el-input v-model="search" clearable placeholder="搜索新旧 SKU / 商品名称" aria-label="参考商品搜索" @keyup.enter="generate" />
      <el-button :loading="loading" :disabled="disabled" @click="generate">生成国家参考清单</el-button>
      <el-select v-model="filter" aria-label="本页建议筛选">
        <el-option label="本页全部" value="all" />
        <el-option label="本页建议订货" value="positive" />
        <el-option label="本页无需订货" value="zero" />
        <el-option label="本页数据待核对" value="unknown" />
      </el-select>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="generated">
      <p class="muted">参考生成时间：{{ generatedAt }}。筛选仅作用于本页；加入订货明细时会重新计算所选商品，保存前仍须人工复核。</p>
      <div class="reference-scroll" v-loading="loading">
        <el-table :data="visibleRows" border empty-text="本页没有符合条件的商品，可调整筛选或翻页">
          <el-table-column label="选择" width="65"><template #default="{row}"><el-checkbox :model-value="!!chosen[row.sku_id]" :disabled="loading || !selectable(row)" :aria-label="`选择 ${row.sku}`" @change="value=>toggle(row,value)" /></template></el-table-column>
          <el-table-column label="商品图片" width="105"><template #default="{row}"><OperatingProductImageV2 :sku-id="row.sku_id" :source="row.product_details?.image_url || ''" /></template></el-table-column>
          <el-table-column label="SKU / 商品" min-width="200"><template #default="{row}"><DocumentSkuV2 :sku="row.sku" :legacy-sku-code="row.legacy_sku_code" /><small>{{ row.product_name }}</small></template></el-table-column>
          <el-table-column label="国家销售依据" min-width="130"><template #default="{row}"><div>销量 {{ show(row.sales_quantity) }}</div><small>日均 {{ show(row.daily_sales) }}</small></template></el-table-column>
          <el-table-column v-if="analysisMode==='platform'" label="所选平台销售贡献" min-width="175"><template #default="{row}"><div>销量 {{ show(row.platform_analysis?.sales_quantity) }}</div><div>日均 {{ show(row.platform_analysis?.daily_sales) }}</div><div>占国家销量 {{ share(row.platform_analysis?.country_sales_share) }}</div><small v-for="issue in row.platform_analysis?.issues || []" :key="issue">{{ issueLabel(issue) }}</small></template></el-table-column>
          <el-table-column label="库存与供应" min-width="165"><template #default="{row}"><div>可用库存 {{ show(row.available_stock) }}</div><div>按期到货 {{ show(row.in_transit_stock) }}</div><div>开放需求 {{ show(row.pipeline?.open_operating_demand) }}</div></template></el-table-column>
          <el-table-column label="建议订货量" width="110"><template #default="{row}"><strong>{{ show(row.suggested_quantity) }}</strong></template></el-table-column>
          <el-table-column label="数据依据 / 提示" min-width="240"><template #default="{row}"><small>库存快照 {{ row.source_snapshot_ids?.join('、') || '无' }} · 销量批次 {{ row.source_run_ids?.join('、') || '无' }}</small><small v-for="issue in row.issues || []" :key="issue">{{ issueLabel(issue) }}</small><small v-if="!selectable(row)">无有效正数建议，暂不加入；新品可使用手工订货。</small></template></el-table-column>
        </el-table>
      </div>
      <div class="reference-actions">
        <el-pagination layout="total, prev, pager, next" :total="total" :page-size="20" :current-page="page" :disabled="loading" @current-change="changePage" />
        <el-button :disabled="loading" @click="selectPage">勾选本页建议订货商品</el-button>
        <el-button :disabled="!selectedRows.length" @click="clearSelection">清空勾选</el-button>
        <el-button type="primary" :disabled="loading || disabled || !!error || !selectedRows.length" @click="$emit('select',selectedRows)">加入订货明细并复核（{{ selectedRows.length }}）</el-button>
      </div>
    </template>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { fetchOperatingReferences } from '../../api/operatingOrdersV2';
import OperatingProductImageV2 from './OperatingProductImageV2.vue';
import DocumentSkuV2 from './DocumentSkuV2.vue';
const props = defineProps({ parameters: { type: Object, required: true }, disabled: Boolean, validate: { type: Function, required: true }, issueLabel: { type: Function, default: value => value } });
defineEmits(['select']);
const search=ref(''), appliedSearch=ref(''), filter=ref('all'), rows=ref([]), chosen=ref({}), page=ref(1), total=ref(0), loading=ref(false), error=ref(''), generated=ref(false), generatedAt=ref('');
const analysisMode=ref('country'), platformType=ref(''), platformOptions=ref([]);
let sequence=0;
const selectedRows=computed(()=>Object.values(chosen.value));
const selectable=row=>Number.isInteger(Number(row.suggested_quantity)) && Number(row.suggested_quantity)>0;
const show=value=>value==null?'—':value;
const share=value=>value==null?'—':`${(Number(value)*100).toFixed(1)}%`;
const visibleRows=computed(()=>rows.value.filter(row=>filter.value==='all' || (filter.value==='positive' && selectable(row)) || (filter.value==='zero' && row.suggested_quantity!=null && Number(row.suggested_quantity)===0) || (filter.value==='unknown' && row.suggested_quantity==null)));
function reset(){++sequence;rows.value=[];chosen.value={};page.value=1;total.value=0;generated.value=false;loading.value=false;error.value='';}
watch(()=>JSON.stringify(props.parameters),()=>{reset();platformOptions.value=[];platformType.value='';analysisMode.value='country';});
function resetAnalysis(){reset();}
onBeforeUnmount(()=>{++sequence;});
async function load(){
  if(props.disabled || !props.validate())return;
  if(analysisMode.value==='platform'&&!platformType.value){error.value='请选择有权限的平台；可先生成国家汇总清单。';return;}
  const request=++sequence;loading.value=true;error.value='';rows.value=[];
  try{
    const result=await fetchOperatingReferences({...props.parameters,analysis_mode:analysisMode.value,...(analysisMode.value==='platform'?{platform_type:platformType.value}:{}),search:appliedSearch.value,limit:20,offset:(page.value-1)*20});
    if(request!==sequence)return;
    if(!result?.success)throw new Error(result?.message || result?.data?.detail || '参考清单读取失败，请重试。');
    rows.value=result.data.lines || [];platformOptions.value=result.data.platform_options || [];total.value=Number(result.data.count || 0);generatedAt.value=result.data.generated_at;generated.value=true;
  }catch(e){if(request===sequence)error.value=e.message || '参考清单读取失败，请重试。';}
  finally{if(request===sequence)loading.value=false;}
}
function generate(){page.value=1;chosen.value={};appliedSearch.value=search.value.trim();return load();}
function changePage(value){page.value=value;return load();}
function clearSelection(){chosen.value={};if(error.value.includes('最多选择100'))error.value='';}
function toggle(row,value){if(!value){if(error.value.includes('最多选择100'))error.value='';const copy={...chosen.value};delete copy[row.sku_id];chosen.value=copy;return;}if(!selectable(row))return;if(selectedRows.value.length>=100&&!chosen.value[row.sku_id]){error.value='每张建议订货单最多选择100个商品，请分单处理。';return;}chosen.value={...chosen.value,[row.sku_id]:row};}
function selectPage(){visibleRows.value.filter(selectable).forEach(row=>toggle(row,true));}
</script>
<style scoped>
.reference-list{margin-top:16px}.reference-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}.reference-actions>.el-input{width:min(280px,100%)}.reference-actions>.el-select{width:180px}.reference-scroll{overflow:auto}small{display:block;line-height:1.6}.muted{color:#64748b;font-size:12px}
</style>
