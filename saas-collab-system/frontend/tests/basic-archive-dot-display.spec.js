import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { productLifecycleStatusLabel, productSalesStatusLabel } from '../src/utils/productLabels';

const read = (file) => fs.readFileSync(path.resolve(process.cwd(), file), 'utf8');

function componentFunction(file, name, args = ['value']) {
  const source = read(file);
  const signature = `function ${name}(${args[0]}) {`;
  const start = source.indexOf(signature);
  if (start < 0) throw new Error(`Could not find ${signature} in ${file}`);
  const bodyStart = start + signature.length;
  let depth = 1;
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1;
    if (source[index] === '}') depth -= 1;
    if (depth === 0) return new Function(...args, source.slice(bodyStart, index));
  }
  throw new Error(`Could not find end of ${name} in ${file}`);
}

function moneyFormatter() {
  const source = read('src/views/products/ProductCostLedger.vue');
  const expression = source.match(/const money = \(value\) => ([^;]+);/)?.[1];
  if (!expression) throw new Error('Could not find cost money formatter');
  return new Function('number', `return (value) => ${expression};`)((value) => Number(value || 0));
}

describe('基础档案详情显示口径', () => {
  it('成本列表与只读详情使用 system_cost；零、缺失和正数分别显示', () => {
    const page = read('src/views/products/ProductCostLedger.vue');
    expect(page).toContain('money(row.system_cost)');
    expect(page).toContain('const systemCost = form.system_cost;');
    expect(page).toContain('if (systemCost === null || systemCost === undefined || systemCost === \'\') return null;');
    expect(page).toContain('return Number.isFinite(parsed) ? parsed : null;');

    const money = moneyFormatter();
    expect(money(0)).toBe('¥0.00');
    expect(money(null)).toBe('-');
    expect(money(undefined)).toBe('-');
    expect(money(13.97)).toBe('¥13.97');
  });

  it('商品状态复用列表字典，未知值保留原编码', () => {
    expect(productLifecycleStatusLabel('draft')).toBe('草稿');
    expect(productLifecycleStatusLabel('unknown_lifecycle')).toBe('unknown_lifecycle');
    expect(productSalesStatusLabel('not_listed')).toBe('未刊登');
    expect(productSalesStatusLabel('unknown_sales')).toBe('unknown_sales');
    const page = read('src/views/products/ProductMasterDetail.vue');
    expect(page).not.toContain('UI-P5');
    expect(componentFunction('src/views/products/ProductMasterDetail.vue', 'stateLabel', ['value', 'stateLabels'])('connected', { connected: '已连接' })).toBe('已连接');
  });

  it.each([
    ['src/views/masterdata/PlatformMasterList.vue', 'statusLabel', 'active', '启用'],
    ['src/views/masterdata/WarehouseMasterList.vue', 'statusLabel', 'active', '启用'],
    ['src/views/masterdata/StoreMasterList.vue', 'storeStatusLabel', 'active', '启用'],
    ['src/views/masterdata/StoreMasterList.vue', 'businessModelLabel', 'other', '其他'],
  ])('%s 将已知 %s 映射为中文并对未知值回退原值', (file, functionName, code, label) => {
    const formatter = componentFunction(file, functionName);
    expect(formatter(code)).toBe(label);
    expect(formatter('future_enum')).toBe('future_enum');
  });
});
