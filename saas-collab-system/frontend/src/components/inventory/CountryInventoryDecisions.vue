<template>
  <AppPage :title="mode === 'replenishment' ? '补货建议' : '国家 SKU 经营汇总'" eyebrow="库存决策" subtitle="按国家复核库存、销量窗口与供应进度；缺失数据会单独标明。" :capability="error ? 'degraded' : 'connected'">
    <el-alert v-if="notice" :title="notice" type="info" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div class="filters">
      <el-select v-model="countryId" filterable placeholder="选择国家" aria-label="国家" :disabled="loading || saving || previewing || evaluating" @change="countryChanged">
        <el-option v-for="country in countries" :key="country.id" :label="`${country.name} (${country.country_code || '—'})`" :value="country.id" />
      </el-select>
      <el-input v-model="search" clearable placeholder="搜索新旧 SKU / 商品" aria-label="搜索新旧 SKU" :disabled="loading || saving || previewing || evaluating" @keyup.enter="applyFilters" />
      <el-select v-model="windowDays" aria-label="销量窗口" :disabled="loading || saving || previewing || evaluating" @change="applyFilters"><el-option v-for="days in [7, 15, 30]" :key="days" :label="`${days} 日销量`" :value="days" /></el-select>
      <el-input-number v-model="targetDays" :min="1" :max="365" :precision="0" aria-label="目标覆盖天数" :disabled="loading || saving || previewing || evaluating" />
      <span>目标覆盖天数</span>
      <el-button type="primary" :loading="loading" :disabled="saving || previewing || evaluating || !countryId" @click="applyFilters">查询</el-button>
    </div>
    <div class="table-scroll">
      <el-table ref="tableRef" :data="rows" v-loading="loading" row-key="sku_id" stripe @selection-change="selectionChanged" @expand-change="expandedChanged" empty-text="请选择国家并查询经营汇总">
        <el-table-column v-if="canWrite || canEvaluate" type="selection" width="48" :selectable="row => canEvaluate || (Number.isInteger(row.suggested_quantity) && row.suggested_quantity > 0 && row.inventory_complete)" />
        <el-table-column type="expand"><template #default="{row}">
          <div class="detail">
            <div class="product"><DocumentProductImageV2 :image-path="safeImage(row.image_preview_url)" :alt="`${row.sku || ''} 商品图片`"/><DocumentSkuV2 :sku="row.sku" :legacy-sku-code="row.legacy_sku_code"/><span>{{ row.product_name || '商品名称待核对' }}</span></div>
            <h4>仓库库存</h4><div v-for="warehouse in row.warehouses || []" :key="warehouse.id" class="detail-row"><strong>{{ warehouse.name }}</strong><span>可用：{{ display(warehouse.available_qty) }}</span><span>快照（北京时间）：{{ sourceTime(warehouse.snapshot_at) }}</span><span v-if="warehouse.issues?.length" class="issue">{{ warehouse.issues.map(issueLabel).join('、') }}</span></div>
            <h4>供应进度（互斥阶段）</h4><el-alert v-if="row.pipeline?.authorized === false" title="当前账号没有供应汇总读取权限；各供应量为空，补货建议不可用。" type="warning" :closable="false"/><div class="stage-grid"><span v-for="stage in pipelineStages" :key="stage.key">{{ stage.label }}：{{ display(row.pipeline?.[stage.key]) }}</span></div>
            <p>WMS 在途库存：{{ display(row.wms_in_transit_stock) }}（仅观察，不计入供应合计）</p><p>有效到货：{{ display(row.pipeline?.effective_incoming) }}　开放运营需求：{{ display(row.pipeline?.open_operating_demand) }}（已从测算扣除）　未知 ETA：{{ display(row.pipeline?.unknown_eta) }}</p>
            <h4>销量窗口</h4><div class="sales-grid"><div v-for="window in row.sales_windows || []" :key="window.days"><strong>{{ window.days }} 日（{{ window.start_date }} 至 {{ window.end_date }}）</strong><span>销量：{{ display(window.units) }}；日均：{{ display(window.daily_units) }}；覆盖：{{ window.coverage_complete ? '完整' : '待核对' }}</span><span>已采集完成退款：{{ display(window.refund_units) }}；金额：{{ currencyAmounts(window.amount_by_currency) }}</span><span v-if="window.refund_amount_by_currency">退款金额：{{ currencyAmounts(window.refund_amount_by_currency) }}</span></div></div>
            <p>数据问题：{{ row.issues?.length ? row.issues.map(issueLabel).join('、') : '暂无' }}</p><p>库龄：{{ row.stock_age?.status === 'unavailable' ? (row.stock_age.notice || '待核对') : display(row.stock_age?.status) }}</p><p>库存账本：<a v-if="row.cost_ledger_url" :href="row.cost_ledger_url">查看成本账本</a><span v-else>待核对</span></p>
          </div>
        </template></el-table-column>
        <el-table-column label="SKU / 商品" min-width="280"><template #default="{row}"><div class="product"><DocumentProductImageV2 :image-path="safeImage(row.image_preview_url)" :alt="`${row.sku} 商品图片`"/><div><DocumentSkuV2 :sku="row.sku" :legacy-sku-code="row.legacy_sku_code"/><small>{{ row.product_name || '商品名称待核对' }}</small></div></div></template></el-table-column>
        <el-table-column label="可用库存" min-width="105"><template #default="{row}">{{ display(row.available_stock) }}</template></el-table-column>
        <el-table-column :label="`近 ${windowDays} 日销量`" min-width="120"><template #default="{row}">{{ display(salesFor(row, windowDays)?.units) }}<small v-if="salesFor(row, windowDays)?.coverage_complete === false" class="issue">采集覆盖待核对</small></template></el-table-column>
        <el-table-column label="日均 / 覆盖" min-width="130"><template #default="{row}">{{ display(row.daily_sales) }} / {{ display(row.coverage_days) }} 日</template></el-table-column>
        <el-table-column label="建议数量" min-width="105"><template #default="{row}">{{ display(row.suggested_quantity) }}</template></el-table-column>
        <el-table-column label="复核状态" width="100"><template #default="{row}"><el-tag type="warning">{{ row.needs_review ? '需人工复核' : '—' }}</el-tag><small v-if="row.issues?.length" class="issue">{{ issueLabel(row.issues[0]) }}</small></template></el-table-column>
      </el-table>
    </div>
    <el-pagination class="pagination" layout="total, prev, pager, next" :total="total" :current-page="page" :page-size="20" :disabled="loading || saving || previewing || evaluating" @current-change="changePage" />
    <div v-if="canWrite || canEvaluate" class="selection-actions"><span>已选 {{ selectedRows.length }} 个 SKU</span><el-button v-if="canEvaluate" :loading="evaluating" :disabled="saving || loading || previewing || !selectedRows.length" @click="evaluateAlerts">生成库存预警</el-button><el-button v-if="canWrite" type="primary" :disabled="saving || evaluating || !selectedRows.length || !permissions.can_preview || selectedRows.some(row => !row.inventory_complete || !Number.isInteger(row.suggested_quantity) || row.suggested_quantity <= 0)" :loading="previewing" @click="preview">预览并复核</el-button></div>
    <el-dialog v-model="reviewOpen" title="复核运营订货草稿" width="min(900px, 96vw)" append-to-body class="sc2-scroll-dialog" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :before-close="closeReview">
      <el-alert title="预览结果仅供人工复核；确认后只创建运营订货草稿，不会提交给采购。" type="warning" :closable="false" />
      <el-form label-position="top" :disabled="saving">
        <div class="form-grid"><el-form-item label="来源"><el-select v-model="sourceKind"><el-option label="周期建议" value="cycle"/><el-option label="季节建议" value="season"/></el-select></el-form-item><el-form-item label="订单日期"><el-input :model-value="businessToday()" disabled /></el-form-item><el-form-item label="版本说明"><el-input v-model="planRevision" placeholder="例如：Q4 第 1 版" /></el-form-item>
          <el-form-item label="活动或季节"><el-input v-model="campaign" placeholder="活动或季节名称" /></el-form-item><el-form-item label="需求开始日期"><el-date-picker v-model="demandStart" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="需求结束日期"><el-date-picker v-model="demandEnd" type="date" value-format="YYYY-MM-DD" /></el-form-item></div>
        <el-form-item label="人工复核说明"><el-input v-model="notes" type="textarea" :rows="3" maxlength="2000" show-word-limit placeholder="说明调整依据或确认依据" /></el-form-item>
      </el-form>
      <el-alert v-if="reviewError" :title="reviewError" type="error" :closable="false" />
      <div v-if="previewData" class="table-scroll"><el-table :data="reviewLines" border><el-table-column prop="sku" label="SKU" min-width="130"/><el-table-column prop="suggested_quantity" label="系统建议" width="100"/><el-table-column label="复核订货数量" width="180"><template #default="{row}"><el-input-number v-model="row.quantity" :min="1" :precision="0" :controls="false" :disabled="saving || !canWrite" /></template></el-table-column><el-table-column label="复核问题" min-width="180"><template #default="{row}">{{ row.issues?.map(issueLabel).join('、') || '请核对' }}</template></el-table-column></el-table></div>
      <template #footer><el-button :disabled="saving" @click="closeReview">返回</el-button><el-button type="primary" :loading="saving" :disabled="!canWrite || !permissions.can_create || !validReview" @click="createDraft">创建运营订货草稿</el-button></template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import AppPage from '../AppPage.vue';
import DocumentSkuV2 from '../supply-chain/DocumentSkuV2.vue';
import DocumentProductImageV2 from '../supply-chain/DocumentProductImageV2.vue';
import { useAuthStore } from '../../stores/auth';
import * as api from '../../api/inventoryDecisions';
import '../../styles/supplyCollaboration.css';

const props = defineProps({ mode: { type: String, default: 'summary' } });
const auth = useAuthStore(), router = useRouter();
const canWrite = computed(() => auth.isInternal && !auth.authorizationStale && auth.hasPermission('sales_management.operating_orders.manage'));
const rows = ref([]), countries = ref([]), countryId = ref(null), search = ref(''), windowDays = ref(30), targetDays = ref(60), page = ref(1), total = ref(0), loading = ref(false), error = ref(''), notice = ref(''), permissions = ref({ can_preview: false, can_create: false }), selectedRows = ref([]), expanded = ref(new Set()), tableRef = ref(null);
const evaluating = ref(false);
const canEvaluate = computed(() => auth.isInternal && !auth.authorizationStale && auth.hasPermission('alerts.evaluate') && permissions.value.can_evaluate);
const previewing = ref(false), saving = ref(false), reviewOpen = ref(false), reviewError = ref(''), previewData = ref(null), reviewLines = ref([]), sourceKind = ref('cycle'), planRevision = ref(''), campaign = ref(''), demandStart = ref(null), demandEnd = ref(null), notes = ref('');
const pipelineStages = [{ key: 'production_unshipped', label: '生产未发' }, { key: 'awaiting_dispatch', label: '待发运' }, { key: 'transporting', label: '运输中' }, { key: 'arrived_unchecked', label: '到仓待检' }, { key: 'received_awaiting_wms', label: '已收未入 WMS' }, { key: 'wms_received', label: '已对账收货（累计）' }, { key: 'excess_shipped', label: '超额发运' }, { key: 'additional_shipped', label: '追加发运' }];
const validReview = computed(() => !!notes.value.trim() && !!planRevision.value.trim() && reviewLines.value.length > 0 && reviewLines.value.every(line => Number.isInteger(Number(line.quantity)) && Number(line.quantity) > 0));
let requestSequence = 0;
const issueLabels = {missing_inventory_snapshot:'缺少库存快照',available_quantity_unverified:'数量来源字段待核对',inventory_source_incomplete:'库存同步未完整成功',stale_inventory_snapshot:'库存快照超过24小时',ambiguous_inventory_aliases:'新旧编码库存来源有歧义',unmapped_inventory:'存在未映射库存',unmapped_sales_lines:'存在未映射销售商品',collection_coverage_unproven:'销量采集覆盖尚未证实',no_sales_facts:'无可验证销量',supply_summary_not_authorized:'缺少供应数量汇总权限',warehouse_supply_scope_incomplete:'授权仓范围内供应量不完整',unassigned_warehouse_supply:'供应量目的仓未指定',unknown_eta:'部分供应无预计到仓日期，未计入按期到货',overdue_eta:'存在逾期预计到仓',wms_receipt_overlap_unresolved:'WMS已收货与在途可能重复，请对账',wms_allocation_requires_review:'WMS关联需重新核对',local_receipt_quantity_difference:'实收与发货数量有差异',invalid_store_timezone:'店铺时区未正确配置',unfinished_store_day:'销售周期尚未结束',no_authorized_sales_store:'暂无可读取的销售店铺',refunds_not_deducted:'退款已单列，未扣减销量'};
const issueLabel = code => issueLabels[code] || code;
async function evaluateAlerts() {
  if (!canEvaluate.value || evaluating.value || previewing.value || saving.value || loading.value || !countryId.value || !selectedRows.value.length) return;
  evaluating.value = true;
  try {
    const response = await api.evaluateCountryInventoryAlerts({country_id:countryId.value,sku_ids:selectedRows.value.map(row=>row.sku_id),window_days:windowDays.value,target_days:targetDays.value});
    if (!response?.success) { error.value = failed(response); return; }
    const result=response.data;
    ElMessage.success(`已生成 ${result.created} 条，更新 ${result.updated} 条；${result.skipped?.length||0} 个 SKU 因数据或授权待核对跳过。启用规则 ${result.rule_count} 条。`);
  } catch(e) {error.value=e?.message||'库存预警评估失败。';} finally {evaluating.value=false;}
}
const sourceTime = value => { if(!value)return '待核对'; const date=new Date(value); return Number.isNaN(date.getTime())?'待核对':new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(date); };
const display = value => value === null || value === undefined || value === '' ? '待核对' : value;
const salesFor = (row, days) => row.sales_windows?.find(item => Number(item.days) === Number(days));
const currencyAmounts = values => values && Object.keys(values).length ? Object.entries(values).map(([currency, amount]) => `${currency} ${amount}`).join('；') : '待核对';
const safeImage = value => typeof value === 'string' && /^\/api\/internal\/commerce\/[^?#]*\/image\/$/.test(value) ? value : '';
function businessToday() { const parts = new Intl.DateTimeFormat('en', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date()); return `${parts.find(x => x.type === 'year').value}-${parts.find(x => x.type === 'month').value}-${parts.find(x => x.type === 'day').value}`; }
function businessDateOffset(date, days) { const [y,m,d] = date.split('-').map(Number); const value = new Date(Date.UTC(y,m-1,d + days)); return `${value.getUTCFullYear()}-${String(value.getUTCMonth()+1).padStart(2,'0')}-${String(value.getUTCDate()).padStart(2,'0')}`; }
const failed = response => response?.data?.detail || response?.message || '请求失败，请检查网络后重试。';
async function load({ optionsOnly = false } = {}) {
  const seq = ++requestSequence; const expandedIds = new Set(expanded.value); loading.value = true; error.value = ''; rows.value=[]; total.value=0; selectedRows.value=[];
  try {
    const params = optionsOnly || !countryId.value ? { search: search.value.trim(), limit: 20, offset: 0, target_days: targetDays.value, window_days: windowDays.value } : { country_id: countryId.value, search: search.value.trim(), limit: 20, offset: (page.value - 1) * 20, target_days: targetDays.value, window_days: windowDays.value };
    const response = await api.fetchCountryInventoryDecisions(params);
    if (seq !== requestSequence) return;
    if (!response?.success) { error.value = failed(response); return; }
    const data = response.data || {}; countries.value = data.countries || [];
    if (!countryId.value) { rows.value = []; total.value = 0; }
    else { rows.value = data.results || []; total.value = Number(data.count || 0); await nextTick(); if(seq!==requestSequence)return; for (const row of rows.value) tableRef.value?.toggleRowExpansion?.(row, expandedIds.has(row.sku_id)); }
    permissions.value = data.permissions || { can_preview: false, can_create: false }; notice.value = data.notice || '';
    selectedRows.value = selectedRows.value.filter(old => rows.value.some(row => row.sku_id === old.sku_id));
  } catch (e) { if (seq === requestSequence) error.value = e?.message || '请求失败，请重试。'; }
  finally { if (seq === requestSequence) loading.value = false; }
}
function countryChanged() { page.value = 1; selectedRows.value = []; expanded.value.clear(); load(); }
function applyFilters() { page.value = 1; selectedRows.value = []; load(); }
function changePage(value) { page.value = value; selectedRows.value = []; load(); }
function selectionChanged(selection) { selectedRows.value = selection; }
function expandedChanged(row, rowsExpanded) { expanded.value = new Set(rowsExpanded.map(row => row.sku_id)); }
async function preview() {
  if (!canWrite.value || !permissions.value.can_preview || previewing.value || saving.value || evaluating.value || !countryId.value || !selectedRows.value.length) return;
  previewing.value = true; reviewError.value = '';
  const today = businessToday(), salesEnd = businessDateOffset(today, -1), salesStart = businessDateOffset(salesEnd, -(Number(windowDays.value) - 1));
  const payload = { country_id: countryId.value, sku_ids: selectedRows.value.map(row => row.sku_id), sales_start: salesStart, sales_end: salesEnd, target_stock_sales_ratio: Number((Number(targetDays.value) / Number(windowDays.value)).toFixed(4)), include_in_transit: true, sales_window_days: Number(windowDays.value), target_days: Number(targetDays.value) };
  const fingerprint = JSON.stringify(payload);
  if (!previewPending || previewPending.fingerprint !== fingerprint) previewPending = { fingerprint, key: api.createIdempotencyKey() };
  try {
    const response = await api.previewCountryOperatingOrder(payload, previewPending.key);
    if (!canWrite.value) return;
    if (!response?.success) { error.value = `${failed(response)}${!response?.http_status || response.http_status >= 500 ? ' 可用相同内容安全重试。' : ''}`; if (response?.http_status && response.http_status < 500) previewPending = null; return; }
    previewPending = null;
    previewData.value = response.data; reviewLines.value = (response.data?.lines || []).map(line => ({ ...line, quantity: Number.isInteger(line.suggested_quantity) && line.suggested_quantity > 0 ? line.suggested_quantity : null }));
    const previewIds = reviewLines.value.map(line => line.sku_id);
    const selectedIds = payload.sku_ids;
    if (!reviewLines.value.length || new Set(previewIds).size !== selectedIds.length || selectedIds.some(id => !previewIds.includes(id)) || reviewLines.value.some(line => !Number.isInteger(line.quantity) || line.quantity <= 0)) { reviewError.value = '预览建议不完整或数量无效；请返回核对库存和销量后再操作。'; error.value=reviewError.value; return; }
    reviewOpen.value = true;
  } catch (e) { error.value = e?.message || '预览失败，请重试。'; }
  finally { previewing.value = false; }
}
function closeReview(done) { if (saving.value) return; reviewOpen.value = false; previewData.value = null; reviewLines.value = []; if (typeof done === 'function') done(); }
async function createDraft() {
  if (!canWrite.value || !permissions.value.can_create || saving.value || !validReview.value || !previewData.value?.preview_token) return;
  saving.value = true; reviewError.value = '';
  const payload = { country_id: countryId.value, source_kind: sourceKind.value, order_date: businessToday(), notes: notes.value.trim(), lines: reviewLines.value.map(line => ({ sku_id: line.sku_id, quantity: Number(line.quantity) })), preview_token: previewData.value.preview_token, campaign: campaign.value.trim(), demand_start: demandStart.value || null, demand_end: demandEnd.value || null, plan_revision: planRevision.value.trim() };
  const fingerprint = JSON.stringify(payload);
  if (!createPending || createPending.fingerprint !== fingerprint) createPending = { fingerprint, key: api.createIdempotencyKey() };
  try {
    const response = await api.createCountryOperatingOrder(payload, createPending.key);
    if (!canWrite.value) { reviewError.value = '授权状态已变化，已停止创建。'; return; }
    if (!response?.success) { reviewError.value = `${failed(response)}${!response?.http_status || response.http_status >= 500 ? ' 可用相同内容安全重试。' : ''}`; if (response?.http_status && response.http_status < 500) createPending = null; return; }
    createPending = null; reviewOpen.value = false; ElMessage.success('运营订货草稿已创建。'); await router.push('/sales-management/operating-orders');
  } catch (e) { reviewError.value = `${e?.message || '网络异常'}，结果未确认，可用相同内容安全重试。`; }
  finally { saving.value = false; }
}
let createPending = null;
let previewPending = null;
onMounted(() => load({ optionsOnly: true }));
</script>

<style scoped>
.filters,.selection-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:12px 0 18px}.filters>.el-select{width:220px}.filters>.el-input{width:min(300px,100%)}.filters>span{color:#64748b}.table-scroll{width:100%;overflow-x:auto}.detail{padding:12px 22px;line-height:1.7}.detail h4{margin:14px 0 6px}.product,.detail-row,.stage-grid,.sales-grid{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.detail-row,.stage-grid span,.sales-grid>div{padding:7px 10px;background:#f8fafc;border-radius:6px}.sales-grid>div{display:flex;flex-direction:column;min-width:230px}.product>span{overflow-wrap:anywhere}.issue{color:#b42318}.pagination{margin-top:14px}.selection-actions{justify-content:flex-end}.form-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0 14px}.form-grid :deep(.el-select),.form-grid :deep(.el-date-editor),.form-grid :deep(.el-input){width:100%}.filters :deep(.el-input-number){width:140px}@media(max-width:700px){.filters>.el-select,.filters>.el-input{width:100%}.form-grid{grid-template-columns:1fr}}
</style>
