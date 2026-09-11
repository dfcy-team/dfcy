// @vitest-environment jsdom
import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, expect, test, vi } from 'vitest';
import Preview from '../src/components/MissingSyncJobsPreview.vue';
import { requestApi } from '../src/api/request';

vi.mock('../src/api/request', () => ({ requestApi: vi.fn() }));
const stubs = {
  'el-button': { template: '<button :disabled="$attrs.disabled" @click="$emit(\'click\')"><slot /></button>' },
  'el-alert': { props: ['title'], template: '<p role="status">{{ title }}</p>' },
  'el-table': { props: ['data', 'emptyText'], template: '<div>{{ data.length ? JSON.stringify(data) : emptyText }}</div>' },
  'el-table-column': true,
};
beforeEach(() => vi.clearAllMocks());

test('preview is explicit, GET-only, and shows empty-state meaning', async () => {
  requestApi.mockResolvedValue({ success: true, data: { items: [], notice: '不创建、不启用任务' } });
  const wrapper = mount(Preview, { global: { stubs } });
  expect(requestApi).not.toHaveBeenCalled();
  await wrapper.get('button').trigger('click');
  await flushPromises();
  expect(requestApi).toHaveBeenCalledExactlyOnceWith({ method: 'get', url: '/api/internal/integrations/sync-jobs/missing-preview/' });
  expect(wrapper.text()).toContain('不创建、不启用任务');
  expect(wrapper.text()).toContain('已有停用任务不重复列出');
});

test('failed refresh clears stale success and allows retry', async () => {
  requestApi.mockResolvedValueOnce({ success: true, data: { items: [], notice: '旧结果' } })
    .mockResolvedValueOnce({ success: false, message: '无权限' });
  const wrapper = mount(Preview, { global: { stubs } });
  await wrapper.get('button').trigger('click');
  await flushPromises();
  await wrapper.get('button').trigger('click');
  await flushPromises();
  expect(wrapper.text()).toContain('无权限');
  expect(wrapper.text()).not.toContain('旧结果');
  expect(wrapper.get('button').attributes('disabled')).toBeUndefined();
});
