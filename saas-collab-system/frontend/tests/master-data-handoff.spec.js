import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('基础档案交接包界面契约', () => {
  it('恢复平台和国家档案的原始字段与编辑操作', () => {
    const platform = read('src/views/masterdata/PlatformMasterList.vue');
    const country = read('src/views/masterdata/CountrySiteMasterList.vue');
    expect(platform).toContain("{ prop: 'platform_type', label: '平台类型'");
    expect(platform).not.toContain("{ prop: 'tenant_id'");
    expect(platform).toContain(':edit-handler');
    for (const field of ['国家档案编码', '国家名称', '国家代码', '币种', '时区', '状态']) {
      expect(country).toContain(field);
    }
    expect(country).not.toContain("{ prop: 'platform', label: '平台'");
  });

  it('使用当前租户平台和国家档案联动店铺表单', () => {
    const store = read('src/views/masterdata/StoreMasterList.vue');
    expect(store).toContain("fetchPlatforms({ status: 'active', page: 1, page_size: 100 })");
    expect(store).toContain("fetchCountrySites({ status: 'active', page: 1, page_size: 100 })");
    expect(store).toContain('onChange: applyCountryDefaults');
    expect(store).not.toContain("default: 1, options: [{ label: '示例平台'");
    expect(store).not.toContain('function platformLabel');
    for (const field of ['平台店铺名', 'API 接入', '类目', '负责运营', 'BD', '组长', '是否建联', '战斧客户端']) {
      expect(store).toContain(field);
    }
  });

  it('保留店铺导入与店铺、仓库 API 接入操作', () => {
    const store = read('src/views/masterdata/StoreMasterList.vue');
    const warehouse = read('src/views/masterdata/WarehouseMasterList.vue');
    expect(store).toContain('importStores(importFile.value)');
    expect(store).toContain('下载 CSV 导入模板');
    expect(store).toContain('SubjectApiAccessDialog');
    expect(store).toContain('selectedStore.value = row');
    expect(warehouse).toContain('SubjectApiAccessDialog');
    expect(warehouse).toContain('selectedWarehouse.value = row');
    expect(warehouse).toContain(':edit-handler');
    expect(warehouse).not.toContain("{ prop: 'last_sync_at'");
  });

  it('区分仓储平台与商城平台并按仓库类型绑定 API 服务商', () => {
    const platform = read('src/views/masterdata/PlatformMasterList.vue');
    const store = read('src/views/masterdata/StoreMasterList.vue');
    const warehouse = read('src/views/masterdata/WarehouseMasterList.vue');
    expect(platform).toContain("{ label: '三方仓服务', value: 'warehouse_third_party' }");
    expect(platform).toContain("{ label: '平台仓服务', value: 'warehouse_platform' }");
    expect(store).toContain(".filter((row) => !String(row.platform_type || '').startsWith('warehouse_'))");
    expect(warehouse).toContain("fetchPlatforms({ status: 'active', page: 1, page_size: 100 })");
    expect(warehouse).toContain("service_platform_id");
    expect(warehouse).toContain("servicePlatformTypeByWarehouseType");
    expect(warehouse).toContain("row.api_access_available");
    expect(warehouse).toContain("API 接入（待配置）");
  });

  it('接入配置下拉项由服务端基础档案和能力数据驱动', () => {
    const workspace = read('src/views/integrations/IntegrationWorkspace.vue');
    expect(workspace).toContain('data.value.reference_options?.platforms');
    expect(workspace).toContain('selectedReferencePlatform.value?.api_types');
    expect(workspace).toContain('data.value.reference_options?.countries');
    expect(workspace).toContain('data.value.reference_options?.environments');
    expect(workspace).toContain(':model-value="configForm.regions.includes(region.country_code)"');
    expect(workspace).toContain('@change="setConfigRegion(region.country_code, $event)"');
    expect(workspace).toContain('已选择 {{ configForm.regions.length }} 个站点');
    expect(workspace).not.toContain('<el-option label="Shopee" value="shopee" />');
    expect(workspace).not.toContain("new Set(['SG', 'MY', 'TH', 'VN', 'ID', 'PH'])");
  });

  it('按原设计维度联动展示主体、配置、授权与最近同步', () => {
    const access = read('src/components/SubjectApiAccessDialog.vue');
    for (const field of ['档案编码', '国家/站点', '令牌策略', '商城 API', '广告 API', '库存 API', '接入配置', '授权时间', '最近同步']) {
      expect(access).toContain(field);
    }
    expect(access).toContain('fetchSubjectApiAccess(props.subjectType, props.row.id)');
    expect(access).toContain('checkIntegrationReadonlyConnection(');
    expect(access).toContain("{ warehouse_authorization_id: binding.id }");
    expect(access).toContain("path: '/integrations/sync-jobs'");
  });

  it('通用档案页支持编辑、筛选标签和每页条数', () => {
    const page = read('src/components/AdminResourcePage.vue');
    expect(page).toContain('v-if="editHandler && manageAccess.visible"');
    expect(page).toContain("showPageSize ? 'sizes, prev, pager, next, jumper'");
    expect(page).toContain('field.onChange?.($event, resourceForm)');
    expect(page).toContain("typeof field.options === 'function'");
  });
});
