import { requestApi } from './request';

// All development resources deliberately stay under one tenant-scoped API
// prefix. The small resource factory keeps the workflow endpoints consistent
// while retaining the original project/archive functions below.
const DEVELOPMENT_API_ROOT = '/api/internal/development';
const collectionUrl = (resource) => `${DEVELOPMENT_API_ROOT}/${resource}/`;
const resourceApi = (resource) => ({
  list: (params = {}) => requestApi({ url: collectionUrl(resource), method: 'get', params }),
  get: (id) => requestApi({ url: `${collectionUrl(resource)}${id}/`, method: 'get' }),
  create: (data) => requestApi({ url: collectionUrl(resource), method: 'post', data }),
  update: (id, data) => requestApi({ url: `${collectionUrl(resource)}${id}/`, method: 'patch', data }),
  remove: (id) => requestApi({ url: `${collectionUrl(resource)}${id}/`, method: 'delete' })
});

const candidatesApi = resourceApi('candidates');
const competitorsApi = resourceApi('competitors');
const projectsApi = resourceApi('projects');
const samplesApi = resourceApi('samples');
const quotationsApi = resourceApi('quotations');
const listingDecisionsApi = resourceApi('listing-decisions');
const trialsApi = resourceApi('trials');
const trialMetricsApi = resourceApi('trial-metrics');
const launchPlansApi = resourceApi('launch-plans');
const reorderDecisionsApi = resourceApi('reorder-decisions');
const eliminationsApi = resourceApi('eliminations');
const eventsApi = resourceApi('events');
const settingsApi = resourceApi('settings');

export const fetchDevelopmentCandidates = (params = {}) => candidatesApi.list(params);
export const fetchDevelopmentCandidate = (id) => candidatesApi.get(id);
export const createDevelopmentCandidate = (data) => candidatesApi.create(data);
export const updateDevelopmentCandidate = (id, data) => candidatesApi.update(id, data);
export const deleteDevelopmentCandidate = (id) => candidatesApi.remove(id);

export const fetchDevelopmentSamples = (params = {}) => samplesApi.list(params);
export const fetchDevelopmentSample = (id) => samplesApi.get(id);
export const createDevelopmentSample = (data) => samplesApi.create(data);
export const updateDevelopmentSample = (id, data) => samplesApi.update(id, data);

export const fetchDevelopmentQuotations = (params = {}) => quotationsApi.list(params);
export const fetchDevelopmentQuotation = (id) => quotationsApi.get(id);
export const createDevelopmentQuotation = (data) => quotationsApi.create(data);
export const updateDevelopmentQuotation = (id, data) => quotationsApi.update(id, data);

export const fetchDevelopmentListingDecisions = (params = {}) => listingDecisionsApi.list(params);
export const fetchDevelopmentListingDecision = (id) => listingDecisionsApi.get(id);
export const createDevelopmentListingDecision = (data) => listingDecisionsApi.create(data);
export const updateDevelopmentListingDecision = (id, data) => listingDecisionsApi.update(id, data);

export const fetchDevelopmentTrials = (params = {}) => trialsApi.list(params);
export const fetchDevelopmentTrial = (id) => trialsApi.get(id);
export const createDevelopmentTrial = (data) => trialsApi.create(data);
export const updateDevelopmentTrial = (id, data) => trialsApi.update(id, data);

export const fetchDevelopmentTrialMetrics = (params = {}) => trialMetricsApi.list(params);
export const fetchDevelopmentTrialMetric = (id) => trialMetricsApi.get(id);
export const createDevelopmentTrialMetric = (data) => trialMetricsApi.create(data);
export const updateDevelopmentTrialMetric = (id, data) => trialMetricsApi.update(id, data);

export const fetchDevelopmentLaunchPlans = (params = {}) => launchPlansApi.list(params);
export const fetchDevelopmentLaunchPlan = (id) => launchPlansApi.get(id);
export const createDevelopmentLaunchPlan = (data) => launchPlansApi.create(data);
export const updateDevelopmentLaunchPlan = (id, data) => launchPlansApi.update(id, data);

export const fetchDevelopmentReorderDecisions = (params = {}) => reorderDecisionsApi.list(params);
export const fetchDevelopmentReorderDecision = (id) => reorderDecisionsApi.get(id);
export const createDevelopmentReorderDecision = (data) => reorderDecisionsApi.create(data);
export const updateDevelopmentReorderDecision = (id, data) => reorderDecisionsApi.update(id, data);

export const fetchDevelopmentEliminations = (params = {}) => eliminationsApi.list(params);
export const fetchDevelopmentElimination = (id) => eliminationsApi.get(id);
export const createDevelopmentElimination = (data) => eliminationsApi.create(data);
export const updateDevelopmentElimination = (id, data) => eliminationsApi.update(id, data);

export const fetchDevelopmentEvents = (params = {}) => eventsApi.list(params);
export const fetchDevelopmentEvent = (id) => eventsApi.get(id);
export const createDevelopmentEvent = (data) => eventsApi.create(data);

export const fetchDevelopmentSettings = (params = {}) => settingsApi.list(params);
export const fetchDevelopmentSetting = (id) => settingsApi.get(id);
export const createDevelopmentSetting = (data) => settingsApi.create(data);
export const updateDevelopmentSetting = (id, data) => settingsApi.update(id, data);

// This is the stable boundary for the external collector. Until that service
// is configured the backend returns an empty collection and integration status.
export const fetchDevelopmentCompetitors = (params = {}) => competitorsApi.list(params);

export const fetchDevelopmentProjects = (params = {}) => projectsApi.list(params);
export const fetchDevelopmentProject = (id) => projectsApi.get(id);
export const createDevelopmentProject = (data) => projectsApi.create(data);
export const updateDevelopmentProject = (id, data) => projectsApi.update(id, data);
export const deleteDevelopmentProject = (id) => projectsApi.remove(id);

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
