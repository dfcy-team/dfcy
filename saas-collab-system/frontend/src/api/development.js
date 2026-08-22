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

export const fetchDevelopmentProductArchives = (params = {}) => requestApi({
  url: '/api/internal/development/product-archives/', method: 'get', params
});

export const createDevelopmentProductArchive = (data) => requestApi({
  url: '/api/internal/development/product-archives/', method: 'post', data
});

export const fetchDevelopmentProductArchive = (id) => requestApi({
  url: `/api/internal/development/product-archives/${id}/`, method: 'get'
});

export const updateDevelopmentProductArchive = (id, data) => requestApi({
  url: `/api/internal/development/product-archives/${id}/`, method: 'patch', data
});

export const confirmDevelopmentProductArchive = (id, data = {}) => requestApi({
  url: `/api/internal/development/product-archives/${id}/confirm-trial/`, method: 'post', data
});

export const generateDevelopmentProductArchiveTrial = (id, data = {}) => requestApi({
  url: `/api/internal/development/product-archives/${id}/generate-trial/`, method: 'post', data
});

export const formalizeDevelopmentProductArchive = (id) => requestApi({
  url: `/api/internal/development/product-archives/${id}/formalize/`, method: 'post'
});
