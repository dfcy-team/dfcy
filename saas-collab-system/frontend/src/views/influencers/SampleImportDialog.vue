<template>
  <el-dialog
    :model-value="canManage && modelValue"
    title="导入送样"
    width="min(1080px, 94vw)"
    :close-on-click-modal="false"
    :close-on-press-escape="!busy"
    :show-close="!busy"
    @update:model-value="closeDialog"
  >
    <div class="import-workspace">
      <p class="import-hint">上传订单 SKU CSV（最多 2 MB）。仅支持北京时间；预览不会创建送样或达人档案。</p>
      <div class="import-actions">
        <input :key="fileInputKey" type="file" accept=".csv,text/csv" aria-label="订单 SKU CSV" :disabled="locked" @change="chooseFile" />
        <el-button :disabled="!file || locked" :loading="previewing" @click="loadPreview">校验并预览</el-button>
      </div>
      <el-alert v-if="error" :title="error" :type="attempt ? 'warning' : 'error'" :closable="false" show-icon />
      <el-alert v-if="receipt" :title="receipt" type="success" :closable="false" show-icon />

      <template v-if="preview">
        <div class="import-actions import-summary">
          <span>共 <b>{{ preview.rows.length }}</b> 个订单 · 负责人：<b>{{ preview.ownerLabel }}</b>（系统分配）</span>
          <el-button link type="primary" :disabled="locked || !readyCount" @click="checkReadyRows">勾选所有可导入订单</el-button>
        </div>
        <el-checkbox v-model="timezoneConfirmed" :disabled="locked">确认此文件的下单/发货时间为北京时间 UTC+8</el-checkbox>
        <div class="import-orders">
          <section v-for="row in visibleRows" :key="row.key" class="import-order">
            <div class="order-header">
              <el-checkbox
                v-model="row.checked"
                :aria-label="`勾选订单 ${row.orderNo}`"
                :disabled="locked || row.imported || !!row.hardErrors.length"
              />
              <div class="order-title">
                <strong>{{ row.orderNo }}</strong>
                <small>{{ [row.storeLabel, row.country, row.orderStatus].filter(Boolean).join(' · ') }}</small>
              </div>
              <el-tag size="small" :type="row.imported || !rowIssues(row).length ? 'success' : row.hardErrors.length ? 'danger' : 'info'">
                {{ row.imported ? '已导入' : row.hardErrors.length ? '不可导入' : rowIssues(row).length ? '待核对' : '可导入' }}
              </el-tag>
            </div>
            <div v-if="!row.imported && !row.hardErrors.length" class="order-fields">
              <div class="order-field">
                <span>达人昵称</span>
                <div class="nickname-field">
                  <el-input
                    :model-value="row.nickname"
                    aria-label="达人昵称"
                    maxlength="120"
                    placeholder="填写昵称"
                    :disabled="locked"
                    @update:model-value="changeNickname(row, $event)"
                    @keyup.enter.prevent="findCreator(row)"
                  />
                  <el-button :disabled="locked || !row.nickname.trim()" :loading="row.lookupPending" @click="findCreator(row)">查找</el-button>
                </div>
              </div>
              <div class="order-field">
                <span>达人档案</span>
                <el-select
                  v-if="row.candidates.length"
                  :model-value="row.influencerId"
                  aria-label="达人档案"
                  clearable
                  :disabled="locked || row.lookupPending"
                  placeholder="选择匹配达人"
                  @update:model-value="chooseCreator(row, $event)"
                >
                  <el-option
                    v-for="candidate in row.candidates"
                    :key="candidate.id"
                    :label="candidate.label"
                    :value="candidate.id"
                    :disabled="candidate.isBlacklisted"
                  />
                </el-select>
                <small v-else class="import-hint">{{ row.lookupDone ? '未找到可匹配的达人' : '请先按昵称查找' }}</small>
                <el-checkbox
                  v-if="row.lookupDone && !row.candidates.length && !row.mustSelectExisting"
                  :model-value="row.confirmDraft"
                  :disabled="locked || row.lookupPending"
                  @update:model-value="chooseDraft(row, $event)"
                >确认导入时创建待补全档案</el-checkbox>
              </div>
              <div class="order-field">
                <span>送样类型</span>
                <el-select v-model="row.linkType" aria-label="送样类型" :disabled="locked" placeholder="选择送样类型" @change="clearRowError(row)">
                  <el-option v-for="type in preview.linkTypes" :key="type.value" :label="`${type.label}（${type.value}）`" :value="type.value" />
                </el-select>
              </div>
            </div>
            <div v-if="!row.imported && row.recentWarning && !row.hardErrors.length" class="order-warning">
              <el-alert :title="row.recentWarning" type="warning" :closable="false" show-icon />
              <el-checkbox v-model="row.confirmRecentDuplicate" :disabled="locked">确认仍要导入本订单</el-checkbox>
              <el-input
                v-if="row.confirmRecentDuplicate"
                v-model="row.confirmationReason"
                aria-label="重复送样原因"
                placeholder="填写重复送样原因（必填）"
                :maxlength="MAX_DUPLICATE_REASON_LENGTH"
                :disabled="locked"
              />
            </div>
            <ul v-if="displayedIssues(row).length" class="order-errors" role="status">
              <li v-for="issue in displayedIssues(row)" :key="issue">{{ issue }}</li>
            </ul>
            <details :open="row.hardErrors.length > 0 || row.confirmErrors.length > 0 || !!row.recentWarning">
              <summary>SKU / 仓库 / 数量（{{ row.items.length }} 条）</summary>
              <p v-if="row.productId" class="import-hint">商品 ID：{{ row.productId }}</p>
              <p v-if="row.orderedAt || row.shippedAt" class="import-hint">下单：{{ formatTaskDateTime(row.orderedAt) }} · 发货：{{ formatTaskDateTime(row.shippedAt) }}</p>
              <ul class="sku-details">
                <li v-for="(item, index) in row.items" :key="index">
                  <span>{{ item.sku || 'SKU 未识别' }}</span>
                  <span>{{ item.warehouse || '仓库未识别' }}</span>
                  <span>数量 {{ item.quantity ?? '未识别' }}</span>
                </li>
              </ul>
            </details>
          </section>
        </div>
        <el-pagination
          v-if="preview.rows.length > pageSize"
          v-model:current-page="page"
          :page-size="pageSize"
          :total="preview.rows.length"
          layout="prev, pager, next"
          small
        />
      </template>
    </div>

    <template #footer>
      <div class="import-footer">
        <span v-if="preview" aria-live="polite">已勾选 {{ selectedRows.length }} 单，可提交 {{ readySelectedCount }} 单</span>
        <el-button :disabled="busy" @click="closeDialog(false)">{{ attempt ? '暂时关闭' : '关闭' }}</el-button>
        <el-button type="primary" :loading="submitting" :disabled="!canSubmit" @click="submitImport">
          {{ attempt && !submitting ? '重试原请求' : '确认导入' }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, shallowRef } from 'vue';
import { confirmSampleImport, fetchSampleImportInfluencerCandidates, previewSampleImport } from '../../api/sampleImport';
import {
  buildSampleImportOrder,
  MAX_DUPLICATE_REASON_LENGTH,
  readSampleImportCandidates,
  readSampleImportConfirmation,
  readSampleImportPreview,
  sampleImportErrorMessage,
  sampleImportRowIssues,
  SAMPLE_IMPORT_TIME_ZONE,
  validateSampleImportFile
} from './sampleImport';
import { formatTaskDateTime } from './taskDateTime';

const props = defineProps({ modelValue: Boolean, canManage: Boolean });
const emit = defineEmits(['update:modelValue', 'imported']);
const file = shallowRef(null);
const fileInputKey = ref(0);
const preview = ref(null);
const timezoneConfirmed = ref(false);
const page = ref(1);
const pageSize = 20;
const error = ref('');
const receipt = ref('');
const previewing = ref(false);
const submitting = ref(false);
const attempt = shallowRef(null);
const busy = computed(() => previewing.value || submitting.value);
const locked = computed(() => !props.canManage || busy.value || !!attempt.value);
const rows = computed(() => preview.value?.rows ?? []);
const visibleRows = computed(() => rows.value.slice((page.value - 1) * pageSize, page.value * pageSize));
const selectedRows = computed(() => rows.value.filter(row => row.checked));
const rowIssues = row => sampleImportRowIssues(row, preview.value?.linkTypes ?? []);
const readyCount = computed(() => rows.value.filter(row => !rowIssues(row).length).length);
const readySelectedCount = computed(() => selectedRows.value.filter(row => !rowIssues(row).length).length);
const canSubmit = computed(() => props.canManage && !busy.value && (!!attempt.value
  || (timezoneConfirmed.value && selectedRows.value.length > 0 && selectedRows.value.length === readySelectedCount.value)));

function closeDialog(open) {
  if (open || busy.value) return;
  if (!attempt.value) {
    file.value = null;
    fileInputKey.value += 1;
    resetPreview();
  }
  emit('update:modelValue', false);
}

function resetPreview() {
  preview.value = null;
  timezoneConfirmed.value = false;
  page.value = 1;
  error.value = '';
  receipt.value = '';
}

function chooseFile(event) {
  if (locked.value) return;
  resetPreview();
  const selected = event.target.files?.[0];
  error.value = validateSampleImportFile(selected);
  file.value = error.value ? null : selected;
  if (error.value) event.target.value = '';
}

async function loadPreview() {
  if (!file.value || locked.value) return;
  resetPreview();
  previewing.value = true;
  try {
    const response = await previewSampleImport(file.value);
    preview.value = readSampleImportPreview(response);
    if (!preview.value) error.value = sampleImportErrorMessage(response, '无法取得有效的送样预览，请重试。');
  } catch {
    error.value = '无法读取送样预览，请重试。';
  } finally {
    previewing.value = false;
  }
}

function clearRowError(row) {
  row.confirmErrors = [];
}

function clearRecentWarning(row) {
  row.recentWarning = '';
  row.confirmRecentDuplicate = false;
  row.confirmationReason = '';
}

function changeNickname(row, nickname) {
  if (locked.value || nickname === row.nickname) return;
  Object.assign(row, { nickname, influencerId: null, candidates: [], lookupDone: false, lookupError: '', confirmDraft: false, mustSelectExisting: false });
  clearRowError(row);
  clearRecentWarning(row);
}

async function findCreator(row) {
  const nickname = row.nickname.trim().replace(/\s+/g, ' ');
  if (locked.value || row.lookupPending || !nickname) return;
  if (nickname !== row.nickname) changeNickname(row, nickname);
  row.lookupPending = true;
  row.lookupError = '';
  try {
    const response = await fetchSampleImportInfluencerCandidates(nickname);
    if (row.nickname !== nickname || !rows.value.includes(row)) return;
    const candidates = readSampleImportCandidates(response);
    if (!candidates) {
      row.lookupError = sampleImportErrorMessage(response, '达人查找失败，请重试。');
      return;
    }
    const previous = row.influencerId;
    row.candidates = candidates;
    row.lookupDone = true;
    const retained = candidates.find(candidate => candidate.id === previous && !candidate.isBlacklisted);
    const unique = !row.mustSelectExisting && candidates.length === 1 && !candidates[0].isBlacklisted;
    row.influencerId = retained?.id ?? (unique ? candidates[0].id : null);
    if (previous !== row.influencerId) clearRecentWarning(row);
    if (row.influencerId || candidates.some(candidate => candidate.isBlacklisted)) row.confirmDraft = false;
    clearRowError(row);
  } catch {
    row.lookupError = '达人查找失败，请重试。';
  } finally {
    row.lookupPending = false;
  }
}

function chooseCreator(row, id) {
  if (locked.value) return;
  row.influencerId = row.candidates.find(candidate => candidate.id === id && !candidate.isBlacklisted)?.id ?? null;
  row.confirmDraft = false;
  clearRowError(row);
  clearRecentWarning(row);
}

function chooseDraft(row, checked) {
  if (locked.value) return;
  row.confirmDraft = checked === true;
  clearRowError(row);
}

function checkReadyRows() {
  if (locked.value) return;
  for (const row of rows.value) {
    if (!rowIssues(row).length) row.checked = true;
  }
}

function displayedIssues(row) {
  return [...new Set([
    ...row.hardErrors, ...row.confirmErrors, row.lookupError,
    ...(row.checked ? rowIssues(row) : [])
  ].filter(Boolean))];
}

async function submitImport() {
  if (!canSubmit.value) return;
  const retrying = !!attempt.value;
  if (!retrying) {
    const requestKey = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    attempt.value = {
      orders: selectedRows.value.map(buildSampleImportOrder),
      request_key: requestKey,
      source_timezone: SAMPLE_IMPORT_TIME_ZONE,
      timezone_confirmed: true
    };
  }
  const payload = attempt.value;
  submitting.value = true;
  error.value = '';
  receipt.value = '';
  try {
    const response = await confirmSampleImport(payload);
    const outcome = readSampleImportConfirmation(response, payload, retrying);
    if (outcome.uncertain) {
      showUncertain();
      return;
    }
    attempt.value = null;
    error.value = outcome.message;
    for (const result of outcome.results) {
      const row = rows.value.find(item => item.sourceOrderNo === result.orderNo && !item.hardErrors.length);
      if (!row) continue;
      if (result.imported) {
        row.imported = true;
        row.checked = false;
        clearRowError(row);
      } else if (result.recentWarning) {
        clearRecentWarning(row);
        row.recentWarning = result.recentWarning;
        clearRowError(row);
      } else if (result.candidates) {
        row.candidates = result.candidates.map(candidate => row.candidates.find(current => current.id === candidate.id) || candidate);
        row.influencerId = null;
        row.confirmDraft = false;
        row.mustSelectExisting = true;
        row.lookupDone = !!row.candidates.length;
        row.lookupError = '';
        row.confirmErrors = [result.message];
        clearRecentWarning(row);
      } else {
        row.checked = false;
        if (result.blocked) row.hardErrors.push(result.message);
        else row.confirmErrors = [result.message];
        if (result.recheckCreator) {
          Object.assign(row, { candidates: [], influencerId: null, lookupDone: false, confirmDraft: false, mustSelectExisting: true });
          clearRecentWarning(row);
        }
      }
    }
    const firstFailure = outcome.results.find(result => !result.imported);
    if (firstFailure) {
      const index = rows.value.findIndex(row => row.sourceOrderNo === firstFailure.orderNo);
      if (index >= 0) page.value = Math.floor(index / pageSize) + 1;
    }
    if (outcome.importedCount) {
      receipt.value = `已确认导入 ${outcome.importedCount} 单。`;
      emit('imported');
    }
  } catch {
    showUncertain();
  } finally {
    submitting.value = false;
  }
}

function showUncertain() {
  error.value = '导入结果暂未确认。当前页面已保留原请求编号与内容，请勿重新上传；可重试原请求核对结果。';
}
</script>

<style scoped>
.import-workspace, .import-orders, .order-field, .order-warning { display: grid; gap: 10px; }
.import-hint, .order-title small { color: var(--el-text-color-secondary); font-size: 12px; }
.import-hint { margin: 0; }
.import-actions, .import-footer, .order-header, .nickname-field { display: flex; align-items: center; gap: 10px; }
.import-actions, .import-footer { flex-wrap: wrap; }
.import-actions input { max-width: 100%; }
.import-summary { justify-content: space-between; }
.import-orders { max-height: 54vh; overflow: auto; padding: 1px 6px 1px 1px; }
.import-order { padding: 12px; border: 1px solid var(--el-border-color); border-radius: 8px; }
.order-title { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.order-title small { display: block; }
.order-fields { display: grid; grid-template-columns: 1.15fr 1.2fr 1fr; align-items: start; gap: 12px; margin: 10px 0; }
.order-field { min-width: 0; gap: 5px; }
.order-field :deep(.el-checkbox__label) { white-space: normal; }
.order-warning { margin: 10px 0; }
.order-errors { margin: 8px 0; padding-left: 20px; color: var(--el-color-danger); }
details { margin-top: 8px; }
summary { width: fit-content; color: var(--el-color-primary); cursor: pointer; }
.sku-details { margin: 4px 0 0; padding: 0; list-style: none; }
.sku-details li { display: grid; grid-template-columns: 1fr 1fr minmax(70px, .5fr); gap: 8px; padding: 5px 0; overflow-wrap: anywhere; }
.import-footer { justify-content: flex-end; }
.import-footer > span { margin-right: auto; }
.import-footer .el-button + .el-button { margin-left: 0; }
@media (max-width: 700px) {
  .order-fields { grid-template-columns: 1fr; }
  .import-orders { max-height: 48vh; }
}
</style>
