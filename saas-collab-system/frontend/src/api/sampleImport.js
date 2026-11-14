import { requestApi } from './request';

const API_ROOT = '/api/internal/influencers';

export function previewSampleImport(file) {
  const data = new FormData();
  data.append('file', file);
  return requestApi({ method: 'post', url: `${API_ROOT}/sample-import/preview/`, data, timeout: 60000 });
}

export const confirmSampleImport = (payload) => requestApi({
  method: 'post', url: `${API_ROOT}/sample-import/confirm/`, data: payload, timeout: 60000
});

export const fetchSampleImportInfluencerCandidates = (nickname) => requestApi({
  method: 'get', url: `${API_ROOT}/resolve/`, params: { q: nickname }
});
