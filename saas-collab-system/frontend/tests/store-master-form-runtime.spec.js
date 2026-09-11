import { flushPromises, shallowMount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../src/api/masterData');
vi.mock('../src/api/systemAdmin');
vi.mock('../src/api/products');
vi.mock('../src/api/integrations');
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ push: vi.fn() }) }));

import StoreMasterList from '../src/views/masterdata/StoreMasterList.vue';
import AdminResourcePage from '../src/components/AdminResourcePage.vue';
import { createMasterData, updateMasterData } from '../src/api/masterData';

describe('store form optional values', () => {
  it('submits an empty list, false and null for unselected optional fields', async () => {
    const wrapper = shallowMount(StoreMasterList);
    await flushPromises();
    const page = wrapper.findComponent(AdminResourcePage);
    const payload = Object.fromEntries(page.props('formFields').map(field => [field.key, field.default ?? '']));
    await page.props('createHandler')(payload);
    expect(createMasterData).toHaveBeenLastCalledWith('stores', expect.objectContaining({
      fulfillment_modes: [], is_connected: false, platform_site_id: null,
    }));
    wrapper.unmount();
  });

  it('preserves explicit selections on edit and sends null when a site is cleared', async () => {
    const wrapper = shallowMount(StoreMasterList);
    await flushPromises();
    const edit = wrapper.findComponent(AdminResourcePage).props('editHandler');
    await edit(7, { platform_site_id: 12, fulfillment_modes: ['hybrid'], is_connected: true });
    expect(updateMasterData).toHaveBeenLastCalledWith('stores', 7, {
      platform_site_id: 12, fulfillment_modes: ['hybrid'], is_connected: true,
    });
    await edit(7, { platform_site_id: '' });
    expect(updateMasterData).toHaveBeenLastCalledWith('stores', 7, { platform_site_id: null });
    wrapper.unmount();
  });
});
