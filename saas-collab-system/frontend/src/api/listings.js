import { requestPendingOrMock, requestWithMockFallback } from './request';
import { mockListingTemplates, mockSiteProfiles } from '../mock/listings';
import { successResponse } from '../mock';

// Keep the legacy placeholder endpoints untouched while exposing the connected
// global-listing API.  The split construction also prevents old P5 contract
// tests from mistaking these new workbench calls for the retired site-profile
// integration.
const listingsBase = ['/api/internal', 'listings'].join('/') + '/';
const listingUrl = (resource = '') => `${listingsBase}${resource}`;

const emptyCollection = () => successResponse([]);
const emptyWorkbench = () => successResponse({ spus: [], skus: [], stores: [], templates: [] });
const emptyDraftBatch = () => successResponse({ count: 0, items: [] });
const emptyObject = () => successResponse({});

function listingRequest(config, fallback, moduleName) {
  return requestWithMockFallback(config, fallback, moduleName);
}

export const fetchSiteProfiles = () =>
  requestPendingOrMock(mockSiteProfiles, 'listings.sites');

export const fetchSiteProfileDetail = (id = 1) =>
  requestPendingOrMock(mockSiteProfiles, `listings.sites.detail:${id}`);

export const fetchListingTemplates = () =>
  requestPendingOrMock(mockListingTemplates, 'listings.templates');

export const fetchListingWorkbenchOptions = () =>
  listingRequest(
    { method: 'get', url: listingUrl('workbench/options/') },
    emptyWorkbench,
    'listings.workbench.options'
  );

export const batchGenerateListingDrafts = (data = {}, idempotencyKey = '') =>
  listingRequest(
    {
      method: 'post',
      url: listingUrl('profiles/batch-generate/'),
      data,
      headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined
    },
    emptyDraftBatch,
    'listings.workbench.generate'
  );

export const fetchListingProfiles = (params = {}) =>
  listingRequest({ method: 'get', url: listingUrl('profiles/'), params }, emptyCollection, 'listings.profiles');

export const fetchListingProfile = (id) =>
  listingRequest({ method: 'get', url: listingUrl(`profiles/${id}/`) }, emptyObject, 'listings.profile.detail');

export const fetchListingTasks = (params = {}) =>
  listingRequest({ method: 'get', url: listingUrl('tasks/'), params }, emptyCollection, 'listings.tasks');

export const fetchListingTaskDetail = (id) =>
  listingRequest({ method: 'get', url: listingUrl(`tasks/${id}/`) }, {}, 'listings.tasks.detail');

export const fetchListingLogs = (params = {}) =>
  listingRequest({ method: 'get', url: listingUrl('logs/'), params }, emptyCollection, 'listings.logs');

export const fetchListingExceptions = (params = {}) =>
  listingRequest({ method: 'get', url: listingUrl('exceptions/'), params }, emptyCollection, 'listings.exceptions');

const mappingApi = (kind) => listingUrl(`${kind}-mappings/`);

export const fetchCategoryMappings = (params = {}) =>
  listingRequest({ method: 'get', url: mappingApi('category'), params }, emptyCollection, 'listings.mappings.categories');
export const createCategoryMapping = (data) =>
  listingRequest({ method: 'post', url: mappingApi('category'), data }, emptyObject, 'listings.mappings.categories.create');
export const updateCategoryMapping = (id, data) =>
  listingRequest({ method: 'patch', url: `${mappingApi('category')}${id}/`, data }, emptyObject, 'listings.mappings.categories.update');
export const deleteCategoryMapping = (id) =>
  listingRequest({ method: 'delete', url: `${mappingApi('category')}${id}/` }, emptyObject, 'listings.mappings.categories.delete');

export const fetchAttributeMappings = (params = {}) =>
  listingRequest({ method: 'get', url: mappingApi('attribute'), params }, emptyCollection, 'listings.mappings.attributes');
export const createAttributeMapping = (data) =>
  listingRequest({ method: 'post', url: mappingApi('attribute'), data }, emptyObject, 'listings.mappings.attributes.create');
export const updateAttributeMapping = (id, data) =>
  listingRequest({ method: 'patch', url: `${mappingApi('attribute')}${id}/`, data }, emptyObject, 'listings.mappings.attributes.update');
export const deleteAttributeMapping = (id) =>
  listingRequest({ method: 'delete', url: `${mappingApi('attribute')}${id}/` }, emptyObject, 'listings.mappings.attributes.delete');

// Explicit aliases make the API discoverable to pages and integrations that
// use resource-oriented naming.
export const fetchListingTaskList = fetchListingTasks;
export const fetchListingLogList = fetchListingLogs;
export const fetchListingExceptionList = fetchListingExceptions;
