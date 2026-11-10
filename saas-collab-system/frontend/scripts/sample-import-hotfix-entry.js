// Temporary additive entry for servers that still contain unreleased page fixes.
// The normal release uses SampleFulfillmentList's native component integration.
import { createApp, h, ref } from 'vue';
import SampleImportDialog from '../src/views/influencers/SampleImportDialog.vue';

const marker = 'sample-import-hotfix-20261110';
if (!document.getElementById(marker)) {
  const mount = document.createElement('div');
  mount.id = marker;
  document.body.appendChild(mount);
  const visible = ref(false);
  const canManage = ref(false);
  createApp({
    setup: () => () => h(SampleImportDialog, {
      modelValue: visible.value,
      canManage: canManage.value,
      'onUpdate:modelValue': value => { visible.value = value; },
      onImported: () => {
        const query = [...document.querySelectorAll('.sample-page .toolbar button')]
          .find(button => button.textContent.trim() === '查询');
        query?.click();
      }
    })
  }).mount(mount);

  function attachButton() {
    const toolbar = document.querySelector('.sample-page .toolbar');
    if (!toolbar) {
      canManage.value = false;
      visible.value = false;
      return;
    }
    const buttons = [...toolbar.querySelectorAll('button')];
    const existing = buttons.find(button => button.textContent.trim() === '导入送样');
    const create = buttons.find(button => button.textContent.trim() === '新增送样');
    canManage.value = !!create && !create.disabled && !create.classList.contains('is-disabled');
    if (existing && existing.dataset.sampleImportHotfix !== marker) return;
    if (!create || create.disabled || create.classList.contains('is-disabled')) {
      existing?.remove();
      return;
    }
    if (existing) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'el-button';
    button.dataset.sampleImportHotfix = marker;
    button.textContent = '导入送样';
    button.addEventListener('click', () => { visible.value = true; });
    create.after(button);
  }

  let scheduled = false;
  const observer = new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      attachButton();
    });
  });
  observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled'] });
  attachButton();
  window.addEventListener('pagehide', () => observer.disconnect(), { once: true });
}
