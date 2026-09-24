import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { mockCreateInternalReadonlyClient, mockInternalReadonlyClients, mockRotateInternalReadonlyCredential } from '../src/mock/internalReadonly';
import { internalReadonlyModules, internalReadonlyResources } from '../src/config/internalReadonlyResources';

const read = (file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8');

describe('内部系统只读调用方配置', () => {
  it('使用统一后端端点并为轮换传递幂等键', () => {
    const api = read('src/api/internalReadonly.js');
    expect(api).toContain("'/api/internal/integrations/internal-api-clients/'");
    expect(api).toContain("'Idempotency-Key': idempotencyKey");
    expect(api).toContain('/status/'); expect(api).toContain('/rotate/'); expect(api).toContain('audit/');
  });

  it('创建和轮换仅在响应中返回一次性密钥，列表不泄露', () => {
    const created = mockCreateInternalReadonlyClient({ name: '测试系统', resources: ['products'] });
    expect(created.data.client_secret).toContain('only_once');
    expect(created.data.resources.products).toEqual(internalReadonlyResources.find((item) => item.code === 'products').fields);
    expect(JSON.stringify(mockInternalReadonlyClients().data.items)).not.toContain('client_secret');
    expect(mockRotateInternalReadonlyCredential(created.data.id).data.client_secret).toContain('only_once');
  });

  it('页面提供完整配置闭环并保留只读与未上线声明', () => {
    const page = read('src/views/integrations/AIExternalApiSettings.vue');
    for (const text of ['新增调用系统','编辑','停用','轮换密钥','调用审计','一次性凭据','二次确认','强制只读']) expect(page).toContain(text);
    for (const field of ['name','caller_type','resources','cidrs','rate_limit','page_size','expires_at']) expect(page).toContain(field);
    expect(page).not.toContain('允许字段');
    expect(page).toContain('无需逐字段配置');
    expect(page).toContain('resources:[...form.resources]');
    expect(page).toContain('/api/internal-readonly/v1/ 尚未上线');
    expect(page).toContain('@closed="oneTimeCredential=null"');
  });

  it('所列模块的数据块均可选择，并由服务端确定块内可读字段', () => {
    expect(internalReadonlyModules).toHaveLength(6);
    expect(internalReadonlyResources).toHaveLength(50);
    expect(internalReadonlyResources.map((item) => item.code)).toEqual(expect.arrayContaining([
      'products', 'product_details', 'product_mappings', 'product_costs', 'product_bundles',
      'platform_products', 'product_categories', 'product_attributes', 'product_colors',
      'product_specifications', 'platforms', 'country_sites', 'foundation_settings',
      'suppliers', 'stores', 'warehouses', 'purchase_orders',
      'supplier_shipments', 'sales_orders', 'sales_returns', 'inventory_snapshots', 'shipments',
      'influencers', 'outreach_tasks', 'sample_fulfillments',
      'advertising_overview', 'advertising_performance', 'advertising_reconciliation',
    ]));
    expect(internalReadonlyResources.every((item) => item.module && item.fields.includes('id') && item.fields.length > 1)).toBe(true);
    expect(internalReadonlyResources.every((item) => internalReadonlyModules.some((module) => module.code === item.module))).toBe(true);
    const backendCatalog = read('../backend/apps/integrations/serializers.py')
      .split('INTERNAL_API_RESOURCE_FIELDS = {')[1].split('\n}')[0];
    const backendCodes = [...backendCatalog.matchAll(/^    "([^"]+)":/gm)].map((match) => match[1]);
    expect(new Set(backendCodes)).toEqual(new Set(internalReadonlyResources.map((item) => item.code)));
    const page = read('src/views/integrations/AIExternalApiSettings.vue');
    expect(page).toContain('v-for="r in availableResources"');
    expect(page).not.toContain(':disabled="r.');
  });
});
