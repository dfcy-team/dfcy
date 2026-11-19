import { flushPromises, shallowMount } from '@vue/test-utils';
import { expect, it, vi } from 'vitest';
import { fetchInventoryWarnings } from '../src/api/alerts';
import InventoryWarningSnapshot from '../src/views/inventory/InventoryWarningSnapshot.vue';

vi.mock('../src/api/alerts', () => ({ fetchInventoryWarnings: vi.fn() }));

it('uses the applied country and selected SPU for read-only variant details', async () => {
  fetchInventoryWarnings.mockResolvedValue({ success: true, data: { results: [] } });
  const page = shallowMount(InventoryWarningSnapshot, { global: { stubs: { RouterLink: true } } });
  await flushPromises();
  page.vm.filters.country_id = 7;
  page.vm.apply();
  await flushPromises();
  page.vm.filters.country_id = 8;
  await page.vm.openDetails({ spu_id: 12 });

  expect(fetchInventoryWarnings).toHaveBeenLastCalledWith(
    { country_id: 7, spu_id: 12 }, expect.any(AbortSignal),
  );
  const signal = fetchInventoryWarnings.mock.calls.at(-1)[1];
  page.vm.closeDetails();
  expect(signal.aborted).toBe(true);
  page.unmount();
});
