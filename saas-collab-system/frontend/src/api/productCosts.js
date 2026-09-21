import { requestApi } from './request';

export const fetchProductCosts = (params = {}) => requestApi({ method: 'get', url: '/api/internal/products/costs/', params });

export const createProductCostVersion = (data) => requestApi({ method: 'post', url: '/api/internal/products/costs/versions/', data });

export const previewProductCostBackfill = (data = {}) => requestApi({ method: 'post', url: '/api/internal/products/costs/backfill-preview/', data });
