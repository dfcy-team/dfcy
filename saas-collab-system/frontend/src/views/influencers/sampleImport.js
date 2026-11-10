export const SAMPLE_IMPORT_TIME_ZONE = 'Asia/Shanghai';
export const MAX_DUPLICATE_REASON_LENGTH = 240;

const MAX_FILE_BYTES = 2 * 1024 * 1024;
const REQUIRES_PREVIEW = new Set(['preview_required', 'preview_changed', 'archives_changed', 'scope_changed']);
const CREATOR_ERRORS = new Set(['invalid_influencer', 'influencer_unavailable', 'influencer_restricted']);
const REJECTED_HTTP_STATUSES = new Set([400, 401, 403, 404, 405, 413, 415, 422]);
const clean = value => typeof value === 'string' ? value.trim() : '';
const chineseText = value => /[\u3400-\u9fff]/u.test(clean(value)) ? clean(value) : '';
const isObject = value => value && typeof value === 'object' && !Array.isArray(value);
const positiveId = value => Number.isSafeInteger(value) && value > 0;
const isLiveSuccess = response => response?.success === true
  && !['mock', 'degraded'].includes(response.data?.api_status);

export function validateSampleImportFile(file) {
  if (!file) return '';
  if (!/\.csv$/i.test(file.name)) return '请选择 CSV 文件。';
  if (!file.size) return 'CSV 文件为空。';
  return file.size > MAX_FILE_BYTES ? 'CSV 文件不能超过 2 MB。' : '';
}

export function sampleImportErrorMessage(response, fallback) {
  const errors = {
    401: '登录状态已过期，请重新登录。',
    403: '当前角色或数据范围无权执行此操作。',
    404: '送样导入接口暂不可用。',
    413: 'CSV 文件不能超过 2 MB。'
  };
  const fieldError = ['file', 'timezone_confirmed', 'request_key', 'orders']
    .map(field => {
      const error = response?.data?.[field];
      return chineseText(Array.isArray(error) ? error[0] : error);
    })
    .find(Boolean);
  return errors[response?.http_status] || fieldError || chineseText(response?.message) || fallback;
}

function previewIssue(issue) {
  const message = chineseText(issue?.message) || '订单数据校验未通过。';
  return Number.isInteger(issue?.row_number) ? `CSV 第 ${issue.row_number} 行：${message}` : message;
}

function makeRow(order, index) {
  const rowNumber = order.row_numbers?.[0];
  const hardErrors = order.errors.map(previewIssue);
  if (!hardErrors.length && (!clean(order.preview_token) || !clean(order.order_no) || !order.items.length)) {
    hardErrors.push('订单没有有效预览，无法导入。');
  }
  return {
    key: index,
    orderNo: clean(order.order_no) || `CSV 第 ${rowNumber ?? index + 2} 行（无订单号）`,
    sourceOrderNo: order.order_no,
    previewToken: order.preview_token,
    storeLabel: order.store_name || order.big_seller_store || order.platform_store || '',
    country: order.country_code || '',
    orderStatus: order.source_status || '',
    productId: order.external_product_id,
    orderedAt: order.sample_sent_at,
    shippedAt: order.shipped_at,
    items: order.items.map(item => ({
      sku: item.requested_sku,
      warehouse: item.warehouse_name || order.warehouse_name,
      quantity: item.quantity
    })),
    hardErrors,
    nickname: '',
    linkType: '',
    influencerId: null,
    candidates: [],
    lookupDone: false,
    lookupPending: false,
    lookupError: '',
    confirmDraft: false,
    mustSelectExisting: false,
    recentWarning: '',
    confirmRecentDuplicate: false,
    confirmationReason: '',
    confirmErrors: [],
    checked: false,
    imported: false
  };
}

export function readSampleImportPreview(response) {
  const { orders, order_count: orderCount, source_timezone: timezone, link_types: linkTypes, owner } = response?.data ?? {};
  if (!isLiveSuccess(response) || timezone !== SAMPLE_IMPORT_TIME_ZONE
    || !Array.isArray(orders) || !orders.length || orders.length !== orderCount
    || orders.some(order => !isObject(order) || !Array.isArray(order.errors) || !Array.isArray(order.items)
      || order.items.some(item => !isObject(item)))
    || !Array.isArray(linkTypes) || !linkTypes.length
    || linkTypes.some(type => !clean(type?.value) || !clean(type?.label) || type.value === 'DRJL')) return null;
  const rows = orders.map(makeRow);
  const eligible = rows.filter(row => !row.hardErrors.length);
  if (new Set(eligible.map(row => row.sourceOrderNo.toLowerCase())).size !== eligible.length) return null;
  const ownerLabel = clean(owner?.full_name) || clean(owner?.display_name) || clean(owner?.username) || '当前登录用户';
  return { ownerLabel, rows, linkTypes };
}

function readCandidates(candidates, requireRestriction = false) {
  if (!Array.isArray(candidates) || candidates.some(candidate =>
    !positiveId(candidate?.id) || (requireRestriction && typeof candidate.is_blacklisted !== 'boolean')
  )) return null;
  return candidates.map(candidate => ({
    id: candidate.id,
    isBlacklisted: candidate.is_blacklisted === true,
    label: [
      candidate.display_name || candidate.name || '达人',
      candidate.handle ? `@${candidate.handle}` : candidate.code,
      `ID ${candidate.id}`,
      candidate.is_blacklisted ? '黑名单' : ''
    ].filter(Boolean).join(' · ')
  }));
}

export function readSampleImportCandidates(response) {
  return isLiveSuccess(response) ? readCandidates(response.data?.candidates, true) : null;
}

export function sampleImportRowIssues(row, linkTypes) {
  if (row.imported) return ['本订单已导入。'];
  if (row.hardErrors.length) return row.hardErrors;
  const issues = [];
  if (!clean(row.nickname)) issues.push('请填写达人昵称。');
  else if (!row.lookupDone || row.lookupPending || row.lookupError) issues.push('请先核对达人档案。');
  else if (!row.influencerId) {
    if (row.candidates.every(candidate => candidate.isBlacklisted) && row.candidates.length) issues.push('匹配达人在黑名单中，不能导入。');
    else if (row.candidates.length || row.mustSelectExisting) issues.push('请选择正确的达人档案。');
    else if (!row.confirmDraft) issues.push('未找到达人，请确认仅在导入时创建待补全档案。');
  }
  if (!linkTypes.some(type => type.value === row.linkType)) issues.push('请选择独立送样类型。');
  if (row.recentWarning) {
    if (!row.confirmRecentDuplicate || !clean(row.confirmationReason)) issues.push('请明确确认重复送样并填写原因。');
    else if (row.confirmationReason.length > MAX_DUPLICATE_REASON_LENGTH) issues.push('重复送样原因不能超过 240 个字符。');
  }
  return issues;
}

export function buildSampleImportOrder(row) {
  const confirmed = !!row.recentWarning && row.confirmRecentDuplicate;
  return {
    order_no: row.sourceOrderNo,
    preview_token: row.previewToken,
    nickname: clean(row.nickname),
    link_type: row.linkType,
    ...(row.influencerId ? { influencer_id: row.influencerId } : {}),
    confirm_recent_duplicate: confirmed,
    confirmation_reason: confirmed ? clean(row.confirmationReason) : ''
  };
}

function parseResult(result, order, index) {
  if (result?.index !== index || result.order_no !== order.order_no) return null;
  const { order_no: orderNo, status, code } = result;
  const message = chineseText(result.message) || '该订单未通过校验，请核对后再试。';
  switch (status) {
    case 'created':
      return positiveId(result.fulfillment_id) ? { orderNo, status, imported: true } : null;
    case 'conflict':
      return { orderNo, status, blocked: true, message };
    case 'needs_confirmation':
      return { orderNo, status, recentWarning: chineseText(result.message) || '该达人近 30 天有同商品送样，请明确确认并填写原因。' };
    case 'needs_influencer': {
      const candidates = readCandidates(result.candidates);
      return candidates ? { orderNo, status, candidates, message } : null;
    }
    case 'invalid':
      return { orderNo, status, message, blocked: REQUIRES_PREVIEW.has(code), recheckCreator: CREATOR_ERRORS.has(code) };
    default:
      return null;
  }
}

export function readSampleImportConfirmation(response, payload, retrying) {
  const uncertain = { uncertain: true };
  if (!isLiveSuccess(response)) {
    // Only a complete receipt can reconcile an earlier uncertain attempt.
    if (retrying || response?.success !== false || !REJECTED_HTTP_STATUSES.has(response.http_status)) return uncertain;
    return { results: [], importedCount: 0, message: sampleImportErrorMessage(response, '导入请求未受理，请核对后重试。') };
  }
  const data = response.data;
  if (!positiveId(data?.batch_id) || data.mode !== 'partial' || typeof data.replayed !== 'boolean'
    || !Array.isArray(data.results) || data.results.length !== payload.orders.length) return uncertain;
  const results = data.results.map((result, index) => parseResult(result, payload.orders[index], index));
  if (results.some(result => !result)) return uncertain;
  const importedCount = results.filter(result => result.imported).length;
  if (importedCount !== data.created_count) return uncertain;
  const failedCount = results.length - importedCount;
  return {
    results,
    importedCount,
    message: failedCount ? `${failedCount} 单未导入，请查看对应订单提示。` : ''
  };
}
