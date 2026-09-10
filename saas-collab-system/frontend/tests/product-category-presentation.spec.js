import { describe, expect, it } from 'vitest';
import {
  buildCategoryTree,
  categoryBackgroundColor,
  categoryRowClass,
  categoryRowStyle,
  mergeCategoryBackgroundColors,
} from '../src/utils/productCategoryPresentation';

describe('商品分类展示工具', () => {
  const categories = [
    { id: '10', level: 1, code: '1', name: '家居' },
    { id: '20', parent_id: '10', level: 2, code: '01', name: '卧室', row_background_color: '#AABBCC' },
    { id: '30', parent_id: '20', level: 3, code: '01', name: '床品' },
  ];

  it('兼容 parent_id 并把三级节点放到正确的二级节点下面', () => {
    const tree = buildCategoryTree(categories);
    expect(tree[0].children[0].children[0].id).toBe('30');
  });

  it('为三级商品继承当前二级分类的自定义背景色', () => {
    const row = { category_node: '30' };
    expect(categoryBackgroundColor(row, categories)).toBe('#AABBCC');
    expect(categoryRowClass(row, categories)).toBe('product-category-custom');
    expect(categoryRowStyle(row, categories)).toEqual({
      '--product-category-row-background': '#AABBCC',
    });
  });

  it('在列表返回嵌套分类对象时也能直接应用二级颜色', () => {
    const row = {
      category_node: {
        id: '31',
        level: 3,
        parent: { id: '21', level: 2, code: '02', name: '厨房', row_background_color: '#DDEEFF' },
      },
    };
    expect(categoryBackgroundColor(row, [])).toBe('#DDEEFF');
    expect(categoryRowClass(row, [])).toBe('product-category-custom');
  });

  it('有最新平面字典时覆盖嵌套对象中的旧颜色', () => {
    const row = {
      category_node: {
        id: '31',
        level: 3,
        parent: { id: '21', level: 2, code: '02', name: '厨房', row_background_color: '#000000' },
      },
    };
    const currentCategories = [
      { id: '31', parent: '21', level: 3, code: '01', name: '餐具' },
      { id: '21', level: 2, code: '02', name: '厨房', row_background_color: '#DDEEFF' },
    ];
    expect(categoryBackgroundColor(row, currentCategories)).toBe('#DDEEFF');
  });

  it('仅返回二级编码时优先选择二级节点，避免与一级编码重号', () => {
    const row = { category_l2_code: '01' };
    const withSameCode = [
      { id: 1, level: 1, code: '01', name: '一级' },
      { id: 2, level: 2, code: '01', name: '二级', row_background_color: '#112233' },
    ];
    expect(categoryBackgroundColor(row, withSameCode)).toBe('#112233');
  });

  it('不同一级目录下二级编码重号且无名称时不误套任意自定义颜色', () => {
    const row = { category_l2_code: '01' };
    const duplicateL2Code = [
      { id: 11, level: 1, code: '1', name: '家居' },
      { id: 12, level: 1, code: '2', name: '厨房' },
      { id: 21, parent: 11, level: 2, code: '01', name: '卧室', row_background_color: '#112233' },
      { id: 22, parent: 12, level: 2, code: '01', name: '餐厨', row_background_color: '#445566' },
    ];
    expect(categoryBackgroundColor(row, duplicateL2Code)).not.toBe('#112233');
    expect(categoryBackgroundColor(row, duplicateL2Code)).not.toBe('#445566');
    expect(categoryRowClass(row, duplicateL2Code)).not.toBe('product-category-custom');
    expect(categoryRowStyle(row, duplicateL2Code)).toEqual({});
  });

  it('二级编码重号时用名称选择正确的自定义颜色', () => {
    const row = { category_l2_code: '01', category_l2_name: '餐厨' };
    const duplicateL2Code = [
      { id: 21, parent: 11, level: 2, code: '01', name: '卧室', row_background_color: '#112233' },
      { id: 22, parent: 12, level: 2, code: '01', name: '餐厨', row_background_color: '#445566' },
    ];
    expect(categoryBackgroundColor(row, duplicateL2Code)).toBe('#445566');
    expect(categoryRowStyle(row, duplicateL2Code)).toEqual({
      '--product-category-row-background': '#445566',
    });
  });

  it('按 L2 id 合并 FoundationSettings 颜色，即使分类接口缺少 L2 节点或颜色', () => {
    const row = {
      category_node: 18,
      category_l2_id: 16,
      category_l2_code: '01',
      category_l2_name: '床上用品',
    };
    const categoriesWithoutL2Color = [
      { id: 14, level: 1, code: '1', name: '家纺' },
      { id: 18, parent: 16, level: 3, code: '01', name: '床笠' },
      { id: 15, level: 1, code: '2', name: '厨房' },
      { id: 17, parent: 15, level: 2, code: '01', name: '餐厨', row_background_color: '#445566' },
    ];
    const merged = mergeCategoryBackgroundColors(categoriesWithoutL2Color, [
      { id: 16, parent: 14, level: 2, code: '01', name: '床上用品', row_background_color: '#FFF4E6' },
      { id: 17, parent: 15, level: 2, code: '01', name: '餐厨', row_background_color: '' },
    ]);
    expect(categoryBackgroundColor(row, merged)).toBe('#FFF4E6');
    expect(categoryRowClass(row, merged)).toBe('product-category-custom');
    expect(merged.find((item) => String(item.id) === '17').row_background_color).toBe('');
  });
});
