import { beforeEach, describe, expect, it } from 'vitest';
import { mockSyncAlertIncidents } from '../src/mock/integrations';
import {
  resetMappingMocks, mockPlatformProductDetails, mockCreateProductMapping, mockUpdateProductMapping,
  mockProductMappings, mockUpdatePlatformProductDetail, mockUpdateStoreMapping, mockStoreMappings,
  mockStoreMappingOptions, mockProductMappingOptions
} from '../src/mock/mappings';

describe('mapping rehearsal shares one decision with platform details', () => {
  beforeEach(resetMappingMocks);

  it('suggestion remains unconfirmed until explicit confirmation and persists on refresh', () => {
    const created = mockCreateProductMapping({ platform_detail_id: 702 });
    expect(created.success).toBe(true);
    const id = created.data.id;
    expect(mockUpdateProductMapping(id, { sku_id: 12, manually_confirmed: true }).success).toBe(false);
    expect(mockUpdateProductMapping(id, { sku_id: 12, confidence: 85, manually_confirmed: false }).success).toBe(true);
    expect(mockPlatformProductDetails().data.results.find((row) => row.id === 702).internal_sku).toBeNull();
    expect(mockProductMappings({ status: 'suggested' }).data.results.some((row) => row.id === id)).toBe(true);
    expect(mockUpdateProductMapping(id, { sku_id: 12, manually_confirmed: true }).success).toBe(true);
    const reloaded = mockPlatformProductDetails({ mapping_status: 'mapped' }).data.results.find((row) => row.id === 702);
    expect(reloaded.internal_sku_code).toBe('SKU-DEMO-002');
    expect(reloaded.mapping.manually_confirmed).toBe(true);
    expect(mockUpdatePlatformProductDetail(702, { internal_sku: 11 }).success).toBe(false);
  });

  it('keeps the prior SKU when a new suggestion conflicts and retains inactive history', () => {
    expect(mockUpdateProductMapping(404, { sku_id: 12, confidence: 60 }).data.status).toBe('conflict');
    const row = mockPlatformProductDetails().data.results.find((item) => item.id === 704);
    expect(row.internal_sku).toBe(14);
    expect(mockUpdateProductMapping(404, { sku_id: 12, manually_confirmed: true }).success).toBe(false);
    expect(mockUpdateProductMapping(404, { status: 'inactive' }).success).toBe(true);
    expect(mockProductMappings({ status: 'inactive' }).data.results.some((item) => item.id === 404)).toBe(true);
    expect(mockUpdateProductMapping(404, { sku_id: 14, manually_confirmed: true }).success).toBe(false);
  });

  it('blocks product creation after store linkage is disabled and refresh shows the new state', () => {
    expect(mockUpdateStoreMapping(301, { status: 'inactive' }).success).toBe(true);
    expect(mockStoreMappings({ store_id: 1, status: 'inactive' }).data.results).toHaveLength(1);
    expect(mockCreateProductMapping({ platform_detail_id: 702 }).success).toBe(false);
    expect(mockUpdateStoreMapping(301, { status: 'active' }).success).toBe(true);
    expect(mockCreateProductMapping({ platform_detail_id: 702 }).success).toBe(true);
  });

  it('requires the current SKU to be acknowledged before manually resolving a mapping conflict', () => {
    mockUpdateProductMapping(404, { sku_id: 12, confidence: 90 });
    expect(mockUpdateProductMapping(404, { sku_id: 12, manually_confirmed: true, replace_existing: true, expected_internal_sku_id: 99 }).success).toBe(false);
    expect(mockUpdateProductMapping(404, { sku_id: 12, manually_confirmed: true, replace_existing: true, expected_internal_sku_id: 14 }).success).toBe(true);
    expect(mockPlatformProductDetails().data.results.find((row) => row.id === 704).internal_sku).toBe(12);
  });

  it('keeps unrelated store authorization choices out of contextual selection', () => {
    expect(mockStoreMappingOptions({ store_id: 999 }).data.authorizations).toEqual([]);
    const options = mockStoreMappingOptions({ store_id: 1 }).data.authorizations;
    expect(options.length).toBeGreaterThan(0);
    expect(options.every((row) => row.store_id === 1 && row.status === 'active')).toBe(true);
    expect(options.every((row) => !('credential_mask' in row))).toBe(true);
  });

  it('carries a store context through the sync incident link', () => {
    expect(mockSyncAlertIncidents({ store_id: 1 }).data.length).toBeGreaterThan(0);
    expect(mockSyncAlertIncidents({ store_id: 999 }).data).toEqual([]);
  });

  it('paginates detail choices independently and retains orphan history without false confirmation', () => {
    const second = mockProductMappingOptions({ page: 2, page_size: 2 }).data;
    expect(second.count).toBe(6);
    expect(second.platform_details.map((row) => row.id)).toEqual([703, 704]);
    expect(mockProductMappings({ unlinked: true }).data.results.map((row) => row.id)).toEqual([406]);
    expect(mockUpdateProductMapping(406, { sku_id: 16, manually_confirmed: true }).success).toBe(false);
  });

  it('allows a pre-existing detail SKU to enter a reviewed conflict without overwriting it', () => {
    mockUpdatePlatformProductDetail(702, { internal_sku: 11 });
    const mapping = mockCreateProductMapping({ platform_detail_id: 702 }).data;
    expect(mockUpdateProductMapping(mapping.id, { sku_id: 12, confidence: 80 }).data.status).toBe('conflict');
    expect(mockPlatformProductDetails().data.results.find((row) => row.id === 702).internal_sku).toBe(11);
    expect(mockUpdateProductMapping(mapping.id, { sku_id: 12, manually_confirmed: true, replace_existing: true, expected_internal_sku_id: 11 }).success).toBe(true);
  });
});
