import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const page = fs.readFileSync(
  path.resolve(process.cwd(), 'src/views/masterdata/PlatformProductDetailList.vue'),
  'utf8',
);

describe('平台商品明细 SKU 图片展示契约', () => {
  it('uses the API image from the linked internal SKU and supports preview', () => {
    expect(page).toContain('internal_sku_image_url');
    expect(page).toContain('label="商品图片"');
    expect(page).toContain('<el-image');
    expect(page).toContain(':preview-src-list="[skuImageUrl(row)]"');
    expect(page).toContain('preview-teleported');
    expect(page).toContain('function skuImageUrl(row)');
    expect(page).toContain('apiBaseUrl');
  });

  it('has explicit empty and load-error states with stable test ids', () => {
    expect(page).toContain('platform-product-detail-image-${row.id}');
    expect(page).toContain('platform-product-detail-image-empty-${row.id}');
    expect(page).toContain('>无图</span>');
    expect(page).toContain('>加载失败</span>');
  });

  it('places the image before the platform detail columns', () => {
    expect(page.indexOf('label="商品图片"')).toBeLessThan(page.indexOf('prop="platform_name" label="平台"'));
  });
});
