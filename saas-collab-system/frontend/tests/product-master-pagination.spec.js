import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const page = fs.readFileSync(
  path.resolve(process.cwd(), 'src/views/products/ProductMasterList.vue'),
  'utf8'
);

describe('商品主数据列表分页与 SKU 展示契约', () => {
  it('使用服务端 page/page_size，并支持总数、每页条数和筛选回到第 1 页', () => {
    expect(page).toContain('page: page.value');
    expect(page).toContain('page_size: pageSize.value');
    expect(page).toContain(':page-sizes="pageSizes"');
    expect(page).toContain('@current-change="changePage"');
    expect(page).toContain('@size-change="changePageSize"');
    expect(page).toContain('共 {{ total }} 条');
    expect(page).toContain('function search()');
    expect(page).toContain('function selectCategory(node)');
    expect(page).toContain('page.value = 1');
  });

  it('使用受控 popover 展示可滚动 SKU 明细，且列名明确为 SPU 商品名称', () => {
    expect(page).toContain('label="SPU商品名称"');
    expect(page).toContain('<el-popover');
    expect(page).toContain(':visible="skuPopoverId === row.id"');
    expect(page).toContain('@hide="handleSkuPopoverHide(row.id)"');
    expect(page).toContain('popper-class="sku-popover"');
    expect(page).toContain(':global(.sku-popover .sku-details)');
    expect(page).toContain("document.addEventListener('click', handleDocumentClick, true)");
    expect(page).toContain("document.removeEventListener('click', handleDocumentClick, true)");
    expect(page).toContain('max-height: 220px');
    expect(page).not.toContain('show-overflow-tooltip');
  });
});
