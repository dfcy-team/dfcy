import { describe, expect, it } from 'vitest';
import {
  mockBindWarehouseAuthorization,
  mockIntegrationWorkspace,
  mockSyncAlertIncidents,
  mockWarehouseAuthorizations,
} from '../src/mock/integrations';

describe('mock integration resource and warehouse binding contracts', () => {
  it('rebinds a warehouse when only the provider code changes and disables the old job', () => {
    const current = mockWarehouseAuthorizations({ warehouse_id: 1 }).data.results.find((row) => row.status === 'active');
    expect(current).toMatchObject({ id: 202, integration_config_id: 3, external_warehouse_code: 'MY-JIFENG-01' });

    const response = mockBindWarehouseAuthorization({
      warehouse_id: 1,
      integration_config_id: 3,
      external_warehouse_code: 'QA-EXTERNAL-WH-01',
      replace: true,
      expected_authorization_id: current.id,
    });

    expect(response).toMatchObject({ success: true, data: { idempotent: false, operation: 'warehouse_rebind' } });
    expect(response.data.authorization).toMatchObject({
      warehouse_id: 1,
      integration_config_id: 3,
      external_warehouse_code: 'QA-EXTERNAL-WH-01',
      status: 'active',
    });
    expect(mockWarehouseAuthorizations({ warehouse_id: 1 }).data.results.find((row) => row.id === current.id)).toMatchObject({ status: 'revoked' });

    const jobs = mockIntegrationWorkspace('sync-jobs').data.results;
    expect(jobs.find((row) => row.id === 3)).toMatchObject({
      selected_authorization_id: current.id,
      is_enabled: false,
      status: 'disabled',
      health_state: 'disabled',
      schedule_state: 'disabled',
    });

    const repeated = mockBindWarehouseAuthorization({
      warehouse_id: 1,
      integration_config_id: 3,
      external_warehouse_code: 'QA-EXTERNAL-WH-01',
      expected_authorization_id: response.data.authorization.id,
    });
    expect(repeated).toMatchObject({ success: true, data: { idempotent: true, operation: 'already_bound' } });
  });

  it('filters workspace jobs and incidents by store and resource type', () => {
    const storeJobs = mockIntegrationWorkspace('sync-jobs', { store_id: 1 }).data.results;
    expect(storeJobs.map((row) => row.id)).toEqual(expect.arrayContaining([1, 2, 4]));
    expect(storeJobs.some((row) => row.id === 3)).toBe(false);

    const storeIncidents = mockSyncAlertIncidents({ store_id: 1 }).data;
    expect(storeIncidents.map((row) => row.id)).toEqual([901, 902]);
    expect(mockSyncAlertIncidents({ resource_type: 'platform_product' }).data).toEqual([]);
    expect(mockSyncAlertIncidents({ resource_type: 'sales_order' }).data.map((row) => row.id)).toEqual([901]);
  });
});
