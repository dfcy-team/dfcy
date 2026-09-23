import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const read = (file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8');
const menu = read('src/router/menu.js');
const router = read('src/router/index.js');
const page = read('src/views/products/ProductCostLedger.vue');
const api = read('src/api/productCosts.js');
const samplePage = read('src/views/influencers/SampleFulfillmentList.vue');

describe('商品成本菜单与页面契约', () => {
  it('在基础档案中提供独立菜单和受控路由', () => {
    expect(menu).toContain("{ path: '/products/costs', label: '商品成本', permissions: ['products.cost.view'] }");
    expect(menu).toContain("{ path: '/products/costs', permissions: ['products.cost.view'], userTypes: ['internal'] }");
    expect(router).toContain("const ProductCostLedger = () => import('../views/products/ProductCostLedger.vue')");
    expect(router).toContain("{ path: 'products/costs', component: ProductCostLedger }");
  });

  it('明确区分采购价格、系统成本与已确认商品成本', () => {
    expect(page).toContain('采购价格仅作为成本构成项');
    expect(page).toContain('label="采购价格"');
    expect(page).toContain('label="系统成本"');
    expect(page).toContain('label="已确认商品成本"');
    expect(page).toContain('物流分摊');
    expect(page).toContain('税费');
    expect(page).toContain('包装费');
  });

  it('提供人工维护、审计原因和系统回填预览', () => {
    expect(page).toContain('维护商品成本');
    expect(page).toContain('调整原因');
    expect(page).toContain('采用系统成本');
    expect(page).toContain('系统生成回填');
    expect(page).toContain('回填不会覆盖或改写任何历史成本');
    expect(page).toContain('dry_run: true');
    expect(api).toContain('/api/internal/products/costs/backfill-preview/');
    expect(api).toContain('/api/internal/products/costs/backfill-execute/');
    expect(api).toContain('/confirm/');
    expect(page).toContain('写入待核对版本');
    expect(api).toContain('/api/internal/products/costs/');
  });
  it('成本调整新增版本且不覆盖历史', () => {
    expect(page).toContain('调整成本只新增版本，不覆盖历史');
    expect(page).toContain('下游业务须按仓库和发生时间锁定成本快照');
    expect(page).toContain('成本历史版本');
    expect(page).toContain('新增版本并确认');
    expect(page).toContain('effective_from');
    expect(page).toContain('await load()');
    expect(api).toContain('/versions/');
    expect(api).toContain("method: 'post'");
    expect(api).not.toContain("method: 'patch'");
    expect(api).toContain('requestApi');
    expect(api).not.toContain('Mock');
  });
  it('维护时展示成本变化影响', () => {
    expect(page).toContain('data-testid="cost-change-preview"');
    expect(page).toContain('当前生效成本');
    expect(page).toContain('拟生效成本');
    expect(page).toContain('成本变化');
    expect(page).toContain('changeAmount');
    expect(page).toContain('changeRate');
  });

  it('支持每期 CSV/XLSX 成本预检后确认导入', () => {
    expect(page).toContain('每期成本导入');
    expect(page).toContain('accept=".csv,.xlsx"');
    expect(page).toContain('导入只追加版本');
    expect(page).toContain('cost-import-preview');
    expect(api).toContain('/api/internal/products/costs/import/preview/');
    expect(api).toContain('/api/internal/products/costs/import/confirm/');
    expect(api).toContain('Idempotency-Key');
  });

  it('提供可直接下载和导入的中文成本模板', () => {
    expect(page).toContain('cost-template-download');
    expect(page).toContain('下载导入模板');
    expect(page).toContain('商品成本导入模板.csv');
    expect(page).toContain("'SKU编码（二选一）', '旧SKU编码（二选一）', '*仓库编码', '*生效开始', '生效结束', '*币种'");
    expect(page).toContain('SKU编码和旧SKU编码二选一');
    expect(page).toContain("'*确认成本'");
    expect(page).toContain('其余带 * 的列为必填项');
    expect(page).not.toContain('CSV/XLSX 列：<code>sku_code</code>');
  });

  it('展示导入阶段进度并可导出完整异常记录', () => {
    expect(page).toContain('cost-import-progress');
    expect(page).toContain('正在上传文件');
    expect(page).toContain('正在解析并校验数据');
    expect(page).toContain('正在写入成本版本');
    expect(page).toContain('cost-error-export');
    expect(page).toContain('导出完整异常明细');
    expect(page).toContain('商品成本导入异常_');
    expect(page).toContain('error_batch_id');
  });
  it('按仓库所在地分组、维护、导入和回填', () => {
    expect(page).toContain('SKU × 仓库');
    expect(page).toContain('仓库 / 所在国家');
    expect(page).toContain('version.warehouse ||');
    expect(page).toContain('row.warehouse === applied.warehouse');
    expect(page).toContain('warehouse: form.warehouse');
    expect(page).toContain('warehouse_id: backfill.warehouse');
    expect(page).toContain('每行指定仓库编码');
    expect(api).toContain('/api/internal/products/costs/warehouses/');
  });
  it('下游送样逐 SKU 明确选仓并校验店铺国家', () => {
    expect(samplePage).toContain('仓库（与店铺同国）');
    expect(samplePage).toContain('v-model="item.warehouse"');
    expect(samplePage).toContain('selectedStore.value?.country_code');
    expect(samplePage).toContain('发货仓库国家必须与店铺国家一致');
    expect(samplePage).toContain('warehouse: item.warehouse || null');
  });
});
