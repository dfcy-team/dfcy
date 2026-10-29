import { describe, it, expect } from 'vitest';
import { amountUnits, natureLabel, validateAllocations } from '../src/utils/payeeSettlement';

describe('收款账户累计分配', () => {
  it('uses exact four-place amounts including large totals', () => {
    expect(amountUnits('99999999999999999999.9999')).toBe(999999999999999999999999n);
    expect(validateAllocations([{account_id:1,amount:'0.1'},{account_id:2,amount:'0.2'}],'0.3')).toHaveLength(2);
  });
  it('rejects unassigned, duplicate and mismatched allocations', () => {
    expect(()=>validateAllocations([],'1')).toThrow('请选择');
    expect(()=>validateAllocations([{account_id:1,amount:'1'},{account_id:1,amount:'1'}],'2')).toThrow('重复');
    expect(()=>validateAllocations([{account_id:1,amount:'1'}],'2')).toThrow('合计');
    expect(()=>validateAllocations([{account_id:1,amount:'0'}],'0')).toThrow('大于0');
    expect(()=>amountUnits('1.00001')).toThrow();
    expect(validateAllocations([],'0')).toEqual([]);
  });
  it('retains unclassified and mixed labels', () => {
    expect(natureLabel('corporate')).toBe('对公');
    expect(natureLabel('personal')).toBe('对私');
    expect(natureLabel('mixed')).toBe('混合结算');
    expect(natureLabel(null)).toBe('未标识');
  });
});
