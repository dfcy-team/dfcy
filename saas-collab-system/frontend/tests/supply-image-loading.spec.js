import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';

const mocks = vi.hoisted(() => ({ fetchApiFile: vi.fn() }));
vi.mock('../src/api/request', () => ({ fetchApiFile: mocks.fetchApiFile }));
import DocumentProductImageV2 from '../src/components/supply-chain/DocumentProductImageV2.vue';
import SupplierProductImageV2 from '../src/components/supply-chain/SupplierProductImageV2.vue';

const options = { global: { stubs: { 'el-image': { props: ['src'], template: '<div><img v-if="src" :src="src"/><slot v-else name="error"/></div>' } } } };
let wrappers = [];
let observers;

function mountDocument(index) {
  const wrapper = mount(DocumentProductImageV2, { ...options, props: { imagePath: `/api/internal/supply-chain/v2/options/skus/${index}/image/` } });
  wrappers.push(wrapper);
  return wrapper;
}

beforeEach(() => {
  mocks.fetchApiFile.mockReset();
  wrappers = [];
  observers = [];
  let objectUrl = 0;
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => `blob:supply-${++objectUrl}`), revokeObjectURL: vi.fn() });
});
afterEach(() => {
  wrappers.forEach(wrapper => wrapper.unmount());
  vi.unstubAllGlobals();
});

describe('supply chain image loading', () => {
  it('waits until an image is within the 150px viewport margin and caps active authorized requests at four', async () => {
    class MockIntersectionObserver {
      constructor(callback, settings) { this.callback = callback; this.settings = settings; this.target = null; observers.push(this); }
      observe(target) { this.target = target; }
      disconnect() {}
      enter() { this.callback([{ target: this.target, isIntersecting: true, intersectionRatio: 1 }]); }
    }
    vi.stubGlobal('IntersectionObserver', MockIntersectionObserver);
    const pending = [];
    mocks.fetchApiFile.mockImplementation(() => new Promise(resolve => pending.push(resolve)));
    for (let index = 1; index <= 6; index += 1) mountDocument(index);
    await flushPromises();
    expect(mocks.fetchApiFile).not.toHaveBeenCalled();
    expect(observers.every(observer => observer.settings.rootMargin === '150px')).toBe(true);

    observers.forEach(observer => observer.enter());
    expect(mocks.fetchApiFile).toHaveBeenCalledTimes(4);
    pending[0]({ success: false });
    await flushPromises();
    expect(mocks.fetchApiFile).toHaveBeenCalledTimes(5);
    pending[1]({ success: false });
    await flushPromises();
    expect(mocks.fetchApiFile).toHaveBeenCalledTimes(6);
    pending.slice(2).forEach(resolve => resolve({ success: false }));
    await flushPromises();
  });

  it('keeps supplier order authorization, drops stale responses, and revokes the previous URL after a SKU change', async () => {
    const first = { success: true, blob: new Blob(['first']) };
    const second = { success: true, blob: new Blob(['second']) };
    mocks.fetchApiFile.mockResolvedValueOnce(first).mockResolvedValueOnce(second);
    const wrapper = mount(SupplierProductImageV2, { ...options, props: { orderId: 17, skuId: 23, source: '/media/source.jpg' } });
    wrappers.push(wrapper);
    await flushPromises();
    expect(mocks.fetchApiFile).toHaveBeenNthCalledWith(1, '/api/external/supplier/supply-chain/v2/purchase-orders/17/skus/23/image/');
    expect(wrapper.find('img').attributes('src')).toBe('blob:supply-1');

    await wrapper.setProps({ skuId: 24 });
    await flushPromises();
    expect(mocks.fetchApiFile).toHaveBeenNthCalledWith(2, '/api/external/supplier/supply-chain/v2/purchase-orders/17/skus/24/image/');
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:supply-1');
    expect(wrapper.find('img').attributes('src')).toBe('blob:supply-2');
  });

  it('does not create an object URL when an authorized request finishes after unmount', async () => {
    let finish;
    mocks.fetchApiFile.mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const wrapper = mountDocument(88);
    wrappers.push(wrapper);
    await flushPromises();
    wrapper.unmount();
    wrappers = [];
    finish({ success: true, blob: new Blob(['late']) });
    await flushPromises();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});
