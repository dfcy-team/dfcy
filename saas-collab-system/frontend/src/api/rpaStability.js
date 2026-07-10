import { requestWithMockFallback } from './request';
import {
  mockRpaAccountLocks,
  mockRpaAttemptDetail,
  mockRpaAttempts,
  mockRpaManualQueue,
  mockRpaPageSignatures,
  mockRpaStabilityDashboard
} from '../mock/rpaStability';

export const fetchRpaStabilityDashboard = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/rpa/tasks/' }, mockRpaStabilityDashboard, 'rpa.stability.dashboard');

export const fetchRpaAttempts = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/rpa/attempts/' }, mockRpaAttempts, 'rpa.attempts');

export const fetchRpaAttemptDetail = (id = 1) =>
  requestWithMockFallback({ method: 'get', url: `/api/internal/rpa/attempts/${id}/` }, mockRpaAttemptDetail, 'rpa.attempts.detail');

export const fetchRpaManualQueue = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/rpa/manual-queue/' }, mockRpaManualQueue, 'rpa.manual_queue');

export const fetchRpaAccountLocks = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/rpa/account-locks/' }, mockRpaAccountLocks, 'rpa.account_locks');

export const fetchRpaPageSignatures = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/rpa/page-signatures/' }, mockRpaPageSignatures, 'rpa.page_signatures');

export const assignRpaManual = (id = 1) =>
  requestWithMockFallback({ method: 'post', url: `/api/internal/rpa/tasks/${id}/assign-manual/` }, mockRpaManualQueue, 'rpa.assign_manual');

export const retryRpaMock = (id = 1) =>
  requestWithMockFallback({ method: 'post', url: `/api/internal/rpa/tasks/${id}/retry-mock/` }, mockRpaAttempts, 'rpa.retry_mock');
