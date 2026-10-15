<template>
  <el-dialog :model-value="Boolean(supplier)" :title="`${supplier?.name || '供应商'}联系人账号`" width="min(900px, 96vw)" @close="emit('close')">
    <div class="contacts" v-loading="loading">
      <div class="portal-address">
        <span>供应商登录地址：<code>{{ loginUrl }}</code></span>
        <el-button size="small" @click="copyLoginUrl">复制地址</el-button>
      </div>
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="feedback" />

      <el-form v-if="canManage" :model="createForm" label-position="top" class="create-form" @submit.prevent="createContact">
        <el-form-item label="登录用户名" required>
          <el-input v-model="createForm.username" maxlength="100" autocomplete="off" placeholder="3–100 位英文、数字或 . _ @ + -" />
        </el-form-item>
        <el-form-item label="联系人姓名" required>
          <el-input v-model="createForm.full_name" maxlength="100" autocomplete="off" />
        </el-form-item>
        <el-form-item label="初始密码" required>
          <el-input v-model="createForm.password" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-button type="primary" :loading="saving" :disabled="saving" @click="createContact">创建联系人账号</el-button>
      </el-form>

      <div class="table-wrap">
        <el-table :data="contacts" empty-text="暂无联系人账号">
          <el-table-column prop="username" label="登录用户名" min-width="180" />
          <el-table-column prop="full_name" label="联系人" min-width="150" />
          <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag></template></el-table-column>
          <el-table-column label="操作" min-width="225">
            <template #default="{ row }">
              <el-button link type="primary" :disabled="!canManage || saving" @click="toggleContact(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
              <el-button link type="primary" :disabled="!canManage || saving" @click="openPasswordReset(row)">重置密码</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <el-pagination v-if="count > pageSize" v-model:current-page="page" :page-size="pageSize" :total="count" layout="prev, pager, next, total" @current-change="loadContacts" />
      <p class="handoff-note">账号和初始密码请由采购人员自行联系供应商传达；系统不会自动发送凭证。</p>
    </div>

    <el-dialog v-model="resetVisible" title="重置联系人密码" width="min(440px, 94vw)" append-to-body>
      <p>为 {{ resetTarget?.username }} 设置新密码。密码只会提交一次，不会回显。</p>
      <el-input v-model="resetPassword" type="password" show-password autocomplete="new-password" placeholder="输入新密码" @keyup.enter="resetContactPassword" />
      <template #footer><el-button @click="closePasswordReset">取消</el-button><el-button type="primary" :loading="saving" :disabled="saving" @click="resetContactPassword">保存新密码</el-button></template>
    </el-dialog>
    <template #footer><el-button @click="emit('close')">关闭</el-button></template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { requestApi, formatApiError } from '../../api/request';
import { createIdempotencyKey } from '../../api/supplyChainV2';

const props = defineProps({ supplier: { type: Object, default: null }, canManage: { type: Boolean, default: false } });
const emit = defineEmits(['close']);
const pageSize = 50;
const contacts = ref([]), count = ref(0), page = ref(1), loading = ref(false), saving = ref(false), error = ref('');
const resetVisible = ref(false), resetTarget = ref(null), resetPassword = ref('');
const createForm = reactive({ username: '', full_name: '', password: '' });
const pendingActions = new Map();
const base = computed(() => `/api/internal/supply-chain/v2/suppliers/${encodeURIComponent(props.supplier?.id || '')}/contacts/`);
const loginUrl = computed(() => `${globalThis.location?.origin || ''}/supplier/login`);

function failure(response) { return formatApiError(response) || '请求失败，请重试。'; }
function clearCreateForm() { createForm.username = ''; createForm.full_name = ''; createForm.password = ''; }
function getPayload(slot, payload) {
  const fingerprint = JSON.stringify(payload);
  let pending = pendingActions.get(slot);
  if (!pending || pending.fingerprint !== fingerprint) {
    pending = { fingerprint, key: createIdempotencyKey() };
    pendingActions.set(slot, pending);
  }
  return pending;
}
async function mutate(slot, payload, method, url) {
  if (!props.canManage || saving.value) return false;
  const pending = getPayload(slot, payload);
  saving.value = true;
  error.value = '';
  try {
    const response = await requestApi({ method, url, data: payload, headers: { 'Idempotency-Key': pending.key } });
    if (!response?.success) {
      const uncertain = !response?.http_status || response.http_status >= 500;
      if (!uncertain) pendingActions.delete(slot);
      error.value = `${failure(response)}${uncertain ? ' 操作结果暂未确认；使用相同内容重试会复用请求标识。' : ''}`;
      return false;
    }
    pendingActions.delete(slot);
    return true;
  } catch (exception) {
    error.value = `${exception?.message || '网络异常'}。操作结果暂未确认；使用相同内容重试会复用请求标识。`;
    return false;
  } finally { saving.value = false; }
}
async function loadContacts() {
  if (!props.supplier?.id) return;
  loading.value = true;
  error.value = '';
  const response = await requestApi({ method: 'get', url: base.value, params: { limit: pageSize, offset: (page.value - 1) * pageSize } });
  loading.value = false;
  if (!response?.success) { error.value = failure(response); return; }
  contacts.value = Array.isArray(response.data) ? response.data : [];
  count.value = Number(response.count) || 0;
}
async function createContact() {
  const username = createForm.username.trim();
  const fullName = createForm.full_name.trim();
  const password = createForm.password;
  if (!/^[A-Za-z0-9_.@+-]{3,100}$/.test(username)) { error.value = '用户名需为 3–100 位英文、数字或 . _ @ + -。'; return; }
  if (!fullName || !password) { error.value = '请填写联系人姓名和初始密码。'; return; }
  const payload = { username, full_name: fullName, password, is_active: true };
  if (await mutate('create', payload, 'post', base.value)) {
    clearCreateForm();
    page.value = 1;
    await loadContacts();
    ElMessage.success('联系人账号已创建。请由采购人员联系供应商传达账号和初始密码。');
  }
}
async function toggleContact(contact) {
  const payload = { full_name: contact.full_name, is_active: !contact.is_active, expected_version: contact.version };
  if (await mutate(`contact:${contact.id}:state`, payload, 'patch', `${base.value}${encodeURIComponent(contact.id)}/`)) {
    ElMessage.success(payload.is_active ? '联系人账号已启用。' : '联系人账号已停用。');
    await loadContacts();
  }
}
function openPasswordReset(contact) { resetTarget.value = contact; resetPassword.value = ''; resetVisible.value = true; error.value = ''; }
function closePasswordReset() { resetVisible.value = false; resetTarget.value = null; resetPassword.value = ''; }
async function resetContactPassword() {
  if (!resetTarget.value || !resetPassword.value) { error.value = '请输入新密码。'; return; }
  const contact = resetTarget.value;
  const payload = { full_name: contact.full_name, is_active: contact.is_active, expected_version: contact.version, password: resetPassword.value };
  if (await mutate(`contact:${contact.id}:password`, payload, 'patch', `${base.value}${encodeURIComponent(contact.id)}/`)) {
    closePasswordReset();
    ElMessage.success('联系人密码已重置。请由采购人员联系供应商传达新密码。');
    await loadContacts();
  }
}
async function copyLoginUrl() {
  try { await globalThis.navigator.clipboard.writeText(loginUrl.value); ElMessage.success('登录地址已复制。'); }
  catch (_error) { error.value = '无法访问剪贴板，请手动复制登录地址。'; }
}
watch(() => props.supplier?.id, (id) => { contacts.value = []; count.value = 0; page.value = 1; clearCreateForm(); closePasswordReset(); if (id) loadContacts(); }, { immediate: true });
</script>

<style scoped>
.contacts { min-width: 0; }
.portal-address { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; border-radius: 6px; background: #f5f7fa; color: #475467; overflow-wrap: anywhere; }
.portal-address code { color: #344054; }
.feedback { margin-top: 14px; }
.create-form { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0 14px; align-items: end; margin-top: 18px; }
.create-form :deep(.el-form-item) { min-width: 0; }
.create-form > .el-button { margin-bottom: 18px; }
.table-wrap { width: 100%; overflow-x: auto; margin: 18px 0 12px; }
.handoff-note { color: #667085; font-size: 13px; line-height: 1.6; }
@media (max-width: 680px) { .portal-address { align-items: flex-start; flex-direction: column; } .create-form { grid-template-columns: 1fr; gap: 0; } .create-form > .el-button { margin: 0 0 12px; } }
</style>
