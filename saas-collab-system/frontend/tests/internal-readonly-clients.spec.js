import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { mockCreateInternalReadonlyClient, mockInternalReadonlyClients, mockReviewInternalReadonlyClient, mockRotateInternalReadonlyCredential, mockSetInternalReadonlyClientStatus } from '../src/mock/internalReadonly';
import { internalReadonlyModules, internalReadonlyResources } from '../src/config/internalReadonlyResources';
import { menuItems } from '../src/router/menu';

const read = (file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8');

describe('内部系统只读调用方配置', () => {
  it('使用统一后端端点并为轮换传递幂等键', () => {
    const api = read('src/api/internalReadonly.js');
    expect(api).toContain("'/api/internal/integrations/internal-api-clients/'");
    expect(api).toContain("'Idempotency-Key': idempotencyKey");
    expect(api).toContain('/status/'); expect(api).toContain('/rotate/'); expect(api).toContain('audit/');
    expect(api).toContain('/review/'); expect(api).toContain('/api/internal-readonly/v1/capabilities/');
  });

  it('创建和轮换仅在响应中返回一次性密钥，列表不泄露', () => {
    const created = mockCreateInternalReadonlyClient({ name: '测试系统', resources: ['products'] });
    expect(created.data.client_secret).toContain('only_once');
    expect(created.data.resources.products).toEqual(internalReadonlyResources.find((item) => item.code === 'products').fields);
    expect(JSON.stringify(mockInternalReadonlyClients().data.items)).not.toContain('client_secret');
    expect(mockRotateInternalReadonlyCredential(created.data.id).data.client_secret).toContain('only_once');
    expect(created.data.status).toBe('disabled');
    expect(created.data.approval_status).toBe('pending');
    expect(mockSetInternalReadonlyClientStatus(created.data.id, 'active').success).toBe(false);
    expect(mockReviewInternalReadonlyClient(created.data.id, 'approve').data.client.approval_status).toBe('approved');
    expect(mockSetInternalReadonlyClientStatus(created.data.id, 'active').success).toBe(true);
  });

  it('页面提供审核闭环并只报告实时核实的数据块可读', () => {
    const page = read('src/views/integrations/AIExternalApiSettings.vue');
    for (const text of ['新增调用系统','编辑','停用','轮换密钥','调用审计','一次性凭据','二次确认','强制只读']) expect(page).toContain(text);
    for (const field of ['name','caller_type','resources','cidrs','rate_limit','page_size','expires_at']) expect(page).toContain(field);
    expect(page).not.toContain('允许字段');
    expect(page).toContain('无需逐字段配置');
    expect(page).toContain('resources:[...form.resources]');
    expect(page).toContain('另一位管理员审核');
    expect(page).toContain('审核通过');
    expect(page).toContain('驳回');
    expect(page).toContain('readyCodes.has(r.code)');
    expect(page).toContain('无法核实业务只读 API 的实时状态');
    expect(page).toContain('@closed="oneTimeCredential=null"');
  });

  it('所列模块的数据块均可选择，并由服务端确定块内可读字段', () => {
    expect(internalReadonlyModules).toHaveLength(14);
    expect(internalReadonlyResources).toHaveLength(85);
    expect(internalReadonlyResources.map((item) => item.code)).toEqual(expect.arrayContaining([
      'products', 'product_details', 'product_mappings', 'product_costs', 'product_bundles',
      'platform_products', 'product_categories', 'product_attributes', 'product_colors',
      'product_specifications', 'platforms', 'country_sites', 'foundation_settings',
      'suppliers', 'stores', 'warehouses', 'purchase_orders',
      'supplier_shipments', 'sales_orders', 'sales_returns', 'inventory_snapshots', 'shipments',
      'influencers', 'outreach_tasks', 'sample_fulfillments',
      'advertising_overview', 'advertising_performance', 'advertising_reconciliation',
      'product_research', 'development_projects', 'finance_imports', 'platform_statements',
      'analytics_overview', 'lifecycle_reviews', 'basic_reports', 'approval_records', 'rpa_runs',
    ]));
    expect(internalReadonlyResources.every((item) => item.module && item.fields.includes('id') && item.fields.length > 1)).toBe(true);
    expect(internalReadonlyResources.every((item) =>
      (Array.isArray(item.module) ? item.module : [item.module]).every((code) =>
        internalReadonlyModules.some((module) => module.code === code)))).toBe(true);
    const counts = Object.fromEntries(internalReadonlyModules.map((module) => [module.code,
      internalReadonlyResources.filter((item) => (Array.isArray(item.module) ? item.module : [item.module]).includes(module.code)).length]));
    expect(counts).toEqual({ master_data: 16, product_development: 9, listing: 9, supply_chain: 5,
      inventory: 4, sales: 8, influencer_collaboration: 5, advertising: 3, analytics: 5,
      business_decision: 4, finance: 8, reports: 2, workflow: 3, rpa: 7 });
    for (const module of internalReadonlyModules.filter((item) => item.code !== 'advertising')) {
      const menu = menuItems.find((item) => item.label === module.label);
      expect(menu, module.label).toBeTruthy();
      const labels = new Set(internalReadonlyResources
        .filter((item) => (Array.isArray(item.module) ? item.module : [item.module]).includes(module.code))
        .map((item) => item.label));
      for (const child of menu.children) expect(labels.has(child.label), `${module.label} / ${child.label}`).toBe(true);
    }
    const backendCatalog = read('../backend/apps/integrations/serializers.py')
      .split('INTERNAL_API_RESOURCE_FIELDS = {')[1].split('\n}')[0];
    const backendCodes = [...backendCatalog.matchAll(/^    "([^"]+)":/gm)].map((match) => match[1]);
    expect(new Set(backendCodes)).toEqual(new Set(internalReadonlyResources.map((item) => item.code)));
    const page = read('src/views/integrations/AIExternalApiSettings.vue');
    expect(page).toContain('v-for="r in availableResources"');
    expect(page).not.toContain(':disabled="r.');
  });
});
