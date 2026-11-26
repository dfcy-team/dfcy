import { beforeEach, describe, expect, it } from 'vitest';
import { stageCockpitDraft, consumeCockpitDraft } from '../src/utils/cockpitDraft';

const input = (edited_order_quantity = 9) => ({
  parameters: { country_id: 3, source_kind: 'cycle', job_id: 'daily:123e4567-e89b-42d3-a456-426614174000' },
  rows: [{ sku_id: 7, sku_code: 'S7', suggested_quantity: 5, edited_order_quantity, stock_balance_quantity: -2, evidence: { source: 'daily' } }],
});

describe('V545 replenishment draft handoff', () => {
  beforeEach(() => stageCockpitDraft({ id: 1, tenant_id: 2, active_membership_id: 4 }, input(), 100));
  it('hands off edited quantity separately from original suggestion and evidence', () => {
    const draft = consumeCockpitDraft({ id: 1, tenant_id: 2, active_membership_id: 4 }, 101);
    expect(draft.lines[0]).toMatchObject({ quantity: 9, suggested_quantity: 5, stock_balance_quantity: -2, evidence: { source: 'daily' } });
  });
  it('rejects edited quantities that are not positive safe integers', () => {
    for (const value of [0, -1, 1.5, null]) expect(() => stageCockpitDraft(1, input(value))).toThrow();
  });
  it('keeps the one-use handoff actor bound', () => {
    expect(consumeCockpitDraft({ id: 1, tenant_id: 2, active_membership_id: 5 }, 101)).toBeNull();
  });
});
