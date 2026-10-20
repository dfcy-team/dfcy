import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import DispatchProductLinesV2 from '../src/components/supply-chain/DispatchProductLinesV2.vue';

const stubs = {
  'el-table': { template: '<div><slot /></div>' },
  'el-table-column': {
    props: ['label'],
    inject: ['tableRows'],
    template: '<div>{{ label }}<div v-for="row in tableRows" :key="row.id"><slot :row="row" /></div></div>',
  },
  DocumentProductImageV2: true,
  DocumentSkuV2: true,
};

describe('dispatch product quantity details', () => {
  it('keeps candidate totals and exposes split batch quantity fields', () => {
    const tableStubs = {
      ...stubs,
      'el-table': {
        props: ['data'],
        provide() { return { tableRows: this.data }; },
        template: '<div><slot /></div>',
      },
    };
    const candidates = mount(DispatchProductLinesV2, {
      props: { shipments: [{ number: 'S-1', lines: [{ id: 1, quantity: 10, allocated_quantity: 3, remaining_quantity: 7 }] }] },
      global: { stubs: tableStubs },
    });
    const candidateLines = candidates.vm.$.setupState.lines;
    expect(candidateLines[0]).toMatchObject({ quantity: 10, allocated_quantity: 3, remaining_quantity: 7 });
    expect(candidates.text()).toContain('原发货量');
    expect(candidates.text()).toContain('原发货量 10');
    expect(candidates.text()).toContain('已集货数量 3');
    expect(candidates.text()).toContain('当前未分配 7');

    const batch = mount(DispatchProductLinesV2, {
      props: { shipments: [{ number: 'S-1', lines: [{ id: 1, quantity: 3, source_quantity: 10,
        current_batch_quantity: 3, allocated_quantity: 3, remaining_quantity: 7, available_quantity: 10 }] }] },
      global: { stubs: tableStubs },
    });
    expect(batch.vm.$.setupState.lines[0]).toMatchObject({
      quantity: 3, source_quantity: 10, current_batch_quantity: 3, allocated_quantity: 3, remaining_quantity: 7, available_quantity: 10,
    });
    expect(batch.text()).toContain('本批数量');
    expect(batch.text()).toContain('原发货量 10');
    expect(batch.text()).toContain('已集货数量 3');
    expect(batch.text()).toContain('当前未分配 7');
    expect(batch.text()).toContain('本批数量 3');
    expect(batch.text()).toContain('本批可用量 10');
    expect(candidates.text()).not.toContain('本批数量');
  });

  it('preserves explicit zeroes and fractional quantities in every quantity field', () => {
    const wrapper = mount(DispatchProductLinesV2, {
      props: { shipments: [{ lines: [
        { id: 1, quantity: 9, source_quantity: 0, current_batch_quantity: 0, allocated_quantity: 0, remaining_quantity: 0, available_quantity: 0 },
        { id: 2, quantity: 2.75, source_quantity: 4.5, current_batch_quantity: 0.5, allocated_quantity: 1.25, remaining_quantity: 3.25, available_quantity: 2.25 },
      ] }] },
      global: {
        stubs: {
          ...stubs,
          'el-table': {
            props: ['data'],
            provide() { return { tableRows: this.data }; },
            template: '<div><slot /></div>',
          },
        },
      },
    });

    expect(wrapper.text()).toContain('原发货量 0');
    expect(wrapper.text()).toContain('已集货数量 0');
    expect(wrapper.text()).toContain('当前未分配 0');
    expect(wrapper.text()).toContain('本批数量 0');
    expect(wrapper.text()).toContain('本批可用量 0');
    expect(wrapper.text()).toContain('原发货量 4.5');
    expect(wrapper.text()).toContain('已集货数量 1.25');
    expect(wrapper.text()).toContain('当前未分配 3.25');
    expect(wrapper.text()).toContain('本批数量 0.5');
    expect(wrapper.text()).toContain('本批可用量 2.25');
  });

  it('renders unavailable values as an em dash without changing them to zero', () => {
    const wrapper = mount(DispatchProductLinesV2, {
      props: { shipments: [{ lines: [{ quantity: 4, allocated_quantity: null, remaining_quantity: undefined }] }] },
      global: {
        stubs: {
          ...stubs,
          'el-table': {
            props: ['data'],
            provide() { return { tableRows: this.data }; },
            template: '<div><slot /></div>',
          },
        },
      },
    });
    expect(wrapper.vm.$.setupState.lines[0].allocated_quantity).toBeNull();
    expect(wrapper.vm.$.setupState.lines[0].remaining_quantity).toBeUndefined();
    expect(wrapper.vm.$.setupState.display(null)).toBe('—');
    expect(wrapper.vm.$.setupState.display(undefined)).toBe('—');
    expect(wrapper.vm.$.setupState.display(0)).toBe(0);
    expect(wrapper.text()).toContain('已集货数量 —');
    expect(wrapper.text()).toContain('当前未分配 —');
  });
});
