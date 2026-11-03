<template>
  <section class="ledger-page" aria-label="财务流水">
    <el-form class="ledger-filters" @submit.prevent="search">
      <el-form-item label="财务日期">
        <el-date-picker v-model="filters.period" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" range-separator="至" clearable />
      </el-form-item>
      <el-form-item label="国家"><el-select v-model="filters.country" clearable placeholder="全部国家"><el-option v-for="(name, code) in countries" :key="code" :label="name" :value="code" /></el-select></el-form-item>
      <el-form-item label="平台"><el-select v-model="filters.platform" clearable placeholder="全部平台"><el-option label="Shopee" value="shopee" /><el-option label="Lazada" value="lazada" /><el-option label="TikTok Shop" value="tiktok" /></el-select></el-form-item>
      <el-form-item label="店铺"><el-select v-model="filters.store_id" filterable clearable placeholder="全部店铺"><el-option v-for="[id, code] in data.stores || []" :key="id" :value="id" :label="code" /></el-select></el-form-item>
      <el-form-item label="订单号"><el-input v-model.trim="filters.external_order_id" placeholder="完整订单号，多个用逗号分隔" clearable /></el-form-item>
      <el-form-item label="流水类型"><el-select v-model="filters.kind" clearable placeholder="全部类型"><el-option v-for="(name, kind) in kinds" :key="kind" :label="name" :value="kind" /></el-select></el-form-item>
      <el-form-item label="币种"><el-input v-model.trim="filters.currency" placeholder="全部币种，分别汇总" maxlength="3" clearable /></el-form-item>
      <el-form-item label="核对状态"><el-select v-model="filters.status" clearable placeholder="全部状态"><el-option v-for="(name, code) in statuses" :key="code" :label="name" :value="code" /></el-select></el-form-item>
      <div class="filter-actions"><el-button type="primary" native-type="submit" :loading="loading">查询</el-button><el-button @click="reset">重置</el-button></div>
      <div class="quick-dates"><el-button link @click="quickDate('month')">本月</el-button><el-button link @click="quickDate('last')">上月</el-button><el-button link @click="quickDate('recent')">最近30天</el-button><el-button link @click="quickDate('all')">全部历史</el-button></div>
      <details class="more-filters"><summary>更多条件：来源、仓库</summary><div class="more-fields">
        <el-form-item label="来源"><el-select v-model="filters.source" clearable placeholder="全部来源"><el-option v-for="name in sources" :key="name" :label="name" :value="name" /></el-select></el-form-item>
        <el-form-item label="仓库 ID"><el-input v-model.trim="filters.warehouse_id" placeholder="系统仓库 ID" clearable /></el-form-item>
      </div></details>
    </el-form>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <p class="ledger-caption">直接归属与销售额分摊合并展示，点击金额查看构成。不跨币种合计；“—”表示没有对应来源数据，不代表零费用。</p>
    <div v-if="!error" class="ledger-totals" aria-live="polite">
      <div v-for="total in data.totals || []" :key="total.currency" class="currency-total">
        <strong>{{ total.currency }}</strong>
        <span>已确认收入 <b class="positive">{{ money(total.income) }}</b></span>
        <span>已确认支出 <b class="negative">{{ money(total.expense) }}</b></span>
        <span>收支差额 <b>{{ money(total.balance) }}</b></span>
        <span class="muted">待核对 {{ total.pending_count }} 笔</span>
      </div>
      <p v-if="!loading && !data.totals?.length" class="muted">当前筛选暂无流水。可切换“全部历史”查询已登记的历史费用。</p>
    </div>
    <details v-if="data.notices?.length" class="ledger-notices">
      <summary>数据口径与缺口（{{ data.notices.length }} 项）</summary>
      <ul><li v-for="notice in data.notices" :key="notice">{{ notice }}</li></ul>
      <p>当前来源笔数：<span v-for="(name, kind) in kinds" :key="kind">{{ name }} {{ data.coverage?.[kind] || 0 }}；</span>笔数仅代表当前已连接来源，不代表采集完整。</p>
    </details>

    <div class="ledger-toolbar">
      <el-radio-group v-model="view" aria-label="查看维度" @change="search"><el-radio-button v-for="(name, key) in views" :key="key" :value="key">{{ name }}</el-radio-button></el-radio-group>
      <span class="muted">{{ loading ? '正在查询本地流水…' : `${pagination.total} ${view === 'detail' ? '笔' : '组'} · ${data.source_count || 0} 个来源` }}</span>
      <el-button v-if="data.can_export" :disabled="loading || !!error || !data.items?.length" @click="exportPage">导出当前页</el-button>
    </div>
    <p class="ledger-caption">{{ view === 'detail' ? '明细保留原始归属；在国家、店铺、订单汇总中查看直接归属与分摊结果。' : '仅已确认金额计入收支差额；待核对和参考项不计入。国家汇总向上直接归集，不作分摊。' }}</p>
    <p v-if="data.hidden_reference_refund_count" class="ledger-caption">已隐藏 {{ data.hidden_reference_refund_count }} 笔参考退款，不影响金额合计；仍可在汇总金额详情或平台原始流水核对。</p>
    <el-table v-if="view === 'detail'" v-loading="loading" :data="data.items || []" border empty-text="暂无财务流水">
      <el-table-column prop="date" label="财务日期" width="115" />
      <el-table-column label="国家" width="90"><template #default="{ row }">{{ countries[row.country] || row.country }}</template></el-table-column>
      <el-table-column prop="store_code" label="店铺" width="120"><template #default="{ row }">{{ row.store_code || '国家费用' }}</template></el-table-column>
      <el-table-column prop="external_order_id" label="订单号" min-width="175" show-overflow-tooltip />
      <el-table-column label="类型" width="140"><template #default="{ row }">{{ kinds[row.kind] }}</template></el-table-column>
      <el-table-column label="金额" min-width="150" align="right"><template #default="{ row }"><button class="money-button" :class="amountClass(row.amount)" @click="openFact(row)">{{ money(row.amount) }}</button></template></el-table-column>
      <el-table-column prop="currency" label="币种" width="80" />
      <el-table-column label="状态" width="100"><template #default="{ row }">{{ statuses[row.status] }}</template></el-table-column>
      <el-table-column prop="source" label="来源" width="125" />
      <el-table-column prop="description" label="说明／原账单" min-width="230" show-overflow-tooltip />
    </el-table>
    <el-table v-else v-loading="loading" :data="data.items || []" border empty-text="暂无可汇总流水">
      <el-table-column label="国家" width="90" fixed><template #default="{ row }">{{ countries[row.country] || row.country }}</template></el-table-column>
      <el-table-column v-if="view !== 'country'" prop="store_code" label="店铺" width="115" fixed />
      <el-table-column v-if="view === 'order'" prop="external_order_id" label="订单号" min-width="175" fixed show-overflow-tooltip />
      <el-table-column prop="currency" label="币种" width="75" />
      <el-table-column v-for="(name, kind) in kinds" :key="kind" :label="name" min-width="146" align="right">
        <template #default="{ row }">
          <button v-if="row.cells[kind]" class="money-button" :class="amountClass(row.cells[kind].amount)" @click="openComposition(row, kind)">
            {{ cellAmount(row.cells[kind]) }}<span v-if="row.cells[kind].allocated" class="amount-hint" aria-label="含销售额分摊"> ⓘ</span>
          </button><span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="收支差额" min-width="155" align="right"><template #default="{ row }"><button class="money-button" :class="amountClass(row.balance)" @click="openComposition(row)">{{ money(row.balance) }}</button></template></el-table-column>
      <el-table-column prop="pending_count" label="待核对" width="80" />
    </el-table>
    <footer class="ledger-pagination"><el-pagination v-model:current-page="pagination.page" v-model:page-size="pagination.page_size" :page-sizes="[20, 50, 100]" :total="pagination.total" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="search" /></footer>

    <details v-if="data.unallocated_count" class="unallocated-panel" open>
      <summary>{{ data.unallocated_count }} 笔费用未分摊，保留原归属（不计入当前下级汇总）</summary>
      <el-table :data="data.unallocated || []" size="small" max-height="260"><el-table-column prop="country" label="国家" width="85" /><el-table-column prop="description" label="来源" min-width="230" show-overflow-tooltip /><el-table-column prop="amount" label="原金额" width="150" align="right" /><el-table-column prop="currency" label="币种" width="80" /><el-table-column prop="reason" label="原因" min-width="230" /></el-table>
      <p v-if="data.unallocated_count > 100" class="muted">显示前100笔，请缩小范围或切换流水明细查看原始费用。</p>
    </details>

    <el-drawer v-model="drawer.open" title="金额构成与来源" size="min(650px, 100%)" @closed="closeDrawer">
      <el-alert v-if="drawer.error" :title="drawer.error" type="error" :closable="false" />
      <div v-loading="drawer.loading" class="composition-list">
        <article v-for="entry in drawer.items" :key="entry.source_id + entry.external_order_id" class="composition-entry">
          <div class="composition-heading"><strong>{{ kinds[entry.kind] }}</strong><b :class="amountClass(entry.amount)">{{ money(entry.amount) }} {{ entry.currency }}</b></div>
          <p>{{ entry.date }} · {{ entry.store_code || entry.country }} · {{ entry.external_order_id || '无订单归属' }} · {{ statuses[entry.status] }}</p>
          <p>{{ entry.description }}</p><small>{{ entry.source }} · {{ entry.source_id }}</small>
          <dl v-if="entry.allocation" class="allocation-detail">
            <dt>原始费用</dt><dd>{{ money(entry.allocation.source_amount) }} {{ entry.currency }}</dd>
            <template v-if="entry.allocation.source_scope === 'country'"><dt>店铺销售额／国家销售额</dt><dd>{{ money(entry.allocation.store_sales) }} ／ {{ money(entry.allocation.country_sales) }} {{ entry.allocation.basis_currency }}</dd></template>
            <template v-else><dt>店铺销售额</dt><dd>{{ money(entry.allocation.store_sales) }} {{ entry.allocation.basis_currency }}</dd></template>
            <template v-if="entry.allocation.order_sales"><dt>订单销售额／店铺销售额</dt><dd>{{ money(entry.allocation.order_sales) }} ／ {{ money(entry.allocation.store_sales) }} {{ entry.allocation.basis_currency }}</dd></template>
            <dt>口径</dt><dd>{{ entry.allocation.basis }}；{{ entry.allocation.precision }}</dd>
          </dl>
          <ul v-if="entry.parts?.length"><li v-for="part in entry.parts" :key="part.name">{{ part.name }}：{{ money(part.amount) }} {{ entry.currency }}<span v-if="part.count">（{{ part.count }} 条）</span></li></ul>
          <el-button v-if="entry.source === '平台结算'" link type="primary" @click="showRaw(entry)">查看平台原始流水</el-button>
        </article>
      </div>
      <el-pagination v-if="drawer.total > 20" v-model:current-page="drawer.page" :page-size="20" :total="drawer.total" layout="total, prev, pager, next" @current-change="loadComposition" />
    </el-drawer>
  </section>
</template>

<script setup>
import { reactive, ref, onMounted, onBeforeUnmount } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { fetchFinanceLedger } from '../../api/financeReconciliation';
import { recentFinancePeriod } from './financePresentation';
import { ledgerMoney as money, ledgerCsv } from './ledgerPresentation';

const route = useRoute();
const router = useRouter();
const countries = { PH: '菲律宾', TH: '泰国', MY: '马来西亚', SG: '新加坡', ID: '印度尼西亚', VN: '越南', BR: '巴西', TW: '中国台湾' };
const kinds = { receipt:'订单回款', refund:'订单退款', advertising:'广告花费', product_cost:'商品成本', gcash:'GCash退款', promotion:'刷单费用', warehouse_order:'仓库处理费', warehouse_other:'仓库其他处理费' };
const statuses = { confirmed:'已确认', pending:'待核对', reference:'参考，不重复计入' };
const views = { detail:'流水明细', country:'国家汇总', store:'店铺汇总', order:'订单汇总' };
const sources = ['平台结算', '广告账单', 'GCash登记', '订单推广登记', '仓库账单'];
const filters = reactive({ period:recentFinancePeriod(), country:'', platform:'', store_id:'', external_order_id:'', kind:'', currency:'', status:'', source:'', warehouse_id:'' });
const pagination = reactive({ page:1, page_size:20, total:0 });
const data = ref({});
const view = ref('detail');
const loading = ref(false);
const error = ref('');
const drawer = reactive({ open:false, items:[], error:'', loading:false, query:{}, page:1, total:0 });
let sequence = 0;
let drawerSequence = 0;
let appliedQuery = {};

function params() {
  const query = { view:view.value, all_history:!filters.period?.length, period_start:filters.period?.[0], period_end:filters.period?.[1] };
  for (const key of ['country','platform','store_id','external_order_id','kind','status','source','warehouse_id']) if (filters[key]) query[key] = filters[key];
  if (filters.currency) query.currency = filters.currency.toUpperCase();
  return query;
}
async function load() {
  const current = ++sequence;
  loading.value = true; error.value = ''; data.value = {}; pagination.total = 0;
  closeDrawer(); drawer.open = false;
  const query = params();
  try {
    const result = await fetchFinanceLedger({ ...query, page:pagination.page, page_size:pagination.page_size });
    if (current !== sequence) return;
    if (!result.success || !Array.isArray(result.data?.items)) throw new Error(result.message || '财务流水返回格式异常');
    data.value = result.data;
    pagination.total = result.data.pagination.total;
    appliedQuery = query;
  } catch (reason) {
    if (current === sequence) error.value = reason?.message || '财务流水加载失败，请重试';
  } finally { if (current === sequence) loading.value = false; }
}
function search() { pagination.page = 1; load(); }
function reset() { Object.assign(filters, { period:recentFinancePeriod(), country:'', platform:'', store_id:'', external_order_id:'', kind:'', currency:'', status:'', source:'', warehouse_id:'' }); search(); }
function quickDate(mode) {
  const today = new Date();
  const localDate = date => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
  filters.period = mode === 'all' ? [] : mode === 'recent' ? recentFinancePeriod() : mode === 'month'
    ? [localDate(new Date(today.getFullYear(),today.getMonth(),1)),localDate(today)]
    : [localDate(new Date(today.getFullYear(),today.getMonth()-1,1)),localDate(new Date(today.getFullYear(),today.getMonth(),0))];
  search();
}
function amountClass(value) { return value == null ? 'muted' : String(value).startsWith('-') ? 'negative' : 'positive'; }
function cellAmount(cell) { return cell.amount != null ? money(cell.amount) : cell.reference_amount != null ? `${money(cell.reference_amount)}（参考）` : `待核对 ${cell.pending_count} 笔`; }
function openFact(entry) { closeDrawer(); Object.assign(drawer, { open:true, items:[entry], total:1, page:1 }); }
function openComposition(row, kind) {
  Object.assign(drawer, { open:true, page:1, items:[], error:'', query:{ ...appliedQuery, country:row.country, currency:row.currency,
    store_id:row.store_id || undefined, external_order_id:row.external_order_id || undefined, kind:kind || appliedQuery.kind, breakdown:true } });
  loadComposition();
}
async function loadComposition() {
  const current = ++drawerSequence;
  drawer.items = []; drawer.error = ''; drawer.loading = true;
  try {
    const response = await fetchFinanceLedger({ ...drawer.query, page:drawer.page, page_size:20 });
    if (current !== drawerSequence) return;
    if (!response.success) throw new Error(response.message || '构成加载失败');
    drawer.items = response.data.items; drawer.total = response.data.pagination.total;
  } catch (reason) { if (current === drawerSequence) drawer.error = reason?.message || '构成加载失败'; }
  finally { if (current === drawerSequence) drawer.loading = false; }
}
function closeDrawer() { drawerSequence++; drawer.items = []; drawer.error = ''; drawer.loading = false; drawer.total = 0; }
function showRaw(entry) { router.push({ path:'/finance/statements', query:{ tab:'raw', all_history:'1', store_id:entry.store_id, external_order_id:entry.external_order_id || undefined, currency:entry.currency, period_start:entry.date, period_end:entry.date } }); }
function exportPage() {
  const content = ledgerCsv(data.value.items, view.value, kinds);
  const url = URL.createObjectURL(new Blob(['\ufeff',content], { type:'text/csv;charset=utf-8;' }));
  const anchor = document.createElement('a'); anchor.href=url; anchor.download=`财务流水_${view.value}_${pagination.page}.csv`; anchor.click(); URL.revokeObjectURL(url);
}
onMounted(() => {
  const query = route.query || {};
  if (query.period_start && query.period_end) filters.period = [String(query.period_start),String(query.period_end)];
  else if (query.all_history === '1') filters.period = [];
  for (const key of ['country','platform','external_order_id','currency']) if (query[key]) filters[key] = String(query[key]);
  if (query.store_id) filters.store_id = Number(query.store_id);
  search();
});
onBeforeUnmount(() => { sequence++; drawerSequence++; });
</script>

<style scoped>
.ledger-page { display:grid; gap:14px; min-width:0; }
.ledger-filters { display:grid; grid-template-columns:repeat(5,minmax(140px,1fr)); gap:0 16px; padding:18px 18px 10px; background:#fff; border:1px solid #d9e2ec; border-radius:8px; }
.ledger-filters :deep(.el-form-item) { display:flex; flex-direction:column; align-items:stretch; margin-bottom:12px; }
.ledger-filters :deep(.el-form-item__label) { justify-content:flex-start; height:27px; line-height:27px; font-size:12px; }
.ledger-filters :deep(.el-date-editor), .ledger-filters :deep(.el-select) { width:100%; }
.ledger-filters :deep(.el-form-item:first-child) { grid-column:span 2; }
.filter-actions { display:flex; align-items:flex-end; padding-bottom:12px; gap:4px; }
.quick-dates, .more-filters { grid-column:1/-1; }
.more-filters { font-size:12px; color:#526176; border-top:1px solid #e5eaf0; padding-top:10px; margin-top:5px; }
summary { cursor:pointer; line-height:1.8; }
.more-fields { display:flex; gap:18px; padding-top:10px; }
.ledger-caption, .ledger-notices, .unallocated-panel { margin:0; font-size:12px; color:#526176; line-height:1.8; }
.ledger-notices, .unallocated-panel { border:1px solid #d9e2ec; border-radius:6px; padding:10px 14px; background:#fff; }
.ledger-notices p { margin:8px 0 0; }
.ledger-notices ul { padding-left:18px; margin:8px 0; }
.ledger-totals { background:#fff; border-block:1px solid #d9e2ec; }
.currency-total { display:flex; flex-wrap:wrap; gap:16px 30px; padding:16px; border-bottom:1px solid #edf0f5; align-items:baseline; font-size:13px; }
.currency-total b { font-variant-numeric:tabular-nums; margin-left:7px; font-size:18px; font-weight:600; }
.currency-total > strong { min-width:46px; }
.ledger-toolbar { display:flex; flex-wrap:wrap; justify-content:space-between; gap:12px; align-items:center; }
.money-button { font:inherit; font-variant-numeric:tabular-nums; border:0; background:none; padding:4px 0; cursor:pointer; text-align:right; }
.money-button:hover { text-decoration:underline; }
.money-button:focus-visible, summary:focus-visible { outline:2px solid #245be5; outline-offset:3px; }
.amount-hint { color:#68788a; font-size:11px; }
.positive { color:#176b3a; }.negative { color:#b42318; }.muted { color:#65748a; font-size:12px; }
.ledger-pagination { display:flex; justify-content:flex-end; overflow:auto; }
.composition-list { display:grid; gap:18px; }
.composition-entry { border-bottom:1px solid #d9e2ec; padding-bottom:18px; font-size:13px; line-height:1.7; overflow-wrap:anywhere; }
.composition-heading { display:flex; justify-content:space-between; gap:12px; }
.composition-entry p { margin:8px 0; color:#526176; }.composition-entry small { color:#68788a; }
.allocation-detail { display:grid; grid-template-columns:145px minmax(0,1fr); gap:7px 10px; background:#f5f7fa; padding:12px; font-size:12px; }
.allocation-detail dt { color:#526176; }.allocation-detail dd { margin:0; }
@media(max-width:900px) { .ledger-filters { grid-template-columns:repeat(2,minmax(0,1fr)); padding:12px; gap:0 12px; }.currency-total { gap:12px; }.currency-total b { font-size:16px; } }
@media(max-width:520px) { .ledger-filters { grid-template-columns:minmax(0,1fr); }.ledger-filters :deep(.el-form-item:first-child) { grid-column:auto; }.ledger-toolbar { align-items:stretch; }.allocation-detail { grid-template-columns:1fr; }.currency-total { flex-direction:column; }.more-fields { flex-direction:column; } }
</style>
