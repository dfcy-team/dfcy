import { requestApi } from './request';
export const fetchFinanceImports = () => requestApi({ method: 'get', url: '/api/finance/imports/' });
export function submitFinanceImport(kind, file, mode = 'preview', sha256 = '') {
  const data = new FormData();
  data.append('kind', kind);
  data.append('file', file);
  data.append('mode', mode);
  if (sha256) data.append('sha256', sha256);
  return requestApi({ method: 'post', url: '/api/finance/imports/', data, timeout: 30000 });
}
