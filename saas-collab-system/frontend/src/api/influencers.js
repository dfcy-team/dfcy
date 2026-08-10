import { requestApi } from './request';

export const fetchInfluencers = (params = {}) => requestApi({ url: '/api/internal/influencers/', method: 'get', params });
export const createInfluencer = (data) => requestApi({ url: '/api/internal/influencers/', method: 'post', data });

export const fetchOutreachTasks = (params = {}) => requestApi({ url: '/api/internal/influencers/outreach-tasks/', method: 'get', params });
export const createOutreachTask = (data) => requestApi({ url: '/api/internal/influencers/outreach-tasks/', method: 'post', data });
export const updateOutreachStatus = (id, status, version) => requestApi({
  url: `/api/internal/influencers/outreach-tasks/${id}/status/`,
  method: 'post',
  data: { status },
  headers: { 'If-Match': String(version) }
});

export const fetchSampleFulfillments = (params = {}) => requestApi({ url: '/api/internal/influencers/sample-fulfillments/', method: 'get', params });
export const createSampleFulfillment = (data, idempotencyKey) => requestApi({
  url: '/api/internal/influencers/sample-fulfillments/',
  method: 'post',
  data,
  headers: { 'Idempotency-Key': idempotencyKey }
});
export const updateSampleStatus = (id, status, version, reason = '') => requestApi({
  url: `/api/internal/influencers/sample-fulfillments/${id}/status/`,
  method: 'post',
  data: { status, reason },
  headers: { 'If-Match': String(version) }
});

export const lookupProductPrice = (params) => requestApi({
  url: '/api/internal/influencers/product-price-lookup/',
  method: 'get',
  params
});
