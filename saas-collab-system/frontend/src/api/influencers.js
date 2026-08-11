import { requestWithMockFallback } from './request';
import { influencerMocks } from '../mock/influencers';

export const fetchInfluencers = (params = {}) => requestWithMockFallback(
  { method: 'get', url: '/api/internal/influencers/', params },
  influencerMocks.list,
  'influencers.list'
);

const mockWrite = (data) => () => ({ success: true, code: 'OK', message: 'Mock操作已记录', data: { ...data, api_status: 'mock' } });

export const createInfluencer = (payload) => requestWithMockFallback(
  { method: 'post', url: '/api/internal/influencers/', data: payload },
  mockWrite(payload),
  'influencers.create'
);

export const updateInfluencerStatus = (row, status) => requestWithMockFallback(
  { method: 'post', url: `/api/internal/influencers/${row.id}/status/`, data: { status } },
  mockWrite({ id: row.id, status }),
  'influencers.status'
);
