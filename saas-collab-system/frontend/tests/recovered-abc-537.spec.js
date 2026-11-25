import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import Badge from '../src/components/inventory/RecoveredABCBadges537.js';
const abc = () => ({classification_basis:'composite',policy_version:'composite_revenue_units_v1_20261120',status:'ready',spu_grade:'A',sku_grade:'B',spu_evidence:{revenue_grade:'A',units_grade:'B',continuity_label:'sustained',reasons:[]},sku_evidence:{revenue_grade:'B',units_grade:'C',continuity_label:'intermittent_or_unproven',reasons:[]}});
describe('restored panel retains current composite ABC', () => {
  it('renders SPU composite grade and separate evidence', () => {
    const w=mount(Badge,{props:{row:{__spu:true,abc:abc()}}});
    expect(w.text()).toContain('SPU 综合 A'); expect(w.text()).toContain('销售额 A · 销量 B'); expect(w.text()).not.toContain('SKU 综合');
  });
  it('uses SKU evidence for variant rows', () => {
    const w=mount(Badge,{props:{row:{spu_id:1,sku_id:2,abc:abc()}}});
    expect(w.text()).toContain('SKU 综合 B'); expect(w.text()).toContain('销售额 B · 销量 C');
  });
  it('does not mislabel an older policy as composite', () => {
    const w=mount(Badge,{props:{row:{__spu:true,abc:{...abc(),policy_version:'legacy'}}}});
    expect(w.text()).toBe('综合分类更新中');
  });
});
