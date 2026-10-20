import { mount } from '@vue/test-utils';
import { describe, it, expect } from 'vitest';
import Demand from '../src/components/supply-chain/OperatingDemandV2.vue';

describe('operating demand evidence', () => {
  it('shows direct sales and component demand separately without hiding zero', () => {
    const w = mount(Demand, { props: { evidence: {
      direct_sales_quantity: 0, bundle_sales_quantity: 20, total_demand_quantity: 20,
    } } });
    expect(w.text()).toContain('直接销量 0');
    expect(w.text()).toContain('组合折算 20');
    expect(w.text()).toContain('合计需求 20');
    expect(w.text()).not.toContain('历史依据');
  });
  it('does not replace unknown demand with partial observed sales', () => {
    const w = mount(Demand, { props: { evidence: {
      direct_sales_quantity: 5, bundle_sales_quantity: null, total_demand_quantity: null, sales_quantity: 5,
    } } });
    expect(w.text()).toContain('组合折算 —');
    expect(w.text()).toContain('合计需求 —');
    expect(w.text()).not.toContain('合计需求 5');
  });
  it('labels old snapshots without inventing a component breakdown', () => {
    const w = mount(Demand, { props: { evidence: { sales_quantity: 12 } } });
    expect(w.text()).toContain('直接销量 —');
    expect(w.text()).toContain('组合折算 —');
    expect(w.text()).toContain('合计需求 12');
    expect(w.text()).toContain('历史依据未记录拆分明细');
  });
});
