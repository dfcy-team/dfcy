import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { mockSubjectApiAccess, mockWarehouseAuthorizations } from '../src/mock/integrations';
import { masterDataMocks } from '../src/mock/masterData';

const root = path.resolve(import.meta.dirname, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');

describe('仓库 API 接入操作闭环', () => {
  it('exposes explicit bind, rebind, revoke, readonly and sync task actions', () => {
    const dialog = read('src/components/SubjectApiAccessDialog.vue');
    for (const label of ['绑定此配置', '更换绑定', '解除绑定', '执行只读检查', '创建库存同步任务', '查看同步任务', '维护接入凭据']) {
      expect(dialog).toContain(label);
    }
    for (const permission of ['integrations.warehouse.view', 'integrations.warehouse.authorize', 'integrations.warehouse.revoke']) {
      expect(dialog).toContain(permission);
    }
    expect(dialog).toContain('warehouse_authorization_id: binding.id');
    expect(dialog).toContain('{ warehouse_authorization_id: binding.id }');
    expect(dialog).toContain("resource_type: 'inventory_snapshot'");
    expect(dialog).toContain("subject: access.value.subject.name");
    expect(dialog).toContain('has_sync_job === false');
    expect(dialog).toContain('请先创建库存同步任务，再执行只读检查。');
    expect(dialog).toContain('response.data?.simulated === true');
    expect(dialog).toContain('response.data?.external_api_called === false');
    expect(dialog).toContain('模拟检查完成，未调用真实平台。');
    expect(dialog).toContain("query.action = 'credentials'");
    expect(dialog).toContain("query.config_id = selected.id");
    expect(dialog).toContain('requiresCredentialRotate');
    expect(dialog).toContain('selectedConfig(apiType) && credentialMaintenanceAccess.visible');
    expect(dialog).toContain('await load();');
    const warehouseActionOrder = [
      '@click="bindWarehouse(apiType)"',
      '@click="createInventorySyncJob(primaryBinding(apiType))"',
      '@click="checkToken(primaryBinding(apiType))"',
      '@click="viewSyncJobs(apiType)"',
      '@click="revokeWarehouseBinding(primaryBinding(apiType))"',
    ].map((marker) => dialog.indexOf(marker));
    expect(warehouseActionOrder.every((position) => position >= 0)).toBe(true);
    expect(warehouseActionOrder).toEqual([...warehouseActionOrder].sort((left, right) => left - right));
  });

  it('uses the tenant-scoped warehouse authorization endpoints and masked mocks', () => {
    const api = read('src/api/integrations.js');
    expect(api).toContain("/api/internal/integrations/warehouse-authorizations/");
    expect(api).toContain("/rebind/");
    expect(api).toContain("/revoke/");
    expect(api).toContain('checkIntegrationReadonlyConnection = (id, payload = {})');
    const mock = read('src/mock/integrations.js');
    expect(mock).toContain('mockWarehouseAuthorizationRows');
    expect(mock).toContain('mockBindWarehouseAuthorization');
    expect(mock).toContain('mockRevokeWarehouseAuthorization');
    expect(mock).toContain('mockCheckIntegrationReadonlyConnection');
    expect(mock).toContain("resource_type: 'inventory_snapshot'");
    expect(mock).toContain("simulated: true");
    expect(mock).toContain("external_api_called: false");
    expect(mock).toContain("'SYNC_JOB_REQUIRED'");
    const readonlyBlock = api.slice(
      api.indexOf('export const checkIntegrationReadonlyConnection'),
      api.indexOf('export const updateIntegrationConfig')
    );
    expect(readonlyBlock).toContain('mockCheckIntegrationReadonlyConnection');
    expect(readonlyBlock).not.toContain('mockIntegrationConfigDetail');
    const syncJobs = read('src/views/integrations/SyncJobList.vue');
    expect(syncJobs).toContain('useRoute');
    expect(syncJobs).toContain('fetchSyncJobs({');
    expect(syncJobs).toContain('subject: route.query.subject');
  });

  it('registers warehouse permissions in the administrator-facing catalog', () => {
    const adminMock = read('src/mock/systemAdmin.js');
    const authMock = read('src/mock/auth.js');
    const labels = read('src/utils/permissionLabels.js');
    const administratorStart = adminMock.indexOf("code: 'administrator'");
    const administratorEnd = adminMock.indexOf('data_scopes', administratorStart);
    const administratorRole = adminMock.slice(administratorStart, administratorEnd);
    for (const permission of [
      'integrations.view', 'integrations.manage', 'integrations.run_live_readonly',
      'integrations.warehouse.view', 'integrations.warehouse.authorize', 'integrations.warehouse.revoke'
    ]) {
      expect(administratorRole).toContain(permission);
      expect(authMock).toContain(`'${permission}'`);
      expect(labels).toContain(permission);
    }
  });

  it('requires both generic integration view and warehouse view at the warehouse entry', () => {
    const warehousePage = read('src/views/masterdata/WarehouseMasterList.vue');
    expect(warehousePage).toContain("permission: 'integrations.view'");
    expect(warehousePage).toContain("permission: 'integrations.warehouse.view'");
    expect(warehousePage).toContain('integrationViewAccess.allowed && warehouseViewAccess.allowed');
    expect(warehousePage).toContain('integrationViewAccess.visible && warehouseViewAccess.visible');
  });

  it('binds the computed permission gate to both API buttons and handlers', () => {
    const warehousePage = read('src/views/masterdata/WarehouseMasterList.vue');
    expect(warehousePage).toContain(':disabled="apiAccess.disabled"');
    expect(warehousePage).toContain("if (!apiAccess.value.allowed)");
    expect(warehousePage).toContain("if (!row?.api_access_available)");
    expect(warehousePage).toContain("notifyApiAccessBlocked(row)");
  });

  it('keeps the warehouse master fixture on the same MY Jifeng identity as the API fixture', () => {
    const masterData = read('src/mock/masterData.js');
    const integrations = read('src/mock/integrations.js');
    expect(masterData).toContain("code: 'MY-WMS-01'");
    expect(masterData).toContain("country_code: 'MY'");
    expect(masterData).toContain("warehouse_type: 'third_party'");
    expect(masterData).toContain("api_access_available: true");
    expect(masterData).toContain("service_platform_id: 2");
    expect(integrations).toContain("subject_code: 'MY-WMS-01'");
    expect(integrations).toContain("subject_name: '马来极风仓'");
    expect(integrations).toContain("region: 'MY'");
    for (const status of ['pending', 'expired', 'revoked', 'error']) expect(integrations).toContain(`status: '${status}'`);
    expect(integrations).toContain('credential_mask');
    expect(integrations).toContain('token_expires_at');
    const access = mockSubjectApiAccess('warehouse', 1);
    const warehouse = masterDataMocks.warehouses().data.results.find((row) => row.id === 1);
    expect(warehouse).toMatchObject({ id: 1, code: 'MY-WMS-01', country_code: 'MY', service_platform_id: 2 });
    expect(access.data.subject).toMatchObject({
      id: warehouse.id,
      code: warehouse.code,
      country_code: warehouse.country_code,
      platform: 'jifeng_wms',
      service_platform_id: warehouse.service_platform_id,
    });
    expect(access.data.bindings.map((row) => row.status)).toEqual(expect.arrayContaining(['active', 'pending', 'expired', 'revoked', 'error']));
    expect(mockWarehouseAuthorizations({ warehouse_id: 1 }).data.results.length).toBeGreaterThanOrEqual(5);
  });
});
