import { requestApi } from './request';

const BASE = '/api/internal/supply-chain/v2/';

export const fetchReplenishmentStrategy = (countryId) => requestApi({
  method: 'get', url: `${BASE}replenishment-strategies/`,
  params: countryId ? { country_id: countryId } : undefined
});

export const saveReplenishmentStrategy = (countryId, data) => requestApi({
  method: 'put', url: `${BASE}replenishment-strategies/`, params: { country_id: countryId }, data
});

export const fetchReplenishmentReferences = (data) => requestApi({
  method: 'post', url: `${BASE}replenishment-references/`, data
});

const JOBS = `${BASE}replenishment-jobs/`;
export const createReplenishmentJob = (data) => requestApi({ method: 'post', url: JOBS, data });
export const fetchReplenishmentJob = (id, config = {}) => requestApi({ method: 'get', url: `${JOBS}${encodeURIComponent(id)}/`, ...config });
export const fetchReplenishmentJobRows = (id, params, config = {}) => requestApi({ method: 'get', url: `${JOBS}${encodeURIComponent(id)}/rows/`, params, ...config });
export const cancelReplenishmentJob = (id) => requestApi({ method: 'delete', url: `${JOBS}${encodeURIComponent(id)}/` });
