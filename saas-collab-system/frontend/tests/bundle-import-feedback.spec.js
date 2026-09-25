import { describe, expect, it } from 'vitest';
import { bundleImportErrorCsvRows, bundleImportErrorMessage } from '../src/utils/bundleImportFeedback';

describe('组合商品导入反馈', () => {
  it('显示服务端字段错误，而不是笼统的校验失败提示', () => {
    const error = {
      response: {
        data: {
          message: '提交内容校验失败，请检查字段提示。',
          data: {
            legacy_sku_code: ['旧 SKU 编码已存在。'],
            components: [{ component_sku: ['组成 SKU 已停用。'] }],
          },
        },
      },
    };
    expect(bundleImportErrorMessage(error)).toContain('旧SKU编码：旧 SKU 编码已存在。');
    expect(bundleImportErrorMessage(error)).toContain('组成SKU 第1项 / 单品SKU：组成 SKU 已停用。');
    expect(bundleImportErrorMessage(error)).not.toContain('提交内容校验失败');
  });

  it('错误导出保留源行号和编码，并区分商品与图片错误', () => {
    expect(bundleImportErrorCsvRows({
      errors: [{ line: 3, legacySpuCode: 'OLD-SPU', legacySkuCode: 'OLD-SKU', name: '组合', message: '颜色不存在' }],
      imageErrors: [{ line: 4, legacySkuCode: 'OLD-IMAGE', message: '图片下载失败' }],
    })).toEqual([
      [3, '商品导入', 'OLD-SPU', 'OLD-SKU', '组合', '颜色不存在'],
      [4, '图片缓存', '', 'OLD-IMAGE', '', '图片下载失败'],
    ]);
  });

  it('把已有组合SPU的空值错误定位成可操作的中文提示', () => {
    expect(bundleImportErrorMessage({
      response: { data: { message: '提交内容校验失败，请检查字段提示。', data: { existing_spu: ['This field may not be null.'] } } },
    })).toBe('已有组合SPU：选择已有组合SPU时必须提供编号；新建组合SPU时不应提交此字段');
  });
});
