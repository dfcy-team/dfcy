<template>
  <section aria-label="原始仓库账单解析">
    <p class="muted">直接选择 Z:\处理费 中的原始 xlsx 账单，每份最多128MB。自动区分订单处理费和其他费用；上传只暂存解析，不登记、不付款、不改订单。</p>
    <p class="muted">仅匹配本地SaaS数据，不查询 financial_data、不调用平台接口。预约单优先通过本地归档 booking_sn → order_sn 关联订单，缺少对应关系再通过完整运单匹配；系统店铺取自实际订单。</p>
    <div class="upload-line">
      <label>选择原始账单<input type="file" accept=".xlsx" :disabled="busy || active || pendingEdit" @change="upload" /></label>
      <el-select v-model="historyId" placeholder="继续查看最近上传" aria-label="最近上传的原账单" :disabled="busy || pendingEdit" @change="selectHistory">
        <el-option v-for="item in history" :key="item.id" :value="item.id" :label="`${item.file_name} · ${states[item.status] || item.status}`" />
      </el-select>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon role="alert" />
    <el-alert v-if="feedback" :title="feedback" type="success" :closable="false" show-icon role="status" />
    <p v-if="uploadPercent !== null" role="status">上传中 {{ uploadPercent }}% · 上传完成后自动开始解析</p>
    <template v-if="job">
      <p class="job-state" role="status"><strong>{{ job.file_name }}</strong> · {{ states[job.status] || job.status }}<span v-if="active"> · 已处理 {{ job.processed }} 行</span><el-button :loading="busy" :disabled="pendingEdit" @click="refresh">刷新状态</el-button></p>
      <el-button v-if="!active && !hasImported && ['ready', 'failed'].includes(job.status)" :disabled="busy || pendingEdit" aria-label="重新匹配本地订单" @click="reparse">重新解析并匹配本地订单</el-button>
      <el-alert v-if="job.error" :title="job.error" type="warning" :closable="false" show-icon />
      <el-alert v-if="job.summary?.settlement_summary_only" title="已读取业务结算清单，订单明细尚未重新解析；未分配金额已保留为待核对差额，不代表明细已全部核对。" type="info" :closable="false" show-icon />
      <p v-if="job.status === 'queued'" class="muted">等待后台解析，不占用页面。可关闭窗口，稍后从“最近上传”继续查看。</p>
      <template v-if="job.summary?.country">
        <template v-if="job.summary.settlement">
          <p><strong>业务结算清单：{{ job.summary.settlement.total }} {{ job.summary.settlement.currency || '币种待确认' }}</strong>。其他工作表仅作为明细依据，不重复叠加费用。</p>
          <p v-if="job.summary.settlement_result" role="status">已登记 {{ job.summary.settlement_result.registered_total }} {{ job.summary.settlement_result.currency }}；未落实到订单的金额保留在仓库其他处理费。</p>
          <p v-for="item in job.summary.settlement_result?.adjustments || []" :key="item.id" class="muted">{{ item.item }}：{{ item.amount }} {{ job.summary.settlement.currency }} · {{ item.warehouse_id ? archiveLabel('warehouses', item.warehouse_id) : '仓库待分配' }}</p>
          <el-button v-if="canSettle() && !active" :loading="busy" :disabled="pendingEdit || !job.summary.settlement.valid" @click="confirmSettlement">按结算清单登记／重算差额</el-button>
        </template>
        <p>{{ job.summary.country }} · {{ job.summary.bill_month }} · {{ job.summary.format }} · 订单费用 {{ job.summary.counts?.order || 0 }} 条，其他费用 {{ job.summary.counts?.other || 0 }} 条</p>
        <p class="muted">原账单金额合计（含待核对）：<span v-for="total in job.summary.totals" :key="total.currency">{{ total.amount }} {{ total.currency }}　</span></p>
        <p v-if="job.summary.corrected_totals" class="muted">修正后金额合计（含待核对）：<span v-for="total in job.summary.corrected_totals" :key="total.currency">{{ total.amount }} {{ total.currency }}　</span>修改金额不改变原账单对账结果。</p>
        <p class="muted">订单对账：明细 {{ job.summary.order_detail_sum }} / 账单 {{ job.summary.order_bill_total ?? '缺失' }}；差额 {{ job.summary.order_difference ?? '无法核对' }} {{ job.summary.currency }}</p>
        <p v-if="job.summary.corrected_totals" class="muted">修正后订单差额：{{ job.summary.corrected_order_difference ?? '无法核对' }} {{ job.summary.currency }}</p>
        <el-alert v-if="job.summary.correction_warning" :title="job.summary.correction_warning" type="warning" :closable="false" show-icon />
        <el-alert v-for="warning in job.summary.warnings || []" :key="warning" :title="warning" type="warning" :closable="false" />
      </template>
      <el-collapse v-if="!active && !hasImported && hasMappings">
        <el-collapse-item title="本账单店铺与仓库映射" name="mapping">
          <p class="muted">映射仅影响此账单，不修改档案。</p>
          <div v-for="group in ['warehouses', 'stores']" :key="group">
            <label v-for="item in job.summary?.unresolved?.[group] || []" :key="item.name" class="mapping-row">
              <span>{{ group === 'warehouses' ? '仓库' : '店铺' }}：{{ item.name || '原单未标明（本账单统一）' }} · {{ item.count }} 行</span>
              <el-select v-model="settings[group][item.name]" clearable filterable :disabled="pendingEdit || busy" :aria-label="`映射${group === 'warehouses' ? '仓库' : '店铺'}${item.name}`">
                <el-option v-for="target in mappingOptions(group)" :key="target.id" :value="target.id" :label="`${target.code} · ${target.name}`" />
              </el-select>
            </label>
          </div>
          <el-button :loading="busy" :disabled="pendingEdit" aria-label="应用本账单店铺与仓库映射" @click="reparse">应用映射（不导入）</el-button>
        </el-collapse-item>
      </el-collapse>
      <template v-if="['ready', 'completed', 'failed'].includes(job.status) && job.summary?.country">
        <div class="preview-controls">
          <span>待导入 {{ job.counts?.valid || 0 }} · 待核对 {{ job.counts?.error || 0 }} · 已新增 {{ job.counts?.created || 0 }} · 已存在 {{ job.counts?.existing || 0 }}</span>
          <el-button v-if="job.counts?.error" :disabled="pendingEdit || busy" aria-label="查看待核对区" @click="rowStatus = 'error'; query()">待核对区（{{ job.counts.error }}）</el-button>
          <el-select v-model="rowStatus" clearable :disabled="pendingEdit || busy" placeholder="全部解析结果" aria-label="解析结果筛选" @change="query"><el-option v-for="(label, value) in rowStates" :key="value" :label="label" :value="value" /></el-select>
          <el-select v-model="rowKind" clearable :disabled="pendingEdit || busy" placeholder="两类费用" aria-label="原账单费用类型" @change="query"><el-option label="订单处理费" value="order" /><el-option label="仓库其他处理费" value="other" /></el-select>
        </div>
        <p v-if="hasImported" class="muted">此账单已有导入结果，预览只读；需要修改时请到处理费草稿中处理。</p>
        <p v-else class="muted">仅修正本账单的待导入值，不修改原文件。展开行可查看原始值和修改记录。</p>
        <el-table ref="previewTable" :data="job.results || []" row-key="number" max-height="390" aria-label="原账单解析预览" @selection-change="selectedRows = $event">
          <el-table-column v-if="editable" type="selection" width="44" :selectable="row => !busy && !editRow && ['valid', 'error'].includes(row.status)" />
          <el-table-column type="expand"><template #default="{ row }">
            <div class="row-details">
              <p>原始解析值（不随人工修正改变）：{{ archiveLabel('stores', original(row).store_id) }} / {{ archiveLabel('warehouses', original(row).warehouse_id) }}</p>
              <p>平台订单号：{{ original(row).external_order_id || '—' }}；金额：{{ original(row).amount ?? row.source.raw_amount }} {{ original(row).currency }}；费用项目：{{ original(row).fee_item || '—' }}</p>
              <p v-if="row.source.original_order_id">原账单编号：{{ row.source.original_order_id }}；运单号：{{ row.source.tracking_numbers?.join('、') || '未提供' }}</p>
              <p v-if="row.source.settlement_evidence">原币明细：{{ row.source.settlement_evidence.original_amount }} {{ row.source.settlement_evidence.original_currency }}；结算依据：{{ row.source.settlement_evidence.settlement_amount }} {{ row.source.settlement_evidence.settlement_currency }}，不重复登记两种币种。</p>
              <p v-for="candidate in row.source.matching?.candidates || []" :key="candidate.order_id">{{ row.match_status === 'bf_candidate' ? '待确认候选' : '本地订单' }}：{{ candidate.external_order_id }} · {{ archiveLabel('stores', candidate.store_id) }}</p>
              <p>发生日期：{{ row.data.occurred_on || '仅有月份' }}；备注：{{ row.data.note || '—' }}</p>
              <el-button :disabled="busy" @click="loadAudit(row)">查看修改记录</el-button>
              <p v-if="auditRows[row.number]?.length === 0" class="muted">暂无修改记录。</p>
              <div v-for="event in auditRows[row.number] || []" :key="event.id" class="audit-entry">
                <p>{{ event.action === 'restore' ? '恢复原始值' : '编辑' }} · 操作人 #{{ event.actor }} · {{ formatTime(event.at) }} · {{ event.detail.reason || '未填写原因' }}</p>
                <p v-for="field in changedFields(event.detail.before, event.detail.after)" :key="field">{{ fieldLabels[field] || field }}：{{ displayField(field, event.detail.before[field]) }} → {{ displayField(field, event.detail.after[field]) }}</p>
              </div>
            </div>
          </template></el-table-column>
          <el-table-column label="来源" min-width="155"><template #default="{ row }">{{ row.source.sheet }}!{{ row.source.row }}</template></el-table-column>
          <el-table-column label="类型／费用项目" min-width="170"><template #default="{ row }">{{ row.data.kind === 'order' ? '订单' : '其他' }} · <el-input v-if="editRow?.number === row.number" v-model="editForm.fee_item" aria-label="编辑费用项目" :disabled="busy" maxlength="80" /><template v-else>{{ row.data.fee_item }}</template></template></el-table-column>
          <el-table-column label="原店铺／原仓库" min-width="160"><template #default="{ row }">{{ row.source.raw_store || '—' }} / {{ row.source.raw_warehouse || '未标明' }}</template></el-table-column>
          <el-table-column label="系统店铺／系统仓库" min-width="210"><template #default="{ row }">
            <template v-if="editRow?.number === row.number">
              <el-select v-if="row.data.kind === 'order'" v-model="editForm.store_id" filterable clearable aria-label="编辑系统店铺" :disabled="busy"><el-option v-for="item in mappingOptions('stores')" :key="item.id" :value="item.id" :label="`${item.code} · ${item.name}`" /></el-select>
              <el-select v-model="editForm.warehouse_id" filterable aria-label="编辑系统仓库" :disabled="busy"><el-option v-for="item in mappingOptions('warehouses')" :key="item.id" :value="item.id" :label="`${item.code} · ${item.name}`" /></el-select>
            </template>
            <template v-else>{{ row.data.kind === 'other' ? '国家级费用' : archiveLabel('stores', row.data.store_id) }}<small>{{ archiveLabel('warehouses', row.data.warehouse_id) }}</small></template>
          </template></el-table-column>
          <el-table-column label="平台订单号" min-width="210"><template #default="{ row }"><el-input v-if="editRow?.number === row.number && row.data.kind === 'order'" v-model="editForm.external_order_id" aria-label="编辑平台订单号" :disabled="busy" maxlength="191" /><template v-else>{{ row.data.external_order_id || '—' }}</template></template></el-table-column>
          <el-table-column label="结算金额" min-width="190"><template #default="{ row }"><template v-if="editRow?.number === row.number">
            <el-input v-model="editForm.amount" inputmode="decimal" aria-label="编辑结算金额" :disabled="busy" />
            <el-select v-model="editForm.currency" aria-label="编辑结算币种" :disabled="busy"><el-option v-for="currency in options.currencies" :key="currency" :value="currency" :label="currency" /></el-select>
          </template><template v-else>{{ row.data.amount ?? '缺失' }} {{ row.data.currency }}</template></template></el-table-column>
          <el-table-column label="解析结果／订单关联" min-width="230"><template #default="{ row }">{{ rowStates[row.status] }}<small v-if="row.source.possible_duplicate">疑似重复计费（已保留，未删除）</small><small v-if="row.source.order_unlinked">未关联本地 SaaS 订单，待核对，暂不登记</small><small>{{ matches[row.match_status] || '订单关联待核对' }}<span v-if="row.source.correction"> · 已修正</span></small><small v-if="row.error">{{ row.error }}</small></template></el-table-column>
          <el-table-column v-if="editable" label="操作" fixed="right" width="150"><template #default="{ row }">
            <template v-if="editRow?.number === row.number"><el-button link type="primary" :loading="busy" @click="saveEdit">保存并校验</el-button><el-button link :disabled="busy" @click="cancelEdit">取消</el-button></template>
            <template v-else><el-button link type="primary" :disabled="busy || pendingEdit" @click="startEdit(row)">编辑</el-button><el-button v-if="row.source.correction || row.source.correction_conflict" link :disabled="busy || pendingEdit" @click="restoreRow(row)">恢复原始值</el-button></template>
          </template></el-table-column>
        </el-table>
        <section v-if="editRow" class="edit-extra" aria-label="本行编辑补充信息">
          <p>正在编辑 {{ editRow.source.sheet }}!{{ editRow.source.row }}；请保存或取消后再翻页、筛选或导入。</p>
          <p v-if="busy" role="status">正在保存并重新检查整份账单，请等待，不要重复提交。</p>
          <label>发生日期<el-date-picker v-model="editForm.occurred_on" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" aria-label="编辑发生日期" :disabled="busy" /></label>
          <label>备注<el-input v-model="editForm.note" aria-label="编辑备注" maxlength="500" :disabled="busy" /></label>
          <label>修改原因{{ reasonRequired ? '（必填）' : '（选填）' }}<el-input v-model="editReason" aria-label="本行修改原因" maxlength="500" :disabled="busy" /></label>
          <p class="muted">金额最多六位小数；更改币种仅修正登记币种，不自动换算金额。</p>
        </section>
        <section v-if="editable && selectedRows.length && !editRow" class="batch-edit" aria-label="批量修正所选记录">
          <span>已选 {{ selectedRows.length }} 条（仅当前页勾选记录）</span>
          <el-select v-model="batchField" aria-label="批量修改字段" :disabled="busy" @change="batchValue = ''"><el-option label="系统店铺" value="store_id" /><el-option label="系统仓库" value="warehouse_id" /><el-option label="费用项目" value="fee_item" /></el-select>
          <el-input v-if="batchField === 'fee_item'" v-model="batchValue" aria-label="批量费用项目" maxlength="80" :disabled="busy" />
          <el-select v-else v-model="batchValue" filterable aria-label="批量目标档案" :disabled="busy"><el-option v-for="item in mappingOptions(batchField === 'store_id' ? 'stores' : 'warehouses')" :key="item.id" :value="item.id" :label="`${item.code} · ${item.name}`" /></el-select>
          <el-input v-model="batchReason" aria-label="批量修改原因" placeholder="修改原因" maxlength="500" :disabled="busy" />
          <el-button type="primary" :loading="busy" @click="saveBatch">应用并校验（不导入）</el-button><el-button :disabled="busy" @click="clearSelection">取消批量修改</el-button>
        </section>
        <el-pagination v-model:current-page="page" :page-size="20" :total="job.count || 0" layout="total, prev, pager, next" :disabled="busy || pendingEdit" @current-change="refresh" />
        <div class="preview-controls">
          <el-button v-if="job.counts?.error" :disabled="busy" @click="downloadErrors">下载待核对清单</el-button>
          <el-checkbox v-if="job.counts?.error && job.counts?.valid" v-model="validOnly" :disabled="busy">仅导入有效记录，待核对行不导入</el-checkbox>
          <el-button v-if="job.counts?.valid" type="primary" :loading="busy" :disabled="pendingEdit || Boolean(job.summary.correction_warning) || !canImport() || (Boolean(job.counts?.error) && !validOnly)" @click="confirmImport">确认导入有效草稿（不登记）</el-button>
        </div>
      </template>
      <p v-if="job.status === 'completed'" role="status">导入完成。费用仅保存为草稿，请回到列表核对；没有发起付款或修改订单。</p>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { ElMessageBox } from 'element-plus';
import { requestApi, downloadApiFile } from '../api/request';
import { useAuthStore } from '../stores/auth';

const props = defineProps({ options: { type: Object, required: true } });
const emit = defineEmits(['imported']);
const BASE = '/api/finance/warehouse-fees/original-bills/';
const auth = useAuthStore();
const states = { queued: '等待解析', parsing: '正在解析', ready: '解析完成，待核对', import_queued: '等待导入草稿', importing: '正在导入草稿', completed: '草稿导入完成', failed: '未完成，请核对' };
const rowStates = { valid: '可导入', error: '待核对，不导入', created: '已新增草稿', existing: '已存在，跳过' };
const matches = { matched: '已匹配销售订单', unmatched: '未匹配本地订单', ambiguous: '订单匹配有歧义', not_applicable: '国家级费用，无需关联订单' };
Object.assign(matches, { booking_matched: '预约号已通过本地归档匹配订单', booking_order_missing: '预约对应关系已找到，本地销售订单待补齐', reservation_matched: '预约单已通过运单匹配本地订单', missing_order: '本地未找到订单',
  missing_tracking: '预约单缺少完整运单号', tracking_unmatched: '缺少本地物流关联',
  temu_unintegrated: 'Temu待关联', manual_pending: '疑似手工单，待核实', manual_confirmed: '手工单归属已确认',
  bf_candidate: 'BF附加后缀候选，待确认', country_conflict: '订单国家或平台冲突', store_conflict: '所选店铺与订单冲突' });
const fieldLabels = { store_id: '系统店铺', warehouse_id: '系统仓库', external_order_id: '平台订单号', fee_item: '费用项目', amount: '结算金额', currency: '结算币种', occurred_on: '发生日期', note: '备注' };
const sensitiveFields = ['store_id', 'warehouse_id', 'external_order_id', 'amount', 'currency'];
const job = ref(null), busy = ref(false), error = ref(''), history = ref([]), historyId = ref(''), page = ref(1), rowStatus = ref(''), rowKind = ref(''), validOnly = ref(false), uploadPercent = ref(null);
const feedback = ref(''), previewTable = ref(null), editRow = ref(null), editForm = reactive({}), editReason = ref('');
const selectedRows = ref([]), batchField = ref('warehouse_id'), batchValue = ref(''), batchReason = ref(''), auditRows = reactive({});
const settings = reactive({ country: '', bill_month: '', currency: '', warehouses: {}, stores: {} });
const active = computed(() => ['queued', 'parsing', 'import_queued', 'importing'].includes(job.value?.status));
const hasImported = computed(() => Boolean(job.value?.counts?.created || job.value?.counts?.existing));
const hasMappings = computed(() => ['warehouses', 'stores'].some(group => job.value?.summary?.unresolved?.[group]?.length));
const canImport = () => auth.hasPermission('finance.warehouse_fees.import');
const canSettle = () => canImport() && auth.hasPermission('finance.warehouse_fees.register') && auth.hasPermission('finance.warehouse_fees.edit');
const editable = computed(() => job.value?.status === 'ready' && !hasImported.value && canImport());
const editChanges = computed(() => editRow.value ? Object.fromEntries(Object.keys(fieldLabels)
  .filter(key => (editForm[key] || null) !== (editRow.value.data[key] || null)).map(key => [key, key === 'occurred_on' ? editForm[key] || null : editForm[key]])) : {});
const reasonRequired = computed(() => sensitiveFields.some(key => key in editChanges.value));
const pendingEdit = computed(() => Boolean(editRow.value || (selectedRows.value.length && (batchValue.value !== '' || batchReason.value))));
const dirty = computed(() => Boolean(Object.keys(editChanges.value).length || editReason.value || (selectedRows.value.length && (batchValue.value !== '' || batchReason.value))));
let timer, disposed = false, requestId = 0;
const formatTime = value => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
const original = row => row.source.original_data || row.data;
const changedFields = (before, after) => Object.keys(fieldLabels).filter(field => before?.[field] !== after?.[field]);
function archiveLabel(group, id) {
  const item = props.options[group]?.find(x => x.id === id);
  return item ? `${item.code} · ${item.name}` : id ? `档案 #${id}` : '未匹配';
}
function displayField(field, value) {
  if (field === 'store_id' || field === 'warehouse_id') return archiveLabel(field === 'store_id' ? 'stores' : 'warehouses', value);
  return value ?? '—';
}
function clearSelection() {
  selectedRows.value = []; batchValue.value = ''; batchReason.value = '';
  previewTable.value?.clearSelection?.();
}
function cancelEdit() { if (!busy.value) { editRow.value = null; editReason.value = ''; } }
function startEdit(row) {
  if (!editable.value || busy.value || pendingEdit.value || !['valid', 'error'].includes(row.status)) return;
  clearSelection(); editRow.value = JSON.parse(JSON.stringify(row)); editReason.value = ''; error.value = ''; feedback.value = '';
  for (const key of Object.keys(fieldLabels)) editForm[key] = row.data[key] ?? (['store_id', 'warehouse_id', 'occurred_on'].includes(key) ? null : '');
}
async function saveCorrections(rows, reason, operation = 'edit') {
  await run(async () => {
    const saved = await api({ method: 'post', url: BASE + job.value.id + '/', timeout: 120000,
      data: { operation, version: job.value.version, rows, reason } });
    job.value = { ...job.value, ...saved }; editRow.value = null; editReason.value = ''; clearSelection();
    for (const key of Object.keys(auditRows)) delete auditRows[key];
    validOnly.value = false; feedback.value = '修正已保存并重新校验，未导入、未登记。';
    try { await readCurrent(); } catch (e) { throw new Error(`修正已保存，但预览刷新失败：${e.message}。请刷新状态，不要重复提交。`); }
  });
}
async function saveEdit() {
  if (!editable.value || busy.value || !editRow.value) return;
  if (!Object.keys(editChanges.value).length) { cancelEdit(); return; }
  if (reasonRequired.value && !editReason.value.trim()) { error.value = '修改金额、币种或归属时，请填写修改原因。'; return; }
  await saveCorrections([{ number: editRow.value.number, changes: editChanges.value }], editReason.value.trim());
}
async function saveBatch() {
  if (!editable.value || busy.value || editRow.value || !selectedRows.value.length) return;
  if (!['store_id', 'warehouse_id', 'fee_item'].includes(batchField.value)) return;
  if (!batchValue.value || !batchReason.value.trim()) { error.value = '请选择批量目标并填写修改原因。'; return; }
  if (batchField.value === 'store_id' && selectedRows.value.some(row => row.data.kind !== 'order')) { error.value = '国家级其他费用不能设置店铺，请仅选择订单处理费。'; return; }
  try { await ElMessageBox.confirm(`仅修改明确勾选的${selectedRows.value.length}条记录的${fieldLabels[batchField.value]}，不会导入。`, '批量修正预览'); } catch { return; }
  await saveCorrections(selectedRows.value.map(row => ({ number: row.number, changes: { [batchField.value]: batchValue.value } })), batchReason.value.trim());
}
async function restoreRow(row) {
  if (!editable.value || busy.value || pendingEdit.value) return;
  let reason;
  try { reason = (await ElMessageBox.prompt('填写恢复原因；仅恢复本行原始解析值并重新校验。', '恢复原始值', { inputValidator: value => Boolean(value?.trim()) || '请填写原因' })).value; } catch { return; }
  await saveCorrections([{ number: row.number }], reason.trim(), 'restore');
}
async function loadAudit(row) {
  await run(async () => { auditRows[row.number] = (await api({ url: BASE + job.value.id + '/', params: { audit_row: row.number } })).results; });
}
async function canLeave() {
  if (busy.value) return false;
  if (dirty.value) {
    try { await ElMessageBox.confirm('本账单有未保存的修正，是否放弃修改？已保存修正不受影响。', '未保存的修改'); } catch { return false; }
  }
  cancelEdit(); clearSelection(); return true;
}
function beforeUnload(event) { if (dirty.value) { event.preventDefault(); event.returnValue = ''; } }
defineExpose({ canLeave });
async function api(config) {
  const result = await requestApi({ timeout: 30000, ...config, noMockFallback: true });
  if (!result.success) throw new Error(result.message || '操作失败，请重新核对。');
  return result.data;
}
async function run(task) {
  if (busy.value || !canImport()) return;
  busy.value = true; error.value = '';
  try { await task(); } catch (e) { error.value = e.message || '操作未完成，请刷新核对。'; }
  finally { busy.value = false; uploadPercent.value = null; schedule(); }
}
function schedule() {
  clearTimeout(timer);
  if (!disposed && active.value) timer = setTimeout(refresh, 2500);
}
function setSettings(value = {}) {
  Object.assign(settings, { country: value.country || '', bill_month: value.bill_month || '', currency: value.currency || '', warehouses: { ...value.warehouses }, stores: { ...value.stores } });
}
function supplied() {
  return { ...Object.fromEntries(['country', 'bill_month', 'currency'].filter(k => settings[k]).map(k => [k, settings[k]])),
    warehouses: Object.fromEntries(Object.entries(settings.warehouses).filter(([, v]) => v)), stores: Object.fromEntries(Object.entries(settings.stores).filter(([, v]) => v)) };
}
function mappingOptions(group) { return (props.options[group] || []).filter(x => !job.value?.summary?.country || x.country === job.value.summary.country); }
async function loadHistory() { history.value = (await api({ url: BASE })).results; }
async function readCurrent() {
  if (!job.value) return;
  const id = job.value.id, sequence = ++requestId;
  const result = await api({ url: BASE + id + '/', params: { page: page.value, page_size: 20, status: rowStatus.value, kind: rowKind.value } });
  if (disposed || sequence !== requestId || job.value.id !== id) return;
  const finished = result.status === 'completed' && job.value.status !== 'completed';
  job.value = result;
  if (finished) emit('imported');
}
async function refresh() { if (!pendingEdit.value) { clearSelection(); await run(readCurrent); } }
async function query() { if (pendingEdit.value) return; page.value = 1; await refresh(); }
async function upload(event) {
  const file = event.target.files?.[0];
  if (!file || busy.value || active.value || pendingEdit.value || !canImport()) return;
  if (!file.name.toLowerCase().endsWith('.xlsx') || file.size > 128 * 1024 * 1024) { error.value = '请选择不超过128MB的原始xlsx账单。'; return; }
  await run(async () => {
    const data = new FormData(); data.append('file', file); data.append('options', '{}');
    uploadPercent.value = 0;
    job.value = await api({ method: 'post', url: BASE, data, timeout: 300000, onUploadProgress: p => { if (p.total) uploadPercent.value = Math.round(p.loaded / p.total * 100); } });
    historyId.value = job.value.id; page.value = 1; rowStatus.value = ''; rowKind.value = ''; validOnly.value = false;
    setSettings(job.value.overrides); await readCurrent(); await loadHistory();
  });
  event.target.value = '';
}
async function selectHistory(id) {
  if (pendingEdit.value) return;
  await run(async () => {
    ++requestId; job.value = { id }; page.value = 1; validOnly.value = false; rowStatus.value = ''; rowKind.value = '';
    clearSelection(); for (const key of Object.keys(auditRows)) delete auditRows[key];
    feedback.value = ''; await readCurrent(); setSettings(job.value.overrides);
  });
}
async function reparse() {
  if (!job.value || active.value || hasImported.value || pendingEdit.value) return;
  await run(async () => {
    job.value = await api({ method: 'post', url: BASE + job.value.id + '/', data: { operation: 'parse', version: job.value.version, options: supplied() } });
    page.value = 1; validOnly.value = false; rowStatus.value = ''; await readCurrent();
  });
}
async function confirmImport() {
  if (busy.value || !job.value || active.value || pendingEdit.value || job.value.summary?.correction_warning || !canImport() || !job.value.counts?.valid || (job.value.counts?.error && !validOnly.value)) return;
  try { await ElMessageBox.confirm(`将${job.value.counts.valid}条有效记录导入为草稿，待核对行不导入。不会确认登记或付款。`, '确认导入费用草稿'); } catch { return; }
  await run(async () => { job.value = await api({ method: 'post', url: BASE + job.value.id + '/', data: { operation: 'import', version: job.value.version, valid_only: validOnly.value } }); await readCurrent(); });
}
async function confirmSettlement() {
  if (busy.value || active.value || pendingEdit.value || !canSettle() || !job.value?.summary?.settlement?.valid) return;
  const invoice = job.value.summary.settlement;
  try { await ElMessageBox.confirm(`按业务结算清单登记 ${invoice.total} ${invoice.currency}。已登记明细不重复计费，未分配金额和正负差额进入仓库其他处理费，无法确定仓库时保留待分配。不发起付款。`, '确认结算登记'); } catch { return; }
  await run(async () => {
    job.value = await api({ method: 'post', url: BASE + job.value.id + '/', data: { operation: 'settle', version: job.value.version } });
    await readCurrent(); emit('imported'); feedback.value = '已按结算清单核对登记，差额已同步重算。';
  });
}
async function downloadErrors() { await run(async () => { const result = await downloadApiFile(BASE + job.value.id + '/errors/', '原账单待核对清单.csv'); if (result?.success === false) throw new Error(result.message); }); }
onMounted(() => { window.addEventListener('beforeunload', beforeUnload); run(loadHistory); });
onUnmounted(() => { disposed = true; ++requestId; clearTimeout(timer); window.removeEventListener('beforeunload', beforeUnload); });
</script>

<style scoped>
.muted, small { color: #465971; line-height: 1.65; }
small { display: block; }
.upload-line, .preview-controls, .job-state { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 16px 0; }
.upload-line label { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.upload-line input { max-width: 320px; }
.upload-line > .el-select { width: 350px; }
.preview-controls > .el-select { width: 185px; }
.mapping-row { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(220px, 1fr); gap: 12px; align-items: center; margin: 12px 0; }
.row-details { padding: 12px 24px; color: #263b54; overflow-wrap: anywhere; }
.audit-entry { border-top: 1px solid #d8e1ec; margin-top: 12px; padding-top: 8px; }
.edit-extra, .batch-edit { padding: 12px; margin: 12px 0; background: #f5f8fc; border: 1px solid #d8e1ec; border-radius: 6px; }
.edit-extra label { display: inline-flex; flex-direction: column; gap: 6px; margin: 0 12px 12px 0; width: min(290px, 100%); color: #263b54; }
.edit-extra :deep(.el-date-editor) { width: 100%; }
.batch-edit { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.batch-edit > .el-select, .batch-edit > .el-input { width: 200px; }
:deep(.el-table .el-select), :deep(.el-table .el-input) { width: 100%; margin: 3px 0; }
.el-pagination { margin: 16px 0; flex-wrap: wrap; }
@media (max-width: 700px) { .mapping-row { grid-template-columns: 1fr; } .upload-line > .el-select { width: 100%; } }
</style>
