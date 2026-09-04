import { requestWithMockFallback } from './request';
import { influencerMocks } from '../mock/influencers';

const API_ROOT = '/api/internal/influencers';

export const OUTREACH_STATUS_LABELS = Object.freeze({
  pending: '待开始',
  in_progress: '进行中',
  completed: '已完成',
  cancelled: '已取消'
});

export const OUTREACH_PRIORITY_LABELS = Object.freeze({
  low: '低',
  normal: '普通',
  high: '高',
  urgent: '紧急'
});

export const OUTREACH_RESULT_LABELS = Object.freeze({
  pending: '待处理',
  success: '已成功',
  rejected: '已拒绝',
  no_response: '无响应',
  blocked: '已阻断'
});

export const FULFILLMENT_STATUS_LABELS = Object.freeze({
  pending: '待处理',
  processing: '处理中',
  shipped: '已发货',
  delivered: '已送达',
  completed: '已完成',
  cancelled: '已取消',
  creating: '创建中',
  published: '已发布',
  live_creator: '达人直播中',
  overdue: '已逾期',
  blank: '空白'
});

export const FULFILLMENT_LINK_TYPE_LABELS = Object.freeze({
  DRJL: 'BD建联',
  YYJL: '运营建联',
  PKDJ: '品库达人',
  ZBDR: '直播达人',
  TKOne: 'TikTokOne建联'
});

export const FULFILLMENT_STATUS_TRANSITIONS = Object.freeze({
  pending: Object.freeze(['completed', 'cancelled']),
  creating: Object.freeze(['completed', 'cancelled']),
  published: Object.freeze(['completed', 'cancelled']),
  live_creator: Object.freeze(['completed', 'cancelled']),
  overdue: Object.freeze(['completed', 'cancelled']),
  blank: Object.freeze(['completed', 'cancelled']),
  processing: Object.freeze(['completed', 'cancelled']),
  shipped: Object.freeze(['completed', 'cancelled']),
  delivered: Object.freeze(['completed', 'cancelled']),
  completed: Object.freeze([]),
  cancelled: Object.freeze([])
});

export const PRICING_STATUS_LABELS = Object.freeze({
  pending: '待匹配',
  full: '完整匹配',
  partial: '部分匹配',
  not_found: '未匹配'
});

export const PRICE_MATCH_STATUS_LABELS = Object.freeze({
  matched: '销售价已匹配',
  not_imported: '销售价未导入'
});

export const COST_MATCH_STATUS_LABELS = Object.freeze({
  pending: '采购成本待匹配',
  matched_new_sku: '采购成本已匹配',
  matched_legacy_sku: '采购成本已匹配',
  matched_normalized: '采购成本已匹配',
  not_priced: 'SKU 无采购价',
  ambiguous: 'SKU 匹配有歧义',
  not_found: 'SKU 未匹配'
});

export const statusLabel = (labels, value) => labels[value] || value || '—';

export const BD_PERFORMANCE_ATTRIBUTION_LABELS = Object.freeze({
  strict: '方式一',
  fallback: '方式二'
});

export const BD_PERFORMANCE_CURRENCIES = Object.freeze([
  { value: 'CNY', label: '人民币 CNY' },
  { value: 'PHP', label: '菲律宾比索 PHP' },
  { value: 'MYR', label: '马来西亚令吉 MYR' },
  { value: 'THB', label: '泰铢 THB' },
  { value: 'USD', label: '美元 USD' }
]);

export const INFLUENCER_COOPERATION_STATUS_LABELS = Object.freeze({
  prospect: '待接洽',
  contacted: '已联系',
  cooperating: '合作中',
  paused: '已暂停'
});

export const INFLUENCER_CONTACT_CHANNEL_LABELS = Object.freeze({
  email: '邮箱',
  phone: '电话',
  whatsapp: 'WhatsApp',
  wechat: '微信',
  telegram: 'Telegram',
  tiktok: 'TikTok 私信',
  instagram: 'Instagram',
  messenger: 'Facebook Messenger',
  line: 'LINE',
  viber: 'Viber',
  other: '其他'
});

const mockWrite = (data = {}) => () => ({
  success: true,
  code: 'OK',
  message: 'Mock操作已记录',
  data: { ...data, api_status: 'mock' }
});

const mockCollection = () => ({
  success: true,
  code: 'OK',
  message: 'success',
  data: { status: 'mock', count: 0, next: null, previous: null, results: [] }
});

const mockDetail = (data = {}) => () => ({
  success: true,
  code: 'OK',
  message: 'success',
  data: { ...data, api_status: 'mock' }
});

const ifMatchHeaders = (version) => {
  if (version === undefined || version === null || version === '') return {};
  const value = String(version).replace(/^"|"$/g, '');
  return { headers: { 'If-Match': `"${value}"` } };
};

const requestKey = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;

export function formatInfluencerError(response, fallback = '操作失败，请稍后重试。') {
  const message = response?.message || '';
  if (/blacklist|blacklisted|黑名单/i.test(message)) return '该达人已被加入黑名单，不能执行本次操作。';
  if (response?.http_status === 409 || response?.code === 'STATE_CONFLICT' || response?.code === 'CONFLICT') {
    if (/terminal|completed|cancelled|终态/i.test(message)) return `任务已进入终态，不能再修改目标或送样。${message ? ` ${message}` : ''}`;
    return `数据已被其他操作更新（409），请刷新后重试。${message ? ` ${message}` : ''}`;
  }
  if (response?.http_status === 403) return '当前角色或数据范围无权执行此操作。';
  return message || fallback;
}

export const fetchInfluencers = (params = {}) => requestWithMockFallback(
  { method: 'get', url: `${API_ROOT}/`, params },
  influencerMocks.list,
  'influencers.list'
);

const emptyPerformance = () => ({
  success: true,
  code: 'OK',
  message: 'success',
  data: {
    source_status: 'not_imported',
    rows: [],
    results: [],
    totals: {},
    video_status: 'unavailable',
    data_as_of: null,
    updated_at: null,
    api_status: 'mock'
  }
});

export const fetchBdPerformance = (params = {}) => requestWithMockFallback(
  { method: 'get', url: `${API_ROOT}/bd-performance/`, params },
  emptyPerformance,
  'influencers.bd_performance'
);

// Keep the acronym spelling available to callers that use the backend name.
export const fetchBDPerformance = fetchBdPerformance;

export const fetchInfluencer = (id, params = {}) => requestWithMockFallback(
  { method: 'get', url: `${API_ROOT}/${encodeURIComponent(id)}/`, params },
  () => mockDetail({ id, contacts: [], blacklist_history: [] })(),
  'influencers.detail'
);

export const updateInfluencer = (id, payload, version) => requestWithMockFallback(
  {
    method: 'patch',
    url: `${API_ROOT}/${encodeURIComponent(id)}/`,
    data: payload,
    ...ifMatchHeaders(version)
  },
  mockWrite({ id, ...payload, updated_at: version }),
  'influencers.update'
);

export const fetchInfluencerContacts = (id) => requestWithMockFallback(
  { method: 'get', url: `${API_ROOT}/${encodeURIComponent(id)}/contacts/` },
  mockCollection,
  'influencers.contacts.list'
);

export const updateInfluencerContacts = (id, contacts, version) => requestWithMockFallback(
  {
    method: 'patch',
    url: `${API_ROOT}/${encodeURIComponent(id)}/contacts/`,
    data: { contacts },
    ...ifMatchHeaders(version)
  },
  mockWrite({ id, contacts, updated_at: version }),
  'influencers.contacts.update'
);

export const updateInfluencerBlacklist = (id, payload, version) => requestWithMockFallback(
  {
    method: 'post',
    url: `${API_ROOT}/${encodeURIComponent(id)}/blacklist/`,
    data: payload,
    ...ifMatchHeaders(version)
  },
  mockWrite({ id, ...payload, updated_at: version }),
  'influencers.blacklist.update'
);

export const fetchInfluencerBlacklistHistory = (id, params = {}) => requestWithMockFallback(
  {
    method: 'get',
    url: `${API_ROOT}/${encodeURIComponent(id)}/blacklist-history/`,
    params
  },
  mockCollection,
  'influencers.blacklist.history'
);

export const updateInfluencerRestriction = updateInfluencerBlacklist;
export const fetchInfluencerRestrictionHistory = fetchInfluencerBlacklistHistory;

export const createInfluencer = (payload) => requestWithMockFallback(
  { method: 'post', url: `${API_ROOT}/`, data: payload },
  mockWrite(payload),
  'influencers.create'
);

export const updateInfluencerStatus = (row, status) => requestWithMockFallback(
  { method: 'post', url: `${API_ROOT}/${row.id}/status/`, data: { status }, ...ifMatchHeaders(row.updated_at) },
  mockWrite({ id: row.id, status }),
  'influencers.status'
);

export const fetchOutreachTasks = (params = {}) => requestWithMockFallback(
  { method: 'get', url: `${API_ROOT}/outreach-tasks/`, params },
  mockCollection,
  'influencers.outreach.list'
);

export const fetchOutreachTaskOptions = (params = {}) => requestWithMockFallback(
  { method: 'get', url: `${API_ROOT}/outreach-task-options/`, params },
  () => ({ success: true, data: { stores: [], bd_users: [] } }),
  'influencers.outreach.options'
);

export const matchOutreachProduct = (productId) => requestWithMockFallback(
  { method: 'get', url: `${API_ROOT}/outreach-product-match/`, params: { product_id: productId } },
  () => ({ success: true, data: { matched: false, unique: false, reason: 'data_source_not_imported', candidates: [] } }),
  'influencers.outreach.product_match'
);

export const fetchOutreachTask = (id, params = {}) => requestWithMockFallback(
  { method: 'get', url: `${API_ROOT}/outreach-tasks/${id}/`, params },
  mockDetail({ id }),
  'influencers.outreach.detail'
);

export const fetchOutreachProgress = (id) => requestWithMockFallback(
  { method: 'get', url: `${API_ROOT}/outreach-tasks/${id}/progress/` },
  mockDetail({ task_id: id, linked_count: 0, target_count: 0, remaining_count: 0, result_counts: {} }),
  'influencers.outreach.progress'
);

export const fetchOutreachTargets = (taskId, params = {}) => requestWithMockFallback(
  { method: 'get', url: `${API_ROOT}/outreach-tasks/${taskId}/targets/`, params },
  mockCollection,
  'influencers.outreach.targets'
);

export const createOutreachTask = (payload) => requestWithMockFallback(
  { method: 'post', url: `${API_ROOT}/outreach-tasks/`, data: payload },
  mockWrite(payload),
  'influencers.outreach.create'
);

export const updateOutreachStatus = (id, status, version) => requestWithMockFallback(
  { method: 'post', url: `${API_ROOT}/outreach-tasks/${id}/status/`, data: { status }, ...ifMatchHeaders(version) },
  mockWrite({ id, status, version: Number(version || 1) + 1 }),
  'influencers.outreach.status'
);

export const updateOutreachTask = (id, payload, version) => requestWithMockFallback(
  {
    method: 'patch',
    url: `${API_ROOT}/outreach-tasks/${id}/`,
    data: payload,
    ...ifMatchHeaders(version)
  },
  mockWrite({ id, ...payload, version: Number(version || 1) + 1 }),
  'influencers.outreach.update'
);

export const deleteOutreachTask = (id, version) => requestWithMockFallback(
  { method: 'delete', url: `${API_ROOT}/outreach-tasks/${id}/`, ...ifMatchHeaders(version) },
  mockWrite({ id, is_deleted: true, version: Number(version || 1) + 1 }),
  'influencers.outreach.delete'
);

export const restoreOutreachTask = (id, version) => requestWithMockFallback(
  { method: 'post', url: `${API_ROOT}/outreach-tasks/${id}/restore/`, ...ifMatchHeaders(version) },
  mockWrite({ id, is_deleted: false, version: Number(version || 1) + 1 }),
  'influencers.outreach.restore'
);

export const fetchInfluencerResolve = (query = '') => requestWithMockFallback(
  { method: 'get', url: `${API_ROOT}/resolve/`, params: { q: query } },
  () => ({ success: true, data: { query, candidates: [], results: [] } }),
  'influencers.resolve'
);

export const resolveOrCreateInfluencer = (handle) => requestWithMockFallback(
  { method: 'post', url: `${API_ROOT}/resolve/`, data: { handle } },
  mockDetail({ id: `mock-${handle}`, handle, name: handle, platform: 'TikTok', is_blacklisted: false, created: true }),
  'influencers.resolve.create'
);

export const fetchSampleFulfillmentOptions = (params = {}) => requestWithMockFallback(
  { method: 'get', url: `${API_ROOT}/sample-fulfillment-options/`, params },
  () => ({ success: true, data: { tasks: [], influencers: [] } }),
  'influencers.fulfillment.options'
);

export const addOutreachTarget = (taskId, influencer, version, notes = '') => requestWithMockFallback(
  {
    method: 'post',
    url: `${API_ROOT}/outreach-tasks/${taskId}/targets/`,
    data: { influencer, ...(notes ? { notes } : {}) },
    ...ifMatchHeaders(version)
  },
  mockWrite({ task: taskId, influencer, version: Number(version || 1) + 1 }),
  'influencers.outreach.target.add'
);

export const updateOutreachTarget = (taskId, targetId, payload, version) => requestWithMockFallback(
  {
    method: 'patch',
    url: `${API_ROOT}/outreach-tasks/${taskId}/targets/${targetId}/`,
    data: payload,
    ...ifMatchHeaders(version)
  },
  mockWrite({ id: targetId, task: taskId, ...payload, version: Number(version || 1) + 1 }),
  'influencers.outreach.target.update'
);

export const deleteOutreachTarget = (taskId, targetId, version) => requestWithMockFallback(
  {
    method: 'delete',
    url: `${API_ROOT}/outreach-tasks/${taskId}/targets/${targetId}/`,
    ...ifMatchHeaders(version)
  },
  mockWrite({ id: targetId, task: taskId, is_deleted: true, version: Number(version || 1) + 1 }),
  'influencers.outreach.target.delete'
);

export const restoreOutreachTarget = (taskId, target, version, notes = '') =>
  addOutreachTarget(taskId, target.influencer, version, notes || target.notes || '');

export const fetchSampleFulfillments = (params = {}) => requestWithMockFallback(
  { method: 'get', url: `${API_ROOT}/sample-fulfillments/`, params },
  mockCollection,
  'influencers.fulfillment.list'
);

export const fetchSampleFulfillment = (id, params = {}) => requestWithMockFallback(
  { method: 'get', url: `${API_ROOT}/sample-fulfillments/${id}/`, params },
  mockDetail({ id }),
  'influencers.fulfillment.detail'
);

export const createSampleFulfillment = (payload, idempotencyKey = requestKey()) => requestWithMockFallback(
  {
    method: 'post',
    url: `${API_ROOT}/sample-fulfillments/`,
    data: payload,
    headers: { 'Idempotency-Key': idempotencyKey }
  },
  mockWrite(payload),
  'influencers.fulfillment.create'
);

export const updateSampleFulfillmentStatus = (id, status, version, reason = '') => requestWithMockFallback(
  {
    method: 'post',
    url: `${API_ROOT}/sample-fulfillments/${id}/status/`,
    data: { status, confirm_terminal: true, ...(reason ? { reason } : {}) },
    ...ifMatchHeaders(version)
  },
  mockWrite({ id, status, version: Number(version || 1) + 1 }),
  'influencers.fulfillment.status'
);

export const updateSampleFulfillment = (id, payload, version) => requestWithMockFallback(
  {
    method: 'patch',
    url: `${API_ROOT}/sample-fulfillments/${id}/`,
    data: payload,
    ...ifMatchHeaders(version)
  },
  mockWrite({ id, ...payload, version: Number(version || 1) + 1 }),
  'influencers.fulfillment.update'
);

export const deleteSampleFulfillment = (id, version) => requestWithMockFallback(
  { method: 'delete', url: `${API_ROOT}/sample-fulfillments/${id}/`, ...ifMatchHeaders(version) },
  mockWrite({ id, is_deleted: true, version: Number(version || 1) + 1 }),
  'influencers.fulfillment.delete'
);

export const restoreSampleFulfillment = (id, version) => requestWithMockFallback(
  { method: 'post', url: `${API_ROOT}/sample-fulfillments/${id}/restore/`, ...ifMatchHeaders(version) },
  mockWrite({ id, is_deleted: false, version: Number(version || 1) + 1 }),
  'influencers.fulfillment.restore'
);

export const lookupProductPrice = (params = {}) => requestWithMockFallback(
  { method: 'get', url: `${API_ROOT}/product-price-lookup/`, params },
  mockDetail({ matched: false, reason: 'data_source_not_imported', results: [] }),
  'influencers.catalog.price_lookup'
);
