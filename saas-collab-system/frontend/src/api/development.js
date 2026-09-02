import { requestApi, requestWithMockFallback, useMock } from './request';
import { successResponse } from '../mock';

// Keep the development workflow resources behind one tenant-scoped factory so
// each workspace uses the same list/detail/create/update contract.
const DEVELOPMENT_API_ROOT = '/api/internal/development';
const collectionUrl = (resource) => `${DEVELOPMENT_API_ROOT}/${resource}/`;
const resourceApi = (resource) => ({
  list: (params = {}) => requestApi({ url: collectionUrl(resource), method: 'get', params }),
  get: (id) => requestApi({ url: `${collectionUrl(resource)}${id}/`, method: 'get' }),
  create: (data) => requestApi({ url: collectionUrl(resource), method: 'post', data }),
  update: (id, data) => requestApi({ url: `${collectionUrl(resource)}${id}/`, method: 'patch', data }),
  remove: (id) => requestApi({ url: `${collectionUrl(resource)}${id}/`, method: 'delete' })
});

const candidatesApi = resourceApi('candidates');
const competitorsApi = resourceApi('competitors');
const projectsApi = resourceApi('projects');
const samplesApi = resourceApi('samples');
const quotationsApi = resourceApi('quotations');
const listingDecisionsApi = resourceApi('listing-decisions');
const trialsApi = resourceApi('trials');
const trialMetricsApi = resourceApi('trial-metrics');
const launchPlansApi = resourceApi('launch-plans');
const reorderDecisionsApi = resourceApi('reorder-decisions');
const eliminationsApi = resourceApi('eliminations');
const eventsApi = resourceApi('events');
const settingsApi = resourceApi('settings');

export const fetchDevelopmentCandidates = (params = {}) => candidatesApi.list(params);
export const fetchDevelopmentCandidate = (id) => candidatesApi.get(id);
export const createDevelopmentCandidate = (data) => candidatesApi.create(data);
export const updateDevelopmentCandidate = (id, data) => candidatesApi.update(id, data);
export const deleteDevelopmentCandidate = (id) => candidatesApi.remove(id);
export const fetchDevelopmentCompetitors = (params = {}) => competitorsApi.list(params);
export const fetchDevelopmentSamples = (params = {}) => samplesApi.list(params);
export const fetchDevelopmentSample = (id) => samplesApi.get(id);
export const createDevelopmentSample = (data) => samplesApi.create(data);
export const updateDevelopmentSample = (id, data) => samplesApi.update(id, data);
export const fetchDevelopmentQuotations = (params = {}) => quotationsApi.list(params);
export const fetchDevelopmentQuotation = (id) => quotationsApi.get(id);
export const createDevelopmentQuotation = (data) => quotationsApi.create(data);
export const updateDevelopmentQuotation = (id, data) => quotationsApi.update(id, data);
export const fetchDevelopmentListingDecisions = (params = {}) => listingDecisionsApi.list(params);
export const fetchDevelopmentListingDecision = (id) => listingDecisionsApi.get(id);
export const createDevelopmentListingDecision = (data) => listingDecisionsApi.create(data);
export const updateDevelopmentListingDecision = (id, data) => listingDecisionsApi.update(id, data);
export const fetchDevelopmentTrials = (params = {}) => trialsApi.list(params);
export const fetchDevelopmentTrial = (id) => trialsApi.get(id);
export const createDevelopmentTrial = (data) => trialsApi.create(data);
export const updateDevelopmentTrial = (id, data) => trialsApi.update(id, data);
export const fetchDevelopmentTrialMetrics = (params = {}) => trialMetricsApi.list(params);
export const fetchDevelopmentTrialMetric = (id) => trialMetricsApi.get(id);
export const createDevelopmentTrialMetric = (data) => trialMetricsApi.create(data);
export const updateDevelopmentTrialMetric = (id, data) => trialMetricsApi.update(id, data);
export const fetchDevelopmentLaunchPlans = (params = {}) => launchPlansApi.list(params);
export const fetchDevelopmentLaunchPlan = (id) => launchPlansApi.get(id);
export const createDevelopmentLaunchPlan = (data) => launchPlansApi.create(data);
export const updateDevelopmentLaunchPlan = (id, data) => launchPlansApi.update(id, data);
export const fetchDevelopmentReorderDecisions = (params = {}) => reorderDecisionsApi.list(params);
export const fetchDevelopmentReorderDecision = (id) => reorderDecisionsApi.get(id);
export const createDevelopmentReorderDecision = (data) => reorderDecisionsApi.create(data);
export const updateDevelopmentReorderDecision = (id, data) => reorderDecisionsApi.update(id, data);
export const fetchDevelopmentEliminations = (params = {}) => eliminationsApi.list(params);
export const fetchDevelopmentElimination = (id) => eliminationsApi.get(id);
export const createDevelopmentElimination = (data) => eliminationsApi.create(data);
export const updateDevelopmentElimination = (id, data) => eliminationsApi.update(id, data);
export const fetchDevelopmentEvents = (params = {}) => eventsApi.list(params);
export const fetchDevelopmentEvent = (id) => eventsApi.get(id);
export const createDevelopmentEvent = (data) => eventsApi.create(data);
export const fetchDevelopmentSettings = (params = {}) => settingsApi.list(params);
export const fetchDevelopmentSetting = (id) => settingsApi.get(id);
export const createDevelopmentSetting = (data) => settingsApi.create(data);
export const updateDevelopmentSetting = (id, data) => settingsApi.update(id, data);

const projects = [
  { id: 1, project_no: 'DEV-20260803-018', product_name: '便携折叠电热水壶', assigned_to_name: '张三', target_sites: ['TH','MY','SG'], stage: 'sampling', estimated_margin_rate: 0.326, planned_launch_date: '2026-08-28', status: 'active' },
  { id: 2, project_no: 'DEV-20260803-017', product_name: '硅胶折叠收纳套装', assigned_to_name: '李四', target_sites: ['ID','PH'], stage: 'design', estimated_margin_rate: 0.312, planned_launch_date: '2026-09-05', status: 'active' },
  { id: 3, project_no: 'DEV-20260802-016', product_name: '多功能露营照明灯', assigned_to_name: '王五', target_sites: ['TH','VN','MY'], stage: 'review', estimated_margin_rate: 0.385, planned_launch_date: '2026-08-22', status: 'active' },
  { id: 4, project_no: 'DEV-20260801-015', product_name: '宠物自动喂食器', assigned_to_name: '赵六', target_sites: ['SG','MY'], stage: 'finalized', estimated_margin_rate: 0.341, planned_launch_date: '2026-08-18', status: 'completed' }
];

const mock = (data) => Promise.resolve(successResponse(data));
export const fetchDevelopmentProjects = () => useMock ? mock(projects) : requestApi({ url: '/api/internal/development/projects/' });
export const createDevelopmentProject = (data) => requestApi({ url: '/api/internal/development/projects/', method: 'post', data });
export const advanceDevelopmentProject = (id, data) => requestApi({ url: `/api/internal/development/projects/${id}/advance/`, method: 'post', data });
export const finalizeDevelopmentProject = (id) => requestApi({ url: `/api/internal/development/projects/${id}/finalize/`, method: 'post' });
export const importDevelopmentSales = (csvText) => requestApi({ url: '/api/internal/development/sales/import/', method: 'post', data: { csv_text: csvText } });
export const fetchSalesSummary = () => useMock ? mock([]) : requestApi({ url: '/api/internal/development/sales/summary/' });
export const checkRequirementDuplicate = (data) => requestApi({ url: '/api/internal/development/requirements/duplicate-check/', method: 'post', data });

const productArchiveMock = [
  {
    id: 1,
    project: 3,
    project_id: 3,
    project_no: 'DEV-20260802-016',
    archive_no: 'DPA-20260815-001',
    product_name: '多功能露营照明灯',
    category: '户外用品',
    platform: 'shopee',
    site: 'TH',
    inventory_mode: 'virtual',
    virtual_inventory_sku: 'VT-DPA-20260815-001',
    virtual_inventory_qty: 2,
    test_result: 'pending',
    test_notes: '',
    status: 'trial',
    is_virtual: true,
    formal_product_id: null,
    formal_spu_code: null,
    events: [{ action: 'created', to_status: 'trial', created_at: '2026-08-15T08:00:00Z' }]
  }
];

const fetchDevelopmentProductArchivesLegacy = (params = {}) => useMock
  ? mock({ count: productArchiveMock.length, results: productArchiveMock, items: productArchiveMock, page: 1, page_size: productArchiveMock.length })
  : requestApi({ url: '/api/internal/development/product-archives/', params });

const createDevelopmentProductArchiveLegacy = (data) => requestApi({ url: '/api/internal/development/product-archives/', method: 'post', data });
const fetchDevelopmentProductArchiveLegacy = (id) => useMock
  ? mock(productArchiveMock.find((item) => String(item.id) === String(id)) || productArchiveMock[0])
  : requestApi({ url: `/api/internal/development/product-archives/${id}/` });
const updateDevelopmentProductArchiveLegacy = (id, data) => requestApi({ url: `/api/internal/development/product-archives/${id}/`, method: 'patch', data });
const confirmDevelopmentProductArchiveLegacy = (id, data = {}) => requestApi({ url: `/api/internal/development/product-archives/${id}/confirm-trial/`, method: 'post', data });
const formalizeDevelopmentProductArchiveLegacy = (id) => requestApi({ url: `/api/internal/development/product-archives/${id}/formalize/`, method: 'post' });

export const fetchDevelopmentRequirements = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/products/research/', params },
  () => successResponse({ api_status: 'mock', status: 'mock', items: [] }),
  'development.requirements'
);

export const createDevelopmentRequirement = (data) => requestWithMockFallback(
  { method: 'post', url: '/api/internal/products/research/', data },
  () => successResponse({
    api_status: 'mock',
    status: 'mock',
    id: `MOCK-REQUIREMENT-${Date.now()}`,
    research_no: `MOCK-REQ-${Date.now()}`,
    ...data,
    approval_status: 'pending'
  }),
  'development.requirements.create'
);

/*
 * Competitor analysis is an upstream, read-only source for the development
 * workspace.  The workspace stores only a reference and an approval snapshot;
 * it never imports/crawls or mutates competitor data.
 */
const competitorReport = {
  id: 'MOCK-COMPETITOR-REPORT-001',
  report_id: 'MOCK-COMPETITOR-REPORT-001',
  task_id: 'mock-voc-task-001',
  status: 'completed',
  is_mock: true,
  platform: 'shopee',
  site: 'PH',
  product_id: 'mock-platform-product-001',
  product_title: 'Mock long-sleeve yoga sports jacket',
  completed_at: '2026-07-31T15:33:36+08:00',
  updated_at: '2026-07-31T15:33:36+08:00',
  data_updated_at: '2026-07-31T15:33:36+08:00',
  statistics: {
    input_reviews: 143,
    valid_reviews: 143,
    positive: 18,
    neutral: 9,
    negative: 116
  },
  summary: 'Mock report：有效评价主要集中在尺码、面料质量和履约准确性。以下结论仅用于演示竞品判断流程，评价数量不代表销量或市场规模。',
  insights: {
    strengths: [
      { id: 'strength-1', text: '面料柔软、有弹性，部分用户反馈穿着舒适', issue_type: 'product' },
      { id: 'strength-2', text: '合身时版型适合跑步、徒步等运动场景', issue_type: 'product' },
      { id: 'strength-3', text: '部分颜色和外观与图片一致', issue_type: 'product' }
    ],
    pain_points: [
      { id: 'pain-1', text: '尺码普遍偏小，XL/XXL仍被反馈偏小', issue_type: 'product', severity: 'high' },
      { id: 'pain-2', text: '面料偏薄、廉价，容易刮坏或起毛', issue_type: 'product', severity: 'medium' },
      { id: 'pain-3', text: '错发颜色、尺码、款式和漏发问题频繁出现', issue_type: 'fulfillment', severity: 'high' },
      { id: 'pain-4', text: '物流延迟、未收到货和客服响应问题', issue_type: 'logistics', severity: 'medium' }
    ],
    recommendations: [
      { id: 'recommendation-1', text: '优化尺码表和版型标注，增加明确的加码建议', issue_type: 'product' },
      { id: 'recommendation-2', text: '稳定面料规格并加强厚度、弹性和耐磨质检', issue_type: 'supply_chain' },
      { id: 'recommendation-3', text: '针对颜色、尺码、款式和件数建立出库复核流程', issue_type: 'fulfillment' },
      { id: 'recommendation-4', text: '完善颜色展示并增加实物色差提示', issue_type: 'product' }
    ]
  },
  attributes: [
    { id: 'attribute-1', code: 'size_fit', name: '尺码与版型', mentions: 55, positive: 9, neutral: 5, negative: 41, conclusion: '尺码偏小是最高频痛点；少量评价认可合身和舒适。', issue_type: 'product' },
    { id: 'attribute-2', code: 'material_quality', name: '面料与质量', mentions: 42, positive: 16, neutral: 7, negative: 19, conclusion: '正向评价认可柔软、厚实、有弹性；负向集中在薄、廉价、易起毛。', issue_type: 'product' },
    { id: 'attribute-3', code: 'fulfillment_accuracy', name: '履约准确性', mentions: 31, positive: 0, neutral: 0, negative: 31, conclusion: '错发、漏发和漏发是明确的履约痛点，应交由仓储质检处理。', issue_type: 'fulfillment' },
    { id: 'attribute-4', code: 'appearance_color', name: '外观颜色', mentions: 29, positive: 13, neutral: 4, negative: 12, conclusion: '部分买家认可外观和颜色与图片一致；负向集中在色差、错色或外观不符。', issue_type: 'product' },
    { id: 'attribute-5', code: 'workmanship', name: '做工与瑕疵', mentions: 22, positive: 2, neutral: 1, negative: 19, conclusion: '负向问题包括破洞、开线、拉链缝反、拇指孔错位等。', issue_type: 'product' },
    { id: 'attribute-6', code: 'comfort_sport', name: '舒适度与运动适用', mentions: 20, positive: 13, neutral: 3, negative: 4, conclusion: '正向评价认为穿着舒适，适合跑步、徒步等场景；负向提到太紧、腋下痛、吸热闷热。', issue_type: 'product' },
    { id: 'attribute-7', code: 'logistics_service', name: '物流与客服', mentions: 9, positive: 5, neutral: 0, negative: 4, conclusion: '样本较少且评价分化，包含配送失效、客服响应和售后问题。', issue_type: 'logistics' }
  ],
  cautions: [
    '这是已完成的评价分析报告，当前页面只读展示上游结果。',
    '评价样本量仅代表本次分析覆盖的评价数量，不得直接推算销量或市场规模。',
    '履约、物流与客服问题需要运营/仓储协同，不应全部归因于产品设计。',
    'Mock报告用于演示，不代表真实商品、平台或市场结论。'
  ]
};

const competitorEvidence = [
  { id: 'evidence-1', attribute_code: 'size_fit', attribute_name: '尺码与版型', sentiment: 'negative', text: 'Way too small for 2xl', language: 'en' },
  { id: 'evidence-2', attribute_code: 'size_fit', attribute_name: '尺码与版型', sentiment: 'negative', text: 'my second order came very tight', language: 'en' },
  { id: 'evidence-3', attribute_code: 'size_fit', attribute_name: '尺码与版型', sentiment: 'positive', text: 'very comfy and fit', language: 'en' },
  { id: 'evidence-4', attribute_code: 'material_quality', attribute_name: '面料与质量', sentiment: 'positive', text: 'The fabric is comfortable', language: 'en' },
  { id: 'evidence-5', attribute_code: 'fulfillment_accuracy', attribute_name: '履约准确性', sentiment: 'negative', text: 'wrong color was delivered', language: 'en' },
  { id: 'evidence-6', attribute_code: 'fulfillment_accuracy', attribute_name: '履约准确性', sentiment: 'negative', text: 'Ordered pants. You gave me a shirt.', language: 'en' },
  { id: 'evidence-7', attribute_code: 'appearance_color', attribute_name: '外观颜色', sentiment: 'positive', text: 'true to pics', language: 'en' },
  { id: 'evidence-8', attribute_code: 'appearance_color', attribute_name: '外观颜色', sentiment: 'negative', text: 'malayo sa pic ang color', language: 'en' }
];

let mockAssociations = [];

const mockCompetitorReports = () => successResponse({
  api_status: 'mock',
  status: 'mock',
  module: 'development.competitor_reports',
  items: [competitorReport],
  results: [competitorReport],
  total: 1,
  page: 1,
  page_size: 20
});

const mockCompetitorReportDetail = () => successResponse({ api_status: 'mock', status: 'mock', ...competitorReport });

const mockCompetitorEvidence = (params = {}) => {
  const page = Math.max(Number(params.page) || 1, 1);
  const pageSize = Math.min(Math.max(Number(params.page_size) || 20, 1), 100);
  const start = (page - 1) * pageSize;
  return successResponse({
    api_status: 'mock',
    status: 'mock',
    report_id: competitorReport.id,
    items: competitorEvidence.slice(start, start + pageSize),
    results: competitorEvidence.slice(start, start + pageSize),
    total: competitorEvidence.length,
    page,
    page_size: pageSize
  });
};

const mockRequirementAssociations = (requirementId) => successResponse({
  api_status: 'mock',
  status: 'mock',
  requirement_id: requirementId,
  items: mockAssociations.filter((item) => String(item.requirement_id) === String(requirementId)),
  results: mockAssociations.filter((item) => String(item.requirement_id) === String(requirementId))
});

const mockCreateAssociation = (requirementId, payload) => {
  const association = {
    id: `MOCK-ASSOCIATION-${Date.now()}`,
    requirement_id: requirementId,
    report_id: payload.report_id || payload.competitor_report_id || competitorReport.id,
    competitor_report_id: payload.competitor_report_id || payload.report_id || competitorReport.id,
    is_primary: Boolean(payload.is_primary),
    selected_strengths: payload.selected_strengths || [],
    selected_pain_points: payload.selected_pain_points || [],
    selected_recommendations: payload.selected_recommendations || [],
    evidence_ids: payload.evidence_ids || [],
    operator_conclusion: payload.operator_conclusion || payload.manual_conclusion || '',
    excluded_items: payload.excluded_items || payload.exclusions || [],
    snapshot_at: new Date().toISOString(),
    report_snapshot: competitorReport
  };
  mockAssociations = [...mockAssociations.filter((item) => item.report_id !== association.report_id || String(item.requirement_id) !== String(requirementId)), association];
  return successResponse({ api_status: 'mock', status: 'mock', ...association });
};

const mockDeleteAssociation = (requirementId, associationId) => {
  mockAssociations = mockAssociations.filter((item) => String(item.requirement_id) !== String(requirementId) || String(item.id) !== String(associationId));
  return successResponse({ api_status: 'mock', status: 'mock', deleted: true, id: associationId });
};

export const fetchCompetitorReports = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/development/competitor-reports/', params },
  mockCompetitorReports,
  'development.competitor_reports'
);

export const fetchCompetitorReportDetail = (id = competitorReport.id) => requestWithMockFallback(
  { method: 'get', url: `/api/internal/development/competitor-reports/${id}/` },
  mockCompetitorReportDetail,
  'development.competitor_reports.detail'
);

export const fetchCompetitorReportEvidence = (id = competitorReport.id, params = {}) => requestWithMockFallback(
  { method: 'get', url: `/api/internal/development/competitor-reports/${id}/evidence/`, params },
  () => mockCompetitorEvidence(params),
  'development.competitor_reports.evidence'
);

export const fetchRequirementCompetitorAssociations = (requirementId) => requestWithMockFallback(
  { method: 'get', url: `/api/internal/development/requirements/${requirementId}/competitors/` },
  () => mockRequirementAssociations(requirementId),
  'development.requirements.competitor_associations'
);

export const createRequirementCompetitorAssociation = (requirementId, data) => requestWithMockFallback(
  { method: 'post', url: `/api/internal/development/requirements/${requirementId}/competitors/`, data },
  () => mockCreateAssociation(requirementId, data),
  'development.requirements.competitor_associations.create'
);

export const deleteRequirementCompetitorAssociation = (requirementId, associationId) => requestWithMockFallback(
  { method: 'delete', url: `/api/internal/development/requirements/${requirementId}/competitors/${associationId}/` },
  () => mockDeleteAssociation(requirementId, associationId),
  'development.requirements.competitor_associations.delete'
);

// Explicit aliases keep the API readable for callers that use the report's
// full domain name while preserving one implementation and one endpoint.
export const fetchCompetitorAnalysisReports = fetchCompetitorReports;
export const fetchCompetitorAnalysisReportDetail = fetchCompetitorReportDetail;
export const fetchCompetitorAnalysisEvidence = fetchCompetitorReportEvidence;

/*
 * Development product archives
 *
 * Archives are deliberately kept separate from the product master API.  A
 * newly-created row is a virtual trial record; the only calls that can create
 * a formal ProductSPU are the explicit confirm-trial and formalize actions.
 * The mock handlers mirror that lifecycle so the development workspace stays
 * usable when VITE_USE_MOCK is enabled, while production requests always use
 * the canonical backend contract.
 */
export const PRODUCT_ARCHIVES_URL = '/api/internal/development/product-archives/';
export const PRODUCT_ARCHIVES_ALIAS_URL = '/api/internal/development/archives/';

const mockProductArchives = [
  {
    id: 1,
    tenant: 'mock-tenant-001',
    project: 1,
    project_id: 1,
    project_no: 'DEV-20260803-018',
    project_stage: 'sampling',
    project_status: 'active',
    target_sites: ['TH', 'MY', 'SG'],
    assigned_to_id: 1,
    archive_no: 'DPA-20260803-001',
    product_name: '折叠电热水壶',
    category: '厨房小电',
    platform: 'shopee',
    site: 'TH',
    inventory_mode: 'virtual',
    virtual_inventory_sku: 'VT-DPA-20260803-001',
    virtual_inventory_qty: 12,
    test_result: 'pending',
    test_notes: '',
    status: 'trial',
    formal_product: null,
    formal_product_id: null,
    formal_spu_code: null,
    is_virtual: true,
    virtual_inventory: { mode: 'virtual', sku: 'VT-DPA-20260803-001', quantity: 12, platform: 'shopee', site: 'TH' },
    created_by_id: 1,
    updated_by_id: null,
    trial_confirmed_by_id: null,
    trial_confirmed_at: null,
    formalized_by_id: null,
    formalized_at: null,
    created_at: '2026-08-03T08:00:00Z',
    updated_at: '2026-08-03T08:00:00Z',
    events: [{ id: 1, action: 'created', from_status: '', to_status: 'trial', metadata: { inventory_mode: 'virtual' }, actor_id: 1, actor_name: 'Mock operator', created_at: '2026-08-03T08:00:00Z' }]
  },
  {
    id: 2,
    tenant: 'mock-tenant-001',
    project: 3,
    project_id: 3,
    project_no: 'DEV-20260802-016',
    project_stage: 'review',
    project_status: 'active',
    target_sites: ['TH', 'VN', 'MY'],
    assigned_to_id: 1,
    archive_no: 'DPA-20260802-001',
    product_name: '多功能露营照明灯',
    category: '户外用品',
    platform: 'lazada',
    site: 'MY',
    inventory_mode: 'virtual',
    virtual_inventory_sku: 'VT-DPA-20260802-001',
    virtual_inventory_qty: 8,
    test_result: 'pass',
    test_notes: '样品续航和亮度达到目标。',
    status: 'confirmed',
    formal_product: null,
    formal_product_id: null,
    formal_spu_code: null,
    is_virtual: true,
    virtual_inventory: { mode: 'virtual', sku: 'VT-DPA-20260802-001', quantity: 8, platform: 'lazada', site: 'MY' },
    created_by_id: 1,
    updated_by_id: 1,
    trial_confirmed_by_id: 1,
    trial_confirmed_at: '2026-08-08T09:30:00Z',
    formalized_by_id: null,
    formalized_at: null,
    created_at: '2026-08-02T08:00:00Z',
    updated_at: '2026-08-08T09:30:00Z',
    events: [
      { id: 2, action: 'created', from_status: '', to_status: 'trial', metadata: { inventory_mode: 'virtual' }, actor_id: 1, actor_name: 'Mock operator', created_at: '2026-08-02T08:00:00Z' },
      { id: 3, action: 'trial_confirmed', from_status: 'trial', to_status: 'confirmed', metadata: { test_result: 'pass' }, actor_id: 1, actor_name: 'Mock operator', created_at: '2026-08-08T09:30:00Z' }
    ]
  }
];

const cloneArchive = (archive) => JSON.parse(JSON.stringify(archive));

const archiveCollectionMock = (params = {}) => {
  const search = String(params.search || '').trim().toLowerCase();
  const status = String(params.status || '').trim();
  const platform = String(params.platform || '').trim();
  const site = String(params.site || '').trim();
  const items = mockProductArchives
    .filter((item) => !status || item.status === status)
    .filter((item) => !platform || item.platform === platform)
    .filter((item) => !site || item.site === site)
    .filter((item) => !search || [item.archive_no, item.product_name, item.project_no, item.virtual_inventory_sku].some((value) => String(value || '').toLowerCase().includes(search)))
    .map(cloneArchive);
  return successResponse(items);
};

const archiveDetailMock = (id) => {
  const item = mockProductArchives.find((archive) => String(archive.id) === String(id));
  return item ? successResponse(cloneArchive(item)) : successResponse({ status: 'mock', id: Number(id), missing: true });
};

const archiveCreateMock = (payload = {}) => {
  const projectId = Number(payload.project ?? payload.project_id ?? 1);
  const source = projects.find((project) => Number(project.id) === projectId) || projects[0];
  const id = Math.max(0, ...mockProductArchives.map((item) => Number(item.id) || 0)) + 1;
  const archiveNo = `DPA-MOCK-${String(id).padStart(3, '0')}`;
  const archive = {
    ...cloneArchive(mockProductArchives[0]),
    id,
    project: source.id,
    project_id: source.id,
    project_no: source.project_no,
    project_stage: source.stage,
    project_status: source.status,
    target_sites: source.target_sites || [],
    archive_no: archiveNo,
    product_name: payload.product_name || source.product_name || '未命名开发产品',
    category: payload.category || '',
    platform: payload.platform || 'internal',
    site: payload.site || 'internal',
    virtual_inventory_sku: `VT-${archiveNo}`,
    virtual_inventory_qty: Number(payload.virtual_inventory_qty || 0),
    test_result: 'pending',
    test_notes: payload.test_notes || '',
    status: 'trial',
    formal_product: null,
    formal_product_id: null,
    formal_spu_code: null,
    is_virtual: true,
    virtual_inventory: {
      mode: 'virtual',
      sku: `VT-${archiveNo}`,
      quantity: Number(payload.virtual_inventory_qty || 0),
      platform: payload.platform || 'internal',
      site: payload.site || 'internal'
    },
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    events: []
  };
  archive.events = [{ id: Date.now(), action: 'created', from_status: '', to_status: 'trial', metadata: { inventory_mode: 'virtual' }, actor_id: 1, actor_name: 'Mock operator', created_at: archive.created_at }];
  mockProductArchives.unshift(archive);
  return successResponse(cloneArchive(archive));
};

const archiveUpdateMock = (id, payload = {}) => {
  const archive = mockProductArchives.find((item) => String(item.id) === String(id));
  if (!archive) return archiveDetailMock(id);
  if (archive.status === 'trial') {
    ['product_name', 'category', 'platform', 'site', 'virtual_inventory_qty', 'test_notes'].forEach((field) => {
      if (Object.prototype.hasOwnProperty.call(payload, field)) archive[field] = payload[field];
    });
    archive.virtual_inventory = { mode: 'virtual', sku: archive.virtual_inventory_sku, quantity: Number(archive.virtual_inventory_qty || 0), platform: archive.platform, site: archive.site };
    archive.updated_at = new Date().toISOString();
  }
  return successResponse(cloneArchive(archive));
};

const archiveConfirmMock = (id, payload = {}) => {
  const archive = mockProductArchives.find((item) => String(item.id) === String(id));
  if (!archive) return archiveDetailMock(id);
  if (archive.status === 'trial') {
    archive.test_result = payload.test_result || 'pass';
    archive.test_notes = payload.test_notes || archive.test_notes || '';
    archive.status = 'confirmed';
    archive.trial_confirmed_by_id = 1;
    archive.trial_confirmed_at = new Date().toISOString();
    archive.updated_at = archive.trial_confirmed_at;
    archive.events = [...(archive.events || []), { id: Date.now(), action: 'trial_confirmed', from_status: 'trial', to_status: 'confirmed', metadata: { test_result: archive.test_result }, actor_id: 1, actor_name: 'Mock operator', created_at: archive.trial_confirmed_at }];
  }
  return successResponse({ archive: cloneArchive(archive), changed: true });
};

const archiveFormalizeMock = (id) => {
  const archive = mockProductArchives.find((item) => String(item.id) === String(id));
  if (!archive) return archiveDetailMock(id);
  if (archive.status === 'confirmed') {
    archive.status = 'formalized';
    archive.formal_product_id = archive.formal_product_id || 1000 + Number(archive.id);
    archive.formal_product = archive.formal_product_id;
    archive.formal_spu_code = archive.formal_spu_code || `SPU-MOCK-${String(archive.id).padStart(3, '0')}`;
    archive.is_virtual = false;
    archive.formalized_by_id = 1;
    archive.formalized_at = new Date().toISOString();
    archive.updated_at = archive.formalized_at;
    archive.events = [...(archive.events || []), { id: Date.now(), action: 'formalized', from_status: 'confirmed', to_status: 'formalized', metadata: { spu_code: archive.formal_spu_code }, actor_id: 1, actor_name: 'Mock operator', created_at: archive.formalized_at }];
  }
  return successResponse({ archive: cloneArchive(archive), product_id: archive.formal_product_id, spu_code: archive.formal_spu_code, created: true });
};

export const fetchProductArchives = (params = {}) => requestWithMockFallback(
  { method: 'get', url: PRODUCT_ARCHIVES_URL, params },
  () => archiveCollectionMock(params),
  'development.product_archives'
);

export const fetchProductArchiveDetail = (id) => requestWithMockFallback(
  { method: 'get', url: `${PRODUCT_ARCHIVES_URL}${id}/` },
  () => archiveDetailMock(id),
  'development.product_archives.detail'
);

export const createProductArchive = (data) => requestWithMockFallback(
  { method: 'post', url: PRODUCT_ARCHIVES_URL, data },
  () => archiveCreateMock(data),
  'development.product_archives.create'
);

export const updateProductArchive = (id, data) => requestWithMockFallback(
  { method: 'patch', url: `${PRODUCT_ARCHIVES_URL}${id}/`, data },
  () => archiveUpdateMock(id, data),
  'development.product_archives.update'
);

export const confirmProductArchiveTrial = (id, data = {}) => requestWithMockFallback(
  { method: 'post', url: `${PRODUCT_ARCHIVES_URL}${id}/confirm-trial/`, data },
  () => archiveConfirmMock(id, data),
  'development.product_archives.confirm_trial'
);

export const formalizeProductArchive = (id, data = {}) => requestWithMockFallback(
  { method: 'post', url: `${PRODUCT_ARCHIVES_URL}${id}/formalize/`, data },
  () => archiveFormalizeMock(id),
  'development.product_archives.formalize'
);

// Development-prefixed aliases make the API discoverable beside the existing
// project functions without duplicating request implementations.
export const fetchDevelopmentProductArchives = fetchProductArchives;
export const fetchDevelopmentProductArchive = fetchProductArchiveDetail;
export const fetchDevelopmentProductArchiveDetail = fetchProductArchiveDetail;
export const createDevelopmentProductArchive = createProductArchive;
export const updateDevelopmentProductArchive = updateProductArchive;
export const confirmDevelopmentProductArchive = confirmProductArchiveTrial;
export const confirmDevelopmentProductArchiveTrial = confirmProductArchiveTrial;
export const formalizeDevelopmentProductArchive = formalizeProductArchive;
