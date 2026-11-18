import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ requestApi: vi.fn(), fetchApiFile: vi.fn() }));
vi.mock('../src/api/request', () => api);
import Page from '../src/views/influencers/InfluencerRequirements.vue';

afterEach(() => vi.restoreAllMocks());
describe('requirement images', () => {
  it('previews, submits multipart images, and loads saved images through authenticated API', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, writable: true, value: vi.fn(() => 'blob:fixture') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, writable: true, value: vi.fn() });
    api.requestApi.mockImplementation(async config => config.method === 'post'
      ? { success: true, data: { id: 1 } }
      : { success: true, data: { results: [{ id: 1, title: 'Saved', description: 'Details', created_at: '2026-01-01T00:00:00Z', image_ids: [4] }], count: 1, page: 1, can_review: false } });
    api.fetchApiFile.mockResolvedValue({ success: true, blob: new Blob(['fixture']) });
    const wrapper = mount(Page);
    await flushPromises();
    await wrapper.get('input[maxlength="120"]').setValue('Title');
    await wrapper.get('textarea').setValue('Description');
    const file = new File(['fixture'], 'screenshot.png', { type: 'image/png' });
    const input = wrapper.get('input[type="file"]');
    Object.defineProperty(input.element, 'files', { value: [file] });
    await input.trigger('change');
    expect(wrapper.findAll('figure img')).toHaveLength(1);
    await wrapper.get('form').trigger('submit');
    await flushPromises();
    const sent = api.requestApi.mock.calls.find(([config]) => config.method === 'post')[0];
    expect(sent.data).toBeInstanceOf(FormData);
    expect(sent.data.get('images').name).toBe('screenshot.png');
    expect(wrapper.findAll('figure')).toHaveLength(0);
    await wrapper.get('article button').trigger('click');
    await flushPromises();
    expect(api.fetchApiFile).toHaveBeenCalledWith('/api/internal/influencers/requirements/1/images/4/');
    expect(wrapper.findAll('article img')).toHaveLength(1);
    wrapper.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalled();
  });
});
