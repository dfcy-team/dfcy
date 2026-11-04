import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import vm from 'node:vm';
import { afterEach, describe, expect, it } from 'vitest';

const source = readFileSync(resolve(process.cwd(), '../backend/apps/finance/summary_tools.js'), 'utf8');
afterEach(() => { document.body.innerHTML = ''; document.head.querySelectorAll('style').forEach(s => s.remove()); });

describe('独立账务设置面板', () => {
  it('费用按工具当前店铺选择，不受旧账单筛选残留影响；保留三个功能入口', () => {
    document.body.innerHTML = '<main><input id="month"><select id="store"><option value="50">LZ9PH</option><option value="30">SP8PH</option></select></main><dialog id="ads-settings-drawer"></dialog><dialog id="drawer"><h2 id="drawer-title"></h2><div id="drawer-body"></div></dialog><details><input id="profit-close-month"><button id="profit-close-save"></button></details>';
    const state = { filters: {} };
    const context = { document, Option, state, KINDS: { order_fee: '订单费用' },
      LEDGER_FEES: { shops: () => [{ id: '30', code: 'SP8PH', country: 'PH' }, { id: '50', code: 'LZ9PH', country: 'PH' }], kinds: ['order_fee'] },
      HTML2_STORE_HIERARCHY: { controls: () => [{ store_id: 50 }] },
      renderLedger: () => { state.filters.store = '30'; },
      entriesFor: () => [{ store_id: 50, date: '2026-09-01', kind: 'order_fee' }],
      localFact: value => value,
      categoryTable: entries => `<input type="checkbox" data-fee-selection="${entries[0].store_id}">`,
    };
    vm.createContext(context); vm.runInContext(source, context);
    context.SAAS_SETUP_TOOLS({ can_edit: true, context: { toolPanel: 'fees', fields: { store: '50', month: '2026-09' } } });
    expect(document.querySelectorAll('[data-tool]')).toHaveLength(3);
    expect(document.querySelector('[data-fee-selection]').dataset.feeSelection).toBe('50');
    expect(document.querySelector('#drawer').hasAttribute('open')).toBe(true);
    document.querySelector('#tool-shop').value = '30';
    document.querySelector('#tool-apply').click();
    expect(document.querySelector('[data-fee-selection]')).toBeNull();
    document.querySelector('#tool-shop').value = '50';
    document.querySelector('#tool-apply').click();
    expect(document.querySelector('[data-fee-selection]').dataset.feeSelection).toBe('50');
    document.querySelector('[data-tool="closing"]').click();
    expect(document.querySelector('#drawer').hasAttribute('open')).toBe(false);
    expect(document.querySelector('#profit-close-month').value).toBe('2026-09');
    expect(document.querySelector('#saas-settings-tools main')).toBeNull();
  });
});
