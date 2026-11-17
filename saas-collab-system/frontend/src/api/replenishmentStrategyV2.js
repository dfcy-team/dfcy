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
const DAILY = `${BASE}replenishment-daily/`;
const isDailyEligible = (data = {}) => data.source_kind === 'cycle'
  && ['country', 'platform'].includes(data.analysis_mode)
  && (data.analysis_mode !== 'platform' || Boolean(data.platform_type))
  && !data.exclude_operating_order_id
  && !data.activity_start
  && !data.activity_end
  && (data.activity_factor == null || Number(data.activity_factor) === 1);

// Routine country suggestions read the precomputed daily snapshot. Special analyses
// continue to create their own calculation jobs through the existing endpoint.
export const fetchDailyReplenishment = (data) => requestApi({
  method: 'get', url: DAILY,
  params: { country_id: data.country_id, analysis_mode: data.analysis_mode,
    ...(data.analysis_mode === 'platform' ? { platform_type: data.platform_type } : {}) }
});
export const createReplenishmentJob = (data) => isDailyEligible(data)
  ? fetchDailyReplenishment(data)
  : requestApi({ method: 'post', url: JOBS, data });
export const fetchReplenishmentJob = (id, config = {}) => requestApi({ method: 'get', url: `${JOBS}${encodeURIComponent(id)}/`, ...config });
export const fetchReplenishmentJobRows = (id, params, config = {}) => {
  const key = String(id);
  if (key.startsWith('daily:')) {
    const uuid = key.slice('daily:'.length);
    return requestApi({ method: 'get', url: `${DAILY}${encodeURIComponent(uuid)}/rows/`, params, ...config });
  }
  return requestApi({ method: 'get', url: `${JOBS}${encodeURIComponent(id)}/rows/`, params, ...config });
};
export const cancelReplenishmentJob = (id) => requestApi({ method: 'delete', url: `${JOBS}${encodeURIComponent(id)}/` });
