import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import axios from 'axios';

import Phase2DataPage from '../src/components/Phase2DataPage.vue';
import { downloadApiFile, isTrustedApiFilePath } from '../src/api/request';

vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({
    hasPermission: () => true
  })
}));

const stubs = {
  ElTag: { props: ['type'], template: '<span class="status-tag"><slot /></span>' },
  ElAlert: { props: ['title'], template: '<div class="alert"><slot />{{ title }}</div>' },
  ElForm: { template: '<form><slot /></form>' },
  ElFormItem: { template: '<label><slot /></label>' },
  ElInput: { template: '<input />' },
  ElSelect: { template: '<select><slot /></select>' },
  ElOption: { template: '<option><slot /></option>' },
  ElButton: { template: '<button><slot /></button>' },
  ElTable: { template: '<div><slot /></div>' },
  ElTableColumn: { template: '<div />' },
  ElCard: { template: '<div><slot name="header" /><slot /></div>' },
  ElDescriptions: { template: '<dl><slot /></dl>' },
  ElDescriptionsItem: { template: '<div><slot /></div>' },
  ElEmpty: { props: ['description'], template: '<div>{{ description }}</div>' },
  ElDrawer: { template: '<aside><slot /></aside>' }
};

describe('V2.44.43 shared security gates', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('keeps a successful response pending when the API omits status evidence', async () => {
    const wrapper = mount(Phase2DataPage, {
      props: {
        title: '测试数据',
        loader: vi.fn().mockResolvedValue({
          success: true,
          code: 'OK',
          message: 'ok',
          data: { results: [{ id: 1 }] }
        }),
        columns: [{ prop: 'id', label: 'ID' }]
      },
      global: { stubs }
    });

    await flushPromises();
    expect(wrapper.find('.status-tag').text()).toBe('pending');
  });

  it.each([
    'https://attacker.example/file.csv',
    'http://attacker.example/file.csv',
    '//attacker.example/file.csv',
    '/downloads/file.csv',
    'reports/file.csv',
    '/api/../downloads/file.csv'
  ])('rejects untrusted download path %s before making a request', async (url) => {
    const get = vi.spyOn(axios, 'get');
    expect(isTrustedApiFilePath(url)).toBe(false);
    const result = await downloadApiFile(url, 'report.csv');
    expect(result).toMatchObject({ success: false, code: 'INVALID_DOWNLOAD_PATH' });
    expect(get).not.toHaveBeenCalled();
  });

  it('accepts only an API-relative download path', () => {
    expect(isTrustedApiFilePath('/api/internal/reports/exports/1/download/')).toBe(true);
    expect(isTrustedApiFilePath('/api/internal/reports/exports/1/download/?format=csv')).toBe(true);
  });
});
