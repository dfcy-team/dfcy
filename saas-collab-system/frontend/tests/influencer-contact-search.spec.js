import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const request = vi.hoisted(() => vi.fn());
vi.mock('../src/api/request', () => ({ requestApi: request, requestWithMockFallback: request }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, currentUser: { id: 1, tenant_id: 1 }, authorizationStale: false }) }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ replace: vi.fn() }) }));

import InfluencerResourceLibrary from '../src/views/influencers/InfluencerResourceLibrary.vue';

const stubs = {
  ElCard: { template: '<div><slot /></div>' }, ElTable: { template: '<div><slot /></div>' },
  ElTableColumn: { template: '<div />' }, ElPagination: { template: '<div />' },
  ElTag: { template: '<span><slot /></span>' }, ElAlert: { template: '<div />' },
  ElButton: { emits: ['click'], template: '<button @click="$emit(\'click\')"><slot /></button>' },
  ElInput: { props: ['modelValue', 'placeholder'], emits: ['update:modelValue', 'keyup'], template: '<input :placeholder="placeholder" :value="modelValue" @input="$emit(\'update:modelValue\',$event.target.value)" />' },
  ElSelect: { props: ['modelValue', 'placeholder'], emits: ['update:modelValue'], template: '<select :value="modelValue" :aria-label="placeholder" @change="$emit(\'update:modelValue\',$event.target.value)"><slot /></select>' },
  ElOption: { props: ['value', 'label'], template: '<option :value="value">{{ label }}</option>' },
  ElCheckbox: { template: '<div />' },
};

const response = (name) => ({ success: true, data: { count: 1, results: [{ id: name === 'contact' ? 22 : 11, name, platform: 'instagram', status: 'active', follower_count: 0, cooperation_status: 'none', profile: {}, platform_accounts: [] }] } });
const render = () => mount(InfluencerResourceLibrary, { global: { stubs } });
const calls = () => request.mock.calls.map(([config]) => config);

beforeEach(() => {
  vi.clearAllMocks();
  request.mockImplementation(async (config) => response(config.method === 'post' ? 'contact' : 'list'));
});

describe('Influencer contact search', () => {
  it('sends contact in POST body only and returns to GET after reset', async () => {
    const wrapper = render(); await flushPromises();
    await wrapper.find('select[aria-label="联系方式渠道"]').setValue('email');
    await wrapper.find('input[placeholder="精确搜索联系方式"]').setValue('private@example.test');
    await wrapper.findAll('button').find((button) => button.text().includes('搜索联系方式')).trigger('click');
    await flushPromises();
    const post = calls().findLast((config) => config.method === 'post');
    expect(post.url).toBe('/api/internal/influencers/contact-search/');
    expect(post.data).toEqual({ channel: 'email', value: 'private@example.test' });
    expect(JSON.stringify({ url: post.url, params: post.params })).not.toContain('private@example.test');
    expect(wrapper.vm.rows[0].id).toBe(22);
    await wrapper.findAll('button').find((button) => button.text().includes('重置')).trigger('click');
    await flushPromises();
    expect(calls().findLast((config) => config.url === '/api/internal/influencers/').method).toBe('get');
    expect(wrapper.vm.contactValue).toBe('');
    await wrapper.find('select[aria-label="联系方式渠道"]').setValue('email');
    await wrapper.find('input[placeholder="精确搜索联系方式"]').setValue('again@example.test');
    await wrapper.findAll('button').find((button) => button.text().includes('搜索联系方式')).trigger('click');
    await flushPromises();
    await wrapper.find('select[aria-label="联系方式渠道"]').setValue('');
    await wrapper.findAll('button').find((button) => button.text().includes('搜索联系方式')).trigger('click');
    await flushPromises();
    expect(calls().findLast((config) => config.url === '/api/internal/influencers/').method).toBe('get');
    expect(wrapper.vm.contactValue).toBe('');
    wrapper.unmount();
  });

  it('does not let a late old list response overwrite a newer contact response', async () => {
    let finishOld;
    request.mockImplementation((config) => config.method === 'post'
      ? Promise.resolve(response('contact'))
      : new Promise((resolve) => { finishOld = () => resolve(response('old-list')); }));
    const wrapper = render();
    await wrapper.find('select[aria-label="联系方式渠道"]').setValue('email');
    await wrapper.find('input[placeholder="精确搜索联系方式"]').setValue('private@example.test');
    await wrapper.findAll('button').find((button) => button.text().includes('搜索联系方式')).trigger('click');
    await flushPromises();
    expect(wrapper.vm.rows[0].id).toBe(22);
    finishOld(); await flushPromises();
    expect(wrapper.vm.rows[0].id).toBe(22);
    expect(calls().some((config) => config.method === 'post' && config.url.includes('private@example.test'))).toBe(false);
    wrapper.unmount();
  });

  it('keeps the applied private contact in POST body across page and filter reloads', async () => {
    const wrapper = render(); await flushPromises();
    await wrapper.find('select[aria-label="联系方式渠道"]').setValue('email');
    await wrapper.find('input[placeholder="精确搜索联系方式"]').setValue('private@example.test');
    await wrapper.findAll('button').find((button) => button.text().includes('搜索联系方式')).trigger('click');
    await flushPromises();
    wrapper.vm.page = 2; await wrapper.vm.load();
    wrapper.vm.pageSize = 50; await wrapper.vm.changePageSize();
    wrapper.vm.filters.status = 'active'; await wrapper.vm.applyFilters();
    const posts = calls().filter((config) => config.method === 'post');
    expect(posts.length).toBeGreaterThanOrEqual(4);
    expect(posts.at(-3).params.page).toBe(2);
    expect(posts.at(-2).params.page_size).toBe(50);
    expect(posts.at(-1).params.status).toBe('active');
    expect(posts.every((config) => config.data.value === 'private@example.test')).toBe(true);
    expect(posts.every((config) => !JSON.stringify({ url: config.url, params: config.params }).includes('private@example.test'))).toBe(true);
    wrapper.unmount();
  });
});
