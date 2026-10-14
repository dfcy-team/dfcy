import { describe, expect, it } from 'vitest';
import { readBdExchangeRateRows, validateBdExchangeRates } from '../src/utils/bdExchangeRates';

const row = (values = {}) => ({ currency: 'PHP', rate: '0.1234567891', effective_from: '2026-08-01', note: '', ...values });

describe('BD FX typed payload', () => {
  it('preserves decimal text and supports all four foreign currencies', () => {
    const value = validateBdExchangeRates(['THB', 'USD', 'PHP', 'MYR'].map(currency => row({ currency })));
    expect(value.rates.map(item => item.currency)).toEqual(['MYR', 'PHP', 'THB', 'USD']);
    expect(value.rates.every(item => item.rate === '0.1234567891')).toBe(true);
    expect(value).not.toHaveProperty('default_currency');
    expect(value).not.toHaveProperty('default_attribution');
  });
  it.each(['0', '-1', 'NaN', 'Infinity', '1e-2', '0.12345678912', '10000000000', '', '1,000', '1.'])('rejects invalid rate %s', rate => {
    expect(() => validateBdExchangeRates([row({ rate })])).toThrow();
  });
  it.each([0.12, true, null])('rejects non-string rate %s', rate => {
    expect(() => validateBdExchangeRates([row({ rate })])).toThrow();
  });
  it.each(['2026-02-30', '2026-13-01', '2026-8-01', '2026-08-01T00:00:00Z', '1899-12-31', '2101-01-01', ''])('rejects invalid date %s', effective_from => {
    expect(() => validateBdExchangeRates([row({ effective_from })])).toThrow();
  });
  it('allows ordered timeline, rejects duplicate currency and date', () => {
    const value = validateBdExchangeRates([row({ effective_from: '2026-09-01' }), row()]);
    expect(value.rates.map(item => item.effective_from)).toEqual(['2026-08-01', '2026-09-01']);
    expect(() => validateBdExchangeRates([row(), row()])).toThrow(/重复/);
  });
  it('rejects unsupported, oversized and unexpected fields', () => {
    expect(() => validateBdExchangeRates([row({ currency: 'CNY' })])).toThrow();
    expect(() => validateBdExchangeRates([row({ secret: 'invalid' })])).toThrow();
    expect(() => validateBdExchangeRates([row({ note: 'x'.repeat(241) })])).toThrow();
    expect(() => validateBdExchangeRates(Array(1001).fill(row()))).toThrow();
    expect(() => validateBdExchangeRates([])).toThrow();
  });
  it('reads an unconfigured default, but never silently discards incompatible fields', () => {
    expect(readBdExchangeRateRows(null)).toEqual([]);
    expect(readBdExchangeRateRows({ rates: [] })).toEqual([]);
    expect(() => readBdExchangeRateRows({ rates: [row()], hidden: 'retain-me' })).toThrow();
    expect(() => readBdExchangeRateRows({ rates: [row({ hidden: 'retain-me' })] })).toThrow();
  });
  it('allows an explicit last-row deletion without weakening the default empty guard', () => {
    expect(validateBdExchangeRates([], { allowEmpty: true })).toEqual({ rates: [] });
    expect(() => validateBdExchangeRates([])).toThrow();
    expect(() => validateBdExchangeRates(null, { allowEmpty: true })).toThrow();
  });
});
