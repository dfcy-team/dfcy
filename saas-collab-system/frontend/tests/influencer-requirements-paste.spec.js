// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { requestApi } from '../src/api/request';
import InfluencerRequirements from '../src/views/influencers/InfluencerRequirements.vue';

vi.mock('../src/api/request', () => ({
  requestApi: vi.fn(),
  fetchApiFile: vi.fn(),
}));

let wrapper;

function paste(selector, data) {
  const event = new Event('paste', { bubbles: true, cancelable: true });
  Object.defineProperty(event, 'clipboardData', { value: data });
  wrapper.get(selector).element.dispatchEvent(event);
  return event;
}

describe('requirement feedback image paste', () => {
  beforeEach(async () => {
    let next = 0;
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => `blob:fixture-${++next}`),
      revokeObjectURL: vi.fn(),
    });
    requestApi.mockReset();
    requestApi.mockResolvedValue({ success: true, data: { results: [], count: 0, page: 1 } });
    wrapper = mount(InfluencerRequirements);
    await flushPromises();
  });

  afterEach(() => {
    wrapper.unmount();
    vi.unstubAllGlobals();
  });

  it('previews a pasted screenshot and submits it through the existing attachment field', async () => {
    const image = new File(['screenshot'], 'clipboard.png', { type: 'image/png' });
    expect(paste('.paste-images', { files: [image] }).defaultPrevented).toBe(true);
    await wrapper.vm.$nextTick();
    expect(wrapper.findAll('figure img')).toHaveLength(1);
    await wrapper.get('input[required]').setValue('Example title');
    await wrapper.get('textarea').setValue('Example description');
    await wrapper.get('form').trigger('submit');
    await flushPromises();
    const submit = requestApi.mock.calls.find(([request]) => request.method === 'post')[0];
    expect(submit.data.getAll('images')).toEqual([image]);
  });

  it('preserves plain text paste and enforces the shared type, size and count limits', async () => {
    expect(paste('textarea', { files: [], items: [{ kind: 'string', type: 'text/plain' }] }).defaultPrevented).toBe(false);
    const input = wrapper.get('input[type=file]');
    const image = new File(['screenshot'], 'one.png', { type: 'image/png' });
    Object.defineProperty(input.element, 'files', { value: [image] });
    await input.trigger('change');
    const gif = new File(['gif'], 'a.gif', { type: 'image/gif' });
    paste('textarea', { files: [gif] });
    await wrapper.vm.$nextTick();
    expect(wrapper.findAll('figure img')).toHaveLength(1);
    expect(wrapper.get('[role=alert]').text()).toContain('JPG');
    const large = new File([new Uint8Array(2 * 1024 * 1024 + 1)], 'large.png', { type: 'image/png' });
    paste('.paste-images', { files: [large] });
    await wrapper.vm.$nextTick();
    expect(wrapper.findAll('figure img')).toHaveLength(1);
    const item = { kind: 'file', type: 'image/png', getAsFile: () => image };
    paste('.paste-images', { items: [item, item] });
    await wrapper.vm.$nextTick();
    expect(wrapper.findAll('figure img')).toHaveLength(3);
    paste('.paste-images', { files: [image] });
    await wrapper.vm.$nextTick();
    expect(wrapper.findAll('figure img')).toHaveLength(3);
    expect(wrapper.get('[role=alert]').text()).toContain('3 张');
  });
});
