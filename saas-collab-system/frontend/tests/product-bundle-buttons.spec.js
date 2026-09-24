import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const read = (file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8');
const page = read('src/views/products/ProductBundleManager.vue');
const detailPage = read('src/views/products/ProductDetailData.vue');
const api = read('src/api/products.js');

describe('组合商品页面按钮与导入导出契约', () => {
  it('新增组合 SKU 可新建 SPU 或选择已有组合 SPU，并显示旧 SPU 映射', () => {
    expect(page).toContain('data-testid="bundle-spu-mode"');
    expect(page).toContain('新建组合 SPU');
    expect(page).toContain('选择已有组合 SPU');
    expect(page).toContain('搜索新/旧 SPU 编码或商品名称');
    expect(page).toContain('legacy_spu_code');
    expect(page).toContain("spu_mode: spuMode");
    expect(page).toContain("existing_spu: spuMode === 'existing'");
  });
  it('组合 SKU 支持独立主图上传、预览和列表展示', () => {
    expect(page).toContain('组合商品主图');
    expect(page).toContain('accept="image/jpeg,image/png,image/gif,image/webp,image/avif"');
    expect(page).toContain('该图片属于组合 SKU，不会覆盖任何子 SKU 图片');
    expect(page).toContain('uploadProductSkuImage(result.sku.id, bundleImageFile.value)');
    expect(page).toContain('粘贴公网图片链接，保存时自动转存本地');
    expect(page).toContain('cacheProductBundleImage(result.sku.id, bundleImageUrl.value.trim())');
    expect(page).toContain('row.image_url');
    expect(api).toContain('`/api/internal/products/skus/${skuId}/image/`');
    expect(api).toContain('`/api/internal/products/bundles/${skuId}/image-cache/`');
  });
  it('组合商品导入导出归集到商品明细外部菜单', () => {
    expect(page).not.toContain('data-testid="bundle-io-menu"');
    expect(detailPage).toContain('data-testid="detail-io-menu"');
    expect(page).toContain('data-testid="bundle-import-template"');
    expect(page).toContain('下载组合商品导入模板');
    expect(detailPage).toContain('data-testid="detail-bundle-import-button"');
    expect(detailPage).toContain('command="bundle-import"');
    expect(page).toContain('data-testid="bundle-import-file"');
    expect(page.indexOf('title="组合商品导入"')).toBeLessThan(page.indexOf('data-testid="bundle-import-template"'));
    expect(detailPage).toContain('组合商品导入');
  });

  it('保留新建入口并增加可选择的 BigSeller 组合表生成入口', () => {
    expect(page).toContain('data-testid="bundle-create-button"');
    expect(page).toContain('新建组合 SKU');
    expect(detailPage).toContain('data-testid="bigseller-create-bundle-export"');
    expect(detailPage).toContain('下载 BigSeller 组合商品SKU表');
    expect(detailPage).toContain('exportableSelectedBundleRows');
    expect(detailPage).toContain('fetchProductBundleDetail(row.sku_id)');
    expect(detailPage).toContain('downloadBigSellerBundleWorkbook(spus, skus, relations)');
  });

  it('二期支持组合版本、库存可用量和全部旧组合关系的预览确认迁移', () => {
    expect(page).toContain('保存新版本');
    expect(page).toContain('已同步订单继续使用下单时快照');
    expect(page).toContain('库存可用量');
    expect(page).toContain('仅供业务判断，不直接扣减库存');
    expect(detailPage).toContain('data-testid="detail-bundle-legacy-migration-button"');
    expect(page).toContain("if (props.initialAction === 'legacy-migration') openMigration();");
    expect(page).toContain("breakdown['bundle_not_unique:not_found']");
    expect(page).toContain("breakdown['component_not_unique:multiple_matches']");
    expect(page).toContain('不按 ZH 前缀筛选');
    expect(page).toContain('accept=".csv,.xlsx');
    expect(page).toContain("payload.append('file', file)");
    expect(page).toContain('服务端未返回迁移确认令牌');
    expect(page).toContain(':disabled="!migrationPreview.token || migrationPreview.bundleCount === 0"');
    expect(page).toContain('迁移可用组合');
    expect(page).toContain("matched: '匹配成功'");
    expect(page).toContain('旧组合关系迁移异常_');
    expect(page).toContain('已生成异常文件');
    expect(page).toContain('downloadMigrationErrors(migrationPreview.rejectedRows)');
    expect(page).toContain('同一组合存在其他阻断的子 SKU');
    expect(api).toContain("url: `/api/internal/products/bundles/${skuId}/`");
    expect(api).toContain("url: '/api/internal/products/bundles/migrations/preview/'");
    expect(api).toContain('migrations/${encodeURIComponent(token)}/confirm/');
  });

  it('批量导入复用服务端原子创建链路，成功后自动生成 BigSeller 表', () => {
    expect(page).toContain('createProductBundle');
    expect(api).toContain("url: '/api/internal/products/bundles/create/'");
    expect(page).not.toContain('createProductSpu');
    expect(page).not.toContain('createProductSku');
    expect(page).not.toContain('createBundleComponent');
    expect(page).toContain('const input = prepareImportRow(values, headers, line, skuByCode)');
    expect(page).toContain('const result = await createBundle(input)');
    expect(page).toContain("'图片URL'");
    expect(page).toContain("'旧SPU编码', '旧SKU编码', '*组合商品名称'");
    expect(page).toContain("const legacySpuCode = importValue(values, headers, '旧SPU编码')");
    expect(page).toContain("const legacySkuCode = importValue(values, headers, '旧SKU编码')");
    expect(page).toContain('legacy_spu_code: legacySpuCode');
    expect(page).toContain('legacy_sku_code: legacySkuCode');
    expect(page).toContain("const imageUrl = importValue(values, headers, '图片URL')");
    expect(page).toContain('cacheProductBundleImage(result.sku.id, input.imageUrl)');
    expect(page).toContain('result.sku.image_url = cachedImageUrl');
    expect(page).toContain('cost_allocation_ratio: component.costRatio ?? 1');
    expect(detailPage).toContain('const components = detailData(response.data)?.components || []');
    expect(detailPage).toContain('bundle_sku: row.sku_id');
    expect(page).toContain('downloadBigSellerBundleWorkbook(createdSpus, createdSkus, createdComponents)');
    expect(page).toContain("'*组合商品名称', '*末级分类编码', '*属性编码', '*组合颜色英文编码'");
    expect(page).toContain('index <= 20');
    expect(api).toContain("url: dictionaryApi('bundle-components')");
    expect(api).toContain("'products.bundle_components'");
  });
});
