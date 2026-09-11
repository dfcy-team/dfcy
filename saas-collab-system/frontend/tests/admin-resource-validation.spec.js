import { flushPromises, mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../src/api/request', () => ({ useMock: false }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }));
import AdminResourcePage from '../src/components/AdminResourcePage.vue';

let wrapper;
afterEach(() => { wrapper?.unmount(); document.body.innerHTML = ''; });

async function openForm(handler) {
  wrapper = mount(AdminResourcePage, {
    attachTo: document.body,
    props: {
      title: '平台档案', entityLabel: '平台', createHandler: handler,
      loader: async () => ({ success: true, data: { results: [], count: 0 } }),
      formFields: [{ key: 'code', label: '平台编码', required: true }],
    },
    global: { plugins: [ElementPlus], stubs: {
      AppPage: { template: '<main><slot name="action"/><slot/></main>' },
      AppState: true, teleport: true, ElSelect: true, ElPagination: true,
    } },
  });
  wrapper.vm.openCreate();
  await flushPromises();
}

describe('master-data form validation recovery', () => {
  it('locates a missing required field without submitting', async () => {
    const handler = vi.fn();
    await openForm(handler);
    await wrapper.find('.el-dialog__footer .el-button--primary').trigger('click');
    expect(handler).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(wrapper.find('.el-form-item__error').text()).toContain('请填写平台编码'));
  });

  it('keeps input and displays server field errors, then permits a successful retry', async () => {
    const handler = vi.fn()
      .mockResolvedValueOnce({ success: false, code: 'VALIDATION_ERROR', message: 'error message', data: { code: ['平台编码已存在。'] } })
      .mockResolvedValueOnce({ success: true });
    await openForm(handler);
    await wrapper.find('.el-dialog input').setValue('acceptance-test');
    await wrapper.find('.el-dialog__footer .el-button--primary').trigger('click');
    await flushPromises();
    await vi.waitFor(() => expect(wrapper.find('.el-form-item__error').text()).toBe('平台编码已存在。'));
    expect(wrapper.find('.el-dialog input').element.value).toBe('acceptance-test');
    await wrapper.find('.el-dialog input').setValue('acceptance-fixed');
    await wrapper.find('.el-dialog__footer .el-button--primary').trigger('click');
    await flushPromises();
    expect(handler).toHaveBeenLastCalledWith({ code: 'acceptance-fixed' });
    await vi.waitFor(() => expect(wrapper.vm.formOpen).toBe(false));
  });
});
