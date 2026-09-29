import { describe, expect, it } from 'vitest';
import { groupSyncJobsForDisplay, syncJobGroupSpan } from '../src/utils/syncJobGrouping';

describe('sync job platform and business subject grouping', () => {
  it('keeps multiple contents and API sources for the same store together', () => {
    const rows = groupSyncJobsForDisplay([
      { id: 4, platform: 'shopee', subject_type: 'store', store_id: 2, subject_name: '乙店', resource_type: 'sales_order' },
      { id: 3, platform: 'jifeng_wms', subject_type: 'warehouse', warehouse_id: 1, subject_name: '甲仓', resource_type: 'inventory_snapshot' },
      { id: 2, platform: 'shopee', subject_type: 'store', store_id: 1, subject_name: '甲店', resource_type: 'sales_order', selected_authorization_id: 8 },
      { id: 1, platform: 'shopee', subject_type: 'store', store_id: 1, subject_name: '甲店', resource_type: 'platform_product', selected_authorization_id: 7 },
    ]);
    expect(rows.map((row) => row.id)).toEqual([3, 1, 2, 4]);
    expect(syncJobGroupSpan(rows, 0, 'platform')).toEqual([1, 1]);
    expect(syncJobGroupSpan(rows, 1, 'platform')).toEqual([3, 1]);
    expect(syncJobGroupSpan(rows, 2, 'platform')).toEqual([0, 0]);
    expect(syncJobGroupSpan(rows, 1, 'subject_name')).toEqual([2, 1]);
    expect(syncJobGroupSpan(rows, 2, 'subject_name')).toEqual([0, 0]);
    expect(syncJobGroupSpan(rows, 3, 'subject_name')).toEqual([1, 1]);
  });

  it('does not merge different business subjects that share a name', () => {
    const rows = groupSyncJobsForDisplay([
      { id: 1, platform: 'shopee', subject_type: 'store', store_id: 1, subject_name: '同名店' },
      { id: 2, platform: 'shopee', subject_type: 'store', store_id: 2, subject_name: '同名店' },
    ]);
    expect(syncJobGroupSpan(rows, 0, 'subject_name')).toEqual([1, 1]);
    expect(syncJobGroupSpan(rows, 1, 'subject_name')).toEqual([1, 1]);
  });
});
