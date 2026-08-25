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
    for (const field of ['平台店铺名', 'API 接入', '类目', '负责运营', 'BD', '组长', '是否建联', '战斧客户端']) {
      expect(store).toContain(field);
    }
  });

  it('保留店铺导入与店铺、仓库 API 接入操作', () => {
    const store = read('src/views/masterdata/StoreMasterList.vue');
    const warehouse = read('src/views/masterdata/WarehouseMasterList.vue');
    expect(store).toContain('importStores(importFile.value)');
    expect(store).toContain('下载 CSV 导入模板');
    expect(store).toContain("query: { store: row.code }");
    expect(warehouse).toContain("query: { warehouse: row.code }");
    expect(warehouse).toContain(':edit-handler');
    expect(warehouse).not.toContain("{ prop: 'last_sync_at'");
  });

  it('通用档案页支持编辑、筛选标签和每页条数', () => {
    const page = read('src/components/AdminResourcePage.vue');
    expect(page).toContain('v-if="editHandler && manageAccess.visible"');
    expect(page).toContain("showPageSize ? 'sizes, prev, pager, next, jumper'");
    expect(page).toContain('field.onChange?.($event, resourceForm)');
  });
});
