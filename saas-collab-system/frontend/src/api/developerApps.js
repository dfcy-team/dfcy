import { requestApi, fetchApiFile } from './request';
const root = '/api/internal/integrations/';
export const developerRequest = (path, method = 'get', data) => requestApi({ url: `${root}${path}`, method, data });
export const downloadDeveloperDocs = id => fetchApiFile(`${root}developer-apps/${id}/docs/`);
