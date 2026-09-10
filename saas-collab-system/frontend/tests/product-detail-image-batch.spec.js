import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const page = fs.readFileSync(
  path.resolve(process.cwd(), 'src/views/products/ProductDetailData.vue'),
  'utf8',
);

describe('商品明细图片批量缓存流程', () => {
  it('提供提交、逐行状态、重试和保存阶段', () => {
    expect(page).toContain('data-testid="image-batch-open"');
    expect(page).toContain('data-testid="image-batch-submit"');
    expect(page).toContain('data-testid="image-batch-save"');
    expect(page).toContain('data-testid="image-batch-retry"');
    expect(page).toContain("const imageBatchPhase = ref('draft')");
    expect(page).toContain("imageBatchPhase.value = 'completed'");
    expect(page).toContain('await load();');
    expect(page).toContain('if (refreshed) imageBatchVisible.value = false;');
  });

  it('按小批次显示缓存进度，并将缓存地址用于预览和文件信息', () => {
    expect(page).toContain('const batchSize = 5;');
    expect(page).toContain('imageBatchProgressPercent');
    expect(page).toContain('cached_url');
    expect(page).toContain(':preview-src-list="[resolveImageUrl(row.cached_url)]"');
    expect(page).toContain('imageBatchFileInfo(row)');
    expect(page).toContain('服务器未返回缓存图片地址');
  });

  it('按当前 chunk 的 index 匹配结果且不以重复 SKU 作为唯一键', () => {
    expect(page).toContain('function imageBatchResultAt(resultRows, index)');
    expect(page).toContain('item.index !== undefined && item.index !== null');
    expect(page).toContain('batchRows.forEach((row, index) => applyImageBatchResult(row, imageBatchResultAt(resultRows, index)))');
    expect(page).not.toContain('new Map(resultRows.map');
  });

  it('读取 CSV 使用异步解析状态机并限制文件大小', () => {
    expect(page).toContain("import { parseImageCsv, yieldToPage } from '../../utils/imageBatchCsv';");
    expect(page).toContain("imageBatchPhase.value = 'reading'");
    expect(page).toContain("if (file.size > 10 * 1024 * 1024)");
    expect(page).toContain("new TextDecoder('utf-8', { fatal: true })");
    expect(page).toContain("new TextDecoder('gb18030')");
    expect(page).toContain('const parsed = await parseImageCsv(text');
    expect(page).toContain('if (index % 250 === 0)');
    expect(page).toContain("imageBatchPhase === 'reading' ? '读取中…'");
    expect(page).toContain(':disabled="imageBatchSaving || !imageBatchSummary.valid"');
  });

  it('预览分页固定每页 50 行，并在每个后端批次后让出事件循环', () => {
    expect(page).toContain('const imageBatchPreviewSize = 50;');
    expect(page).toContain(':data="imageBatchPreviewRows"');
    expect(page).toContain('data-testid="image-batch-pagination"');
    expect(page).toContain('const batchSize = 5;');
    expect(page).toContain('updateImageBatchProgress(processed, total);\n      await yieldToPage();');
  });
});
