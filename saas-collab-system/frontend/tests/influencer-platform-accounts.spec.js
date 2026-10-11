import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ direct: vi.fn(), fallback: vi.fn(), confirm: vi.fn(), manage: true }));
vi.mock('element-plus', async (importOriginal) => ({ ...await importOriginal(), ElMessage: { error: vi.fn(() => ({ close() {} })), warning: vi.fn(() => ({ close() {} })), success: vi.fn(() => ({ close() {} })) }, ElMessageBox: { confirm: api.confirm, prompt: vi.fn() } }));
vi.mock('../src/api/request', () => ({ requestApi: api.direct, requestWithMockFallback: api.fallback }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => api.manage }) }));
import InfluencerResourceLibrary from '../src/views/influencers/InfluencerResourceLibrary.vue';
import { ElMessage } from 'element-plus';
import { fetchInfluencer, fetchInfluencers, fetchInfluencerForm, saveInfluencerForm, fetchRelatedInfluencerArchives, createRelatedInfluencerArchive, INFLUENCER_PLATFORM_LABELS, INFLUENCER_CONTACT_CHANNEL_LABELS } from '../src/api/influencers';
import { influencerMocks } from '../src/mock/influencers';

const slot = { template: '<div><slot /><slot name="footer" /></div>' };
const stubs = Object.fromEntries(['el-card', 'el-dialog', 'el-form', 'el-form-item', 'el-divider', 'el-tabs', 'el-tab-pane', 'el-tag', 'el-dropdown', 'el-dropdown-menu', 'el-dropdown-item'].map((name) => [name, slot]));
Object.assign(stubs, {
  'el-button': { template: '<button><slot /></button>' },
  'el-table': { template: '<div />' },
  'el-drawer': { template: '<div />' },
  'el-form-item': { props: { label: String, required: Boolean, error: String }, template: '<div :data-label="label" :data-required="required" :data-error="error"><slot /></div>' },
  'el-tab-pane': { props: ['name'], template: '<section :data-platform="name"><slot /></section>' },
  'el-input': { props: ['modelValue', 'disabled', 'placeholder'], emits: ['update:modelValue'], template: '<input :value="modelValue" :disabled="disabled" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
  'el-input-number': { template: '<input />' },
  'el-select': { props: ['modelValue', 'disabled'], emits: ['update:modelValue'], template: '<select :value="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>' },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-switch': true, 'el-checkbox': true, 'el-pagination': true, 'el-alert': true
});

function record() {
  return {
    id: 7, code: 'DEMO7', name: 'Legacy Stored Name', platform: 'TikTok', handle: 'misschedly',
    nickname_id: 'misschedly', account_nickname: 'Demo Display | 品牌', category: '',
    cooperation_status: 'prospect', follower_count: 10, updated_at: '2026-10-10T01:00:00Z',
    profile: { external_influencer_id: '7488000000000000007', display_name: 'Demo Display | 品牌', level: '', tier: '', market: '', content_types: [], profile_url: '', duplicate_reason: '', profile_notes: '', is_active: true },
    contacts: [{ channel: 'email', value: 'demo@example.com', label: '', is_primary: true }],
    related_archives: [{ id: 7, code: 'DEMO7', platform: 'TikTok', nickname_id: 'misschedly', account_nickname: 'Demo Display | 品牌', updated_at: '2026-10-10T01:00:00Z' }], archive_group_id: null, group_version: null,
    platform_accounts: [
      { id: null, source: 'legacy', platform: 'tiktok', handle: 'misschedly', nickname_id: 'misschedly', account_nickname: 'Demo Display | 品牌' },
      { id: 8, platform: 'facebook', handle: 'demo.page', nickname_id: 'demo.page', external_account_id: '0007488000000000000008', display_name: 'Demo Page', account_nickname: 'Demo Page', profile_url: '', follower_count: null, is_active: true }
    ]
  };
}

async function library() {
  const wrapper = mount(InfluencerResourceLibrary, { global: { stubs } });
  await flushPromises();
  return wrapper;
}

describe('independent linked platform archives', () => {
  beforeEach(() => {
    api.manage = true;
    api.direct.mockReset();
    api.fallback.mockReset();
    api.confirm.mockReset();
    api.confirm.mockResolvedValue('confirm');
    ElMessage.error.mockClear(); ElMessage.warning.mockClear(); ElMessage.success.mockClear();
    api.fallback.mockResolvedValue({ success: true, data: { count: 0, results: [] } });
    api.direct.mockResolvedValue({ success: true, data: record() });
  });

  it('offers Facebook without promoting contact channels to account data', async () => {
    const wrapper = await library();
    expect(INFLUENCER_PLATFORM_LABELS.facebook).toBe('Facebook');
    expect(Object.keys(INFLUENCER_PLATFORM_LABELS)).toEqual(['tiktok', 'facebook', 'instagram', 'youtube']);
    expect(INFLUENCER_CONTACT_CHANNEL_LABELS.viber).toBe('Viber');
    await wrapper.vm.openCreate();
    expect(wrapper.vm.form).not.toHaveProperty('platform_accounts');
    expect(wrapper.vm.form.platform).toBe('');
    expect(wrapper.find('[data-label="平台"]').attributes('data-required')).toBe('true');
    expect(wrapper.find('.platform-editor').exists()).toBe(false);
    await wrapper.find('[data-label="平台"] select').setValue('facebook');
    expect(wrapper.vm.form.platform).toBe('facebook');
    expect(wrapper.vm.form.contacts).toHaveLength(1);
    wrapper.unmount();
  });

  it('loads one protected aggregate and never fetches a second contacts version', async () => {
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    expect(api.direct).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ method: 'get', params: { include_form: 'true' } }));
    expect(wrapper.vm.form).not.toHaveProperty('platform_accounts');
    expect(wrapper.vm.editing.platform_accounts[1].platform).toBe('facebook');
    expect(wrapper.find('[data-label="平台"] select').element.disabled).toBe(true);
    expect(wrapper.vm.form.nickname_id).toBe('misschedly');
    expect(wrapper.vm.form.account_nickname).toBe('Demo Display | 品牌');
    expect(wrapper.vm.form).not.toHaveProperty('name');
    expect(wrapper.vm.form).not.toHaveProperty('handle');
    expect(api.fallback.mock.calls.some(([config]) => config.url.endsWith('/contacts/'))).toBe(false);
    wrapper.unmount();
  });

  it('omits legacy child accounts and saves independent sections in one CAS PATCH', async () => {
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    api.direct.mockClear();
    await wrapper.vm.save();
    expect(api.direct).toHaveBeenCalledTimes(1);
    const config = api.direct.mock.calls[0][0];
    expect(config.method).toBe('patch');
    expect(config.headers['If-Match']).toBe('"2026-10-10T01:00:00Z"');
    expect(config.data.contacts[0].value).toBe('demo@example.com');
    expect(config.data).not.toHaveProperty('platform_accounts');
    expect(config.data).not.toHaveProperty('handle');
    expect(config.data).not.toHaveProperty('nickname_id');
    expect(config.data).not.toHaveProperty('name');
    expect(config.data.profile).not.toHaveProperty('display_name');
    expect(config.data.profile.external_influencer_id).toBe('7488000000000000007');
    expect(wrapper.vm.editing.platform_accounts[1]).toMatchObject({ nickname_id: 'demo.page', follower_count: null, is_active: true });
    wrapper.unmount();
  });

  it('creates another full archive with source CAS and no inherited identity or contacts', async () => {
    const wrapper = await library();
    await wrapper.vm.openRelatedCreate({ id: 7 });
    expect(wrapper.vm.relatedSource.id).toBe(7);
    expect(wrapper.vm.editing).toBeNull();
    expect(wrapper.vm.form.nickname_id).toBe('');
    expect(wrapper.vm.form.account_nickname).toBe('');
    expect(wrapper.vm.form.profile.external_influencer_id).toBe('');
    expect(wrapper.vm.form.contacts[0].value).toBe('');
    expect(wrapper.vm.selectablePlatforms).toHaveProperty('tiktok', 'TikTok');
    Object.assign(wrapper.vm.form, { platform: 'facebook', nickname_id: 'new.page', account_nickname: 'New Page' });
    wrapper.vm.form.profile.market = 'PH';
    await wrapper.vm.save();
    const config = api.direct.mock.calls.at(-1)[0];
    expect(config.url).toMatch(/\/7\/related-archives\/$/);
    expect(config.method).toBe('post');
    expect(config.headers['If-Match']).toBe('"2026-10-10T01:00:00Z"');
    expect(config.data.archive).toMatchObject({ platform: 'facebook', nickname_id: 'new.page', account_nickname: 'New Page', profile: { market: 'PH', external_influencer_id: '' }, contacts: [] });
    expect(config.data.archive).not.toHaveProperty('code');
    expect(config.data.archive).not.toHaveProperty('platform_accounts');
    expect(record().platform).toBe('TikTok');
    wrapper.unmount();
  });

  it('blocks editing when any aggregate section is missing', async () => {
    api.direct.mockResolvedValue({ success: true, data: { ...record(), contacts: undefined } });
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    expect(wrapper.vm.editVisible).toBe(false);
    wrapper.unmount();
  });

  it.each(['profile', 'follower_count', 'category', 'nickname_id', 'account_nickname'])('rejects a missing %s instead of saving defaults over legacy data', async (field) => {
    const incomplete = record();
    delete incomplete[field];
    api.direct.mockResolvedValue({ success: true, data: incomplete });
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    expect(wrapper.vm.editVisible).toBe(false);
    expect(api.direct.mock.calls.every(([config]) => config.method === 'get')).toBe(true);
    wrapper.unmount();
  });

  it('rejects an unloaded profile field rather than clearing it', async () => {
    const incomplete = record();
    delete incomplete.profile.profile_notes;
    api.direct.mockResolvedValue({ success: true, data: incomplete });
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    expect(wrapper.vm.editVisible).toBe(false);
    wrapper.unmount();
  });

  it('allows a known absent legacy profile without inferring platform accounts', async () => {
    const legacy = { ...record(), nickname_id: '', handle: '', account_nickname: 'Legacy Stored Name', profile: null, platform_accounts: [] };
    api.direct.mockResolvedValue({ success: true, data: legacy });
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    expect(wrapper.vm.editVisible).toBe(true);
    expect(wrapper.vm.form).not.toHaveProperty('platform_accounts');
    expect(wrapper.vm.form.nickname_id).toBe('');
    expect(wrapper.vm.form.account_nickname).toBe('Legacy Stored Name');
    expect(wrapper.find('[data-label="昵称 ID"] input').element.disabled).toBe(true);
    wrapper.vm.form.profile.profile_notes = 'Metadata only';
    await wrapper.vm.save();
    const saved = api.direct.mock.calls.at(-1)[0].data;
    expect(saved.profile.profile_notes).toBe('Metadata only');
    expect(saved).not.toHaveProperty('platform_accounts');
    expect(saved).not.toHaveProperty('nickname_id');
    expect(saved).not.toHaveProperty('account_nickname');
    expect(saved).not.toHaveProperty('name');
    expect(saved.profile.profile_url).toBe('');
    expect(legacy.name).toBe('Legacy Stored Name');
    wrapper.unmount();
  });

  it('keeps the form open after a conflict without retrying or synthetic success', async () => {
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    api.direct.mockClear();
    api.direct.mockResolvedValue({ success: false, http_status: 409, message: 'Conflict' });
    await wrapper.vm.save();
    expect(api.direct).toHaveBeenCalledTimes(1);
    expect(wrapper.vm.editVisible).toBe(true);
    expect(wrapper.vm.saving).toBe(false);
    wrapper.unmount();
  });

  it('prevents read-only and blacklisted users from creating related archives', async () => {
    api.manage = false;
    const readonly = await library();
    await readonly.vm.openRelatedCreate({ id: 7 });
    expect(readonly.vm.relatedSource).toBeNull();
    expect(api.direct).not.toHaveBeenCalled();
    readonly.unmount();
    api.manage = true;
    api.direct.mockResolvedValue({ success: true, data: { ...record(), is_blacklisted: true } });
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    await wrapper.vm.openRelatedCreate({ id: 7 });
    expect(wrapper.vm.relatedSource).toBeNull();
    expect(api.direct.mock.calls.every(([config]) => config.method === 'get')).toBe(true);
    wrapper.unmount();
  });

  it('uses real API wrappers for create and edit, with no mutation fallback', async () => {
    await fetchInfluencerForm(7);
    await saveInfluencerForm(null, { platform_accounts: [] });
    await saveInfluencerForm(7, { platform_accounts: [] }, 'v1');
    expect(api.direct.mock.calls.map(([config]) => config.method)).toEqual(['get', 'post', 'patch']);
    expect(api.direct.mock.calls.every(([config]) => config.params.include_form === 'true')).toBe(true);
    expect(api.fallback).not.toHaveBeenCalled();
  });

  it('keeps one immutable primary username and changes only the display nickname alias', async () => {
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    const nicknameInput = wrapper.find('[data-label="昵称 ID"] input');
    expect(nicknameInput.element.value).toBe('misschedly');
    expect(nicknameInput.element.disabled).toBe(true);
    expect(wrapper.find('[data-platform="tiktok"] [data-label="昵称 ID"]').exists()).toBe(false);
    expect(wrapper.find('[data-platform="tiktok"] [data-label="账号昵称"]').exists()).toBe(false);
    await wrapper.find('[data-label="账号昵称"] input').setValue('New Decorated Display');
    expect(wrapper.vm.form.profile.display_name).toBe('Demo Display | 品牌');
    await wrapper.vm.save();
    const saved = api.direct.mock.calls.at(-1)[0].data;
    expect(saved.account_nickname).toBe('New Decorated Display');
    expect(saved).not.toHaveProperty('name');
    expect(saved).not.toHaveProperty('nickname_id');
    expect(saved.profile).not.toHaveProperty('display_name');
    expect(wrapper.vm.editing.name).toBe('Legacy Stored Name');
    wrapper.unmount();
  });

  it('marks matching historical values for review without inventing a nickname or rewriting identity', async () => {
    const legacy = record();
    legacy.account_nickname = legacy.nickname_id;
    legacy.profile.display_name = legacy.nickname_id;
    api.direct.mockResolvedValue({ success: true, data: legacy });
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    expect(wrapper.vm.sameNicknameFields(wrapper.vm.form)).toBe(true);
    expect(wrapper.vm.form.account_nickname).toBe('misschedly');
    expect(wrapper.vm.accountNickname({ name: 'Compatibility name', profile: { display_name: 'Ignored raw field' } })).toBe('未填写');
    await wrapper.find('[data-label="账号昵称"] input').setValue('Miss CHE DIY');
    expect(wrapper.vm.sameNicknameFields(wrapper.vm.form)).toBe(false);
    await wrapper.vm.save();
    const saved = api.direct.mock.calls.at(-1)[0].data;
    expect(saved.account_nickname).toBe('Miss CHE DIY');
    expect(saved).not.toHaveProperty('nickname_id');
    expect(saved).not.toHaveProperty('name');
    expect(saved.profile.external_influencer_id).toBe('7488000000000000007');
    expect(wrapper.vm.form.code).toBe('DEMO7');
    wrapper.unmount();
  });

  it('keeps an absent nickname blank and does not submit the username as its replacement', async () => {
    const legacy = record();
    legacy.account_nickname = '';
    legacy.profile.display_name = '';
    legacy.name = legacy.nickname_id;
    api.direct.mockResolvedValue({ success: true, data: legacy });
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    expect(wrapper.vm.form.account_nickname).toBe('');
    expect(wrapper.vm.accountNickname(legacy)).toBe('未填写');
    expect(wrapper.vm.sameNicknameFields(wrapper.vm.form)).toBe(false);
    await wrapper.vm.save();
    const saved = api.direct.mock.calls.at(-1)[0].data;
    expect(saved).not.toHaveProperty('account_nickname');
    expect(saved).not.toHaveProperty('nickname_id');
    expect(saved).not.toHaveProperty('name');
    wrapper.unmount();
  });

  it('creates with username aliases without inferring a URL or changing numeric IDs', async () => {
    const wrapper = await library();
    await wrapper.vm.openCreate();
    wrapper.vm.form.platform = 'tiktok';
    wrapper.vm.form.nickname_id = 'misschedly';
    wrapper.vm.form.account_nickname = 'Decorated Display';
    wrapper.vm.form.profile.external_influencer_id = '7488000000000000007';
    await flushPromises();
    expect(wrapper.vm.form.profile.profile_url).toBe('');
    await wrapper.vm.save();
    const config = api.direct.mock.calls.at(-1)[0];
    expect(config.method).toBe('post');
    expect(config.data).toMatchObject({ nickname_id: 'misschedly', account_nickname: 'Decorated Display' });
    expect(config.data).not.toHaveProperty('name');
    expect(config.data).not.toHaveProperty('handle');
    expect(config.data.profile).not.toHaveProperty('display_name');
    expect(config.data.profile.external_influencer_id).toBe('7488000000000000007');
    expect(config.data).not.toHaveProperty('platform_accounts');
    expect(config.data).not.toHaveProperty('code');
    wrapper.unmount();
  });

  it.each([false, true])('does not materialize a legacy-name fallback unless the display nickname is edited (clear=%s)', async (clear) => {
    const legacy = record();
    legacy.profile.display_name = '';
    legacy.account_nickname = legacy.name;
    api.direct.mockResolvedValue({ success: true, data: legacy });
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    wrapper.vm.form.category = 'Updated metadata';
    if (clear) await wrapper.find('[data-label="账号昵称"] input').setValue('');
    await wrapper.vm.save();
    const saved = api.direct.mock.calls.at(-1)[0].data;
    expect(saved.category).toBe('Updated metadata');
    if (clear) expect(saved.account_nickname).toBe('');
    else expect(saved).not.toHaveProperty('account_nickname');
    expect(saved).not.toHaveProperty('name');
    expect(saved.profile).not.toHaveProperty('display_name');
    expect(saved.profile.external_influencer_id).toBe('7488000000000000007');
    expect(legacy.profile.display_name).toBe('');
    expect(legacy.name).toBe('Legacy Stored Name');
    wrapper.unmount();
  });

  it('allows a manual display-nickname-only create with an omitted empty username', async () => {
    const wrapper = await library();
    await wrapper.vm.openCreate();
    wrapper.vm.form.code = 'MANUAL';
    wrapper.vm.form.platform = 'instagram';
    wrapper.vm.form.account_nickname = 'Manual Display';
    wrapper.vm.form.nickname_id = '  ';
    await wrapper.vm.save();
    const config = api.direct.mock.calls.at(-1)[0];
    expect(config.method).toBe('post');
    expect(config.data.account_nickname).toBe('Manual Display');
    expect(config.data).not.toHaveProperty('platform_accounts');
    expect(config.data).not.toHaveProperty('nickname_id');
    expect(config.data).not.toHaveProperty('name');
    expect(config.data.profile.profile_url).toBe('');
    wrapper.unmount();
  });

  it.each(['nickname_id', 'account_nickname'])('leaves unloaded legacy child %s untouched because this form omits the entire section', async (field) => {
    const incomplete = record();
    delete incomplete.platform_accounts[1][field];
    api.direct.mockResolvedValue({ success: true, data: incomplete });
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    expect(wrapper.vm.editVisible).toBe(true);
    await wrapper.vm.save();
    expect(api.direct.mock.calls.at(-1)[0].data).not.toHaveProperty('platform_accounts');
    wrapper.unmount();
  });

  it('requires an explicit platform before standalone creation', async () => {
    const wrapper = await library();
    await wrapper.vm.openCreate();
    Object.assign(wrapper.vm.form, { code: 'NEW', nickname_id: 'new.creator' });
    await wrapper.vm.save();
    expect(api.direct).not.toHaveBeenCalled();
    expect(wrapper.vm.editVisible).toBe(true);
    wrapper.unmount();
  });

  it.each(['tiktok', 'facebook'])('creates an independent same-platform %s account using source CAS', async (platform) => {
    const source = { ...record(), platform };
    api.direct.mockResolvedValue({ success: true, data: source });
    const wrapper = await library();
    await wrapper.vm.openRelatedCreate({ id: 7 });
    api.direct.mockClear();
    expect(wrapper.vm.selectablePlatforms).toHaveProperty(platform);
    Object.assign(wrapper.vm.form, { platform, nickname_id: 'new.creator' });
    await wrapper.vm.save();
    expect(api.direct).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      method: 'post', url: '/api/internal/influencers/7/related-archives/',
      headers: { 'If-Match': '"2026-10-10T01:00:00Z"' },
      data: { archive: expect.objectContaining({ platform, nickname_id: 'new.creator' }) },
    }));
    wrapper.unmount();
  });

  it('removes the four requested channel choices but keeps the remaining choices', async () => {
    const wrapper = await library();
    await wrapper.vm.openCreate();
    const options = wrapper.findAll('.contact-row option').map((option) => option.attributes('value'));
    expect(options).toEqual(['email', 'phone', 'whatsapp', 'wechat', 'line', 'viber', 'other']);
    wrapper.unmount();
  });

  it('preserves a saved historical contact after its channel leaves the choices', async () => {
    api.direct.mockResolvedValue({ success: true, data: { ...record(), contacts: [{ channel: 'telegram', value: 'old.contact', label: '', is_primary: true }] } });
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    expect(wrapper.find('.contact-row option[value="telegram"]').text()).toContain('已保存');
    await wrapper.vm.save();
    expect(api.direct.mock.calls.at(-1)[0].data.contacts[0]).toMatchObject({ channel: 'telegram', value: 'old.contact' });
    wrapper.unmount();
  });

  it('uses the same solid primary treatment as the outer new-archive button', async () => {
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    const related = wrapper.find('.archive-navigation .archive-create-button');
    const standalone = wrapper.findAll('.toolbar button').find((button) => button.text() === '新建达人');
    expect(related.text()).toBe('新建关联档案');
    expect(related.attributes('type')).toBe(standalone.attributes('type'));
    expect(related.attributes('plain')).toBeUndefined();
    wrapper.unmount();
  });

  it('uses dedicated real related APIs and preserves the source version verbatim', async () => {
    await fetchRelatedInfluencerArchives(7);
    await createRelatedInfluencerArchive(7, { code: 'RELATED', platform: 'facebook' }, 'source-v1');
    expect(api.direct.mock.calls[0][0]).toMatchObject({ method: 'get', url: '/api/internal/influencers/7/related-archives/' });
    expect(api.direct.mock.calls[1][0]).toMatchObject({ method: 'post', data: { archive: { code: 'RELATED', platform: 'facebook' } }, headers: { 'If-Match': '"source-v1"' } });
    expect(api.fallback).not.toHaveBeenCalled();
  });

  it('opens a sibling by its archive ID rather than replacing the source platform', async () => {
    const original = record();
    const sibling = { ...record(), id: 9, code: 'FB9', platform: 'facebook', nickname_id: 'other.creator', account_nickname: 'Other Creator', platform_accounts: [] };
    const related = [original, sibling].map(({ id, code, platform, nickname_id, account_nickname, updated_at }) => ({ id, code, platform, nickname_id, account_nickname, updated_at }));
    original.related_archives = related; sibling.related_archives = related;
    api.direct.mockImplementation((config) => Promise.resolve({ success: true, data: config.url.includes('/9/') ? sibling : original }));
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    await wrapper.vm.openEdit({ id: 9 });
    expect(wrapper.vm.editing.id).toBe(9);
    expect(wrapper.vm.form.platform).toBe('facebook');
    expect(wrapper.vm.form.nickname_id).toBe('other.creator');
    expect(original.platform).toBe('TikTok');
    expect(api.direct.mock.calls.every(([config]) => config.method === 'get')).toBe(true);
    wrapper.unmount();
  });

  it('keeps unsaved source changes when the user cancels navigation', async () => {
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    wrapper.vm.form.category = 'Unsaved category';
    api.confirm.mockRejectedValue('cancel'); api.direct.mockClear();
    await wrapper.vm.openRelatedCreate({ id: 7 });
    expect(api.confirm).toHaveBeenCalledTimes(1);
    expect(api.direct).not.toHaveBeenCalled();
    expect(wrapper.vm.form.category).toBe('Unsaved category');
    expect(wrapper.vm.editing.id).toBe(7);
    wrapper.unmount();
  });

  it('rejects missing related summaries instead of guessing the group', async () => {
    api.direct.mockResolvedValue({ success: true, data: { ...record(), related_archives: undefined } });
    const wrapper = await library();
    await wrapper.vm.openRelatedCreate({ id: 7 });
    expect(wrapper.vm.relatedSource).toBeNull();
    expect(wrapper.vm.editVisible).toBe(false);
    wrapper.unmount();
  });

  it('retains source CAS and draft after a lost response and blocks duplicate creation', async () => {
    const wrapper = await library();
    await wrapper.vm.openRelatedCreate({ id: 7 });
    Object.assign(wrapper.vm.form, { platform: 'facebook', nickname_id: 'new.creator' });
    api.direct.mockClear(); api.direct.mockRejectedValue(new Error('Response lost'));
    await wrapper.vm.save();
    expect(api.direct).toHaveBeenCalledTimes(1);
    expect(wrapper.vm.editVisible).toBe(true);
    expect(wrapper.vm.form.nickname_id).toBe('new.creator');
    expect(wrapper.vm.form.code).toBe('');
    expect(wrapper.vm.createOutcomeUncertain).toBe(true);
    expect(wrapper.vm.relatedSource.updated_at).toBe('2026-10-10T01:00:00Z');
    expect(wrapper.vm.saving).toBe(false);
    await wrapper.vm.save();
    expect(api.direct).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it('displays an automatically generated code as read-only and never sends a code mutation', async () => {
    const wrapper = await library();
    await wrapper.vm.openCreate();
    const field = wrapper.find('[data-label="系统档案编码"]');
    expect(field.attributes('data-required')).not.toBe('true');
    expect(field.find('input').element.disabled).toBe(true);
    expect(field.find('input').attributes('placeholder')).toBe('保存时由系统自动生成');
    await wrapper.vm.openEdit({ id: 7 });
    expect(field.find('input').element.value).toBe('DEMO7');
    wrapper.vm.form.code = 'IGNORED';
    api.direct.mockClear();
    await wrapper.vm.save();
    expect(api.direct.mock.calls[0][0].data).not.toHaveProperty('code');
    expect(wrapper.vm.editing.code).toBe('DEMO7');
    wrapper.unmount();
  });

  it.each(['', '123', '这是主页备注', 'facebook.com/example', 'https://www.facebook.com/example', 'javascript:alert(1)', '<script>alert(1)</script>'])('accepts homepage information as text without URL validation (%s)', async (url) => {
    const wrapper = await library();
    await wrapper.vm.openCreate();
    Object.assign(wrapper.vm.form, { platform: 'facebook', nickname_id: 'new.creator' });
    wrapper.vm.form.profile.profile_url = url;
    await wrapper.vm.save();
    expect(api.direct).toHaveBeenCalledTimes(1);
    expect(api.direct.mock.calls[0][0].data.profile.profile_url).toBe(url);
    expect(ElMessage.warning).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it.each(['123', 'facebook.com/example', 'https:example.com', 'https://', 'javascript:alert(1)', 'ftp://example.com'])('saves arbitrary homepage information for a related archive (%s)', async (url) => {
    const wrapper = await library();
    await wrapper.vm.openRelatedCreate({ id: 7 });
    Object.assign(wrapper.vm.form, { platform: 'facebook', nickname_id: 'new.creator' });
    wrapper.vm.form.profile.profile_url = url;
    api.direct.mockClear();
    await wrapper.vm.save();
    expect(api.direct).toHaveBeenCalledTimes(1);
    expect(api.direct.mock.calls[0][0].data.archive.profile.profile_url).toBe(url);
    expect(wrapper.find('[data-label="主页信息"]').attributes('data-error')).toBeUndefined();
    expect(ElMessage.warning).not.toHaveBeenCalled();
    expect(wrapper.vm.createOutcomeUncertain).toBe(false);
    expect(wrapper.vm.editVisible).toBe(false);
    wrapper.unmount();
  });

  it('does not label a definite server validation rejection as an uncertain creation', async () => {
    const wrapper = await library();
    await wrapper.vm.openRelatedCreate({ id: 7 });
    Object.assign(wrapper.vm.form, { platform: 'facebook', nickname_id: 'new.creator' });
    api.direct.mockClear();
    api.direct.mockResolvedValue({ success: false, http_status: 400, message: 'Field validation failed' });
    await wrapper.vm.save();
    expect(wrapper.vm.createOutcomeUncertain).toBe(false);
    expect(ElMessage.error.mock.calls.at(-1)[0]).not.toContain('不要重复创建');
    expect(ElMessage.error.mock.calls.at(-1)[0]).not.toContain('保留新档案编码');
    wrapper.unmount();
  });

  it('blocks standalone repeat creation after an unconfirmed server error and resets only with a new form', async () => {
    const wrapper = await library();
    await wrapper.vm.openCreate();
    Object.assign(wrapper.vm.form, { platform: 'facebook', account_nickname: 'Independent nickname' });
    api.direct.mockResolvedValue({ success: false, http_status: 502, message: 'Bad gateway' });
    await wrapper.vm.save();
    await wrapper.vm.save();
    expect(api.direct).toHaveBeenCalledTimes(1);
    expect(wrapper.vm.createOutcomeUncertain).toBe(true);
    expect(wrapper.vm.form.account_nickname).toBe('Independent nickname');
    wrapper.vm.resetForm();
    expect(wrapper.vm.createOutcomeUncertain).toBe(false);
    wrapper.unmount();
  });

  it('discards a stale form response when another archive was opened later', async () => {
    let resolveFirst;
    const first = new Promise((resolve) => { resolveFirst = resolve; });
    const sibling = { ...record(), id: 9, code: 'FB9', platform: 'facebook', nickname_id: 'new.page', related_archives: [{ id: 9, code: 'FB9', platform: 'facebook', nickname_id: 'new.page', account_nickname: 'New Page', updated_at: '2026-10-10T01:00:00Z' }] };
    api.direct.mockImplementation((config) => config.url.includes('/7/') ? first : Promise.resolve({ success: true, data: sibling }));
    const wrapper = await library();
    const firstOpen = wrapper.vm.openEdit({ id: 7 });
    await flushPromises();
    await wrapper.vm.openEdit({ id: 9 });
    resolveFirst({ success: true, data: record() });
    await firstOpen;
    expect(wrapper.vm.editing.id).toBe(9);
    expect(wrapper.vm.form.code).toBe('FB9');
    expect(wrapper.vm.form.platform).toBe('facebook');
    wrapper.unmount();
  });

  it('sends only one related create while the previous save is pending', async () => {
    let resolveSave;
    const wrapper = await library();
    await wrapper.vm.openRelatedCreate({ id: 7 });
    Object.assign(wrapper.vm.form, { code: 'NEWFB', platform: 'facebook', nickname_id: 'new.page' });
    api.direct.mockClear();
    api.direct.mockImplementation(() => new Promise((resolve) => { resolveSave = resolve; }));
    const saving = wrapper.vm.save();
    await wrapper.vm.save();
    expect(api.direct).toHaveBeenCalledTimes(1);
    resolveSave({ success: false, http_status: 409, message: 'Conflict' });
    await saving;
    expect(wrapper.vm.editVisible).toBe(true);
    expect(wrapper.vm.relatedSource.updated_at).toBe('2026-10-10T01:00:00Z');
    wrapper.unmount();
  });

  it.each(['failed', 'incomplete'])('does not replace an editing archive with a truthy message handler after a %s GET', async (failure) => {
    const wrapper = await library();
    await wrapper.vm.openEdit({ id: 7 });
    wrapper.vm.form.category = 'Unsaved category';
    api.direct.mockClear();
    api.direct.mockResolvedValue(failure === 'failed' ? { success: false, message: 'Load failed' } : { success: true, data: { ...record(), contacts: undefined } });
    await wrapper.vm.openEdit({ id: 7 });
    expect(wrapper.vm.editing.id).toBe(7);
    expect(wrapper.vm.form.category).toBe('Unsaved category');
    expect(wrapper.vm.relatedSource).toBeNull();
    expect(wrapper.vm.editLoading).toBe(false);
    expect(api.direct.mock.calls.every(([config]) => config.method === 'get')).toBe(true);
    wrapper.unmount();
  });

  it.each(['failed', 'incomplete'])('preserves a new related draft and its valid source after a %s source GET', async (failure) => {
    const wrapper = await library();
    await wrapper.vm.openRelatedCreate({ id: 7 });
    Object.assign(wrapper.vm.form, { code: 'PENDING-FB', platform: 'facebook', nickname_id: 'pending.page' });
    api.direct.mockClear();
    api.direct.mockResolvedValue(failure === 'failed' ? { success: false, message: 'Load failed' } : { success: true, data: { ...record(), contacts: undefined } });
    await wrapper.vm.openRelatedCreate({ id: 7 });
    expect(wrapper.vm.relatedSource.id).toBe(7);
    expect(wrapper.vm.form.code).toBe('PENDING-FB');
    expect(wrapper.vm.form.nickname_id).toBe('pending.page');
    expect(wrapper.vm.form.platform).toBe('facebook');
    expect(wrapper.vm.editing).toBeNull();
    expect(wrapper.vm.editLoading).toBe(false);
    expect(api.direct.mock.calls.every(([config]) => config.method === 'get')).toBe(true);
    wrapper.unmount();
  });

  it('preserves default redaction and requests nickname purpose only when explicitly supplied', async () => {
    await fetchInfluencers();
    await fetchInfluencer(7);
    expect(api.fallback.mock.calls.map(([config]) => config.params)).toEqual([{}, {}]);
    api.fallback.mockClear();
    await fetchInfluencers({ include_nickname_id: 'true', page: 2, platform: 'facebook' });
    await fetchInfluencer(7, { include_nickname_id: 'true', include_relations: 'false' });
    expect(api.fallback.mock.calls[0][0].params).toEqual({ include_nickname_id: 'true', page: 2, platform: 'facebook' });
    expect(api.fallback.mock.calls[1][0].params).toEqual({ include_nickname_id: 'true', include_relations: 'false' });
  });

  it.each([undefined, 'false', 'true'])('keeps list and detail mock identifiers gated for purpose %s', async (purpose) => {
    const params = purpose === undefined ? {} : { include_nickname_id: purpose };
    api.fallback.mockImplementation((_config, fallback) => fallback());
    const list = await fetchInfluencers(params);
    const detail = await fetchInfluencer(7, params);
    expect(list.data.results[0]).toEqual(influencerMocks.list(params).data.results[0]);
    expect(detail.data.id).toBe(7);
    for (const row of [list.data.results[0], detail.data]) {
      expect(row).not.toHaveProperty('handle');
      if (purpose === 'true') {
        expect(row.nickname_id).toBe('creator-demo');
        expect(row.account_nickname).toBe('示例账号昵称');
      } else {
        expect(row).not.toHaveProperty('nickname_id');
        expect(row).not.toHaveProperty('account_nickname');
      }
    }
  });
});
