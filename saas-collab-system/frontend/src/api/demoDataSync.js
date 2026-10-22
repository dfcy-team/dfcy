import { downloadApiFile, requestApi } from './request';

const base = '/api/internal/demo-data-sync/';

// This feature always talks to the configured internal service. In particular,
// a failed request must remain visible instead of being replaced by fixtures.
export const fetchDemoDataSyncOptions = () => requestApi({ method: 'get', url: `${base}options/` });
export const fetchDemoSyncEnvironments = () => requestApi({ method: 'get', url: `${base}environments/` });
export const createDemoSyncEnvironment = (payload) => requestApi({ method: 'post', url: `${base}environments/`, data: payload });
export const updateDemoSyncEnvironmentStatus = (id, active) => requestApi({ method: 'patch', url: `${base}environments/${encodeURIComponent(id)}/`, data: { active } });
export const fetchDemoSyncBatches = () => requestApi({ method: 'get', url: `${base}batches/` });
export const createDemoSyncBatch = (payload) => requestApi({ method: 'post', url: `${base}batches/`, data: payload });
export const fetchDemoSyncBatch = (id) => requestApi({ method: 'get', url: `${base}batches/${encodeURIComponent(id)}/` });
export const retryDemoSyncBatch = (id) => requestApi({ method: 'post', url: `${base}batches/${encodeURIComponent(id)}/retry/` });
export const downloadDemoSyncBatch = (id, filename) => downloadApiFile(
  `/api/internal/demo-data-sync/batches/${encodeURIComponent(id)}/download/`,
  filename,
);
