import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const page = fs.readFileSync(
  path.resolve(process.cwd(), 'src/views/products/ProductMasterList.vue'),
  'utf8'
);

describe('商品主数据列表契约', () => {
  it('头部使用业务文案并提供可展开的编码规则说明', () => {
    const header = page.match(/<header class="page-header">[\s\S]*?<\/header>/)?.[0] || '';
    expect(header).toContain('商品资料与编码');
    expect(header).toContain('商品 SKU 生成规则说明');
    expect(header).toContain('SPU编码-颜色编码[-规格值]');
    expect(header).toContain('001–999');
    expect(header).toContain('启用的颜色字典');
    expect(header).toContain('<details');
    expect(header).not.toContain('UI-P5');
    expect(header).not.toContain('tenant');
    expect(header).not.toContain('data_scope');
    expect(header).not.toContain('connected');
  });

  it('使用服务端分页并在查询、分类、每页条数变化时回到第一页', () => {
    expect(page).toContain('page: page.value, page_size: pageSize.value');
    expect(page).toContain(':page-sizes="pageSizes"');
    expect(page).toContain('@current-change="changePage"');
    expect(page).toContain('@size-change="changePageSize"');
    expect(page).toContain('共 {{ total }} 条');
    expect(page).toContain('function search()');
    expect(page).toContain('function selectCategory(node)');
    expect(page).toContain('page.value = 1');
    expect(page).toMatch(/\.content-panel\s*\{[^}]*align-content:\s*start;/s);
  });

  it('展示 SKU 摘要和数量，并以对话框替代长 tooltip', () => {
    expect(page).toContain('label="SPU商品名称"');
    expect(page).toContain('aria-haspopup="dialog"');
    expect(page).toContain('openSkuDetails(row)');
    expect(page).toContain('skuPreviewLimit = 2');
    expect(page).toContain('<el-dialog v-model="skuDetailOpen" title="SKU 明细"');
    expect(page).toContain('max-height: min(55vh, 420px)');
    expect(page).toContain('overflow-y: auto');
    expect(page).toContain('word-break: break-all');
    expect(page).toContain('@click="copySku(code)"');
    expect(page).toContain('navigator.clipboard');
    expect(page).not.toContain('el-popover');
    expect(page).not.toContain('sku-popover');
    expect(page).not.toContain('document.addEventListener');
    expect(page).not.toContain('show-overflow-tooltip');
  });

  it('保留分类树和创建商品字段', () => {
    expect(page).toContain('categoryTree');
    expect(page).toContain('categoryDisabled');
    expect(page).toContain('createForm.brand');
    expect(page).toContain('createForm.season_code');
    expect(page).toContain("product_type: 'standard'");
  });

  it('仅向商品主数据管理员展示编辑和生成 SKU 操作', () => {
    expect(page).toContain('label="操作" min-width="220" fixed="right"');
    expect(page).toContain('<router-link :to="`/products/master/${row.id}`">查看</router-link>');
    expect(page).toContain('v-if="canManage"');
    expect(page).toContain('@click="openEdit(row)"');
    expect(page).toContain('编辑');
    expect(page).toContain('@click="openSkuCreate(row)"');
    expect(page).toContain('生成 SKU');
    expect(page).toContain("auth.hasPermission('products.master.manage')");
    expect(page).toContain('if (!canManage.value) return;');
  });

  it('通过启用颜色和分类规格动态生成 SKU，成功后刷新列表', () => {
    expect(page).toContain('fetchProductColors');
    expect(page).toMatch(/async function loadColors\(\)\s*\{\s*if \(!canManage\.value\) return;/s);
    expect(page).toContain('activeColors');
    expect(page).toContain('spec_dimensions');
    expect(page).toContain('skuDimensions');
    expect(page).toContain('skuForm.spec_values[dimension.code]');
    expect(page).toContain('createProductSku({');
    expect(page).toContain('color_code: skuForm.color_code');
    expect(page).toContain('spec_values: { ...skuForm.spec_values }');
    expect(page).toContain('await load();');
  });

  it('生成 SKU 时将不含连字符的规格稳定排列在含连字符规格之前', () => {
    expect(page).toContain('function sortSpecValues(values)');
    expect(page).toContain("hasHyphen: String(value).includes('-')");
    expect(page).toContain('Number(left.hasHyphen) - Number(right.hasHyphen) || left.index - right.index');
    expect(page).toContain('values: sortSpecValues(item.values)');
  });

  it('通过 SPU PATCH 保存名称和启用末级分类', () => {
    const api = fs.readFileSync(path.resolve(process.cwd(), 'src/api/products.js'), 'utf8');
    expect(api).toContain('export const updateProductSpu');
    expect(api).toContain("method: 'patch'");
    expect(api).toContain("/api/internal/products/spus/${id}/");
    expect(page).toContain('updateProductSpu(editForm.id');
    expect(page).toContain('category_node: editForm.category_node');
    expect(page).toContain('isUsableCategory');
    expect(page).toContain('data.is_active === false');
  });

  it('商品页面不含旧内部标识或替换字符', () => {
    expect(page).not.toMatch(/[\uFFFD]/u);
    expect(page).not.toContain('UI-P5');
    expect(page).not.toContain('tenant');
    expect(page).not.toContain('data_scope');
  });

  it('让 SPA HTML 每次重新验证并长期缓存内容哈希静态资源', () => {
    const nginx = fs.readFileSync(
      path.resolve(process.cwd(), '../deploy/pilot/application/nginx.conf'),
      'utf8'
    );
    expect(nginx).toContain('location = /index.html');
    expect(nginx).toContain('Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0"');
    expect(nginx).toContain('location /assets/');
    expect(nginx).toContain('Cache-Control "public, max-age=31536000, immutable"');
    expect(nginx).toContain('try_files $uri $uri/ /index.html;');
  });
});
