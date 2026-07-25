import { requestWithMockFallback } from './request';
import {
  mockConfirmReleaseBuild,
  mockCreateReleaseContract,
  mockDecideReleaseApproval,
  mockFetchReleaseContract,
  mockFetchReleaseContracts,
  mockRecordReleaseGate,
  mockRunReleaseAction
} from '../mock/releaseContracts';

const idempotencyKey = (action) =>
  `release-console-${action}-${Date.now()}-${Math.random().toString(16).slice(2)}`;

export const fetchReleaseContracts = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/releases/contracts/', params },
    () => mockFetchReleaseContracts(params),
    'releases.contracts'
  );

export const fetchReleaseContract = (id) =>
  requestWithMockFallback(
    { method: 'get', url: `/api/internal/releases/contracts/${id}/` },
    () => mockFetchReleaseContract(id),
    'releases.contract.detail'
  );

export const createReleaseContract = (payload) =>
  requestWithMockFallback(
    {
      method: 'post',
      url: '/api/internal/releases/contracts/',
      data: payload,
      headers: { 'Idempotency-Key': idempotencyKey('create') }
    },
    () => mockCreateReleaseContract(payload),
    'releases.contract.create'
  );

export const recordReleaseGate = (id, payload) =>
  requestWithMockFallback(
    {
      method: 'post',
      url: `/api/internal/releases/contracts/${id}/gates/`,
      data: payload,
      headers: { 'Idempotency-Key': idempotencyKey('gate') }
    },
    () => mockRecordReleaseGate(id, payload),
    'releases.contract.gate'
  );

export const decideReleaseApproval = (id, payload) =>
  requestWithMockFallback(
    {
      method: 'post',
      url: `/api/internal/releases/contracts/${id}/approvals/`,
      data: payload,
      headers: { 'Idempotency-Key': idempotencyKey('approval') }
    },
    () => mockDecideReleaseApproval(id, payload),
    'releases.contract.approval'
  );

export const confirmReleaseBuild = (id, payload) =>
  requestWithMockFallback(
    {
      method: 'post',
      url: `/api/internal/releases/contracts/${id}/build/`,
      data: payload,
      headers: { 'Idempotency-Key': idempotencyKey('build') }
    },
    () => mockConfirmReleaseBuild(id, payload),
    'releases.contract.build'
  );

export const runReleaseAction = (id, action, payload) =>
  requestWithMockFallback(
    {
      method: 'post',
      url: `/api/internal/releases/contracts/${id}/actions/${action}/`,
      data: payload,
      headers: { 'Idempotency-Key': idempotencyKey(action) }
    },
    () => mockRunReleaseAction(id, action, payload),
    `releases.contract.${action}`
  );
