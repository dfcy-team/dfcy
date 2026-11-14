import { shallowMount, flushPromises } from '@vue/test-utils';
import { expect, it, vi } from 'vitest';
import Records from './SyncExecutionRecords.vue';
const { fetchWorkspace } = vi.hoisted(() => ({ fetchWorkspace: vi.fn() }));
vi.mock('../../api/integrations', () => ({ fetchIntegrationWorkspace: fetchWorkspace,
  retrySyncRun: vi.fn(), previewSyncRunCleanup: vi.fn(), cleanupSyncRuns: vi.fn() }));
vi.mock('../../stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ push:vi.fn(), replace:vi.fn() }) }));

it('shows GMV Max and routes its selection to evidence without creating tasks', async () => {
  fetchWorkspace.mockResolvedValue({ success:true, data:{ results:[], options:{resource_types:['advertising_report']}, pagination:{total:0,page:1} } });
  const wrapper = shallowMount(Records, { global:{directives:{loading:()=>{}},
    stubs:{ElForm:{template:'<div><slot /></div>'}, ElFormItem:{template:'<div><slot /></div>'},
      ElSelect:{name:'ElSelect',template:'<div><slot /></div>'}}} });
  await flushPromises();
  expect(wrapper.html()).toContain('GMV Max 广告');
  const selector = wrapper.findAllComponents({name:'ElSelect'}).find(s => s.attributes('aria-label') === '同步内容');
  selector.vm.$emit('update:modelValue','gmv_max_report');
  await wrapper.find('.filters').trigger('submit');
  await flushPromises();
  expect(fetchWorkspace.mock.lastCall[1]).toMatchObject({resource_type:'gmv_max_report',record_source:'gmv_max',sync_job_id:''});
});
