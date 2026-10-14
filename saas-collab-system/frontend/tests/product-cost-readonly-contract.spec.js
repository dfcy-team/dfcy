import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { internalReadonlyResourceFields, internalReadonlyResources } from '../src/config/internalReadonlyResources';
import { buildInternalApiHandoff } from '../src/utils/internalApiHandoff';

const expectedFields = [
  'id', 'sku_id', 'spu_id', 'sku_code', 'legacy_sku_code', 'spu_code', 'legacy_spu_code', 'product_name',
  'warehouse_id', 'warehouse_code', 'warehouse_name', 'warehouse_country_code',
  'version_no', 'status', 'source', 'currency', 'purchase_cost', 'freight_cost', 'duty_cost',
  'packaging_cost', 'other_cost', 'system_cost', 'confirmed_cost', 'effective_from', 'effective_to', 'reason', 'created_at',
];
const readBackend = (file) => fs.readFileSync(path.resolve(process.cwd(), '../backend/apps/integrations', file), 'utf8');
const quotedFields = (source) => [...source.matchAll(/"([^"]+)"/g)].map((match) => match[1]);

describe('商品成本只读接入合同', () => {
  it('仍属于基础档案，默认提供完整成本版本字段而不是占位金额', () => {
    const cost = internalReadonlyResources.find((item) => item.code === 'product_costs');
    expect(cost.module).toBe('master_data');
    expect(cost.label).toBe('商品成本');
    expect(cost.fields).toEqual(expectedFields);
    expect(internalReadonlyResourceFields.product_costs).toEqual(expectedFields);
    for (const placeholder of ['amount', 'effective_at', 'updated_at']) expect(cost.fields).not.toContain(placeholder);
  });

  it('前端目录、后端配置目录与实际成本读取字段保持一致', () => {
    const configFields = readBackend('serializers.py').match(/"product_costs": \{([^}]+)\}/);
    const readFields = readBackend('internal_readonly_api.py').match(/"product_costs": \(ProductCostVersion, \(([^)]+)\)\)/);
    expect(configFields).not.toBeNull();
    expect(readFields).not.toBeNull();
    expect(new Set(quotedFields(configFields[1]))).toEqual(new Set(expectedFields));
    expect(quotedFields(readFields[1])).toEqual(expectedFields);
  });

  it('接入资料仅在实时能力目录已接入时将授权成本列为可读', () => {
    const client = { name: '成本读取系统', client_id: 'example', resources: { product_costs: ['amount'] } };
    const ready = buildInternalApiHandoff(client, ['product_costs'], 'https://system.example.com', '');
    expect(ready.data_read.ready_resources).toEqual(['product_costs']);
    expect(ready.data_read.pending_resources).toEqual([]);
    expect(ready.caller_must_configure.READABLE_RESOURCE_CODES).toEqual(['product_costs']);
    const pending = buildInternalApiHandoff(client, [], 'https://system.example.com', '');
    expect(pending.data_read.ready_resources).toEqual([]);
    expect(pending.data_read.pending_resources).toEqual(['product_costs']);
  });
});
