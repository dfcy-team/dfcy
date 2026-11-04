<template>
  <AppPage title="处理费登记" subtitle="登记仓库已发生或已出账的费用，分别保留订单归属与国家归属。" capability="内部登记">
    <template #action>
      <el-button v-if="can('export') && kind !== 'imports'" :disabled="busy" @click="exportRows">导出筛选结果</el-button>
      <el-button v-if="can('import') && kind !== 'imports'" :disabled="busy" @click="openImport">批量登记</el-button>
      <el-button v-if="can('create') && kind !== 'imports'" type="primary" :disabled="busy || !optionsReady" @click="newFee">新建登记</el-button>
    </template>
    <p class="boundary">确认登记不代表已付款；不发起付款、不修改订单或仓库数据。订单处理费须唯一关联本地订单，否则保留待核对；按业务结算清单登记时，未落实到订单的金额保留为仓库其他处理费差额。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon role="alert" />
    <el-alert v-if="feedback" :title="feedback" type="success" :closable="false" show-icon role="status" />
    <el-tabs :model-value="kind" :before-leave="beforeTab" @update:model-value="switchKind">
      <el-tab-pane label="订单处理费" name="order" /><el-tab-pane label="仓库其他处理费" name="other" />
      <el-tab-pane v-if="can('import')" label="导入记录" name="imports" />
    </el-tabs>
    <section v-if="kind !== 'imports'" class="workspace-card" aria-label="处理费列表">
      <form class="filters" @submit.prevent="query">
        <el-date-picker v-model="filters.bill_month" type="month" value-format="YYYY-MM" placeholder="全部账单月份" aria-label="账单月份" />
        <el-select v-model="filters.country" clearable placeholder="全部国家" aria-label="国家"><el-option v-for="site in options.countries" :key="site.code" :label="`${site.code} · ${site.name}`" :value="site.code" /></el-select>
        <el-select v-model="filters.warehouse_id" clearable filterable placeholder="全部仓库" aria-label="仓库"><el-option v-for="wh in filterWarehouses" :key="wh.id" :label="`${wh.code} · ${wh.name}`" :value="wh.id" /></el-select>
        <el-select v-if="kind === 'order'" v-model="filters.store_id" clearable filterable placeholder="全部店铺" aria-label="店铺"><el-option v-for="store in filterStores" :key="store.id" :label="store.code" :value="store.id" /></el-select>
        <el-input v-if="kind === 'order'" v-model="filters.order_number" clearable placeholder="完整平台订单号" aria-label="平台订单号" />
        <el-select v-model="filters.status" clearable placeholder="全部状态" aria-label="登记状态"><el-option v-for="(label, value) in statuses" :key="value" :label="label" :value="value" /></el-select>
        <el-select v-if="kind === 'order'" v-model="filters.match_status" clearable placeholder="全部关联状态" aria-label="订单关联状态"><el-option v-for="value in ['matched', 'unmatched', 'ambiguous']" :key="value" :value="value" :label="matches[value]" /></el-select>
        <el-button type="primary" native-type="submit" :loading="busy">查询</el-button><el-button :disabled="busy" @click="resetFilters">重置</el-button>
      </form>
      <div class="list-info"><span>共 {{ count ?? '—' }} 条 · 已登记金额：<template v-if="totals.length"><span v-for="total in totals" :key="total.currency" class="total">{{ total.amount }} {{ total.currency }}</span></template><template v-else>—</template></span>
        <el-button v-if="can('register')" :disabled="busy || !selection.length" @click="registerSelection">确认所选草稿（{{ selection.length }}）</el-button>
      </div>
      <el-table v-loading="busy" :data="rows" row-key="id" :empty-text="error ? '读取失败，请重新查询。' : '暂无费用登记，可新建或按标准模板导入。'" @selection-change="selection = $event">
        <el-table-column v-if="can('register')" type="selection" width="44" :selectable="canRegister" />
        <el-table-column label="账单／费用编号" min-width="190" fixed="left"><template #default="{ row }"><b>{{ row.bill_number }}</b><small>{{ row.reference }} · #{{ row.id }}</small></template></el-table-column>
        <el-table-column label="归属" min-width="165"><template #default="{ row }">{{ row.country }} · {{ row.warehouse_code }}<small>{{ row.store_code || '国家级费用' }}</small></template></el-table-column>
        <el-table-column v-if="kind === 'order'" prop="external_order_id" label="平台订单号" min-width="185" />
        <el-table-column label="月份／发生日期" min-width="145"><template #default="{ row }">{{ row.bill_month }}<small>{{ row.occurred_on || '仅有月份' }}</small></template></el-table-column>
        <el-table-column prop="fee_item" label="费用项目" min-width="135" />
        <el-table-column label="结算金额" min-width="150" align="right"><template #default="{ row }"><b class="numeric">{{ row.amount }} {{ row.currency }}</b></template></el-table-column>
        <el-table-column label="状态" min-width="135"><template #default="{ row }"><el-tag :type="row.status === 'registered' ? 'success' : row.status === 'void' ? 'info' : 'warning'">{{ statuses[row.status] }}</el-tag><small>{{ matches[row.match_status] }}</small><small v-if="row.source.possible_duplicate">疑似重复计费（已保留）</small><small v-if="row.source.type === 'warehouse_settlement_adjustment'">结算差额，随明细登记自动重算</small></template></el-table-column>
        <el-table-column label="操作" fixed="right" width="110"><template #default="{ row }"><el-button link type="primary" :disabled="busy" @click="openFee(row)">详情</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" v-model:page-size="size" :page-sizes="[20, 50, 100]" :total="count || 0" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="query" />
    </section>
    <section v-else class="workspace-card" aria-label="我的导入记录">
      <p>仅显示本人最近50个导入批次。导入仅生成草稿，不自动确认登记。</p>
      <el-table v-loading="busy" :data="batches" empty-text="暂无导入记录。"><el-table-column prop="id" label="批次" width="90" /><el-table-column prop="file_name" label="文件" min-width="250" /><el-table-column label="时间" min-width="180"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column><el-table-column label="结果" min-width="200"><template #default="{ row }">{{ row.results.length }} 条 · 错误 {{ row.results.filter(r => r.status === 'error').length }} 条</template></el-table-column><el-table-column label="明细" width="110"><template #default="{ row }"><el-button link type="primary" @click="showBatch(row)">查看结果</el-button></template></el-table-column></el-table>
    </section>

    <el-drawer v-model="editor" :title="selected ? `费用登记 #${selected.id}` : '新建处理费登记'" size="min(900px, 100vw)" :before-close="beforeEditorClose" :close-on-click-modal="false" :show-close="!busy">
      <el-alert v-if="editorError" :title="editorError" type="error" :closable="false" show-icon role="alert" />
      <template v-if="selected && !editMode">
        <el-alert v-if="selected.possible_duplicate_count" :title="`同账单、同归属和费用项目还有${selected.possible_duplicate_count}条记录，请核对是否分包计费或重复登记。`" type="warning" :closable="false" show-icon />
        <p class="detail-state"><el-tag>{{ statuses[selected.status] }}</el-tag> {{ matches[selected.match_status] }} · 版本 {{ selected.version }}</p>
        <el-descriptions :column="2" border><el-descriptions-item label="账单">{{ selected.bill_number }}</el-descriptions-item><el-descriptions-item label="来源费用编号">{{ selected.reference }}</el-descriptions-item><el-descriptions-item label="国家／仓库">{{ selected.country }} · {{ selected.warehouse_code }}</el-descriptions-item><el-descriptions-item label="月份">{{ selected.bill_month }}</el-descriptions-item><el-descriptions-item label="店铺／订单" :span="2">{{ selected.store_code || '国家级费用' }} · {{ selected.external_order_id || '不关联订单' }}</el-descriptions-item><el-descriptions-item label="费用项目">{{ selected.fee_item }}</el-descriptions-item><el-descriptions-item label="结算金额">{{ selected.amount }} {{ selected.currency }}</el-descriptions-item><el-descriptions-item label="发生日期">{{ selected.occurred_on || '未提供，仅有月份' }}</el-descriptions-item><el-descriptions-item label="原币金额">{{ selected.original_amount ? `${selected.original_amount} ${selected.original_currency}` : '未提供' }}</el-descriptions-item><el-descriptions-item label="换汇信息" :span="2">{{ selected.exchange_rate ? `1 ${selected.original_currency} = ${selected.exchange_rate} ${selected.currency}；${selected.rate_date} · ${selected.rate_source}` : '结算金额已确定，不重复换汇' }}</el-descriptions-item><el-descriptions-item label="来源" :span="2">{{ selected.source.file_name ? `${selected.source.file_name}${selected.source.row ? ` · 第${selected.source.row}行` : ' · 业务结算清单'}` : '手工登记' }}</el-descriptions-item><el-descriptions-item label="备注" :span="2">{{ selected.note || '—' }}</el-descriptions-item></el-descriptions>
        <p v-if="selected.source.type === 'warehouse_settlement_adjustment'">结算依据：{{ selected.source.file_name }}；此差额由账单统一维护，仓库未明确时保留待分配，不能独立修改或作废。</p>
        <div v-else class="actions"><el-button v-if="can('edit') && selected.status !== 'void'" @click="beginEdit">{{ selected.status === 'draft' ? '编辑草稿' : '更正登记（留存历史）' }}</el-button><el-button v-if="can('register') && selected.status === 'draft'" type="primary" :disabled="busy || !canRegister(selected)" @click="singleAction('register')">确认登记</el-button><el-button v-if="can('edit') && selected.kind === 'order' && selected.status !== 'void'" :disabled="busy" @click="singleAction('link')">重新关联订单</el-button><el-button v-if="can('void') && selected.status === 'registered'" type="danger" plain :disabled="busy" @click="singleAction('void')">作废登记</el-button></div>
        <h3>操作与更正历史</h3><el-timeline><el-timeline-item v-for="event in selected.audit || []" :key="event.id" :timestamp="formatTime(event.created_at)"><b>{{ actionLabels[event.action] || event.action }}</b><p>{{ event.detail.reason || '—' }}</p><p v-if="event.action === 'correct'">金额：{{ event.detail.before.amount }} {{ event.detail.before.currency }} → {{ event.detail.after.amount }} {{ event.detail.after.currency }}</p></el-timeline-item></el-timeline>
      </template>
      <el-form v-else label-position="top" :disabled="busy" @submit.prevent="save">
        <h3>费用归属</h3><div class="form-grid">
          <el-form-item label="国家" required><el-select v-model="form.country" :disabled="Boolean(selected)" @change="clearOwnership"><el-option v-for="site in options.countries" :key="site.code" :label="`${site.code} · ${site.name}`" :value="site.code" /></el-select></el-form-item>
          <el-form-item label="仓库" required><el-select v-model="form.warehouse_id" :disabled="Boolean(selected)" filterable><el-option v-for="wh in formWarehouses" :key="wh.id" :value="wh.id" :label="`${wh.code} · ${wh.name}`" /></el-select></el-form-item>
          <el-form-item v-if="form.kind === 'order'" label="店铺" required><el-select v-model="form.store_id" :disabled="Boolean(selected)" filterable><el-option v-for="store in formStores" :key="store.id" :value="store.id" :label="`${store.code} · ${store.name}`" /></el-select></el-form-item>
          <el-form-item v-if="form.kind === 'order'" label="平台订单号" required><el-input v-model="form.external_order_id" :disabled="Boolean(selected)" placeholder="文本；本地缺订单时可先保留待关联" maxlength="191" /></el-form-item>
        </div><h3>账单信息</h3><div class="form-grid">
          <el-form-item label="账单编号" required><el-input v-model="form.bill_number" :disabled="Boolean(selected)" maxlength="191" /></el-form-item><el-form-item label="账单月份" required><el-date-picker v-model="form.bill_month" type="month" value-format="YYYY-MM" :disabled="Boolean(selected)" /></el-form-item>
          <el-form-item label="费用项目" required><el-input v-model="form.fee_item" :disabled="Boolean(selected)" maxlength="80" placeholder="如订单处理费、仓储费、退货入库费" /></el-form-item><el-form-item label="来源费用编号（账单行号／WMS单号）" required><el-input v-model="form.reference" :disabled="Boolean(selected)" maxlength="191" placeholder="同一费用重复导入必须沿用原编号" /></el-form-item>
          <el-form-item label="发生日期（可仅保留月份）"><el-date-picker v-model="form.occurred_on" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD；未知可留空" /></el-form-item>
        </div><h3>结算金额</h3><p class="muted">填写账单确定的结算金额，币种不随店铺变化。“已登记”不代表已经付款。</p><div class="form-grid">
          <el-form-item label="结算金额" required><el-input v-model="form.amount" inputmode="decimal" placeholder="大于0，最多6位小数" /></el-form-item><el-form-item label="结算币种" required><el-select v-model="form.currency"><el-option v-for="c in options.currencies" :key="c" :label="c" :value="c" /></el-select></el-form-item>
        </div><el-collapse><el-collapse-item title="原币与换汇信息（可全部留空）" name="fx"><p class="muted">1 原币 = 汇率 × 结算币。填写后需同时提供金额、币种、汇率、日期及来源。</p><div class="form-grid"><el-form-item label="原币金额"><el-input v-model="form.original_amount" inputmode="decimal" /></el-form-item><el-form-item label="原币币种"><el-select v-model="form.original_currency" clearable><el-option v-for="c in options.currencies" :key="c" :label="c" :value="c" /></el-select></el-form-item><el-form-item label="兑换汇率"><el-input v-model="form.exchange_rate" inputmode="decimal" /></el-form-item><el-form-item label="汇率日期"><el-date-picker v-model="form.rate_date" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="汇率来源"><el-input v-model="form.rate_source" maxlength="191" /></el-form-item></div></el-collapse-item></el-collapse>
        <el-form-item label="备注"><el-input v-model="form.note" type="textarea" maxlength="500" :rows="2" /></el-form-item><el-form-item v-if="selected?.status === 'registered'" label="更正原因" required><el-input v-model="correctionReason" type="textarea" :rows="2" maxlength="500" /></el-form-item>
        <div class="actions"><el-button type="primary" native-type="submit" :loading="busy">{{ selected?.status === 'registered' ? '保存更正并留存历史' : '保存草稿' }}</el-button><el-button v-if="selected" :disabled="busy" @click="editMode = false">取消修改</el-button></div>
      </el-form>
    </el-drawer>

    <el-dialog v-model="importVisible" :title="batchHistory ? '导入结果' : '处理费批量登记'" width="min(1120px, 96vw)" :close-on-click-modal="false" :before-close="beforeImportClose" destroy-on-close>
      <el-radio-group v-if="!batchHistory" :model-value="importMode" :disabled="busy" aria-label="上传方式" @update:model-value="changeImportMode"><el-radio-button value="original">原始仓库账单（自动解析）</el-radio-button><el-radio-button value="template">标准登记模板</el-radio-button></el-radio-group>
      <WarehouseBillUpload v-if="!batchHistory && importMode === 'original'" ref="originalBill" :options="options" @imported="refreshAfterWrite" />
      <template v-else>
      <p>标准登记模板每批最多1000条、5MB。Z:\处理费的原账单请选择“原始仓库账单（自动解析）”。</p>
      <div v-if="!batchHistory" class="actions"><el-button :disabled="busy" @click="downloadTemplate">下载当前类型模板</el-button><label class="file-label">选择登记表<input type="file" accept=".xlsx" :disabled="busy" @change="changeFile" /></label><el-button :loading="busy" :disabled="!file" @click="previewImport(false)">校验预览（不导入）</el-button></div>
      <el-alert v-if="importError" :title="importError" type="error" :closable="false" show-icon />
      <template v-if="importPreview"><p>共 {{ importPreview.results.length }} 条，错误 {{ importPreview.results.filter(r => r.status === 'error').length }} 条。{{ importPreview.confirmed ? `本次新增${importPreview.created}条草稿。` : '预览不写入费用。' }}</p>
        <el-table :data="importPreview.results.slice((importPage - 1) * 20, importPage * 20)" max-height="440"><el-table-column prop="row" label="Excel行号" width="105" /><el-table-column prop="reference" label="费用编号" min-width="160" /><el-table-column prop="order_number" label="平台订单号" min-width="180" /><el-table-column label="结果" width="110"><template #default="{ row }">{{ importStates[row.status] }}</template></el-table-column><el-table-column label="关联／错误" min-width="300"><template #default="{ row }">{{ row.error || matches[row.match_status] }}</template></el-table-column></el-table>
        <el-pagination v-model:current-page="importPage" :page-size="20" :total="importPreview.results.length" layout="total, prev, pager, next" />
        <div class="actions"><el-button v-if="importPreview.results.some(r => r.status === 'error')" @click="downloadErrors">下载错误清单</el-button><el-checkbox v-if="!batchHistory && !importPreview.confirmed" v-model="validOnly">仅导入有效记录，错误行不导入</el-checkbox><el-button v-if="!batchHistory && !importPreview.confirmed" type="primary" :disabled="busy || !hasImportable || (!validOnly && importPreview.results.some(r => r.status === 'error'))" :loading="busy" @click="previewImport(true)">确认导入草稿（不审批）</el-button></div>
      </template>
      </template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { onBeforeRouteLeave } from 'vue-router';
import { ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import WarehouseBillUpload from '../../components/WarehouseBillUpload.vue';
import { requestApi, downloadApiFile } from '../../api/request';
import { useAuthStore } from '../../stores/auth';

const BASE = '/api/finance/warehouse-fees/';
const auth = useAuthStore();
const can = action => auth.hasPermission(`finance.warehouse_fees.${action}`);
const statuses = { draft: '草稿', registered: '已登记（不代表付款）', void: '已作废' };
const matches = { matched: '已关联订单', unmatched: '待核对：未关联本地订单', ambiguous: '待核对：关联有歧义', not_applicable: '国家级费用' };
const canRegister = row => row?.status === 'draft' && (row.kind !== 'order' || row.match_status === 'matched');
const actionLabels = { create: '新建草稿', edit: '编辑草稿', register: '确认登记', correct: '更正登记', link: '核对订单关联', void: '作废登记', settlement_reconcile: '结算差额重算' };
const importStates = { valid: '校验通过', existing: '已存在，跳过', error: '错误，不导入', created: '已导入草稿' };
const editable = ['amount', 'currency', 'original_amount', 'original_currency', 'exchange_rate', 'rate_date', 'rate_source', 'occurred_on', 'note'];
const kind = ref('order'), busy = ref(false), rows = ref([]), count = ref(null), totals = ref([]), page = ref(1), size = ref(20), selection = ref([]), batches = ref([]);
const filters = reactive({ bill_month: '', country: '', warehouse_id: '', store_id: '', order_number: '', status: '', match_status: '' });
const options = reactive({ countries: [], warehouses: [], stores: [], currencies: [] }), optionsReady = ref(false);
const error = ref(''), feedback = ref(''), editorError = ref(''), editor = ref(false), selected = ref(null), editMode = ref(false), form = reactive({}), correctionReason = ref('');
const importVisible = ref(false), batchHistory = ref(false), file = ref(null), importPreview = ref(null), importError = ref(''), validOnly = ref(false), importPage = ref(1), cleanForm = ref('');
const importMode = ref('original');
const originalBill = ref(null);
const filterWarehouses = computed(() => options.warehouses.filter(w => !filters.country || w.country === filters.country));
const filterStores = computed(() => options.stores.filter(s => !filters.country || s.country === filters.country));
const formWarehouses = computed(() => options.warehouses.filter(w => w.country === form.country));
const formStores = computed(() => options.stores.filter(s => s.country === form.country));
const hasImportable = computed(() => importPreview.value?.results.some(r => ['valid', 'existing'].includes(r.status)));
const dirty = computed(() => editor.value && editMode.value && JSON.stringify(form) !== cleanForm.value);
const formatTime = value => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
const params = () => Object.fromEntries(Object.entries({ ...filters, kind: kind.value, ...(kind.value === 'other' ? { store_id: '', order_number: '', match_status: '' } : {}) }).filter(([, v]) => v !== '' && v != null));
async function api(config) {
  const response = await requestApi({ timeout: 30000, ...config, noMockFallback: true });
  if (!response.success) throw new Error(response.message || '请求失败，请重新核对。');
  return response.data;
}
async function guard(task, target = error) {
  if (busy.value) return;
  busy.value = true; target.value = '';
  try { await task(); } catch (e) { target.value = e.message || '操作失败。'; } finally { busy.value = false; }
}
async function loadRows() {
  const data = await api({ url: BASE, params: { ...params(), page: page.value, page_size: size.value } });
  rows.value = data.results; count.value = data.count; totals.value = data.registered_totals; selection.value = [];
}
async function load() { await guard(loadRows); }
async function query() { page.value = 1; await load(); }
async function resetFilters() { for (const key of Object.keys(filters)) filters[key] = ''; await query(); }
async function beforeTab() { return !busy.value && await discard(); }
async function switchKind(value) {
  kind.value = value; feedback.value = ''; error.value = ''; selection.value = []; editor.value = false;
  if (value === 'imports') await guard(async () => { batches.value = (await api({ url: BASE + 'imports/' })).results; });
  else await query();
}
function clearOwnership() { form.warehouse_id = null; form.store_id = null; }
function newFee() {
  if (busy.value || !can('create')) return;
  selected.value = null; editMode.value = true; correctionReason.value = ''; editorError.value = '';
  for (const key of Object.keys(form)) delete form[key];
  Object.assign(form, { kind: kind.value, country: filters.country || '', warehouse_id: null, store_id: null, external_order_id: '',
    bill_number: '', bill_month: filters.bill_month || '', fee_item: kind.value === 'order' ? '订单处理费' : '', reference: '',
    amount: '', currency: options.currencies.includes('CNY') ? 'CNY' : options.currencies[0], original_amount: '', original_currency: '', exchange_rate: '', rate_date: null, rate_source: '', occurred_on: null, note: '' });
  cleanForm.value = JSON.stringify(form); editor.value = true;
}
async function openFee(row) { await guard(async () => { selected.value = await api({ url: `${BASE}${row.id}/` }); editMode.value = false; editorError.value = ''; editor.value = true; }); }
function beginEdit() {
  if (busy.value || !can('edit')) return;
  for (const key of Object.keys(form)) delete form[key];
  const identity = ['kind', 'country', 'warehouse_id', 'store_id', 'external_order_id', 'bill_number', 'bill_month', 'fee_item', 'reference'];
  for (const key of [...identity, ...editable]) form[key] = selected.value[key] ?? '';
  correctionReason.value = ''; cleanForm.value = JSON.stringify(form); editMode.value = true; editorError.value = '';
}
async function refreshAfterWrite() {
  try { await loadRows(); } catch (e) { error.value = `费用处理已保存，但列表刷新失败：${e.message}。请重新查询，不要重复新增。`; }
}
function formData() {
  return { ...form, store_id: form.kind === 'other' ? null : form.store_id,
    original_amount: form.original_amount === '' ? null : form.original_amount, exchange_rate: form.exchange_rate === '' ? null : form.exchange_rate,
    occurred_on: form.occurred_on || null, rate_date: form.rate_date || null };
}
async function save() {
  if (!can(selected.value ? 'edit' : 'create')) return;
  await guard(async () => {
    const value = formData();
    const data = selected.value ? { expected_version: selected.value.version, changes: Object.fromEntries(editable.map(k => [k, value[k]])), reason: correctionReason.value } : value;
    const url = selected.value ? `${BASE}${selected.value.id}/${selected.value.status === 'registered' ? 'correct' : 'edit'}/` : BASE;
    const saved = await api({ method: 'post', url, data });
    selected.value = saved; editMode.value = false; cleanForm.value = JSON.stringify(form); feedback.value = '已保存费用记录，未发起付款。';
    try { selected.value = await api({ url: `${BASE}${saved.id}/` }); } catch { editorError.value = '已保存；详情暂未刷新，请关闭后重新查看。'; }
    await refreshAfterWrite();
  }, editorError);
}
async function singleAction(action) {
  if (busy.value || !can(action === 'link' ? 'edit' : action)) return;
  if (action === 'register' && !canRegister(selected.value)) return;
  let reason = '';
  try {
    if (action === 'void') reason = (await ElMessageBox.prompt('填写作废原因；不撤销任何实际付款。', '作废费用', { inputValidator: v => Boolean(v?.trim()) || '请填写原因' })).value;
    else if (action === 'register') await ElMessageBox.confirm('确认这笔已发生或已出账的费用？此操作不发起付款。', '确认登记');
  } catch { return; }
  await guard(async () => {
    const saved = await api({ method: 'post', url: `${BASE}${selected.value.id}/${action}/`, data: { expected_version: selected.value.version, reason } });
    selected.value = saved; feedback.value = action === 'link' ? matches[saved.match_status] : '处理完成，未发起付款。';
    try { selected.value = await api({ url: `${BASE}${saved.id}/` }); } catch { editorError.value = '处理已保存，请关闭后重新加载详情。'; }
    await refreshAfterWrite();
  }, editorError);
}
async function registerSelection() {
  if (busy.value || !can('register') || !selection.value.length) return;
  if (!selection.value.every(canRegister)) return;
  try { await ElMessageBox.confirm(`确认登记所选${selection.value.length}条草稿？不发起付款。`, '批量确认'); } catch { return; }
  await guard(async () => { await api({ method: 'post', url: BASE + 'batch-register/', data: { targets: selection.value.map(r => ({ id: r.id, version: r.version })) } }); feedback.value = '所选草稿已确认登记，未发起付款。'; await refreshAfterWrite(); });
}
async function discard() {
  if (!dirty.value) return true;
  try { await ElMessageBox.confirm('尚未保存的内容将丢弃，是否继续？', '未保存的修改'); return true; } catch { return false; }
}
async function beforeEditorClose(done) { if (!busy.value && await discard()) done(); }
function openImport() { if (busy.value || !can('import')) return; batchHistory.value = false; importMode.value = 'original'; importPreview.value = null; importError.value = ''; file.value = null; validOnly.value = false; importPage.value = 1; importVisible.value = true; }
function changeFile(event) { file.value = event.target.files?.[0] || null; importPreview.value = null; validOnly.value = false; importError.value = ''; }
async function downloadTemplate() { await guard(async () => { const result = await downloadApiFile(`${BASE}template/?kind=${kind.value}`, `${kind.value === 'order' ? '订单处理费' : '仓库其他处理费'}登记模板.xlsx`); if (result?.success === false) throw new Error(result.message); }, importError); }
async function previewImport(confirm) {
  if (!can('import') || !file.value) return;
  await guard(async () => {
    const data = new FormData(); data.append('file', file.value); data.append('kind', kind.value);
    if (confirm) { data.append('confirm', 'true'); data.append('sha256', importPreview.value.sha256); data.append('valid_only', String(validOnly.value)); }
    try { importPreview.value = await api({ method: 'post', url: BASE + 'import/', data, timeout: 60000 }); }
    catch (e) { if (confirm) { importPreview.value = null; throw new Error(`${e.message} 导入结果可能未确认，请保留同一原文件重新校验；不要更换费用编号重复新增。`); } throw e; }
    importPage.value = 1;
    if (confirm) { feedback.value = `已导入${importPreview.value.created}条草稿；列表仍受当前筛选条件限制。`; await refreshAfterWrite(); }
  }, importError);
}
function showBatch(batch) { batchHistory.value = true; importPreview.value = { confirmed: true, results: batch.results, created: batch.results.filter(r => r.status === 'created').length }; importPage.value = 1; importError.value = ''; importVisible.value = true; }
async function leaveOriginalBill() { return !originalBill.value || await originalBill.value.canLeave(); }
async function changeImportMode(value) { if (!busy.value && await leaveOriginalBill()) importMode.value = value; }
async function beforeImportClose(done) { if (!busy.value && await leaveOriginalBill()) done(); }
function downloadErrors() {
  const escape = x => `"${String(x ?? '').replaceAll('"', '""').replace(/^\s*[=+@-]/, "'$&")}"`;
  const csv = '\ufeff' + [['Excel行号', '来源费用编号', '平台订单号', '原因'], ...importPreview.value.results.filter(r => r.status === 'error').map(r => [r.row, r.reference, r.order_number, r.error])].map(r => r.map(escape).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a'); link.href = url; link.download = '处理费错误清单.csv'; link.click(); URL.revokeObjectURL(url);
}
async function exportRows() { await guard(async () => { const result = await downloadApiFile(`${BASE}export/?${new URLSearchParams(params())}`, '处理费登记.csv'); if (result?.success === false) throw new Error(result.message); }); }
onBeforeRouteLeave(async () => !busy.value && await discard() && await leaveOriginalBill());
onMounted(async () => { await guard(async () => { Object.assign(options, await api({ url: BASE + 'options/' })); optionsReady.value = true; await loadRows(); }); });
</script>

<style scoped>
.boundary, .muted { color: #465971; line-height: 1.65; }
.boundary { margin: 0 0 18px; }
.workspace-card { background: #fff; border: 1px solid #d8e1ec; border-radius: 8px; padding: 18px; }
.filters { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
.filters > .el-input, .filters > .el-select, .filters > .el-date-editor { width: 190px; }
.list-info { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin: 12px 0; color: #465971; }
.total { margin-left: 14px; font-variant-numeric: tabular-nums; color: #182c45; }
.numeric { font-variant-numeric: tabular-nums; }
small { display: block; margin-top: 5px; color: #465971; }
.el-pagination { margin-top: 20px; flex-wrap: wrap; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; }
.form-grid :deep(.el-select), .form-grid :deep(.el-date-editor) { width: 100%; }
h3 { margin: 24px 0 16px; color: #182c45; font-size: 16px; }
.actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin: 20px 0; }
.actions :deep(.el-button + .el-button) { margin-left: 0; }
.file-label { color: #24364c; display: inline-flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.file-label input { max-width: 300px; }
.detail-state { display: flex; align-items: center; gap: 12px; color: #465971; }
:deep(.el-form-item__label), :deep(.el-input__inner::placeholder) { color: #465971; }
@media (max-width: 700px) { .form-grid { grid-template-columns: 1fr; } .filters > .el-input, .filters > .el-select, .filters > .el-date-editor { width: 100%; } .workspace-card { padding: 12px; } }
</style>
