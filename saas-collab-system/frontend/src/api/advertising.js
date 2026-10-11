import { requestApi, requestPendingOrMock } from './request';

// Query persisted provider facts; never fall back to fabricated metrics.
export const fetchAdvertisingOverview = (params = {}) => {
  return requestApi({ url: '/api/internal/analytics/advertising/', method: 'get', params: { kind: 'shop_daily', ...params } });
};

export const fetchAdvertisingPerformance = (params = {}) => {
  return requestApi({ url: '/api/internal/analytics/advertising/', method: 'get', params: { kind: 'campaign_daily', ...params } });
};

export const fetchAdvertisingReconciliation = (params = {}) => {
  void params;
  return requestPendingOrMock(null, 'finance.advertising.reconciliation');
};
