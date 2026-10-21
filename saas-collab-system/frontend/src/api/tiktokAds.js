import { requestApi } from './request';
const base = '/api/internal/integrations/tiktok-ads/oauth/';
export const startAdsOAuth = (data) => requestApi({ method: 'post', url: `${base}start/`, data });
export const completeAdsDirectOAuth = (data) => requestApi({ method: 'post', url: `${base}direct-callback/`,
  data, timeout: 60000, noMockFallback: true, _authRetried: true });
export const completeAdsOAuth = (data) => requestApi({ method: 'post', url: `${base}complete/`, data, timeout: 90000, noMockFallback: true });
export const getAdsSession = (id) => requestApi({ method: 'get', url: `${base}sessions/${encodeURIComponent(id)}/` });
export const discoverAds = (id) => requestApi({ method: 'post', url: `${base}sessions/${encodeURIComponent(id)}/discover/`, data: {}, timeout: 60000 });
export const verifyAds = (id, advertiser) => requestApi({ method: 'post', url: `${base}sessions/${encodeURIComponent(id)}/advertisers/${encodeURIComponent(advertiser)}/verify/`, data: {}, timeout: 60000 });
export const bindAds = (id, data) => requestApi({ method: 'post', url: `${base}sessions/${encodeURIComponent(id)}/bind/`, data });
export const fetchAdsCapabilities = () => requestApi({ method: 'get', url: '/api/internal/integrations/tiktok-ads/capabilities/' });
export const updateAdsReadCapability = (id, readEnabled) => requestApi({ method: 'put',
  url: `/api/internal/integrations/tiktok-ads/mappings/${encodeURIComponent(id)}/capability/`,
  data: { read_enabled: readEnabled }, noMockFallback: true });
