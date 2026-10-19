import { flushPromises, shallowMount } from '@vue/test-utils';
import { beforeEach, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ updateSyncJob: vi.fn(), requestApi: vi.fn() }));
vi.mock('../src/api/integrations', () => ({ updateSyncJob: api.updateSyncJob }));
vi.mock('../src/api/request', () => ({ requestApi: api.requestApi }));
import Bulk from '../src/components/BulkSyncJobPolicyDialog.vue';
import Schedule from '../src/components/SyncScheduleSettings.vue';
const global = { renderStubDefaultSlot: true };
beforeEach(() => { vi.clearAllMocks(); });
it('hides unsupported Ads bulk controls but preserves ordinary resource controls', async () => {
  const wrapper = shallowMount(Bulk, { props: { modelValue: true, jobs: [{ id: 1, platform: 'tiktok', resource_type: 'advertising_report' }] }, global });
  for (const value of ['query_page_size', 'max_pages', 'max_records', 'overlap_minutes', 'execution_budget_seconds']) {
    expect(wrapper.find(`el-checkbox-stub[value="${value}"]`).exists()).toBe(false);
  }
  expect(wrapper.text()).toContain('每天最多 100 页');
  await wrapper.setProps({ jobs: [{ id: 2, platform: 'shopee', resource_type: 'sales_order' }] });
  expect(wrapper.find('el-checkbox-stub[value="max_pages"]').exists()).toBe(true);
});
it('filters unsupported Ads bulk values even if supplied programmatically', async () => {
  const wrapper = shallowMount(Bulk, { props: { modelValue: false, jobs: [{ id: 1, platform: 'tiktok', resource_type: 'advertising_report' }] }, global });
  await wrapper.setProps({ modelValue: true });
  wrapper.vm.chosenFields = ['query', 'execution_budget_seconds', 'max_pages'];
  await flushPromises();
  expect(wrapper.vm.policy.lookback_days).toBe(7);
  expect(wrapper.vm.payload).toEqual({ query_mode: 'incremental', lookback_days: 7 });
  expect(api.updateSyncJob).not.toHaveBeenCalled();
});
it('shows true fixed bounds instead of a nonfunctional Ads budget', async () => {
  const wrapper = shallowMount(Schedule, { props: { canManage: true, job: {
    id: 1, platform: 'tiktok', resource_type: 'advertising_report', advertiser_timezone: 'Asia/Manila' } }, global });
  expect(wrapper.text()).toContain('不支持分段预算');
  expect(wrapper.text()).toContain('每页 1000 条');
  expect(wrapper.find('el-form-item-stub[label="单段执行预算（秒）"]').exists()).toBe(false);
});
it('preserves Shopee advertising datasets, budget, and 30-day range', () => {
  const wrapper = shallowMount(Schedule, { props: { canManage: true, job: {
    id: 2, platform: 'shopee', resource_type: 'advertising_report' } }, global });
  expect(wrapper.vm.isAdsJob).toBe(false);
  expect(wrapper.vm.maxDays).toBe(30);
  expect(wrapper.vm.form.advertising_datasets.length).toBeGreaterThan(0);
  expect(wrapper.find('el-form-item-stub[label="单段执行预算（秒）"]').exists()).toBe(true);
  expect(wrapper.text()).not.toContain('不支持分段预算');
  const bulk = shallowMount(Bulk, { props: { modelValue: true, jobs: [
    { id: 2, platform: 'shopee', resource_type: 'advertising_report' }] }, global });
  expect(bulk.vm.isAds).toBe(false);
  expect(bulk.find('el-checkbox-stub[value="max_pages"]').exists()).toBe(true);
});
