import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import SupplierTermsFieldsV2 from '../src/components/supply-chain/SupplierTermsFieldsV2.vue';

const stubs = {
  'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
  'el-date-picker': { props: ['modelValue', 'valueFormat', 'disabled'], template: '<input data-test="date" :value="modelValue" :data-format="valueFormat" :disabled="disabled" />' },
  'el-input-number': { props: ['modelValue', 'min', 'max', 'step', 'precision', 'disabled'], template: '<input data-test="days" :value="modelValue" :min="min" :max="max" :step="step" :data-precision="precision" :disabled="disabled" />' },
  'el-select': { props: ['modelValue', 'disabled'], template: '<select data-test="start" :value="modelValue" :disabled="disabled"><slot /></select>' },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
};

describe('SupplierTermsFieldsV2', () => {
  it('renders nullable date and whole-day range with all start choices', () => {
    const wrapper = mount(SupplierTermsFieldsV2, {
      props: { form: { first_cooperation_date: null, payment_term_days: null, payment_term_start: 'unspecified' } },
      global: { stubs },
    });
    expect(wrapper.text()).toContain('首次合作日期');
    expect(wrapper.text()).toContain('账期天数');
    expect(wrapper.text()).toContain('账期起算方式');
    expect(wrapper.find('[data-test="date"]').attributes('data-format')).toBe('YYYY-MM-DD');
    expect(wrapper.find('[data-test="days"]').attributes()).toMatchObject({ min: '0', max: '3650', step: '1', 'data-precision': '0' });
    expect(wrapper.findAll('option').map((option) => option.attributes('value'))).toEqual([
      'unspecified', 'shipment_date', 'collection_arrival', 'warehouse_arrival', 'reconciliation_date',
    ]);
  });

  it('disables editing when requested', () => {
    const wrapper = mount(SupplierTermsFieldsV2, {
      props: { form: { first_cooperation_date: null, payment_term_days: 0, payment_term_start: 'unspecified' }, disabled: true },
      global: { stubs },
    });
    expect(wrapper.findAll('input').every((input) => input.attributes('disabled') !== undefined)).toBe(true);
    expect(wrapper.find('select').attributes('disabled')).toBeDefined();
  });
});
