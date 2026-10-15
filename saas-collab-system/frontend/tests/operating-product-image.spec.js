import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
const mocks = vi.hoisted(() => ({ fetchApiFile: vi.fn() }));
vi.mock('../src/api/request', () => ({ fetchApiFile: mocks.fetchApiFile }));
import OperatingProductImageV2 from '../src/components/supply-chain/OperatingProductImageV2.vue';
import DocumentProductImageV2 from '../src/components/supply-chain/DocumentProductImageV2.vue';
const options = { global: { stubs: { 'el-image': { props: ['src'], template: '<div><img v-if="src" :src="src"/><slot v-else name="error"/></div>' } } } };
beforeEach(() => {
  mocks.fetchApiFile.mockReset();
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:operating-image'), revokeObjectURL: vi.fn() });
});
afterEach(() => vi.unstubAllGlobals());
describe('operating order product images', () => {
  it('does not send authenticated image requests to an arbitrary URL', async () => {
    const wrapper = mount(DocumentProductImageV2, { ...options, props: { imagePath: 'https://images.example.test/product.jpg' } });
    await flushPromises();
    expect(mocks.fetchApiFile).not.toHaveBeenCalled();
    expect(wrapper.find('img').exists()).toBe(false);
    wrapper.unmount();
  });
  it('uses the operator endpoint independently of procurement permissions, and releases the file URL', async () => {
    mocks.fetchApiFile.mockResolvedValue({ success: true, blob: new Blob(['image']) });
    const wrapper = mount(OperatingProductImageV2, { ...options, props: { skuId: 6, source: '/media/test.jpg' } });
    await flushPromises();
    expect(mocks.fetchApiFile).toHaveBeenLastCalledWith('/api/internal/commerce/operating-options/skus/6/image/');
    expect(wrapper.find('img').attributes('src')).toBe('blob:operating-image');
    await wrapper.setProps({ procurement: true });
    await flushPromises();
    expect(mocks.fetchApiFile).toHaveBeenLastCalledWith('/api/internal/supply-chain/v2/options/skus/6/image/');
    wrapper.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:operating-image');
  });
  it('discards a response for a previous SKU and leaves missing or failed images readable', async () => {
    let finishOld;
    mocks.fetchApiFile.mockReturnValueOnce(new Promise(resolve => { finishOld = resolve; })).mockResolvedValue({ success: false });
    const wrapper = mount(OperatingProductImageV2, { ...options, props: { skuId: 6, source: '/media/6.jpg' } });
    await wrapper.setProps({ skuId: 7, source: '/media/7.jpg' });
    await flushPromises();
    finishOld({ success: true, blob: new Blob(['old']) });
    await flushPromises();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(wrapper.find('img').exists()).toBe(false);
    expect(wrapper.text()).toContain('图片暂不可用');
    await wrapper.setProps({ source: '' });
    expect(wrapper.text()).toContain('暂无商品图片');
    expect(mocks.fetchApiFile).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });
});
