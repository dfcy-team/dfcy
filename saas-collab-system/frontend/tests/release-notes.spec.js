import { afterEach, describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { ElButton, ElDialog } from 'element-plus';
import { nextTick } from 'vue';
import ReleaseNotes from '../src/components/ReleaseNotes.vue';
import releases from '../src/data/releaseNotes.json';

let wrapper;
afterEach(() => {
  wrapper?.unmount();
  document.body.innerHTML = '';
});

describe('更新记录', () => {
  it('点击入口才展示记录，关闭后可重新打开', async () => {
    wrapper = mount(ReleaseNotes, {
      attachTo: document.body,
      global: { components: { ElButton, ElDialog } }
    });
    expect(wrapper.findComponent(ElDialog).props('modelValue')).toBe(false);
    await wrapper.get('button').trigger('click');
    await nextTick();
    const dialog = document.body.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog.textContent).toContain(`V${releases[0].version}`);
    expect(dialog.textContent).toContain(releases[0].date);
    for (const change of releases[0].changes) expect(dialog.textContent).toContain(change);
    const close = [...dialog.querySelectorAll('button')].find(button => button.textContent.trim() === '关闭');
    close.click();
    await nextTick();
    expect(wrapper.findComponent(ElDialog).props('modelValue')).toBe(false);
    await wrapper.get('button').trigger('click');
    expect(wrapper.findComponent(ElDialog).props('modelValue')).toBe(true);
  });

  it('发布条目版本唯一、日期有效且有非空说明', () => {
    expect(new Set(releases.map(release => release.version)).size).toBe(releases.length);
    for (const release of releases) {
      expect(release.version).toMatch(/^\d+\.\d+\.\d+$/);
      expect(release.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(new Date(release.date).toISOString().slice(0, 10)).toBe(release.date);
      expect(release.changes.length).toBeGreaterThan(0);
      for (const change of release.changes) expect(change.trim().length).toBeGreaterThan(0);
    }
  });
});
