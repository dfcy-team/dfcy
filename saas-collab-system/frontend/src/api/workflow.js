import { requestApi, requestWithMockFallback, useMock } from './request';
import {
  mockApprovalDetail,
  mockApprovals,
  mockCollaborationEvents,
  mockExceptionDetail,
  mockExceptions
} from '../mock/workflow';

const mockWriteDisabled = () => Promise.resolve({
  success: false,
  code: 'MOCK_WRITE_DISABLED',
  message: 'Mock模式不发送审批、异常或协同写请求。',
  data: null
});
const write = (config) => (useMock ? mockWriteDisabled() : requestApi(config));

export const fetchApprovals = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/workflow/approvals/', params }, mockApprovals, 'workflow.approvals');
export const fetchPaymentFlows = () => requestApi({ method: 'get', url: '/api/internal/workflow/payment-flows/' });
export const fetchPaymentFlowReviewers = () => requestApi({ method: 'get', url: '/api/internal/workflow/payment-flow-reviewers/' });
export const fetchPaymentFlowDepartments = () => requestApi({ method: 'get', url: '/api/internal/workflow/payment-flow-departments/' });
export const createPaymentFlow = (data) => write({ method: 'post', url: '/api/internal/workflow/payment-flows/', data });
export const updatePaymentFlowStatus = (id, action) => write({ method: 'post', url: `/api/internal/workflow/payment-flows/${id}/${action}/`, data: {} });
export const fetchApproval = (id) =>
  requestWithMockFallback({ method: 'get', url: `/api/internal/workflow/approvals/${id}/` }, () => mockApprovalDetail(id), 'workflow.approvals.detail');
export const createMockApproval = (payload) => write({ method: 'post', url: '/api/internal/workflow/approvals/mock/', data: payload });
export const approveApproval = (id, payload = {}) => write({ method: 'post', url: `/api/internal/workflow/approvals/${id}/approve/`, data: payload });
export const rejectApproval = (id, payload = {}) => write({ method: 'post', url: `/api/internal/workflow/approvals/${id}/reject/`, data: payload });
export const withdrawApproval = (id, payload = {}) => write({ method: 'post', url: `/api/internal/workflow/approvals/${id}/withdraw/`, data: payload });

export const fetchWorkflowExceptions = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/workflow/exceptions/', params }, mockExceptions, 'workflow.exceptions');
export const fetchWorkflowException = (id) =>
  requestWithMockFallback({ method: 'get', url: `/api/internal/workflow/exceptions/${id}/` }, () => mockExceptionDetail(id), 'workflow.exceptions.detail');
export const createMockException = (payload) => write({ method: 'post', url: '/api/internal/workflow/exceptions/mock/', data: payload });
export const assignWorkflowException = (id, payload) => write({ method: 'post', url: `/api/internal/workflow/exceptions/${id}/assign/`, data: payload });
export const resolveWorkflowException = (id, payload) => write({ method: 'post', url: `/api/internal/workflow/exceptions/${id}/resolve/`, data: payload });
export const closeWorkflowException = (id) => write({ method: 'post', url: `/api/internal/workflow/exceptions/${id}/close/`, data: {} });

export const fetchCollaborationEvents = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/workflow/collaboration-events/', params }, mockCollaborationEvents, 'workflow.collaboration');
export const confirmCollaborationEvent = (id, payload = {}) => write({ method: 'post', url: `/api/internal/workflow/collaboration-events/${id}/confirm/`, data: payload });
export const rejectCollaborationEvent = (id, payload = {}) => write({ method: 'post', url: `/api/internal/workflow/collaboration-events/${id}/reject/`, data: payload });
