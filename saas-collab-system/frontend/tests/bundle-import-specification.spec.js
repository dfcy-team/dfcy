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

  it('单维分类可直接导入已设置的组合规格值', () => {
    const single = { spec_dimensions: [{ code: 'SPEC', values: ['1KG+5LB', '2KG+10LB'] }] };
    expect(parseBundleImportSpecification('1KG+5LB', single)).toEqual({ SPEC: '1KG+5LB' });
    expect(parseBundleImportSpecification('2KG+10LB', single)).toEqual({ SPEC: '2KG+10LB' });
  });

  it('多维分类仅在规格值唯一匹配一个维度时省略编码', () => {
    const multi = { spec_dimensions: [
      { code: 'weight', values: ['1KG+5LB'] },
      { code: 'pack', values: ['2PCS'] }
    ] };
    expect(parseBundleImportSpecification('1KG+5LB;2PCS', multi))
      .toEqual({ weight: '1KG+5LB', pack: '2PCS' });
    expect(() => parseBundleImportSpecification('unknown', multi)).toThrow('无法确定规格维度');
    multi.spec_dimensions[1].values.push('1KG+5LB');
    expect(() => parseBundleImportSpecification('1KG+5LB', multi)).toThrow('对应多个规格维度');
  });
});
