import { mount } from '@vue/test-utils';
import { describe, it, expect } from 'vitest';
import Picker from '../src/components/IntegrationPlatformPicker.vue';

describe('platform image selector', () => {
  it('emits the original API value and clear value in single mode', async () => {
    const wrapper = mount(Picker, { props: { modelValue: '', options: ['Shopee', 'jifeng_wms'] } });
    await wrapper.get('[aria-label="Shopee"]').trigger('click');
    expect(wrapper.emitted('update:modelValue')[0]).toEqual(['Shopee']);
    expect(wrapper.emitted('change')[0]).toEqual(['Shopee']);
    expect(wrapper.get('[aria-label="Shopee"] .shopee').exists()).toBe(true);
    expect(wrapper.get('[aria-label="jifeng_wms"] img').attributes('src')).toContain('jifeng-wms-logo.png');
    expect(wrapper.get('[aria-label="jifeng_wms"]').attributes('title')).toBe('极风 WMS');
    await wrapper.get('button').trigger('click');
    expect(wrapper.emitted('change')[1]).toEqual(['']);
  });
  it('preserves multiple selections and clears them without inventing options', async () => {
    const wrapper = mount(Picker, { props: { modelValue: ['shopee'], options: ['shopee', 'lazada'], multiple: true } });
    await wrapper.get('[aria-label="lazada"]').trigger('click');
    expect(wrapper.emitted('change')[0]).toEqual([['shopee', 'lazada']]);
    await wrapper.get('[aria-label="shopee"]').trigger('click');
    expect(wrapper.emitted('change')[1]).toEqual([[]]);
    expect(wrapper.find('[aria-label="tiktok"]').exists()).toBe(false);
  });
  it('isolates independently mounted contexts and preserves a deep-linked value', async () => {
    const first = mount(Picker, { props: { modelValue: 'tiktok', options: [] } });
    const second = mount(Picker, { props: { modelValue: '', options: ['shopee'] } });
    await first.get('[aria-label="tiktok"]').trigger('click');
    expect(second.emitted()).toEqual({});
    expect(first.get('[aria-label="tiktok"]').attributes('aria-pressed')).toBe('true');
  });
});
