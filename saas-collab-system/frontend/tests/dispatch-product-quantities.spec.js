import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import DispatchProductLinesV2 from '../src/components/supply-chain/DispatchProductLinesV2.vue';

const stubs = {
  'el-table': { template: '<div><slot /></div>' },
  'el-table-column': { props: ['label'], template: '<div>{{ label }}<slot :row="{}" /></div>' },
  DocumentProductImageV2: true,
  DocumentSkuV2: true,
};

describe('dispatch product quantity details', () => {
  it('keeps candidate totals and exposes split batch quantity fields', () => {
    const candidates = mount(DispatchProductLinesV2, {
      props: { shipments: [{ number: 'S-1', lines: [{ id: 1, quantity: 10, allocated_quantity: 3, remaining_quantity: 7 }] }] },
      global: { stubs },
    });
    const candidateLines = candidates.vm.$.setupState.lines;
    expect(candidateLines[0]).toMatchObject({ quantity: 10, allocated_quantity: 3, remaining_quantity: 7 });
    expect(candidates.text()).toContain('发货数量');
    expect(candidates.text()).toContain('已集货数量');
    expect(candidates.text()).toContain('剩余可集货');

    const batch = mount(DispatchProductLinesV2, {
      props: { shipments: [{ number: 'S-1', lines: [{ id: 1, quantity: 3, source_quantity: 10,
        current_batch_quantity: 3, allocated_quantity: 3, remaining_quantity: 7 }] }] },
      global: { stubs },
    });
    expect(batch.vm.$.setupState.lines[0]).toMatchObject({
      quantity: 3, source_quantity: 10, current_batch_quantity: 3, allocated_quantity: 3, remaining_quantity: 7,
    });
    expect(batch.text()).toContain('本批数量');
  });

  it('renders unavailable values as an em dash without changing them to zero', () => {
    const wrapper = mount(DispatchProductLinesV2, {
      props: { shipments: [{ lines: [{ quantity: 4, allocated_quantity: null, remaining_quantity: undefined }] }] },
      global: { stubs },
    });
    expect(wrapper.vm.$.setupState.lines[0].allocated_quantity).toBeNull();
    expect(wrapper.vm.$.setupState.lines[0].remaining_quantity).toBeUndefined();
    expect(wrapper.vm.$.setupState.display(null)).toBe('—');
    expect(wrapper.vm.$.setupState.display(undefined)).toBe('—');
    expect(wrapper.vm.$.setupState.display(0)).toBe(0);
  });
});
