<template>
  <section class="aftersales" :aria-busy="loading">
    <header class="page-header">
      <div><h1>订单售后</h1><p>统一核对退款退货、取消订单和仓库回仓。平台处理状态与实际入库状态分别展示。</p></div>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </header>
    <el-alert title="仅更新本地售后跟踪，不发起退款、不创建仓库退货单、不直接调整库存。" type="info" :closable="false" show-icon />
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon role="alert" />
    <el-alert v-if="feedback" :title="feedback" type="success" :closable="false" show-icon role="status" />
    <p v-if="optionsError" class="warning" role="status">{{ optionsError }} <el-button link @click="loadOptions">重试选项</el-button></p>
    <details v-if="canManage" class="sync-settings">
      <summary>仓库退货接口与同步配置 · {{ settings.warehouse_bound ? '已绑定仓库' : '尚未绑定仓库，不执行同步' }}</summary>
      <p>默认每小时查询已知回仓单，周期可调整。极风支持运单号，百世须先核对仓库退货单号；未配置单号的记录不发起查询。未启用历史补采。</p>
      <el-alert v-if="settingsError" :title="settingsError" type="warning" :closable="false" />
      <el-form v-if="fullAccess" inline label-position="top" @submit.prevent="saveSettings">
        <el-form-item label="同步周期（分钟）"><el-input-number v-model="settings.interval_minutes" :min="5" :max="10080" :disabled="busy" aria-label="同步周期（分钟）" /></el-form-item>
        <el-form-item label="定时同步"><el-switch v-model="settings.is_enabled" :disabled="busy || !settings.warehouse_bound" active-text="开启" inactive-text="关闭" /></el-form-item>
        <el-form-item><el-button native-type="submit" type="primary" :loading="busy">保存周期</el-button></el-form-item>
        <el-form-item><el-button :disabled="busy || !settings.warehouse_bound" @click="manualSync">手动同步</el-button></el-form-item>
      </el-form>
      <p v-if="fullAccess" class="secondary">上次执行：{{ time(settings.last_run_at) }} · 下次计划：{{ time(settings.next_run_at) }}<span v-if="settings.last_error_code"> · {{ syncError(settings.last_error_code) }}</span></p>
    </details>
    <el-tabs v-if="fullAccess" :model-value="tab" aria-label="订单售后分区" @tab-change="changeTab">
      <el-tab-pane label="订单售后" name="cases" />
      <el-tab-pane label="待匹配回仓" name="receipts" />
    </el-tabs>
    <template v-if="tab === 'cases'">
      <el-form class="filters" :model="query" label-position="top" @submit.prevent="search">
        <el-form-item label="平台订单号／售后单号"><el-input v-model="query.external_order_id" clearable placeholder="输入单号" /></el-form-item>
        <el-form-item label="来源"><el-select v-model="query.source_type" clearable placeholder="全部来源"><el-option label="退款退货" value="refund_return" /><el-option label="取消订单" value="cancelled" /><el-option label="仓库退回" value="warehouse_return" /></el-select></el-form-item>
        <el-form-item label="回仓状态"><el-select v-model="query.return_status" clearable placeholder="全部状态"><el-option v-for="(label, key) in states" :key="key" :label="label" :value="key" /></el-select></el-form-item>
        <el-form-item label="平台"><el-select v-model="query.platform" clearable placeholder="全部平台"><el-option v-for="item in platforms" :key="item" :label="item" :value="item" /></el-select></el-form-item>
        <el-form-item label="店铺"><el-select v-model="query.store_id" filterable clearable placeholder="全部可见店铺"><el-option v-for="item in stores" :key="item.id" :label="`${item.code} · ${item.name}`" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="币种"><el-select v-model="query.currency" clearable placeholder="全部币种"><el-option v-for="item in currencies" :key="item" :label="item" :value="item" /></el-select></el-form-item>
        <el-form-item label="Seller／内部 SKU"><el-input v-model="query.sku" clearable placeholder="输入 SKU" /></el-form-item>
        <el-form-item label="平台处理状态"><el-input v-model="query.platform_status" clearable placeholder="输入平台归一化状态" /></el-form-item>
        <el-form-item label="售后类型"><el-input v-model="query.case_type" clearable placeholder="输入售后类型" /></el-form-item>
        <el-form-item label="申请／取消日期"><el-date-picker v-model="dates" type="daterange" start-placeholder="开始日期" end-placeholder="结束日期" range-separator="至" value-format="YYYY-MM-DD" /></el-form-item>
        <div class="filter-actions"><el-button type="primary" native-type="submit" :loading="loading">查询</el-button><el-button @click="reset">重置</el-button></div>
      </el-form>
      <p class="secondary">当前租户及授权店铺范围。无需回仓的订单不计时；待入库起满两个自然月仍有未收商品，标记到仓超时待核对，不代表仓库确认未收到。缺少发货或应退证据时显示待确认。</p>
      <el-table v-loading="loading" :data="rows" row-key="source_key" aria-label="订单售后列表">
        <el-table-column prop="external_order_id" label="平台订单号" min-width="190" />
        <el-table-column label="来源／售后单号" min-width="190"><template #default="{ row }">{{ sourceLabel(row.source_type) }}<small>{{ row.external_return_id || '—' }}</small></template></el-table-column>
        <el-table-column label="店铺／站点" min-width="200"><template #default="{ row }">{{ row.store.code }} · {{ row.store.name }}<small>{{ row.platform }} · {{ row.country }}</small></template></el-table-column>
        <el-table-column prop="platform_status" label="平台处理状态" min-width="130" />
        <el-table-column label="退款金额" min-width="135"><template #default="{ row }">{{ row.refund_amount == null ? '不适用' : `${row.refund_amount} ${row.currency}` }}</template></el-table-column>
        <el-table-column label="回仓状态" min-width="160"><template #default="{ row }"><el-tag :type="stateType(row.return_status)" effect="plain">{{ states[row.return_status] || '待确认' }}</el-tag><small v-if="row.tracking?.timed_out_at">曾超时，保留历史</small></template></el-table-column>
        <el-table-column label="已收／应收件数" min-width="140"><template #default="{ row }">{{ quantityLabel(row) }}</template></el-table-column>
        <el-table-column label="待入库起算／期限" min-width="200"><template #default="{ row }">{{ time(row.tracking?.pending_since) }}<small>{{ time(row.tracking?.due_at) }}</small></template></el-table-column>
        <el-table-column label="申请／取消时间" min-width="185"><template #default="{ row }">{{ time(row.source_at) }}</template></el-table-column>
        <el-table-column label="操作" fixed="right" width="100"><template #default="{ row }"><el-button link type="primary" @click="openCase(row.source_key)">详情</el-button></template></el-table-column>
        <template #empty><span>{{ loading ? '正在读取售后记录…' : error ? '本次读取失败，请重试，不能据此判断没有数据。' : '当前筛选范围没有售后记录；取消订单和退款退货将随平台采集展示。' }}</span></template>
      </el-table>
    </template>
    <template v-else>
      <p>保留仓库实收事实。订单不存在、单号有歧义或应退商品尚未确认时不强行关联，也不按相同 SKU 猜测订单。</p>
      <el-form class="receipt-filters" inline @submit.prevent="search"><el-form-item label="订单号／退货单号／运单号"><el-input v-model="receiptSearch" clearable /></el-form-item><el-form-item><el-checkbox v-model="unmatchedOnly" @change="search">仅显示未分配实收数量</el-checkbox></el-form-item><el-button native-type="submit" :loading="loading">查询</el-button></el-form>
      <details class="import-panel"><summary>从仓库导出文件补充回仓实收</summary>
        <p>支持按模板列整理的 CSV／XLSX，每次最多5MB、5000行。订单号、退货单号、SKU 保持文本；成功入库时间填写含时区的文本，例如 2026-10-22T10:00:00+08:00。</p>
        <div class="actions"><el-button :disabled="busy" @click="downloadTemplate">下载列模板</el-button><label>选择文件<input type="file" accept=".csv,.xlsx" :disabled="busy" @change="chooseFile" /></label><el-button :disabled="!importFile || busy" @click="previewImport">校验预览（不导入）</el-button></div>
        <template v-if="importPreview"><p role="status">格式校验通过：{{ importPreview.documents }} 张回仓单，{{ importPreview.lines }} 条商品。以下最多展示20行，尚未导入。</p><el-table :data="importPreview.preview"><el-table-column prop="row" label="行" width="70" /><el-table-column prop="warehouse_code" label="仓库" /><el-table-column prop="return_no" label="退货单号" /><el-table-column prop="platform_order_no" label="平台订单号" /><el-table-column prop="sku" label="SKU" /><el-table-column prop="received_quantity" label="实收数量" /></el-table><el-button type="primary" :loading="busy" @click="confirmImport">确认导入实收记录</el-button></template>
      </details>
      <el-table v-loading="loading" :data="rows" row-key="id" aria-label="待匹配回仓列表">
        <el-table-column prop="return_no" label="仓库退货单号" min-width="190" />
        <el-table-column label="仓库" min-width="180"><template #default="{ row }">{{ row.warehouse.code }} · {{ row.warehouse.name }}</template></el-table-column>
        <el-table-column prop="platform_order_no" label="平台订单号" min-width="190" /><el-table-column prop="tracking_no" label="运单号" min-width="190" />
        <el-table-column prop="sku" label="实收 SKU" min-width="170" /><el-table-column prop="received_quantity" label="实收数量" width="110" /><el-table-column prop="remaining_quantity" label="待分配数量" width="120" />
        <el-table-column label="成功入库时间" min-width="185"><template #default="{ row }">{{ row.received_at ? time(row.received_at) : '成功入库日期待核对（暂不冲回成本）' }}</template></el-table-column>
        <el-table-column label="关联记录" min-width="200"><template #default="{ row }"><div v-for="item in row.allocations" :key="item.id">{{ item.source_key }} · {{ item.quantity }} 件<el-button link type="danger" :disabled="busy" @click="unlink(row, item)">解除关联</el-button></div><span v-if="!row.allocations.length">未关联</span></template></el-table-column>
        <el-table-column label="操作" fixed="right" width="120"><template #default="{ row }"><el-button link type="primary" :disabled="busy || !row.remaining_quantity" @click="openMatch(row)">关联订单</el-button></template></el-table-column>
        <template #empty><span>{{ error ? '读取失败，请重试。' : '暂无待匹配回仓商品。尚未绑定仓库时不会自动拉取，可通过导出文件补充。' }}</span></template>
      </el-table>
    </template>
    <el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next" :disabled="loading" @current-change="load" />

    <el-drawer v-model="detailOpen" title="订单售后详情" size="min(720px, 100vw)" @closed="clearDetail">
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <p v-if="detailLoading" role="status">正在读取售后详情…</p>
      <template v-if="detail">
        <h2>{{ detail.external_order_id || detail.external_return_id }}</h2><p>{{ detail.store.name }} · {{ detail.platform }} · {{ sourceLabel(detail.source_type) }}</p>
        <el-tag :type="stateType(detail.return_status)">{{ states[detail.return_status] }}</el-tag>
        <div v-if="canManage && fullAccess" class="actions">
          <el-button :loading="busy" :disabled="detail.return_status === 'cancelled'" @click="queryReturn">查询回仓</el-button>
          <span>预期回仓仓库默认取订单实际出库仓库，仅查询该仓库；出库仓库不明确时先核对。实际到仓以仓库实收记录为准。</span>
        </div>
        <p v-if="feedback" role="status">{{ feedback }}</p>
        <p>平台处理状态：{{ detail.platform_status }}；退款金额：{{ detail.refund_amount == null ? '不适用（不生成退款）' : `${detail.refund_amount} ${detail.currency}` }}</p>
        <p>待入库起算：{{ time(detail.tracking?.pending_since) }}<br />两个自然月期限：{{ time(detail.tracking?.due_at) }}<br />曾超时：{{ time(detail.tracking?.timed_out_at) }}</p>
        <el-table :data="detail.tracking?.lines || []" aria-label="应退及实收商品"><el-table-column prop="sku" label="SKU" /><el-table-column prop="expected" label="应收" /><el-table-column prop="received" label="已收" /><el-table-column prop="remaining" label="未收" /></el-table>
        <details v-if="detail.platform_record"><summary>平台退款退货原始事实</summary><p>售后单号：{{ detail.platform_record.external_return_id }}<br />退款单号：{{ detail.platform_record.external_refund_id || '—' }}<br />原因：{{ detail.platform_record.reason_code || '—' }}<br />仲裁状态：{{ detail.platform_record.arbitration_status || '—' }}</p><el-table :data="detail.platform_record.items"><el-table-column prop="seller_sku" label="平台 SKU" /><el-table-column prop="quantity" label="售后数量" /><el-table-column prop="refund_amount" label="商品退款额" /></el-table></details>
        <details v-if="canManage" :open="detail.return_status === 'unknown'" class="case-review"><summary>核对本地应退信息</summary>
          <p>只修正本地跟踪依据，平台原始事实不变。请依据发货、退款或仓库凭证确认；无需回仓的记录不参与超时判定。</p>
          <el-form label-position="top" @submit.prevent="saveCase">
            <el-form-item label="是否需要实物回仓"><el-select v-model="review.required"><el-option label="待确认" value="unknown" /><el-option label="需要回仓" value="yes" /><el-option label="无需回仓" value="no" /></el-select></el-form-item>
            <el-form-item label="仓库退货单号"><el-input v-model="review.warehouse_return_no" maxlength="191" placeholder="百世查询必填：核实仓库退货单号，不以平台售后号或运单号代替" /></el-form-item>
            <el-form-item label="已知回仓运单号"><el-input v-model="review.tracking_no" maxlength="191" placeholder="未获取时留空，不将平台订单号冒充运单号" /></el-form-item>
            <el-form-item label="预期回仓仓库（不绑定 API）"><el-select v-model="review.warehouse_id" clearable filterable><el-option v-for="warehouse in warehouses.filter(item => item.country_code === detail.country)" :key="warehouse.id" :label="`${warehouse.code} · ${warehouse.name}`" :value="warehouse.id" /></el-select></el-form-item>
            <div v-for="(line, index) in review.lines" :key="index" class="sku-edit"><el-input v-model="line.sku" placeholder="明确的应退 SKU" :aria-label="`应退 SKU ${index + 1}`" /><el-input-number v-model="line.quantity" :min="1" :max="2147483647" :aria-label="`应退数量 ${index + 1}`" /><el-button :disabled="busy" @click="review.lines.splice(index, 1)">移除</el-button></div>
            <el-button :disabled="busy" @click="review.lines.push({ sku: '', quantity: 1 })">添加应退商品</el-button>
            <el-form-item label="核对原因"><el-input v-model="review.reason" type="textarea" maxlength="500" show-word-limit /></el-form-item>
            <el-button native-type="submit" type="primary" :loading="busy">保存本地核对结果</el-button>
          </el-form>
        </details>
        <h3>处理历史</h3><p v-if="!detail.history.length">暂无本地处理历史。</p><div v-for="(item, index) in detail.history" :key="index" class="audit"><strong>{{ auditLabel(item.action) }}</strong> · {{ time(item.created_at) }}<p v-if="item.after_data?.reason">{{ item.after_data.reason }}</p><p v-if="item.before_data?.state || item.after_data?.state">{{ states[item.before_data?.state] || '—' }} → {{ states[item.after_data?.state] || '—' }}</p></div>
      </template>
    </el-drawer>

    <el-dialog v-model="matchOpen" title="关联仓库实收商品" width="min(620px, 94vw)" :close-on-click-modal="false" @closed="closeMatch">
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <template v-if="matchLine"><p>{{ matchLine.return_no }} · {{ matchLine.sku }} · 尚可分配 {{ matchLine.remaining_quantity }} 件。可分批关联到不同订单，不能超出实收数量。</p>
        <el-form label-position="top" @submit.prevent="saveMatch">
          <el-form-item label="查找平台订单号"><div class="actions"><el-input v-model="matchSearch" placeholder="至少输入3位，不按 SKU 猜测订单" /><el-button :loading="busy" @click="findMatchingOrders">查找</el-button></div></el-form-item>
          <el-form-item label="明确选择订单／售后单"><el-select v-model="matchForm.source_key" @change="selectMatchingOrder"><el-option v-for="item in matchingOrders" :key="item.source_key" :label="`${item.external_order_id} · ${item.store.name} · ${item.external_return_id || sourceLabel(item.source_type)}`" :value="item.source_key" /></el-select></el-form-item>
          <p v-if="matchDetail && matchDetail.tracking?.requires_return !== true" class="warning">该订单的应退信息尚未确认。请先核对，再分配实收数量。<el-button link type="primary" @click="openMatchingCase">核对应退信息</el-button></p>
          <el-form-item label="对应应退 SKU"><el-select v-model="matchForm.sku"><el-option v-for="line in matchDetail?.tracking?.lines || []" :key="line.sku" :label="`${line.sku} · 尚需 ${line.remaining} 件`" :value="line.sku" :disabled="line.remaining === 0" /></el-select></el-form-item>
          <el-form-item label="本次分配数量"><el-input-number v-model="matchForm.quantity" :min="1" :max="matchLine.remaining_quantity" /></el-form-item>
          <el-form-item label="匹配依据／原因"><el-input v-model="matchForm.reason" type="textarea" maxlength="500" /></el-form-item>
          <el-button type="primary" native-type="submit" :loading="busy" :disabled="!matchForm.sku || matchDetail?.tracking?.requires_return !== true">确认关联（不改库存）</el-button>
        </el-form>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, shallowRef } from 'vue';
import { ElMessageBox } from 'element-plus';
import { requestApi, downloadApiFile } from '../../api/request';
import { useAuthStore } from '../../stores/auth';

const BASE = '/api/internal/commerce/aftersales/';
const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission('sales_management.aftersales.manage'));
const states = { unknown: '待确认', not_required: '无需回仓', pending: '待入库', partial: '部分入库', received: '已入库', failed: '到仓超时待核对', cancelled: '售后已取消' };
const tab = ref('cases'), rows = ref([]), total = ref(0), page = ref(1), dates = ref([]), stores = ref([]);
const loading = ref(false), busy = ref(false), error = ref(''), feedback = ref(''), settingsError = ref(''), fullAccess = ref(false);
const optionsError = ref('');
const query = reactive({ external_order_id: '', source_type: '', return_status: '', platform: '', store_id: '', currency: '', sku: '', platform_status: '', case_type: '' });
const settings = reactive({ version: 0, interval_minutes: 60, is_enabled: false, warehouse_bound: false });
const warehouses = ref([]), receiptSearch = ref(''), unmatchedOnly = ref(true);
const platforms = computed(() => [...new Set(stores.value.map(item => item.platform_type))]);
const currencies = computed(() => [...new Set(stores.value.map(item => item.currency))]);
const detailOpen = ref(false), detailLoading = ref(false), detail = ref(null);
const review = reactive({ required: 'unknown', tracking_no: '', warehouse_return_no: '', warehouse_id: null, lines: [], reason: '' });
const importFile = shallowRef(null), importPreview = ref(null);
const matchOpen = ref(false), matchLine = ref(null), matchSearch = ref(''), matchingOrders = ref([]), matchDetail = ref(null);
const matchForm = reactive({ source_key: '', sku: '', quantity: 1, reason: '' });
let sequence = 0, detailSequence = 0, matchingSequence = 0, disposed = false;

function time(value) { return value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '—'; }
function sourceLabel(value) { return ({ cancelled: '取消订单', refund_return: '退款退货', warehouse_return: '仓库退回' })[value] || value; }
function stateType(value) { return ({ failed: 'danger', received: 'success', partial: 'warning', pending: 'warning', not_required: 'info', unknown: 'info' })[value] || 'info'; }
function syncError(value) { return ({ AFTERSALES_QUERY_FAILED: '仓库查询未成功，请查看同步配置及授权', AFTERSALES_MISSING_RETURN_LOOKUP: '部分记录缺少明确的回仓运单号', AFTERSALES_SCOPE_CHANGED: '同步发起人的数据范围已变化', AFTERSALES_BINDING_OR_PERMISSION_INVALID: '仓库绑定或执行权限无效' })[value] || '存在同步异常，请核对配置'; }
function auditLabel(value) { return ({ return_state_changed: '回仓状态更新', return_expectation_reviewed: '核对应退信息', return_allocated: '关联实收商品', return_unlinked: '解除实收关联', return_warehouse_queried: '仓库回仓查询' })[value] || value; }
function quantityLabel(row) { if (row.return_status === 'not_required') return '不适用'; if (row.return_status === 'unknown') return '待确认'; const lines = row.tracking?.lines; return lines?.length ? `${lines.reduce((sum, item) => sum + item.received, 0)} / ${lines.reduce((sum, item) => sum + item.expected, 0)}` : '待确认'; }
async function api(config) { const result = await requestApi({ noMockFallback: true, ...config }); if (!result.success) throw new Error(result.message || '请求未成功，请重试。'); return result.data; }
async function action(fn) { if (busy.value) return; busy.value = true; error.value = ''; feedback.value = ''; try { await fn(); } catch (e) { error.value = e.message || '操作未完成，请核对后重试。'; } finally { busy.value = false; } }
async function load() {
  const id = ++sequence; loading.value = true; error.value = '';
  try {
    const params = tab.value === 'cases' ? { ...query, date_from: dates.value?.[0], date_to: dates.value?.[1] } : { search: receiptSearch.value, unmatched: String(unmatchedOnly.value) };
    const data = await api({ url: BASE + (tab.value === 'receipts' ? 'receipts/' : ''), params: { ...params, page: page.value, page_size: 20 } });
    if (disposed || id !== sequence) return;
    rows.value = data.results || []; total.value = data.count || 0;
  } catch (e) { if (!disposed && id === sequence) { error.value = e.message; rows.value = []; total.value = 0; } }
  finally { if (!disposed && id === sequence) loading.value = false; }
}
function search() { page.value = 1; return load(); }
function reset() { for (const key of Object.keys(query)) query[key] = ''; dates.value = []; return search(); }
function changeTab(value) { if (tab.value !== value) { tab.value = value; rows.value = []; feedback.value = ''; search(); } }
async function loadSettings() {
  if (!canManage.value) return;
  try { Object.assign(settings, await api({ url: BASE + 'settings/' })); fullAccess.value = true; warehouses.value = (await api({ url: BASE + 'import/' })).warehouses || []; }
  catch (e) { settingsError.value = e.message; fullAccess.value = false; }
}
async function loadOptions() { optionsError.value = ''; try { const data = await api({ url: BASE + 'options/' }); if (!disposed) stores.value = data.stores || []; } catch { if (!disposed) optionsError.value = '筛选选项读取失败，仍可按订单号查询。'; } }
function saveSettings() { return action(async () => { Object.assign(settings, await api({ method: 'patch', url: BASE + 'settings/', data: { expected_version: settings.version, interval_minutes: settings.interval_minutes, is_enabled: settings.is_enabled } })); feedback.value = settings.warehouse_bound ? '同步周期已保存。' : '周期已保存；未绑定仓库，定时与手动同步均未执行。'; }); }
function manualSync() { return action(async () => { await api({ method: 'post', url: BASE + 'sync/', data: {} }); feedback.value = '只读查询任务已排队，尚不代表查询或入库成功。'; }); }
async function openCase(key) {
  const id = ++detailSequence; detailOpen.value = true; detailLoading.value = true; detail.value = null; error.value = ''; feedback.value = '';
  try { const data = await api({ url: BASE + `cases/${encodeURIComponent(key)}/` }); if (disposed || id !== detailSequence) return; detail.value = data; review.required = data.tracking?.requires_return === true ? 'yes' : data.tracking?.requires_return === false || data.return_status === 'not_required' ? 'no' : 'unknown'; review.tracking_no = data.tracking?.tracking_no || ''; review.warehouse_return_no = data.tracking?.warehouse_return_no || ''; review.warehouse_id = data.tracking?.warehouse_id || null; review.lines = Object.entries(data.expected_skus).map(([sku, quantity]) => ({ sku, quantity })); review.reason = ''; }
  catch (e) { if (!disposed && id === detailSequence) error.value = e.message; }
  finally { if (!disposed && id === detailSequence) detailLoading.value = false; }
}
function clearDetail() { ++detailSequence; detail.value = null; }
function queryReturn() { return action(async () => {
  const key = detail.value.source_key;
  const result = await api({ method: 'post', url: BASE + `cases/${encodeURIComponent(key)}/`, data: {}, timeout: 180000 });
  await openCase(key); await load();
  feedback.value = ({ matched: '已唯一匹配仓库退货单；是否到仓按实收数量判断。',
    not_found: '本次未查到退货单，不代表未到仓。', ambiguous: '多个仓库匹配，未自动关联，请核对。',
    incomplete: '部分仓库查询失败或未完成，未自动关联，请核对授权后重试。',
    no_authorization: '没有符合国家及仓库范围的有效仓库授权。' })[result.status] || '查询未完成，请重试。';
}); }
function saveCase() { return action(async () => {
  if (!review.reason.trim()) throw new Error('请填写核对原因。');
  const expected = {};
  for (const line of review.lines) { if (!line.sku.trim() || !Number.isInteger(line.quantity) || line.quantity < 1 || line.sku.trim() in expected) throw new Error('请核对应退 SKU 与数量，SKU 不可重复。'); expected[line.sku.trim()] = line.quantity; }
  if (review.required === 'yes' && !Object.keys(expected).length) throw new Error('需要回仓时请明确应退商品和数量。');
  const key = detail.value.source_key;
  await api({ method: 'patch', url: BASE + `cases/${encodeURIComponent(key)}/`, data: { expected_version: detail.value.tracking?.version || 0, requires_return: review.required === 'unknown' ? null : review.required === 'yes', expected_skus: expected, tracking_no: review.tracking_no, warehouse_return_no: review.warehouse_return_no, warehouse_id: review.warehouse_id || null, reason: review.reason.trim() } });
  await openCase(key); await load(); feedback.value = '本地应退信息已保存，平台订单及仓库库存未改变。';
}); }
function chooseFile(event) { importFile.value = event.target.files?.[0] || null; importPreview.value = null; }
function importData(operation) { const data = new FormData(); data.append('file', importFile.value); data.append('operation', operation); if (operation === 'confirm') data.append('sha256', importPreview.value.sha256); return data; }
function previewImport() { return action(async () => { importPreview.value = null; importPreview.value = await api({ method: 'post', url: BASE + 'import/', data: importData('preview'), timeout: 120000 }); }); }
async function confirmImport() {
  if (!importFile.value || !importPreview.value) return;
  try { await ElMessageBox.confirm(`将保存 ${importPreview.value.documents} 张仓库回仓单及实收商品，并尝试明确单号匹配。不调整库存、不发起退款。`, '确认导入本地实收记录'); } catch { return; }
  return action(async () => { const result = await api({ method: 'post', url: BASE + 'import/', data: importData('confirm'), timeout: 120000 }); importPreview.value = null; feedback.value = `已新增 ${result.created_documents} 张、已存在 ${result.existing_documents} 张回仓单。请核对订单详情及待匹配数量。`; await load(); });
}
function downloadTemplate() { return action(async () => { const result = await downloadApiFile(BASE + 'template/', '仓库回仓实收模板.csv'); if (result?.success === false) throw new Error(result.message || '模板下载失败。'); }); }
function openMatch(row) { matchLine.value = row; matchSearch.value = row.platform_order_no || ''; matchingOrders.value = []; matchDetail.value = null; Object.assign(matchForm, { source_key: '', sku: '', quantity: 1, reason: '' }); matchOpen.value = true; }
function closeMatch() { ++matchingSequence; matchDetail.value = null; }
function findMatchingOrders() { return action(async () => { matchingOrders.value = []; matchDetail.value = null; matchForm.source_key = ''; const data = await api({ url: BASE + 'matching-orders/', params: { external_order_id: matchSearch.value } }); matchingOrders.value = data.results || []; if (!matchingOrders.value.length) throw new Error('没有找到授权范围内的订单，请核对单号或平台采集记录。'); if (data.refine_search) feedback.value = '候选订单较多，请输入更完整的订单号。'; }); }
async function selectMatchingOrder() { const id = ++matchingSequence, key = matchForm.source_key; matchDetail.value = null; matchForm.sku = ''; try { const data = await api({ url: BASE + `cases/${encodeURIComponent(key)}/` }); if (!disposed && id === matchingSequence && key === matchForm.source_key) matchDetail.value = data; } catch (e) { if (!disposed && id === matchingSequence) error.value = e.message; } }
function openMatchingCase() { matchOpen.value = false; return openCase(matchForm.source_key); }
function saveMatch() { return action(async () => { if (!matchForm.reason.trim()) throw new Error('请填写匹配依据或原因。'); await api({ method: 'post', url: BASE + `receipts/${matchLine.value.id}/allocate/`, data: { ...matchForm, expected_version: matchLine.value.version } }); matchOpen.value = false; feedback.value = '实收数量已关联，已重新计算本地回仓状态。'; await load(); }); }
async function unlink(row, item) {
  let reason;
  try { reason = (await ElMessageBox.prompt('仅解除本地关联，保留实收记录及历史。请填写纠错原因。', '解除实收关联', { inputValidator: value => Boolean(value?.trim()) || '请填写原因' })).value; } catch { return; }
  return action(async () => { await api({ method: 'post', url: BASE + `allocations/${item.id}/unlink/`, data: { expected_version: row.version, reason } }); feedback.value = '关联已解除，实收记录和操作历史均保留。'; await load(); });
}
onMounted(() => { load(); loadSettings(); loadOptions(); });
onUnmounted(() => { disposed = true; ++sequence; ++detailSequence; ++matchingSequence; });
</script>

<style scoped>
.aftersales { display: grid; gap: 16px; color: #1e293b; min-width: 0; }
.page-header { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; }
h1 { font-size: 26px; line-height: 1.35; margin: 0; letter-spacing: -.02em; }
h2 { font-size: 20px; overflow-wrap: anywhere; } h3 { font-size: 16px; }
p { line-height: 1.65; margin: 8px 0; } .page-header p, .secondary { color: #475569; }
.filters, .sync-settings, .import-panel { background: #fff; border: 1px solid #dce3ec; border-radius: 8px; padding: 16px; }
.filters { display: flex; flex-wrap: wrap; align-items: end; gap: 0 16px; }
.filters :deep(.el-form-item) { width: 200px; margin-bottom: 12px; }
.filters :deep(.el-form-item:last-of-type) { width: 320px; max-width: 100%; }
.filters :deep(.el-select), .filters :deep(.el-date-editor) { width: 100%; }
.filter-actions { display: flex; margin: 0 0 12px auto; gap: 8px; }
.actions, .sku-edit { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.actions :deep(.el-input) { flex: 1; min-width: 180px; }
summary { cursor: pointer; font-weight: 600; line-height: 1.5; }
.sync-settings > p, .import-panel > p { max-width: 75ch; }
.sync-settings :deep(.el-form) { margin-top: 12px; }
.sync-settings :deep(.el-form-item) { vertical-align: bottom; }
small { display: block; color: #475569; line-height: 1.6; margin-top: 4px; }
.aftersales :deep(.el-table) { width: 100%; }
.aftersales :deep(.el-table__empty-text) { padding: 16px; line-height: 1.6; }
.aftersales :deep(.el-input__inner::placeholder) { color: #64748b; }
.sku-edit { margin-bottom: 12px; } .sku-edit :deep(.el-input) { flex: 1; min-width: 160px; }
.case-review { margin: 20px 0; } .case-review :deep(.el-form-item) { margin-top: 14px; }
.case-review :deep(.el-select) { width: 100%; }
.warning { color: #92400e; } .audit { padding: 12px 0; border-bottom: 1px solid #e2e8f0; }
@media (max-width: 680px) { .page-header { flex-direction: column; gap: 12px; } .filters :deep(.el-form-item) { width: 100%; } .filter-actions { margin-left: 0; } .sku-edit { align-items: stretch; } }
</style>
