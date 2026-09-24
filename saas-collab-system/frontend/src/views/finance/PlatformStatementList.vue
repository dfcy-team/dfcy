<template>
  <section class="statement-page">
    <header class="page-header">
      <div>
        <h1>平台账单</h1>
        <p>查看平台账单汇总及只读同步采集的财务流水；金额保持来源币种，不跨币种合计。</p>
      </div>
      <el-tag :type="loadError ? 'danger' : loaded ? 'success' : 'info'">{{ loadError ? '加载失败' : loaded ? '已连接' : '加载中' }}</el-tag>
    </header>

    <el-tabs v-model="activeTab" @tab-change="loadActiveTab">
      <el-tab-pane label="Lazada 财务宽表" name="wide">
        <el-form class="filter-bar" inline @submit.prevent="searchWide">
          <el-form-item label="财务日期">
            <el-date-picker v-model="filters.period" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" clearable />
          </el-form-item>
          <el-form-item label="订单号"><el-input v-model.trim="filters.external_order_id" placeholder="平台订单号" clearable /></el-form-item>
          <el-form-item label="SKU"><el-input v-model.trim="filters.seller_sku" placeholder="Seller SKU" clearable /></el-form-item>
          <el-form-item label="币种"><el-input v-model.trim="filters.currency" placeholder="如 PHP" maxlength="8" clearable /></el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="loading" @click="searchWide">查询</el-button>
            <el-button @click="resetWide">重置</el-button>
          </el-form-item>
        </el-form>
        <el-alert v-if="loadError" :title="loadError" type="error" show-icon :closable="false" />
        <el-table v-loading="loading" :data="wideRows" border empty-text="暂无 Lazada 财务宽表数据">
          <el-table-column prop="transaction_date" label="财务日期" width="110" fixed />
          <el-table-column prop="site" label="站点" width="72" fixed />
          <el-table-column prop="store_name" label="店铺" min-width="150" fixed show-overflow-tooltip />
          <el-table-column prop="external_order_id" label="订单号" min-width="150" show-overflow-tooltip />
          <el-table-column prop="external_order_item_id" label="订单明细号" min-width="150" show-overflow-tooltip />
          <el-table-column prop="seller_sku" label="Seller SKU" min-width="140" show-overflow-tooltip />
          <el-table-column prop="lazada_sku" label="Lazada SKU" min-width="140" show-overflow-tooltip />
          <el-table-column prop="currency" label="币种" width="76" />
          <el-table-column v-for="column in wideAmountColumns" :key="column.prop" :prop="column.prop" :label="column.label" min-width="138" align="right">
            <template #default="{ row }"><span :class="amountClass(row[column.prop])">{{ formatAmount(row[column.prop]) }}</span></template>
          </el-table-column>
          <el-table-column prop="source_row_count" label="源流水数" width="95" align="right" />
          <el-table-column prop="allocation_methods" label="分摊方式" min-width="150">
            <template #default="{ row }">{{ allocationLabel(row.allocation_methods) }}</template>
          </el-table-column>
          <el-table-column prop="unknown_fee_names" label="未识别费用" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">{{ row.unknown_fee_names?.join('、') || '—' }}</template>
          </el-table-column>
        </el-table>
        <footer v-if="pagination.total" class="table-footer">
          <el-pagination v-model:current-page="pagination.page" v-model:page-size="pagination.page_size" :page-sizes="[20, 50, 100]" :total="pagination.total" layout="total, sizes, prev, pager, next" @current-change="loadWide" @size-change="changePageSize" />
        </footer>
      </el-tab-pane>

      <el-tab-pane label="财务流水" name="transactions">
        <el-form class="filter-bar" inline @submit.prevent="searchTransactions">
          <el-form-item label="业务日期">
            <el-date-picker v-model="filters.period" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" clearable />
          </el-form-item>
          <el-form-item label="平台">
            <el-select v-model="filters.platform" placeholder="全部" clearable>
              <el-option label="Lazada" value="lazada" />
              <el-option label="Shopee" value="shopee" />
              <el-option label="TikTok Shop" value="tiktok" />
            </el-select>
          </el-form-item>
          <el-form-item label="订单号"><el-input v-model.trim="filters.external_order_id" placeholder="平台订单号" clearable /></el-form-item>
          <el-form-item label="币种"><el-input v-model.trim="filters.currency" placeholder="如 MYR" maxlength="8" clearable /></el-form-item>
          <el-form-item label="费用分类">
            <el-select v-model="filters.fee_category" placeholder="全部" clearable>
              <el-option v-for="option in feeCategoryOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="匹配状态">
            <el-select v-model="filters.match_status" placeholder="全部" clearable>
              <el-option v-for="option in matchStatusOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="loading" @click="searchTransactions">查询</el-button>
            <el-button @click="resetTransactions">重置</el-button>
          </el-form-item>
        </el-form>

        <el-alert v-if="loadError" :title="loadError" type="error" show-icon :closable="false" />
        <el-table v-loading="loading" :data="transactions" border empty-text="暂无财务流水">
          <el-table-column prop="occurred_at_utc" label="发生时间（UTC）" min-width="168" :formatter="formatDateTime" />
          <el-table-column prop="platform" label="平台" min-width="90" :formatter="formatPlatform" />
          <el-table-column prop="store_name" label="店铺" min-width="150" show-overflow-tooltip />
          <el-table-column prop="external_order_id" label="平台订单号" min-width="150" show-overflow-tooltip />
          <el-table-column prop="seller_sku" label="SKU" min-width="130" show-overflow-tooltip />
          <el-table-column prop="raw_fee_name" label="费用名称" min-width="150" show-overflow-tooltip />
          <el-table-column prop="fee_category" label="费用分类" min-width="110" :formatter="formatFeeCategory" />
          <el-table-column prop="signed_amount" label="金额" min-width="120" align="right">
            <template #default="{ row }"><span :class="amountClass(row.signed_amount)">{{ formatAmount(row.signed_amount) }}</span></template>
          </el-table-column>
          <el-table-column prop="currency" label="币种" min-width="80" />
          <el-table-column prop="match_status" label="订单匹配" min-width="110">
            <template #default="{ row }"><el-tag :type="matchTagType(row.match_status)" effect="plain">{{ matchStatusLabel(row.match_status) }}</el-tag></template>
          </el-table-column>
        </el-table>
        <footer v-if="pagination.total" class="table-footer">
          <el-pagination v-model:current-page="pagination.page" v-model:page-size="pagination.page_size" :page-sizes="[20, 50, 100]" :total="pagination.total" layout="total, sizes, prev, pager, next" @current-change="loadTransactions" @size-change="changePageSize" />
        </footer>
      </el-tab-pane>

      <el-tab-pane label="账单汇总" name="statements">
        <el-alert v-if="loadError" :title="loadError" type="error" show-icon :closable="false" />
        <el-table v-loading="loading" :data="statements" border empty-text="暂无平台账单汇总">
          <el-table-column prop="platform" label="平台" min-width="100" :formatter="formatPlatform" />
          <el-table-column prop="statement_no" label="账单号" min-width="160" />
          <el-table-column prop="period_start" label="开始日期" min-width="110" />
          <el-table-column prop="period_end" label="结束日期" min-width="110" />
          <el-table-column prop="currency" label="币种" min-width="80" />
          <el-table-column prop="gross_amount" label="总额" min-width="110" align="right" />
          <el-table-column prop="fee_amount" label="费用" min-width="110" align="right" />
          <el-table-column prop="net_amount" label="净额" min-width="110" align="right" />
          <el-table-column prop="status" label="状态" min-width="100" />
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { fetchFinanceTransactions, fetchLazadaFinanceWide, fetchPlatformStatements } from '../../api/financeReconciliation';

const activeTab = ref('transactions');
const loading = ref(false);
const loaded = ref(false);
const loadError = ref('');
const transactions = ref([]);
const wideRows = ref([]);
const statements = ref([]);
const pagination = reactive({ page: 1, page_size: 50, total: 0 });
const filters = reactive({ period: [], platform: '', external_order_id: '', seller_sku: '', currency: '', fee_category: '', match_status: '' });
const wideAmountColumns = [
  ['sales_amount', '销售收入'], ['refund_amount', '退款金额'], ['commission', '佣金'], ['payment_fee', '支付手续费'],
  ['payment_fee_credit', '支付手续费返还'], ['reversal_commission', '佣金冲销'], ['free_shipping_max_fee', '包邮费用'],
  ['reversal_free_shipping_max_fee', '包邮费用冲销'], ['shipping_fee_refund_to_customer', '退买家运费'],
  ['shipping_fee_voucher_refund_to_laz', '运费券退平台'], ['sponsored_affiliates', '联盟推广费'],
  ['promotional_charges_vouchers', '优惠券推广费'], ['reversal_promotional_charges_vouchers', '优惠券推广费冲销'],
  ['promotional_charges_flexi_combo', '组合促销费'], ['reversal_promotional_charges_flexi_combo', '组合促销费冲销'],
  ['lazcoins_discount', 'LazCoins 折扣'], ['reversal_lazcoins_discount', 'LazCoins 折扣冲销'],
  ['lazcoins_discount_promotion_fee', 'LazCoins 推广费'], ['reversal_lazcoins_discount_promotion_fee', 'LazCoins 推广费冲销'],
  ['order_processing_fee', '订单处理费'], ['reversal_order_processing_fee', '订单处理费冲销'],
  ['spa_program_fee', 'SPA 计划费'], ['reversal_spa_program_fee', 'SPA 计划费冲销'],
  ['wrong_shipping_fee_adjustment', '运费调整'], ['withholding_tax', '预扣税'], ['other_fee', '其他费用'],
  ['platform_fee_total', '平台费用合计'], ['net_income', '净收入']
].map(([prop, label]) => ({ prop, label }));
const feeCategoryOptions = [
  ['income', '收入'], ['platform_fee', '平台费用'], ['logistics_fee', '物流费用'], ['discount', '优惠'],
  ['refund', '退款'], ['tax', '税费'], ['adjustment', '调整'], ['other', '其他']
].map(([value, label]) => ({ value, label }));
const matchStatusOptions = [
  ['matched', '已匹配订单行'], ['order_only', '仅匹配订单'], ['unmatched', '未匹配'], ['conflict', '匹配冲突']
].map(([value, label]) => ({ value, label }));

const feeCategoryLabel = (value) => feeCategoryOptions.find((item) => item.value === value)?.label || value || '—';
const matchStatusLabel = (value) => matchStatusOptions.find((item) => item.value === value)?.label || value || '—';
const formatFeeCategory = (_row, _column, value) => feeCategoryLabel(value);
const formatPlatform = (_row, _column, value) => ({ lazada: 'Lazada', shopee: 'Shopee', tiktok: 'TikTok Shop' }[value] || value || '—');
const formatDateTime = (_row, _column, value) => value ? value.replace('T', ' ').replace(/(\.\d+)?Z$/, '') : '—';
const formatAmount = (value) => Number.isFinite(Number(value)) ? Number(value).toFixed(4) : '—';
const amountClass = (value) => Number(value) < 0 ? 'amount-negative' : 'amount-positive';
const matchTagType = (value) => ({ matched: 'success', order_only: 'warning', unmatched: 'info', conflict: 'danger' }[value] || 'info');
const allocationLabel = (methods) => (methods || []).map((value) => ({
  direct: '直接归属', order_sales_ratio: '订单销售额分摊', shop_day_sales_ratio: '店铺日销售额分摊', unallocated: '未分摊'
}[value] || value)).join('、') || '—';

function wideParams() {
  return {
    page: pagination.page, page_size: pagination.page_size,
    period_start: filters.period?.[0] || undefined, period_end: filters.period?.[1] || undefined,
    external_order_id: filters.external_order_id || undefined,
    seller_sku: filters.seller_sku || undefined,
    currency: filters.currency?.toUpperCase() || undefined
  };
}

async function loadWide() {
  loading.value = true;
  loaded.value = false;
  loadError.value = '';
  try {
    const response = await fetchLazadaFinanceWide(wideParams());
    if (!response.success) throw new Error(response.message || 'Lazada 财务宽表加载失败');
    wideRows.value = response.data?.items || [];
    Object.assign(pagination, response.data?.pagination || { page: 1, page_size: 50, total: 0 });
    loaded.value = true;
  } catch (error) {
    wideRows.value = [];
    loadError.value = error?.message || 'Lazada 财务宽表加载失败';
  } finally { loading.value = false; }
}

function transactionParams() {
  return {
    page: pagination.page, page_size: pagination.page_size,
    platform: filters.platform || undefined,
    period_start: filters.period?.[0] || undefined, period_end: filters.period?.[1] || undefined,
    external_order_id: filters.external_order_id || undefined,
    currency: filters.currency?.toUpperCase() || undefined,
    fee_category: filters.fee_category || undefined, match_status: filters.match_status || undefined
  };
}

async function loadTransactions() {
  loading.value = true;
  loaded.value = false;
  loadError.value = '';
  try {
    const response = await fetchFinanceTransactions(transactionParams());
    if (!response.success) throw new Error(response.message || '财务流水加载失败');
    transactions.value = response.data?.items || [];
    Object.assign(pagination, response.data?.pagination || { page: 1, page_size: 50, total: 0 });
    loaded.value = true;
  } catch (error) {
    transactions.value = [];
    loadError.value = error?.message || '财务流水加载失败';
  } finally { loading.value = false; }
}

async function loadStatements() {
  loading.value = true;
  loaded.value = false;
  loadError.value = '';
  try {
    const response = await fetchPlatformStatements();
    if (!response.success) throw new Error(response.message || '平台账单加载失败');
    statements.value = Array.isArray(response.data) ? response.data : (response.data?.items || []);
    loaded.value = true;
  } catch (error) {
    statements.value = [];
    loadError.value = error?.message || '平台账单加载失败';
  } finally { loading.value = false; }
}

function searchTransactions() { pagination.page = 1; loadTransactions(); }
function searchWide() { pagination.page = 1; loadWide(); }
function resetWide() {
  Object.assign(filters, { period: [], external_order_id: '', seller_sku: '', currency: '' });
  searchWide();
}
function resetTransactions() {
  Object.assign(filters, { period: [], platform: '', external_order_id: '', currency: '', fee_category: '', match_status: '' });
  searchTransactions();
}
function changePageSize() {
  pagination.page = 1;
  if (activeTab.value === 'wide') loadWide(); else loadTransactions();
}
function loadActiveTab(name) {
  pagination.page = 1;
  if (name === 'wide') loadWide(); else if (name === 'transactions') loadTransactions(); else loadStatements();
}
onMounted(loadTransactions);
</script>

<style scoped>
.statement-page { display: grid; gap: 16px; }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.page-header h1 { margin: 0; color: #172033; font-size: 24px; line-height: 1.35; }
.page-header p { margin: 6px 0 0; color: #526176; font-size: 13px; line-height: 1.6; }
.filter-bar { padding: 12px 12px 0; border: 1px solid #d9e2ec; border-radius: 8px; background: #fff; }
.filter-bar :deep(.el-input) { width: 160px; }
.filter-bar :deep(.el-select) { width: 150px; }
.filter-bar :deep(.el-date-editor) { width: 250px; }
.amount-positive { color: #176b3a; font-variant-numeric: tabular-nums; }
.amount-negative { color: #b42318; font-variant-numeric: tabular-nums; }
.table-footer { display: flex; justify-content: flex-end; padding-top: 16px; }
@media (max-width: 900px) {
  .page-header { align-items: stretch; flex-direction: column; }
  .filter-bar :deep(.el-form-item) { display: flex; margin-right: 0; }
  .filter-bar :deep(.el-input), .filter-bar :deep(.el-select), .filter-bar :deep(.el-date-editor) { width: min(100%, 320px); }
}
</style>
