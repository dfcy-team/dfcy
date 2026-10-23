<template>
  <section class="reference-list" aria-label="国家订货参考清单">
    <p>先生成国家参考清单，再勾选需订货的商品。候选范围为当前国家有权查看的普通商品，默认只显示建议订货量大于 0 的商品。每批最多计算 20 个候选，可继续查找并保留勾选，最多选择 100 个。</p>
    <p class="muted">{{ parameters.source_kind === 'season' ? '季节模式：请在上方选择历史参考季节的销售期间及目标库销比；当前按历史销量测算，不自动预测季节增长。' : '周期模式：按所选销售期间和目标库销比测算。' }}</p>
    <p class="muted">合计需求为普通商品直接销量＋组合商品按销售时构成折算的件数。组合构成缺失时须先核对；组合库存不自动折成散件可用库存。</p>
    <div class="reference-actions">
      <el-select v-model="analysisMode" aria-label="参考分析方式" @change="resetAnalysis"><el-option label="国家汇总（不区分平台）" value="country"/><el-option label="按平台分析" value="platform"/></el-select>
      <el-select v-if="analysisMode==='platform'" v-model="platformType" placeholder="选择平台" aria-label="参考分析平台" @change="resetAnalysis"><el-option v-for="option in platformOptions" :key="option.platform_type" :label="option.name" :value="option.platform_type"/></el-select>
      <small v-if="analysisMode==='platform' && !platformOptions.length">请先用国家汇总生成清单，获取当前国家有权限的平台。</small>
    </div>
    <p v-if="analysisMode==='platform'" class="muted">平台用于查看需求贡献（含组合折算）；建议订货量仍按国家汇总计算，共享库存、在途及已有需求只扣减一次。</p>
    <div class="reference-actions">
      <el-input v-model="search" clearable placeholder="搜索新旧 SKU / 商品名称" aria-label="参考商品搜索" @keyup.enter="generate" />
      <el-button :loading="loading" :disabled="disabled" @click="generate">生成国家参考清单</el-button>
      <el-select v-model="filter" aria-label="建议订货量筛选" @change="changeFilter">
        <el-option label="建议订货量大于 0" value="positive" />
        <el-option label="全部候选（核对）" value="all" />
        <el-option label="无需订货（核对）" value="zero" />
        <el-option label="数据待核对" value="unknown" />
      </el-select>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-button v-if="error" :disabled="loading || disabled" @click="load">重试本批</el-button>
    <template v-if="generated">
      <p class="muted">参考生成时间：{{ generatedAt }}。当前已扫描 {{ scanOffset + scannedCount }} / {{ candidateCount }} 个候选；每次最多计算 20 个。加入订货明细时会重新计算所选商品，保存前仍须人工复核。</p>
      <div class="reference-scroll" v-loading="loading">
        <el-table :data="rows" border :empty-text="hasMore ? '本批没有符合条件的商品，可继续查找' : '本批没有符合条件的商品，候选已查完'">
          <el-table-column label="选择" width="65"><template #default="{row}"><el-checkbox :model-value="!!chosen[row.sku_id]" :disabled="loading || !selectable(row)" :aria-label="`选择 ${row.sku}`" @change="value=>toggle(row,value)" /></template></el-table-column>
          <el-table-column label="商品图片" width="105"><template #default="{row}"><OperatingProductImageV2 :sku-id="row.sku_id" :source="row.product_details?.image_url || ''" /></template></el-table-column>
          <el-table-column label="SKU / 商品" min-width="200"><template #default="{row}"><DocumentSkuV2 :sku="row.sku" :legacy-sku-code="row.legacy_sku_code" /><small>{{ row.product_name }}</small></template></el-table-column>
          <el-table-column label="国家需求依据" min-width="130"><template #default="{row}"><OperatingDemandV2 :evidence="row" /><small>日均 {{ show(row.daily_sales) }}</small></template></el-table-column>
          <el-table-column label="库存覆盖天数（参考）" width="150"><template #default="{row}">{{ coverage(row) }}<span v-if="coverage(row)!=='待核对'"> 日</span></template></el-table-column>
          <el-table-column v-if="analysisMode==='platform'" label="所选平台销售贡献" min-width="175"><template #default="{row}"><OperatingDemandV2 :evidence="row.platform_analysis || {}" /><div>日均 {{ show(row.platform_analysis?.daily_sales) }}</div><div>占国家需求 {{ share(row.platform_analysis?.country_sales_share) }}</div><small v-for="issue in row.platform_analysis?.issues || []" :key="issue">{{ issueLabel(issue) }}</small></template></el-table-column>
          <el-table-column label="库存与供应" min-width="165"><template #default="{row}"><div>可用库存 {{ show(row.available_stock) }}</div><div>按期到货 {{ show(row.in_transit_stock) }}</div><div>开放需求 {{ show(row.pipeline?.open_operating_demand) }}</div></template></el-table-column>
          <el-table-column label="建议订货量" width="110"><template #default="{row}"><strong>{{ show(row.suggested_quantity) }}</strong></template></el-table-column>
          <el-table-column label="数据依据 / 提示" min-width="240"><template #default="{row}"><small>库存快照 {{ row.source_snapshot_ids?.join('、') || '无' }} · 销量批次 {{ row.source_run_ids?.join('、') || '无' }}</small><small v-for="issue in row.issues || []" :key="issue">{{ issueLabel(issue) }}</small><small v-if="!selectable(row)">无有效正数建议，暂不加入；新品可使用手工订货。</small><el-button link type="primary" @click="openEvidence(row)">查看依据</el-button></template></el-table-column>
        </el-table>
      </div>
      <div class="reference-actions">
        <el-button :disabled="loading || batchIndex===0" @click="previousSearch">上一批</el-button>
        <el-button :loading="loading" :disabled="loading || !!error || !hasMore" @click="continueSearch">继续查找下一批（最多 20 个候选）</el-button>
        <el-button :disabled="loading" @click="selectPage">勾选本批建议订货商品</el-button>
        <el-button :disabled="!selectedRows.length" @click="clearSelection">清空勾选</el-button>
        <el-button type="primary" :disabled="loading || disabled || !!error || !selectedRows.length" @click="$emit('select',selectedRows)">{{ actionLabel }}（{{ selectedRows.length }}）</el-button>
      </div>
    </template>
    <el-dialog v-model="evidenceVisible" title="商品库存依据" width="min(680px,96vw)">
      <template v-if="evidenceRow">
        <h4>{{ evidenceRow.sku }} · {{ evidenceRow.product_name }}</h4>
        <el-table :data="evidenceRow.warehouses || []" border empty-text="没有仓库库存依据">
          <el-table-column prop="name" label="仓库" min-width="140" />
          <el-table-column label="可用库存" width="120"><template #default="{row}">{{ show(row.available_qty) }}</template></el-table-column>
          <el-table-column label="快照时间" min-width="190"><template #default="{row}">{{ row.snapshot_at || '无' }}</template></el-table-column>
          <el-table-column label="问题" min-width="180"><template #default="{row}"><span v-for="issue in row.issues || []" :key="issue" class="evidence-issue">{{ issueLabel(issue) }}</span><span v-if="!row.issues?.length">无</span></template></el-table-column>
        </el-table>
        <div v-if="evidenceRow.blocking_issues?.length" class="blocking-issues"><strong>阻断问题</strong><span v-for="issue in evidenceRow.blocking_issues" :key="issue">{{ issueLabel(issue) }}</span></div>
        <p v-else class="muted">当前商品没有阻断问题。</p>
      </template>
    </el-dialog>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { fetchOperatingReferences } from '../../api/operatingOrdersV2';
import OperatingProductImageV2 from './OperatingProductImageV2.vue';
import DocumentSkuV2 from './DocumentSkuV2.vue';
import OperatingDemandV2 from './OperatingDemandV2.vue';
const props = defineProps({ parameters: { type: Object, required: true }, disabled: Boolean, validate: { type: Function, required: true }, issueLabel: { type: Function, default: value => value }, actionLabel: { type: String, default: '加入订货明细并复核' } });
defineEmits(['select']);
const search=ref(''), appliedSearch=ref(''), filter=ref('positive'), rows=ref([]), chosen=ref({}), scanOffset=ref(0), nextOffset=ref(0), batchOffsets=ref([0]), batchIndex=ref(0), candidateCount=ref(0), scannedCount=ref(0), hasMore=ref(false), loading=ref(false), error=ref(''), generated=ref(false), generatedAt=ref('');
const analysisMode=ref('country'), platformType=ref(''), platformOptions=ref([]);
const evidenceVisible=ref(false), evidenceRow=ref(null);
let sequence=0;
const selectedRows=computed(()=>Object.values(chosen.value));
const selectable=row=>Number.isInteger(Number(row.suggested_quantity)) && Number(row.suggested_quantity)>0;
const show=value=>value==null?'—':value;
const coverage=row=>row.blocking_issues?.length || row.inventory_complete===false || row.coverage_days==null ? '待核对' : row.coverage_days;
const share=value=>value==null?'—':`${(Number(value)*100).toFixed(1)}%`;
function reset(){++sequence;evidenceVisible.value=false;evidenceRow.value=null;rows.value=[];chosen.value={};scanOffset.value=0;nextOffset.value=0;batchOffsets.value=[0];batchIndex.value=0;candidateCount.value=0;scannedCount.value=0;hasMore.value=false;generated.value=false;loading.value=false;error.value='';}
watch(()=>JSON.stringify(props.parameters),()=>{reset();platformOptions.value=[];platformType.value='';analysisMode.value='country';});
function resetAnalysis(){reset();}
onBeforeUnmount(()=>{++sequence;});
async function load(){
  if(props.disabled || !props.validate())return;
  if(analysisMode.value==='platform'&&!platformType.value){error.value='请选择有权限的平台；可先生成国家汇总清单。';return;}
  const request=++sequence;loading.value=true;error.value='';rows.value=[];
  try{
    const result=await fetchOperatingReferences({...props.parameters,analysis_mode:analysisMode.value,...(analysisMode.value==='platform'?{platform_type:platformType.value}:{}),search:appliedSearch.value,quantity_filter:filter.value,limit:20,offset:scanOffset.value});
    if(request!==sequence)return;
    if(!result?.success)throw new Error(result?.message || result?.data?.detail || '参考清单读取失败，请重试。');
    rows.value=result.data.lines || [];platformOptions.value=result.data.platform_options || [];candidateCount.value=Number(result.data.candidate_count ?? result.data.count ?? 0);scannedCount.value=Number(result.data.scanned_count || 0);nextOffset.value=Number(result.data.next_offset ?? (scanOffset.value+scannedCount.value));hasMore.value=!!result.data.has_more;generatedAt.value=result.data.generated_at;generated.value=true;
  }catch(e){if(request===sequence)error.value=e.message || '参考清单读取失败，请重试。';}
  finally{if(request===sequence)loading.value=false;}
}
function generate(){scanOffset.value=0;batchOffsets.value=[0];batchIndex.value=0;chosen.value={};appliedSearch.value=search.value.trim();return load();}
function changeFilter(){scanOffset.value=0;batchOffsets.value=[0];batchIndex.value=0;return load();}
function continueSearch(){if(loading.value)return;if(error.value)return load();if(!hasMore.value)return;if(batchIndex.value+1<batchOffsets.value.length){batchIndex.value++;scanOffset.value=batchOffsets.value[batchIndex.value];}else{scanOffset.value=nextOffset.value;batchOffsets.value=[...batchOffsets.value,scanOffset.value];batchIndex.value=batchOffsets.value.length-1;}return load();}
function previousSearch(){if(batchIndex.value===0)return;batchIndex.value--;scanOffset.value=batchOffsets.value[batchIndex.value];return load();}
function clearSelection(){chosen.value={};if(error.value.includes('最多选择100'))error.value='';}
function toggle(row,value){if(!value){if(error.value.includes('最多选择100'))error.value='';const copy={...chosen.value};delete copy[row.sku_id];chosen.value=copy;return;}if(!selectable(row))return;if(selectedRows.value.length>=100&&!chosen.value[row.sku_id]){error.value='每张建议订货单最多选择100个商品，请分单处理。';return;}chosen.value={...chosen.value,[row.sku_id]:row};}
function selectPage(){rows.value.filter(selectable).forEach(row=>toggle(row,true));}
function openEvidence(row){evidenceRow.value=row;evidenceVisible.value=true;}
</script>
<style scoped>
.reference-list{margin-top:16px}.reference-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}.reference-actions>.el-input{width:min(280px,100%)}.reference-actions>.el-select{width:180px}.reference-scroll{overflow:auto}small{display:block;line-height:1.6}.muted{color:#64748b;font-size:12px}
</style>
