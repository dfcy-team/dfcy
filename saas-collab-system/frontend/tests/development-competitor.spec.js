import fs from 'node:fs';
import nodePath from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  createRequirementCompetitorAssociation,
  fetchCompetitorReportDetail,
  fetchCompetitorReportEvidence,
  fetchCompetitorReports,
  fetchDevelopmentRequirements,
  createDevelopmentRequirement,
  fetchRequirementCompetitorAssociations
} from '../src/api/development';

const read = (path) => fs.readFileSync(nodePath.resolve(process.cwd(), path), 'utf8');

describe('development competitor report contract', () => {
  it('uses canonical report GET endpoints and competitor relation endpoints', () => {
    const api = read('src/api/development.js');
    expect(api).toContain("/api/internal/development/competitor-reports/");
    expect(api).toContain("/api/internal/development/competitor-reports/${id}/evidence/");
    expect(api).toContain("/api/internal/development/requirements/${requirementId}/competitors/");
    expect(api).toContain("/api/internal/development/requirements/${requirementId}/competitors/${associationId}/");
    expect(api).toContain("method: 'get'");
    expect(api).toContain("method: 'post'");
    expect(api).toContain("method: 'delete'");
  });

  it('keeps upstream report and evidence access read-only', () => {
    const api = read('src/api/development.js');
    const reportApi = api.slice(api.indexOf('export const fetchCompetitorReports'));
    expect(reportApi).not.toMatch(/url: `?[^`\n]*competitor-reports[^`\n]*`?, method: 'post'/);
    expect(reportApi).not.toMatch(/url: `?[^`\n]*competitor-reports[^`\n]*`?, method: 'delete'/);
  });

  it('returns explicitly labelled mock report data with screenshot-shaped sections', async () => {
    const list = await fetchCompetitorReports({ status: 'completed' });
    const report = list.data.items[0];
    expect(list.success).toBe(true);
    expect(list.data.api_status).toBe('mock');
    expect(report.is_mock).toBe(true);
    expect(report.status).toBe('completed');
    expect(report.statistics).toMatchObject({ valid_reviews: 143, positive: 18, neutral: 9, negative: 116 });
    expect(report.insights).toEqual(expect.objectContaining({ strengths: expect.any(Array), pain_points: expect.any(Array), recommendations: expect.any(Array) }));
    expect(report.attributes.length).toBeGreaterThan(0);
    expect(report.cautions.join(' ')).toContain('销量或市场规模');

    const detail = await fetchCompetitorReportDetail(report.id);
    const evidence = await fetchCompetitorReportEvidence(report.id, { page: 1, page_size: 2 });
    expect(detail.data.report_id).toBe(report.report_id);
    expect(evidence.data.items).toHaveLength(2);
    expect(evidence.data.items[0]).toHaveProperty('text');
  });

  it('supports requirement creation before snapshot association in mock mode', async () => {
    const requirement = await createDevelopmentRequirement({ product_name: 'Mock requirement' });
    expect(requirement.data.id).toMatch(/^MOCK-REQUIREMENT-/);
    const link = await createRequirementCompetitorAssociation(requirement.data.id, {
      report_id: 'MOCK-COMPETITOR-REPORT-001',
      selected_strengths: ['面料柔软'],
      selected_pain_points: ['尺码偏小'],
      selected_recommendations: [],
      excluded_items: [],
      operator_conclusion: '保留舒适面料，优先修正尺码。'
    });
    expect(link.success).toBe(true);
    expect(link.data.report_id).toBe('MOCK-COMPETITOR-REPORT-001');
    const links = await fetchRequirementCompetitorAssociations(requirement.data.id);
    expect(links.data.items).toHaveLength(1);
  });

  it('exposes bounded UI copy without competitor import or crawling workflow', () => {
    const page = read('src/views/development/DevelopmentWorkspace.vue');
    expect(page).toContain('关联竞品分析');
    expect(page).toContain('实时报告');
    expect(page).toContain('审核快照');
    expect(page).toContain('评价数量不代表销量或市场规模');
    expect(page).toContain('履约/物流问题');
    expect(page).toContain('保存关联快照');
    expect(page).toContain('填写排除原因');
    expect(page).toContain('selectedEvidenceIds');
    expect(page).toContain('research_no');
    expect(page).not.toContain('导入竞品评价');
    expect(page).not.toContain('爬取竞品');
  });
});
