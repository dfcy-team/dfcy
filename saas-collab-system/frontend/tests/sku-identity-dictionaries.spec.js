import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { filterSpecValuesForDimensions, specDimensionLabel } from '../src/utils/skuIdentity';

describe('controlled SKU identity dictionaries', () => {
  it('drops dimensions absent from the selected SPU and values outside populated dictionaries', () => {
    const result = filterSpecValuesForDimensions(
      { size: 'M', material: 'Cotton', fit: 'Regular' },
      [{ code: 'size', name: '尺码', values: ['S', 'L'] }, { code: 'material', values: [] }],
    );
    expect(result).toEqual({ material: 'Cotton' });
    expect(specDimensionLabel('size', [{ code: 'size', name: '尺码' }])).toBe('尺码');
  });

  it('preserves existing values when the target dictionary has no options', () => {
    expect(filterSpecValuesForDimensions({ size: 'Legacy' }, [{ code: 'size', values: [] }])).toEqual({ size: 'Legacy' });
  });
});


it('bundle identity action accepts either management permission', () => {
  const bundle = readFileSync(resolve('src/views/products/ProductBundleEditor.vue'), 'utf8');
  expect(bundle).toContain("auth.hasPermission?.('products.master.manage') || auth.hasPermission?.('products.bundle.manage')");
});
