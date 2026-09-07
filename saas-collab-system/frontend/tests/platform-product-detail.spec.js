import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const page = fs.readFileSync(path.resolve(process.cwd(), 'src/views/masterdata/PlatformProductDetailList.vue'), 'utf8');
const api = fs.readFileSync(path.resolve(process.cwd(), 'src/api/platformProductDetails.js'), 'utf8');

describe('平台商品明细编辑与批量修改契约', () => {
  it('提供服务端分类树筛选和分页', () => {
    expect(page).toContain('分类目录');
    expect(page).toContain('categoryTree');
    expect(page).toContain('filters.category_id');
    expect(page).toContain('@current-change="handlePageChange"');
    expect(page).toContain('fetchProductCategories');
  });

  it('仅管理员展示选择、编辑和批量操作', () => {
    expect(page).toContain("auth.hasPermission('listings.product_detail.manage')");
    expect(page).toContain('type="selection"');
    expect(page).toContain('label="操作"');
    expect(page).toContain('openEdit(row)');
    expect(page).toContain('openBulk');
  });

  it('服务端分页支持每页条数、跳转、筛选重置与越界校正', () => {
    expect(page).toContain('pageSizeOptions');
    expect(page).toContain('v-model:page-size="filters.page_size"');
    expect(page).toContain(':page-sizes="pageSizeOptions"');
    expect(page).toContain('layout="sizes, prev, pager, next, jumper"');
    expect(page).toContain('@size-change="handlePageSizeChange"');
    expect(page).toContain('function handlePageSizeChange');
    expect(page).toContain('function submitFilters');
    expect(page).toContain('function resetFilters');
    expect(page).toContain('function selectCategory(data)');
    expect(page).toMatch(/function submitFilters\(\)\s*\{\s*filters\.page = 1;/);
    expect(page).toMatch(/function resetFilters\(\)\s*\{[\s\S]*?filters\.page = 1;/);
    expect(page).toMatch(/function selectCategory\(data\)\s*\{[\s\S]*?filters\.page = 1;/);
    expect(page).toMatch(/function handlePageSizeChange\(size\)\s*\{[\s\S]*?filters\.page = 1;/);
    expect(page).toContain('retryOutOfRange');
    expect(page).toContain('const lastPage = Math.max(1, Math.ceil(payload.count / filters.page_size));');
    expect(api).toContain('PLATFORM_PRODUCT_DETAIL_PAGE_SIZE');
    expect(api).toContain('page_size');
  });

  it('批量修改支持旧/新 SPU 精确匹配、预览和状态提示', () => {
    expect(page).toContain('旧 SPU 编码');
    expect(page).toContain('新 SPU 编码');
    expect(page).toContain('previewBulk');
    expect(page).toContain('当前条件匹配');
    expect(page).toContain('批量修改完成');
    expect(page).toContain('if (selectedRows.value.length) payload.ids');
    expect(page).toContain('未选择记录，将修改全部匹配记录（含其他分页）');
    expect(page).toContain('ElMessageBox.confirm');
    expect(page).not.toContain(':disabled="!selectedRows.length"');
    expect(api).toContain('/api/internal/listings/product-details/bulk-update/');
  });

  it('提供按变体ID导入平台商品ID的独立模式', () => {
    expect(page).toContain('按变体ID导入平台商品ID');
    expect(page).toContain('onVariantProductIdImport');
    expect(page).toContain('variantProductIdImportFields');
    expect(page).toContain('downloadVariantProductIdTemplate');
    expect(page).toContain('平台商品ID允许多个变体共用');
    expect(api).toContain('importPlatformProductIds');
    expect(api).toContain('/api/internal/listings/product-details/import-platform-product-ids/');
  });

  it('以中文汇总显示导入结果并限制未匹配示例', () => {
    expect(page).toContain('import-summary-grid');
    expect(page).toContain('importSummary.total');
    expect(page).toContain('当前租户平台商品明细中不存在，已跳过');
    expect(page).toContain('importSummary.unmatchedSample.join');
    expect(page).toContain('importSummary.unmatchedRemaining');
    expect(page).toContain('importSummary.errors.slice(0, 5)');
    expect(page).not.toContain('JSON.stringify(importResult');
  });

  it('在窄屏下让页面操作区换行，避免导入按钮被裁切', () => {
    expect(page).toContain(':deep(.app-page__actions)');
    expect(page).toContain('flex-wrap: wrap');
    expect(page).toContain(':deep(.app-page__actions .el-button)');
  });

  it('只对有映射权限的角色显示状态列，并提供未归集历史入口', () => {
    expect(page).toContain('<el-table-column v-if="canViewMapping && integrationEnabled" label="SKU 映射状态"');
    expect(page).toContain('未归集历史');
    expect(page).toContain('<ProductMappingPanel v-if="unlinkedHistoryVisible" standalone initial-status="unlinked" />');
    expect(page).toContain('row.store_id || row.store');
  });

  it('受控明细编辑只提交变化字段并锁定身份与 SKU 字段', () => {
    expect(page).toContain('const editSnapshot = ref(null);');
    expect(page).toContain('const editControlled = computed');
    expect(page).toContain(':disabled="editControlled"');
    expect(page).toContain('if (editControlled.value && controlledEditFields.has(field)) continue;');
    expect(page).toContain('value !== original[field]');
    expect(page).toMatch(/async function saveEdit\(\)[\s\S]*?try \{[\s\S]*?finally \{\s+editSaving\.value = false;/);
  });

  it('缺少映射摘要时保持中性状态，不猜测为待映射', () => {
    expect(page).toContain("return filters.mapping_status === 'unmapped' ? 'unmapped' : 'unknown';");
    expect(page).toContain("unknown: '未获取映射状态'");
  });
});
