import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { canAccessPath, filterMenuItems, flattenMenuItems } from '../src/router/menu';
import { getActionAccess } from '../src/utils/actionAccess';
import { mockApprovals, mockCollaborationEvents, mockExceptions } from '../src/mock/workflow';
import { approveApproval, confirmCollaborationEvent } from '../src/api/workflow';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');
const viewer = {
  user_type: 'internal',
  is_superuser: false,
  permissions: ['workflow.approvals.view', 'workflow.exceptions.view', 'workflow.collaboration.view', 'reports.view']
};
const authFor = (user) => ({
  currentUser: user,
  hasPermission: (...codes) => Boolean(user.is_superuser) || codes.some((code) => user.permissions.includes(code))
});

describe('UI-P4 routes and action permissions', () => {
  it('guards payment flow management with its own permission and renders approval identity labels', () => {
    expect(canAccessPath(viewer, '/workflow/payment-flows')).toBe(false);
    const manager = { ...viewer, permissions: [...viewer.permissions, 'workflow.approvals.manage'] };
    expect(canAccessPath(manager, '/workflow/payment-flows')).toBe(true);
    const page = read('src/views/workflow/ApprovalDetail.vue');
    expect(page).toContain('指定审批人');
    expect(page).toContain('申请人');
    expect(page).toContain('业务类型');
    expect(page).toContain('detail.business_type_label');
    expect(page).toContain('detail.payment_display?.application_reference');
    expect(page).toContain('detail.payment_display.reason');
    expect(page).toContain('付款对象');
    expect(page).toContain('detail.business_reference');
    expect(page).not.toContain('detail.business_id');
    expect(page).toContain("timeZone: 'Asia/Shanghai'");
    expect(page).toContain('formatBeijingTime(item.created_at)');
    expect(page).not.toContain('detail.business_type ||');
    const flows = read('src/views/workflow/PaymentFlowManagement.vue');
    expect(flows.replace(/\s/g, '')).toContain("{value:'purchase',label:'采购定金'}");
    expect(flows.replace(/\s/g, '')).toContain("{value:'shipment',label:'供应商货款'}");
    expect(flows.replace(/\s/g, '')).toContain("{value:'batch',label:'国际/批次货运费'}");
    expect(flows.replace(/\s/g, '')).toContain("{value:'payment_batch',label:'合并付款审批'}");
    expect(flows).toContain('全部部门');
    expect(flows).toContain("row.maximum_amount==null?'':String(row.maximum_amount)");
  });


  it('registers every workflow page behind an explicit internal permission', () => {
    for (const path of ['/workflow/approvals', '/workflow/approvals/1', '/workflow/exceptions', '/workflow/exceptions/1', '/workflow/collaboration-events']) {
      expect(canAccessPath(viewer, path), path).toBe(true);
    }
    expect(canAccessPath({ ...viewer, user_type: 'external' }, '/workflow/approvals')).toBe(false);
    expect(canAccessPath({ ...viewer, user_type: 'rpa' }, '/workflow/exceptions')).toBe(false);
    expect(canAccessPath(viewer, '/workflow/not-registered')).toBe(false);
  });

  it('shows workflow menu entries but hides write actions from view-only users', () => {
    const paths = flattenMenuItems(filterMenuItems(viewer)).map((item) => item.path);
    expect(paths).toContain('/workflow/approvals');
    expect(paths).toContain('/workflow/exceptions');
    expect(paths).toContain('/workflow/collaboration-events');
    expect(getActionAccess(authFor(viewer), { permission: 'workflow.approvals.review' }).visible).toBe(false);
    expect(getActionAccess(authFor(viewer), { permission: 'workflow.exceptions.manage' }).allowed).toBe(false);
  });

  it('allows actions only with the matching backend permission code', () => {
    const operator = {
      ...viewer,
      permissions: [...viewer.permissions, 'workflow.approvals.review', 'workflow.exceptions.manage', 'workflow.collaboration.confirm']
    };
    expect(getActionAccess(authFor(operator), { permission: 'workflow.approvals.review' }).allowed).toBe(true);
    expect(getActionAccess(authFor(operator), { permission: 'workflow.exceptions.manage' }).allowed).toBe(true);
    expect(getActionAccess(authFor(operator), { permission: 'workflow.collaboration.confirm' }).allowed).toBe(true);
  });
});

describe('UI-P4 API and mock safety', () => {
  it('uses the frozen internal workflow and report paths', () => {
    const workflow = read('src/api/workflow.js');
    const reports = read('src/api/reportExports.js');
    for (const path of [
      '/api/internal/workflow/approvals/',
      '/api/internal/workflow/exceptions/',
      '/api/internal/workflow/collaboration-events/'
    ]) expect(workflow).toContain(path);
    expect(reports).toContain('/api/report/exports/${id}/download/');
    expect(workflow).not.toContain('/api/rpa/');
    expect(workflow).not.toContain('/admin/');
  });

  it('keeps read recovery and exception assignment inside the controlled API layer', () => {
    const workflow = read('src/api/workflow.js');
    const exceptionPages = [
      'src/views/workflow/ExceptionList.vue',
      'src/views/workflow/ExceptionDetail.vue'
    ].map(read).join('\n');

    expect(workflow).toContain('requestWithMockFallback');
    expect(workflow).toContain('/api/internal/workflow/exceptions/${id}/assign/');
    expect(exceptionPages).toContain('workflow.exceptions.manage');
    expect(exceptionPages).toContain('分配给我');
  });

  it('keeps mock collections paginated and feedback pending confirmation', () => {
    for (const response of [mockApprovals(), mockExceptions(), mockCollaborationEvents()]) {
      expect(response.data.status).toBe('mock');
      expect(response.data).toHaveProperty('count');
      expect(Array.isArray(response.data.results)).toBe(true);
    }
    expect(mockCollaborationEvents().data.results[0].status).toBe('pending_confirmation');
  });

  it('does not send workflow writes while VITE_USE_MOCK is enabled', async () => {
    expect((await approveApproval(1)).code).toBe('MOCK_WRITE_DISABLED');
    expect((await confirmCollaborationEvent(1)).code).toBe('MOCK_WRITE_DISABLED');
  });

  it('keeps high-risk and external feedback boundaries visible in pages', () => {
    const pages = [
      'src/views/workflow/ApprovalList.vue',
      'src/views/workflow/ExceptionList.vue',
      'src/views/workflow/CollaborationEventList.vue'
    ].map(read).join('\n');
    expect(pages).toContain('不执行采购、改价、刊登、清仓、财务或RPA动作');
    expect(pages).toContain('不直接写入业务主数据');
    expect(pages).not.toMatch(/真实平台连接|立即付款|自动采购/);

    const reports = read('src/views/reports/ReportExportCenter.vue');
    expect(reports).toContain("auth.hasPermission?.('reports.export')");
    expect(reports).toContain("auth.hasPermission?.('reports.download')");
    expect(reports).toContain("!row.has_file || row.status !== 'completed'");
    expect(reports).toContain("reference.startsWith('/api/report/exports/')");
  });
});
