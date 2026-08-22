import { requestApi, requestWithMockFallback, useMock } from './request';
import { successResponse } from '../mock';

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
