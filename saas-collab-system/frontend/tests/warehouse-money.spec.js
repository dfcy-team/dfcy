import { describe, it, expect } from 'vitest';
import { warehouseMoney, warehouseMoneyTotal } from '../src/utils/warehouseMoney';
describe('warehouse money decimal presentation', () => {
  it('sums at source precision before rounding and does not use floating point', () => {
    expect(warehouseMoneyTotal(['0.004999', '0.004999'])).toBe('0.01');
    expect(warehouseMoneyTotal(['99999999999999.999999', '0.000001'])).toBe('100000000000000.00');
    expect(warehouseMoneyTotal([])).toBe('0.00');
    expect(warehouseMoneyTotal(['bad'])).toBe('—');
  });
  it.each([['6','6.00'], ['1.005000','1.01'], ['0.004999','0.00'], ['0.005000','0.01'],
    ['-0.004999','0.00'], ['-0.005000','-0.01'], ['99999999999999.999999','100000000000000.00'], [null,'—']])('%s → %s', (value, expected) => {
    expect(warehouseMoney(value)).toBe(expected);
  });
});
