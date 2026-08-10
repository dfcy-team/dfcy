import { requestApi } from './request';

export const fetchDevelopmentProjects = (params = {}) => requestApi({
  url: '/api/internal/development/projects/', method: 'get', params
});

export const createDevelopmentProject = (data) => requestApi({
  url: '/api/internal/development/projects/', method: 'post', data
});

export const importDevelopmentSales = (csvText) => requestApi({
  url: '/api/internal/development/sales/import/', method: 'post', data: { csv_text: csvText }
});
