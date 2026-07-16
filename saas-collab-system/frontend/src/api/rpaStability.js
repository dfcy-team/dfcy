import { requestWithMockFallback } from './request';
import {
  mockRpaAccountLocks,
  mockRpaDeviceDetail,
  mockRpaDevices,
  mockRpaAttemptDetail,
  mockRpaAttempts,
  mockRpaManualQueue,
  mockRpaPageSignatures,
  mockRpaStabilityDashboard
} from '../mock/rpaStability';

export const fetchRpaStabilityDashboard = () =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/rpa/stability/' }, mockRpaStabilityDashboard, 'rpa.stability.dashboard');

export const fetchRpaRuns = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/rpa/runs/', params }, mockRpaAttempts, 'rpa.runs');

export const fetchRpaRunDetail = (id = 1) =>
  requestWithMockFallback({ method: 'get', url: `/api/internal/rpa/runs/${id}/` }, mockRpaAttemptDetail, 'rpa.runs.detail');

export const fetchRpaManualQueue = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/rpa/manual-queue/', params }, mockRpaManualQueue, 'rpa.manual_queue');

export const fetchRpaAccountLocks = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/rpa/account-locks/', params }, mockRpaAccountLocks, 'rpa.account_locks');

export const fetchRpaPageSignatures = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/rpa/page-signatures/', params }, mockRpaPageSignatures, 'rpa.page_signatures');

export const fetchRpaDevices = (params = {}) =>
  requestWithMockFallback({ method: 'get', url: '/api/internal/rpa/devices/', params }, mockRpaDevices, 'rpa.devices');

export const fetchRpaDeviceDetail = (id = 1) =>
  requestWithMockFallback({ method: 'get', url: `/api/internal/rpa/devices/${id}/` }, mockRpaDeviceDetail, 'rpa.devices.detail');

export const runRpaDeviceDryRun = (id = 1) =>
  requestWithMockFallback({ method: 'post', url: `/api/internal/rpa/devices/${id}/dry-run/` }, mockRpaDeviceDetail, 'rpa.devices.dry_run');

export const fetchRpaAttempts = fetchRpaRuns;
export const fetchRpaAttemptDetail = fetchRpaRunDetail;
