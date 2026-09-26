import { describe, expect, it } from 'vitest';
import { parseBundleImportSpecification } from '../src/utils/bundleImportSpecification';

const category = { spec_dimensions: [{ code: 'size' }, { code: 'material' }] };

describe('组合商品导入规格', () => {
  it('空规格沿用无规格编码，多维规格按分类维度解析', () => {
    expect(parseBundleImportSpecification('', category)).toEqual({});
    expect(parseBundleImportSpecification('size=180cm×240cm；material=棉', category))
      .toEqual({ size: '180cm×240cm', material: '棉' });
  });

  it('拒绝未知、重复或空规格值并给出字段提示', () => {
    expect(() => parseBundleImportSpecification('color=blue', category)).toThrow('不属于当前末级分类');
    expect(() => parseBundleImportSpecification('size=M;size=L', category)).toThrow('重复填写');
    expect(() => parseBundleImportSpecification('size=0', category)).toThrow('缺少有效规格值');
  });
});
