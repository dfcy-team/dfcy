import request from './request';
export const getAutomation = (path, params = {}) => request.get('/api/internal/automation/' + path, { params });
