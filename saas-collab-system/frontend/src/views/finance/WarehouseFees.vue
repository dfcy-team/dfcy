<template>
  <AppPage title="处理费登记" subtitle="登记仓库已发生或已出账的费用，分别保留订单归属与国家归属。" capability="内部登记">
    <template #action>
      <el-button v-if="can('export') && kind !== 'imports'" :disabled="busy" @click="exportRows">导出筛选结果</el-button>
      <el-button v-if="can('import') && kind !== 'imports'" :disabled="busy" @click="openImport">批量登记</el-button>
      <el-button v-if="can('create') && kind !== 'imports'" type="primary" :disabled="busy || !optionsReady" @click="newFee">新建登记</el-button>
    </template>
    <p class="boundary">新上传原文件和新建登记的金额均直接按 CNY 登记，不换算。店铺由本地订单匹配；未匹配或有歧义的费用保留待核对草稿，不能确认登记。金额可调整并保留原值及历史。历史账单沿用原登记规则。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon role="alert" />
    <el-alert v-if="feedback" :title="feedback" type="success" :closable="false" show-icon role="status" />
    <el-tabs :model-value="kind" :before-leave="beforeTab" @update:model-value="switchKind">
      <el-tab-pane label="仓库处理费" name="order" /><el-tab-pane label="其他处理费" name="other" />
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
      <div class="list-info"><span>共 {{ count ?? '—' }} 条 · 已登记金额：<template v-if="totals.length"><span v-for="total in totals" :key="total.currency" class="total">{{ money(total.amount) }} {{ total.currency }}</span></template><template v-else>—</template></span>
        <el-button v-if="can('register')" :disabled="busy || !selection.length" @click="registerSelection">确认所选草稿（{{ selection.length }}）</el-button>
      </div>
      <el-table v-loading="busy" :data="rows" row-key="id" :empty-text="error ? '读取失败，请重新查询。' : '暂无费用登记，可新建登记或上传原文件。'" @selection-change="selection = $event">
        <el-table-column v-if="can('register')" type="selection" width="44" :selectable="canRegister" />
        <el-table-column prop="warehouse_code" label="仓库" min-width="140" />
        <el-table-column prop="country" label="国家" width="90" />
        <el-table-column v-if="kind === 'order'" prop="store_code" label="店铺" min-width="130" />
        <el-table-column v-if="kind === 'order'" prop="external_order_id" label="订单号" min-width="200" />
        <el-table-column v-else prop="fee_item" label="费用名称" min-width="180" />
        <el-table-column label="金额" min-width="150" align="right"><template #default="{ row }"><b class="numeric" :title="row.amount">{{ money(row.amount) }} {{ row.currency }}</b></template></el-table-column>
        <el-table-column prop="bill_month" label="来源月份" width="130" />
        <el-table-column label="状态" min-width="135"><template #default="{ row }"><el-tag :type="row.status === 'registered' ? 'success' : row.status === 'void' ? 'info' : 'warning'">{{ statuses[row.status] }}</el-tag><small>{{ matches[row.match_status] }}</small><small v-if="row.source.possible_duplicate">疑似重复计费（已保留）</small><small v-if="row.source.type === 'warehouse_settlement_adjustment'">结算差额，随明细登记自动重算</small></template></el-table-column>
        <el-table-column label="操作" fixed="right" width="110"><template #default="{ row }"><el-button link type="primary" :disabled="busy" @click="openFee(row)">详情</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" v-model:page-size="size" :page-sizes="[20, 50, 100]" :total="count || 0" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="query" />
    </section>
    <section v-else class="workspace-card" aria-label="我的导入记录">
      <p>仅显示本人最近50个导入批次。导入仅生成草稿，不自动确认登记。</p>
      <el-table v-loading="busy" :data="batches" empty-text="暂无导入记录。"><el-table-column prop="id" label="批次" width="90" /><el-table-column prop="file_name" label="文件" min-width="250" /><el-table-column label="时间" min-width="180"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column><el-table-column label="结果" min-width="200"><template #default="{ row }">{{ row.results.length }} 条 · 错误 {{ row.results.filter(r => r.status === 'error').length }} 条</template></el-table-column><el-table-column label="明细" width="110"><template #default="{ row }"><el-button link type="primary" @click="showBatch(row)">查看结果</el-button></template></el-table-column></el-table>
    </section>

    <el-dialog v-if="!selected" v-model="editor" class="warehouse-create-dialog" title="新建登记" width="min(600px, calc(100vw - 32px))" align-center :before-close="beforeEditorClose" :close-on-click-modal="false" :show-close="false">
      <template #header><div class="create-heading"><strong>新建登记</strong><el-button :disabled="busy" @click="beforeEditorClose(() => editor = false)">关闭</el-button></div></template>
      <el-alert v-if="editorError" :title="editorError" type="error" :closable="false" show-icon role="alert" />
      <el-form label-position="top" :disabled="busy" @submit.prevent="save">
        <el-form-item label="费用类型"><el-select v-model="form.kind" @change="changeNewFeeKind"><el-option label="仓库处理费" value="order" /><el-option label="其他处理费" value="other" /></el-select></el-form-item>
        <el-form-item label="国家" required><el-select v-model="form.country" @change="clearOwnership"><el-option v-for="site in options.countries" :key="site.code" :label="`${site.code} · ${site.name}`" :value="site.code" /></el-select></el-form-item>
        <el-form-item label="仓库" required><el-select v-model="form.warehouse_id" filterable><el-option v-for="wh in formWarehouses" :key="wh.id" :value="wh.id" :label="`${wh.code} · ${wh.name}`" /></el-select></el-form-item>
        <template v-if="form.kind === 'order'">
          <el-form-item label="订单号／预约单号／包裹号" required><el-input v-model="form.external_order_id" maxlength="191" /></el-form-item>
          <p class="muted">店铺在保存时按本地订单匹配，未匹配保留草稿。也支持完整运单号。</p>
        </template>
        <el-form-item v-else label="费用名称" required><el-input v-model="form.fee_item" maxlength="80" placeholder="如仓储费、退货入库费" /></el-form-item>
        <el-form-item label="金额（CNY）" required><el-input v-model="form.amount" inputmode="decimal" /></el-form-item>
        <el-form-item label="来源月份" required><el-date-picker v-model="form.bill_month" type="month" value-format="YYYY-MM" /></el-form-item>
        <p class="muted">金额数字直接按 CNY 登记。保存后进入草稿列表。</p>
        <el-button type="primary" native-type="submit" :loading="busy">保存草稿</el-button>
      </el-form>
    </el-dialog>
    <el-drawer v-else v-model="editor" :title="`费用登记 #${selected.id}`" size="min(900px, 100vw)" :before-close="beforeEditorClose" :close-on-click-modal="false" :show-close="!busy">
      <el-alert v-if="editorError" :title="editorError" type="error" :closable="false" show-icon role="alert" />
      <template v-if="selected && !editMode">
        <el-alert v-if="selected.possible_duplicate_count" :title="`同账单、同归属和费用项目还有${selected.possible_duplicate_count}条记录，请核对是否分包计费或重复登记。`" type="warning" :closable="false" show-icon />
        <p class="detail-state"><el-tag>{{ statuses[selected.status] }}</el-tag> {{ matches[selected.match_status] }} · 版本 {{ selected.version }}</p>
        <el-descriptions :column="1" border aria-label="费用业务信息">
          <el-descriptions-item label="仓库">{{ selected.warehouse_code || '待核对' }}</el-descriptions-item>
          <el-descriptions-item label="国家">{{ selected.country }}</el-descriptions-item>
          <el-descriptions-item v-if="selected.kind === 'order'" label="店铺">{{ selected.store_code || '待匹配店铺' }}</el-descriptions-item>
          <el-descriptions-item v-if="selected.kind === 'order'" label="订单号">{{ selected.external_order_id || '待匹配订单' }}</el-descriptions-item>
          <el-descriptions-item v-else label="费用名称">{{ selected.fee_item }}</el-descriptions-item>
          <el-descriptions-item label="金额"><span :title="selected.amount">{{ money(selected.amount) }} {{ selected.currency }}</span></el-descriptions-item>
          <el-descriptions-item label="来源月份">{{ selected.bill_month }}</el-descriptions-item>
        </el-descriptions>
        <h3>来源与匹配依据</h3>
        <el-descriptions :column="1" border aria-label="费用来源依据">
          <el-descriptions-item label="来源文件">{{ selected.source.file_name || '手工登记' }}</el-descriptions-item>
          <el-descriptions-item v-if="selected.source.sheet" label="工作表／原行">{{ selected.source.sheet }} · 第 {{ selected.source.row }} 行</el-descriptions-item>
          <el-descriptions-item label="原始号码">{{ selected.source.original_order_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="原登记金额"><span :title="String(originalAmount ?? '')">{{ money(originalAmount) }} {{ selected.currency }}</span></el-descriptions-item>
          <el-descriptions-item v-if="selected.source.raw_amount != null" label="原文件金额"><span :title="String(selected.source.raw_amount)">{{ money(selected.source.raw_amount) }}{{ simpleMode ? ' CNY' : '' }}</span></el-descriptions-item>
          <el-descriptions-item label="匹配依据">{{ matches[selected.match_status] }}<p v-for="candidate in selected.source.matching?.candidates || []" :key="candidate.order_id">{{ candidate.external_order_id }} · {{ storeLabel(candidate.store_id) }}</p></el-descriptions-item>
          <el-descriptions-item v-if="selected.source.rule_id || selected.source.applied_rule" label="解析规则">{{ selected.source.applied_rule?.name || selected.source.rule_id }}</el-descriptions-item>
          <el-descriptions-item label="备注">{{ selected.note || '—' }}</el-descriptions-item>
        </el-descriptions>
        <el-collapse><el-collapse-item title="历史账单及换汇依据" name="source">
          <p>账单编号：{{ selected.bill_number }} · 来源费用编号：{{ selected.reference }}</p>
          <p>发生日期：{{ selected.occurred_on || '未提供，仅有月份' }}</p>
          <p>原币金额：{{ selected.original_amount != null ? `${money(selected.original_amount)} ${selected.original_currency}` : '未提供' }}</p>
          <p>{{ selected.exchange_rate ? `1 ${selected.original_currency} = ${selected.exchange_rate} ${selected.currency}；${selected.rate_date} · ${selected.rate_source}` : '登记金额不重复换汇' }}</p>
        </el-collapse-item></el-collapse>
        <p v-if="['warehouse_settlement_adjustment', 'warehouse_file_supplement'].includes(selected.source.type)">结算依据：{{ selected.source.file_name }}；系统差额由来源政策维护，不能独立修改或作废。</p>
        <div v-else class="actions"><el-button v-if="can('edit') && selected.status !== 'void'" @click="beginEdit">{{ selected.status === 'draft' ? '编辑草稿' : '更正登记（留存历史）' }}</el-button><el-button v-if="can('register') && selected.status === 'draft'" type="primary" :disabled="busy || !canRegister(selected)" @click="singleAction('register')">确认登记</el-button><el-button v-if="can('edit') && selected.kind === 'order' && selected.status !== 'void'" :disabled="busy" @click="singleAction('link')">重新关联订单</el-button><el-button v-if="can('void') && selected.status === 'registered'" type="danger" plain :disabled="busy" @click="singleAction('void')">作废登记</el-button></div>
        <h3>操作与更正历史</h3><el-timeline><el-timeline-item v-for="event in selected.audit || []" :key="event.id" :timestamp="formatTime(event.created_at)"><b>{{ actionLabels[event.action] || event.action }}</b><p>{{ event.detail.reason || '—' }} · 操作人 #{{ event.actor }}</p><p v-if="['edit', 'correct'].includes(event.action)">金额：{{ money(event.detail.before.amount) }} {{ event.detail.before.currency }} → {{ money(event.detail.after.amount) }} {{ event.detail.after.currency }}</p></el-timeline-item></el-timeline>
      </template>
      <el-form v-else label-position="top" :disabled="busy" @submit.prevent="save">
        <h3>费用归属</h3><div class="form-grid">
          <el-form-item label="国家" required><el-select v-model="form.country" :disabled="Boolean(selected)" @change="clearOwnership"><el-option v-for="site in options.countries" :key="site.code" :label="`${site.code} · ${site.name}`" :value="site.code" /></el-select></el-form-item>
          <el-form-item label="仓库" required><el-select v-model="form.warehouse_id" :disabled="Boolean(selected)" filterable><el-option v-for="wh in formWarehouses" :key="wh.id" :value="wh.id" :label="`${wh.code} · ${wh.name}`" /></el-select></el-form-item>
          <el-form-item v-if="form.kind === 'order'" label="店铺（自动匹配）"><el-input :model-value="selected?.store_code || '保存草稿后，按号码匹配本地订单及店铺'" readonly /></el-form-item>
          <el-form-item v-if="form.kind === 'order'" label="订单号／预约单号／包裹号" required><el-input v-model="form.external_order_id" :disabled="Boolean(selected)" placeholder="也支持完整运单号；店铺自动匹配" maxlength="191" /></el-form-item>
        </div><h3>账单信息</h3><div class="form-grid">
          <el-form-item v-if="!simpleMode" label="账单编号"><el-input v-model="form.bill_number" disabled /></el-form-item><el-form-item label="来源月份" required><el-date-picker v-model="form.bill_month" type="month" value-format="YYYY-MM" :disabled="Boolean(selected)" /></el-form-item>
          <el-form-item v-if="form.kind === 'other' || !simpleMode" label="费用名称" required><el-input v-model="form.fee_item" :disabled="Boolean(selected)" maxlength="80" placeholder="如仓储费、退货入库费" /></el-form-item><el-form-item v-if="!simpleMode" label="来源费用编号"><el-input v-model="form.reference" disabled /></el-form-item>
          <el-form-item v-if="!simpleMode" label="发生日期（可仅保留月份）"><el-date-picker v-model="form.occurred_on" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD；未知可留空" /></el-form-item>
        </div><h3>登记金额</h3><p class="muted">{{ simpleMode ? '输入数字直接视为人民币，不识别原币、不进行换汇。' : '历史记录沿用原币种及换汇依据。' }} “已登记”不代表已经付款。</p><div class="form-grid">
          <el-form-item :label="simpleMode ? '金额（CNY）' : '结算金额'" required><el-input v-model="form.amount" inputmode="decimal" placeholder="大于0，最多6位小数" /></el-form-item><el-form-item v-if="!simpleMode" label="结算币种" required><el-select v-model="form.currency"><el-option v-for="c in options.currencies" :key="c" :label="c" :value="c" /></el-select></el-form-item>
        </div><el-collapse v-if="!simpleMode"><el-collapse-item title="原币与换汇信息（可全部留空）" name="fx"><p class="muted">1 原币 = 汇率 × 结算币。填写后需同时提供金额、币种、汇率、日期及来源。</p><div class="form-grid"><el-form-item label="原币金额"><el-input v-model="form.original_amount" inputmode="decimal" /></el-form-item><el-form-item label="原币币种"><el-select v-model="form.original_currency" clearable><el-option v-for="c in options.currencies" :key="c" :label="c" :value="c" /></el-select></el-form-item><el-form-item label="兑换汇率"><el-input v-model="form.exchange_rate" inputmode="decimal" /></el-form-item><el-form-item label="汇率日期"><el-date-picker v-model="form.rate_date" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="汇率来源"><el-input v-model="form.rate_source" maxlength="191" /></el-form-item></div></el-collapse-item></el-collapse>
        <p v-if="selected && simpleMode">原登记金额：{{ money(originalAmount) }} CNY <el-button link type="primary" :disabled="originalAmount == null" @click="restoreOriginalAmount">恢复原金额</el-button></p>
        <el-form-item label="备注"><el-input v-model="form.note" type="textarea" maxlength="500" :rows="2" /></el-form-item><el-form-item v-if="selected && (simpleMode || selected.status === 'registered')" label="调整原因" required><el-input v-model="correctionReason" type="textarea" :rows="2" maxlength="500" /></el-form-item>
        <div class="actions"><el-button type="primary" native-type="submit" :loading="busy">{{ selected?.status === 'registered' ? '保存更正并留存历史' : '保存草稿' }}</el-button><el-button v-if="selected" :disabled="busy" @click="cancelFeeEdit">取消修改</el-button></div>
      </el-form>
    </el-drawer>

    <el-dialog v-model="importVisible" :title="batchHistory ? '导入结果' : '处理费批量登记'" class="warehouse-batch-dialog" width="min(1200px, calc(100vw - 32px))" top="4vh" :close-on-click-modal="false" :before-close="beforeImportClose" destroy-on-close>
      <template #header><div class="batch-dialog-heading"><div><strong>{{ batchHistory ? '导入结果' : '处理费批量登记' }}</strong><p v-if="!batchHistory">批量核对工作台 · 完成后返回处理费列表</p></div><el-button @click="beforeImportClose(() => importVisible = false)">返回登记列表</el-button></div></template>
      <WarehouseBillUpload v-if="!batchHistory" ref="originalBill" :options="options" @imported="refreshAfterWrite" />
      <template v-else>
      <template v-if="importPreview"><p>共 {{ importPreview.results.length }} 条，错误 {{ importPreview.results.filter(r => r.status === 'error').length }} 条。{{ importPreview.confirmed ? `本次新增${importPreview.created}条草稿。` : '预览不写入费用。' }}</p>
        <el-table :data="importPreview.results.slice((importPage - 1) * 20, importPage * 20)" max-height="440"><el-table-column prop="row" label="Excel行号" width="105" /><el-table-column prop="reference" label="费用编号" min-width="160" /><el-table-column prop="order_number" label="平台订单号" min-width="180" /><el-table-column label="结果" width="110"><template #default="{ row }">{{ importStates[row.status] }}</template></el-table-column><el-table-column label="关联／错误" min-width="300"><template #default="{ row }">{{ row.error || matches[row.match_status] }}</template></el-table-column></el-table>
        <el-pagination v-model:current-page="importPage" :page-size="20" :total="importPreview.results.length" layout="total, prev, pager, next" />
        <div class="actions"><el-button v-if="importPreview.results.some(r => r.status === 'error')" @click="downloadErrors">下载错误清单</el-button></div>
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
import { warehouseMoney as money } from '../../utils/warehouseMoney';
import { requestApi, downloadApiFile } from '../../api/request';
import { useAuthStore } from '../../stores/auth';

const BASE = '/api/finance/warehouse-fees/';
const auth = useAuthStore();
const can = action => auth.hasPermission(`finance.warehouse_fees.${action}`);
const statuses = { draft: '草稿', registered: '已登记（不代表付款）', void: '已作废' };
const matches = { matched: '已关联订单', unmatched: '待核对：未关联本地订单', ambiguous: '待核对：关联有歧义', not_applicable: '国家级费用' };
const systemFee = row => ['warehouse_settlement_adjustment', 'warehouse_file_supplement'].includes(row?.source?.type);
const canRegister = row => row?.status === 'draft' && Boolean(row.warehouse_id) && !systemFee(row) && (row.kind !== 'order' || row.match_status === 'matched');
const actionLabels = { create: '新建草稿', edit: '编辑草稿', register: '确认登记', correct: '更正登记', link: '核对订单关联', void: '作废登记', settlement_reconcile: '结算差额重算' };
const importStates = { valid: '校验通过', existing: '已存在，跳过', error: '错误，不导入', created: '已导入草稿' };
const editable = ['amount', 'currency', 'original_amount', 'original_currency', 'exchange_rate', 'rate_date', 'rate_source', 'occurred_on', 'note'];
const kind = ref('order'), busy = ref(false), rows = ref([]), count = ref(null), totals = ref([]), page = ref(1), size = ref(20), selection = ref([]), batches = ref([]);
const filters = reactive({ bill_month: '', country: '', warehouse_id: '', store_id: '', order_number: '', status: '', match_status: '' });
const options = reactive({ countries: [], warehouses: [], stores: [], currencies: [] }), optionsReady = ref(false);
const error = ref(''), feedback = ref(''), editorError = ref(''), editor = ref(false), selected = ref(null), editMode = ref(false), form = reactive({}), correctionReason = ref('');
const importVisible = ref(false), batchHistory = ref(false), importPreview = ref(null), importPage = ref(1), cleanForm = ref('');
const originalBill = ref(null);
const filterWarehouses = computed(() => options.warehouses.filter(w => !filters.country || w.country === filters.country));
const filterStores = computed(() => options.stores.filter(s => !filters.country || s.country === filters.country));
const formWarehouses = computed(() => options.warehouses.filter(w => w.country === form.country));
const simpleMode = computed(() => !selected.value || ['cny_simple', 'cny_original_v1', 'file_settlement_v2'].includes(selected.value.source?.registration_mode));
const originalAmount = computed(() => selected.value?.source?.registration_original_amount ?? selected.value?.source?.original_data?.amount ?? null);
const storeLabel = id => options.stores.find(store => store.id === id)?.code || (id ? `店铺 #${id}` : '未匹配');
const dirty = computed(() => editor.value && editMode.value && (JSON.stringify(form) !== cleanForm.value || Boolean(correctionReason.value)));
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
function changeNewFeeKind() {
  form.external_order_id = ''; form.store_id = null;
  form.fee_item = form.kind === 'order' ? '订单处理费' : '';
  editorError.value = '';
}
function newFee() {
  if (busy.value || !can('create')) return;
  selected.value = null; editMode.value = true; correctionReason.value = ''; editorError.value = '';
  for (const key of Object.keys(form)) delete form[key];
  Object.assign(form, { kind: kind.value, country: filters.country || '', warehouse_id: null, store_id: null, external_order_id: '',
    bill_number: '', bill_month: filters.bill_month || '', fee_item: kind.value === 'order' ? '订单处理费' : '', reference: `MANUAL:${crypto.randomUUID()}`,
    amount: '', currency: 'CNY', original_amount: '', original_currency: '', exchange_rate: '', rate_date: null, rate_source: '', occurred_on: null, note: '' });
  cleanForm.value = JSON.stringify(form); editor.value = true;
}
async function openFee(row) { await guard(async () => { selected.value = await api({ url: `${BASE}${row.id}/` }); editMode.value = false; editorError.value = ''; editor.value = true; }); }
function beginEdit() {
  if (busy.value || !can('edit') || systemFee(selected.value)) return;
  for (const key of Object.keys(form)) delete form[key];
  const identity = ['kind', 'country', 'warehouse_id', 'store_id', 'external_order_id', 'bill_number', 'bill_month', 'fee_item', 'reference'];
  for (const key of [...identity, ...editable]) form[key] = selected.value[key] ?? '';
  correctionReason.value = ''; cleanForm.value = JSON.stringify(form); editMode.value = true; editorError.value = '';
}
function restoreOriginalAmount() {
  if (originalAmount.value == null || systemFee(selected.value)) return;
  form.amount = originalAmount.value;
  correctionReason.value = '恢复原登记金额';
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
  if (!can(selected.value ? 'edit' : 'create') || systemFee(selected.value)) return;
  if (selected.value && (simpleMode.value || selected.value.status === 'registered') && !correctionReason.value.trim()) { editorError.value = '请填写调整原因，保留金额更正依据。'; return; }
  await guard(async () => {
    const creating = !selected.value;
    const value = formData();
    const editFields = simpleMode.value ? ['amount', 'note'] : editable;
    const data = selected.value ? { expected_version: selected.value.version, changes: Object.fromEntries(editFields.map(k => [k, value[k]])), reason: correctionReason.value }
      : { registration_mode: 'cny_simple', ...Object.fromEntries(['kind', 'country', 'warehouse_id', 'external_order_id', 'fee_item', 'amount', 'bill_month', 'reference', 'note'].map(k => [k, value[k]])) };
    const url = selected.value ? `${BASE}${selected.value.id}/${selected.value.status === 'registered' ? 'correct' : 'edit'}/` : BASE;
    const saved = await api({ method: 'post', url, data });
    selected.value = saved; editMode.value = false; cleanForm.value = JSON.stringify(form); feedback.value = '已保存费用记录，未发起付款。';
    if (creating) { editor.value = false; kind.value = form.kind; filters.status = 'draft'; page.value = 1; }
    try { selected.value = await api({ url: `${BASE}${saved.id}/` }); } catch { editorError.value = '已保存；详情暂未刷新，请关闭后重新查看。'; }
    await refreshAfterWrite();
  }, editorError);
}
async function singleAction(action) {
  if (busy.value || !can(action === 'link' ? 'edit' : action) || systemFee(selected.value)) return;
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
async function cancelFeeEdit() { if (!busy.value && await discard()) editMode.value = false; }
async function beforeEditorClose(done) { if (!busy.value && await discard()) done(); }
function openImport() { if (busy.value || !can('import')) return; batchHistory.value = false; importPreview.value = null; importPage.value = 1; importVisible.value = true; }
function showBatch(batch) { batchHistory.value = true; importPreview.value = { confirmed: true, results: batch.results, created: batch.results.filter(r => r.status === 'created').length }; importPage.value = 1; importVisible.value = true; }
async function leaveOriginalBill() { return !originalBill.value || await originalBill.value.canLeave(); }
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
:deep(.warehouse-create-dialog) { padding:24px; max-height:calc(100vh - 32px); overflow:auto; }
.create-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.create-heading strong { font-size:18px; color:#182c45; }
:deep(.warehouse-create-dialog .el-select), :deep(.warehouse-create-dialog .el-date-editor) { width:100%; }
:deep(.warehouse-batch-dialog) { max-width:calc(100vw - 32px); margin-bottom:4vh; }
:deep(.warehouse-batch-dialog .el-dialog__body) { max-height:calc(92vh - 100px); overflow:auto; }
:deep(.el-descriptions__content) { overflow-wrap:anywhere; }

.batch-dialog-heading { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px; padding-right:32px; }
.batch-dialog-heading p { margin:6px 0 0; color:#465971; font-size:13px; }
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
.detail-state { display: flex; align-items: center; gap: 12px; color: #465971; }
:deep(.el-form-item__label), :deep(.el-input__inner::placeholder) { color: #465971; }
@media (max-width: 700px) { .form-grid { grid-template-columns: 1fr; } .filters > .el-input, .filters > .el-select, .filters > .el-date-editor { width: 100%; } .workspace-card { padding: 12px; } }
</style>
