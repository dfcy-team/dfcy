import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import Drawer from '../src/components/FeishuReminderDrawer.vue';
import * as api from '../src/api/feishuReminders';

vi.mock('../src/api/feishuReminders', () => ({ reminderOptions: vi.fn(), previewReminder: vi.fn(), sendReminder: vi.fn(), reminderHistory: vi.fn(), reminderStatus: vi.fn(), retryReminder: vi.fn() }));
vi.mock('element-plus', async importOriginal => ({ ...(await importOriginal()), ElMessage: { success: vi.fn() } }));
const ok = data => ({ success: true, data });
const passthrough = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
const button = defineComponent({ props: ['disabled'], emits: ['click'], setup: (p, { slots, emit }) => () => h('button', { disabled: p.disabled, onClick: () => emit('click') }, slots.default?.()) });
const stubs = Object.fromEntries(['ElDrawer', 'ElTabs', 'ElTabPane', 'ElAlert', 'ElForm', 'ElFormItem', 'ElRadioGroup', 'ElRadio', 'ElInput', 'ElSelect', 'ElOption', 'ElDatePicker'].map(name => [name, passthrough]));
stubs.ElButton = button;

async function ready() {
  const wrapper = mount(Drawer, { props: { modelValue: false, source: 'orders', recordIds: [7], filters: {} }, global: { stubs } });
  await wrapper.setProps({ modelValue: true });
  wrapper.vm.form.recipient_user_ids = [2];
  await flushPromises();
  return wrapper;
}
const click = async (wrapper, text) => { await wrapper.findAll('button').find(b => b.text().includes(text)).trigger('click'); await flushPromises(); };

beforeEach(() => {
  vi.resetAllMocks();
  api.reminderOptions.mockResolvedValue(ok({ recipients: [{ id: 2, name: '成员', bound: true }] }));
  api.previewReminder.mockResolvedValue(ok({ can_send: true, connection_ready: true, preview_token: 'signed', recipients: [{ user_id: 2, name: '成员', eligible: true, summary: '共同可见 1 条记录' }] }));
  api.sendReminder.mockResolvedValue(ok({ id: 10 }));
  api.reminderHistory.mockResolvedValue(ok({ items: [{ id: 10, title: '提醒' }] }));
  api.reminderStatus.mockResolvedValue(ok({ id: 10, title: '提醒', items: [{ operation_id: 3, recipient: '成员', status: 'pending', attempts: 0 }] }));
});

describe('飞书手动提醒交互', () => {
  it('预览后才能发送，修改内容会清除旧预览', async () => {
    const wrapper = await ready();
    expect(wrapper.text()).not.toContain('确认发送给');
    await click(wrapper, '生成发送预览');
    expect(wrapper.text()).toContain('共同可见 1 条记录');
    wrapper.vm.form.message = '新留言';
    await flushPromises();
    expect(wrapper.text()).not.toContain('确认发送给');
    expect(api.sendReminder).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('发送超时后复用同一编号，成功后显示真实队列状态', async () => {
    const wrapper = await ready();
    await click(wrapper, '生成发送预览');
    api.sendReminder.mockRejectedValueOnce(new Error('网络超时'));
    await click(wrapper, '确认发送给');
    expect(wrapper.vm.error).toBe('网络超时');
    await click(wrapper, '确认发送给');
    const calls = api.sendReminder.mock.calls.map(([data]) => data);
    expect(calls).toHaveLength(2);
    expect(calls[0].idempotency_key).toBe(calls[1].idempotency_key);
    expect(calls[0].preview_token).toBe('signed');
    expect(calls[0].record_ids).toEqual([7]);
    expect(wrapper.text()).toContain('待发送');
    wrapper.unmount();
  });

  it('提醒链接页面只能重选具体记录，不能扩大成普通日期范围', async () => {
    const wrapper = await ready();
    await wrapper.setProps({ modelValue: false, allowFiltered: false, recordIds: [] });
    await wrapper.setProps({ modelValue: true });
    expect(wrapper.vm.form.mode).toBe('selected');
    expect(wrapper.findAll('button').find(b => b.text().includes('生成发送预览')).attributes('disabled')).toBeDefined();
    wrapper.unmount();
  });

  it('过期失败投递显示停止重试原因', async () => {
    const wrapper = await ready();
    api.reminderStatus.mockResolvedValueOnce(ok({ id: 10, title: '提醒', items: [{ operation_id: 3, recipient: '成员', status: 'failed', attempts: 1, can_retry: false, retry_blocked_reason: '投递已超过45分钟安全窗口，请先核查飞书送达记录，不能继续重试。' }] }));
    wrapper.vm.tab = 'history';
    await flushPromises();
    await click(wrapper, '提醒');
    expect(wrapper.text()).toContain('45分钟安全窗口');
    expect(wrapper.findAll('button').some(button => button.text() === '重试')).toBe(false);
    wrapper.unmount();
  });

  it('请求中的预览过时后不会重新启用发送', async () => {
    const wrapper = await ready();
    let finish;
    api.previewReminder.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    await wrapper.findAll('button').find(b => b.text().includes('生成发送预览')).trigger('click');
    wrapper.vm.form.title = '内容已修改';
    await flushPromises();
    finish(ok({ can_send: true, connection_ready: true, preview_token: 'stale', recipients: [] }));
    await flushPromises();
    expect(wrapper.text()).not.toContain('确认发送给');
    wrapper.unmount();
  });
});
