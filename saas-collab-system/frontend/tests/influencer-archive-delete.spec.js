import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ direct: vi.fn(), list: vi.fn(), confirm: vi.fn(), manage: true }));
vi.mock('../src/api/request', () => ({ requestApi: api.direct, requestWithMockFallback: api.list }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => api.manage }) }));
vi.mock('element-plus', async (original) => ({ ...await original(), ElMessage: { error: vi.fn(), warning: vi.fn(), success: vi.fn() }, ElMessageBox: { confirm: api.confirm } }));
import Library from '../src/views/influencers/InfluencerResourceLibrary.vue';
import { archiveStateLabel } from '../src/views/influencers/recordEvidence';

const slot = { template: '<div><slot /><slot name="footer" /></div>' };
const stubs = Object.fromEntries(['el-card','el-dialog','el-form','el-form-item','el-divider','el-tag'].map(n => [n, slot]));
Object.assign(stubs, { 'el-table':true, 'el-drawer':true, 'el-select':true, 'el-option':true,
  'el-input':true, 'el-input-number':true, 'el-switch':true, 'el-pagination':true, 'el-checkbox':true,
  'el-alert':true, 'el-button': { template:'<button><slot /></button>' } });
const row = { id:7, platform:'facebook', nickname_id:'demo.page', updated_at:'2026-11-05T01:00:00Z' };
beforeEach(() => {
  vi.clearAllMocks();api.manage=true;api.confirm.mockResolvedValue(true);
  api.direct.mockResolvedValue({success:true,data:{id:7,is_deleted:true}});
  api.list.mockResolvedValue({success:true,data:{count:0,results:[]}});
});
async function render() { const w=mount(Library,{global:{stubs}}); await flushPromises();return w; }

describe('single archive recoverable deletion', () => {
  it('deletes the selected archive only with current version and explicit scope confirmation',async () => {
    const w=await render();await w.vm.changeArchiveDeletion(row);
    expect(api.confirm.mock.calls[0][0]).toContain('Facebook');
    expect(api.confirm.mock.calls[0][0]).toContain('不删除关联的其他平台档案');
    expect(api.direct).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({method:'delete',url:'/api/internal/influencers/7/archive-deletion/',headers:{'If-Match':'"2026-11-05T01:00:00Z"'}}));
    expect(api.list).toHaveBeenCalledTimes(2);w.unmount();
  });
  it('cancel never calls a write',async () => {
    api.confirm.mockRejectedValueOnce(new Error('cancel'));
    const w=await render();await w.vm.changeArchiveDeletion(row);
    expect(api.direct).not.toHaveBeenCalled();w.unmount();
  });
  it('blocks missing manage permission and missing row version',async () => {
    api.manage=false;const w=await render();await w.vm.changeArchiveDeletion(row);
    expect(api.direct).not.toHaveBeenCalled();expect(api.confirm).not.toHaveBeenCalled();w.unmount();
    api.manage=true;const v=await render();await v.vm.changeArchiveDeletion({...row,updated_at:''});
    expect(api.direct).not.toHaveBeenCalled();v.unmount();
  });
  it('restores through the real API without mock write fallback',async () => {
    const w=await render();await w.vm.changeArchiveDeletion({...row,is_deleted:true},true);
    expect(api.direct).toHaveBeenCalledWith(expect.objectContaining({method:'post',url:'/api/internal/influencers/7/archive-deletion/'}));
    expect(archiveStateLabel({is_deleted:true,is_blacklisted:true})).toBe('已删除');w.unmount();
  });
  it('does not repeat a timed-out write or assume success',async () => {
    api.direct.mockRejectedValueOnce(new Error('timeout'));
    const w=await render();await w.vm.changeArchiveDeletion(row);
    expect(api.direct).toHaveBeenCalledTimes(1);expect(api.list).toHaveBeenCalledTimes(1);w.unmount();
  });
  it('includes deleted-only filter and clears it on reset',async () => {
    const w=await render();w.vm.deletedOnly=true;await w.vm.load();
    expect(api.list.mock.lastCall[0].params.deleted_only).toBe('true');
    w.vm.resetFilters();await flushPromises();expect(api.list.mock.lastCall[0].params).not.toHaveProperty('deleted_only');w.unmount();
  });
});
