import { requestPendingOrMock } from './request';

// Advertising reporting is read-only and remains pending until platform
// report resources are connected. Do not fabricate spend or sales metrics.
export const fetchAdvertisingOverview = (params = {}) => {
  void params;
  return requestPendingOrMock(null, 'analytics.advertising.overview');
};

export const fetchAdvertisingPerformance = (params = {}) => {
  void params;
  return requestPendingOrMock(null, 'analytics.advertising.performance');
};

export const fetchAdvertisingReconciliation = (params = {}) => {
  void params;
  return requestPendingOrMock(null, 'finance.advertising.reconciliation');
};
