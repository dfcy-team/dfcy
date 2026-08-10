import { requestApi } from './request';

const baseUrl = '/api/internal/releases/contracts/';

export const fetchReleaseContracts = (params = {}) => requestApi({ url: baseUrl, method: 'get', params });
export const fetchReleaseContract = (id) => requestApi({ url: `${baseUrl}${id}/`, method: 'get' });
export const createReleaseContract = (data) => requestApi({ url: baseUrl, method: 'post', data });
export const recordReleaseGate = (id, data) => requestApi({ url: `${baseUrl}${id}/gates/`, method: 'post', data });
export const decideReleaseApproval = (id, data) => requestApi({ url: `${baseUrl}${id}/approvals/`, method: 'post', data });
export const confirmReleaseBuild = (id, data) => requestApi({ url: `${baseUrl}${id}/build/`, method: 'post', data });
export const runReleaseAction = (id, action, data = {}) => requestApi({
  url: `${baseUrl}${id}/actions/${action}/`, method: 'post', data
});
