<template>
  <el-drawer
    v-model="drawerVisible"
    title="个人设置"
    size="min(480px, 100%)"
    append-to-body
    destroy-on-close
    :close-on-click-modal="!busy"
    :close-on-press-escape="!busy"
    @opened="loadProfile"
  >
    <p class="settings-intro">管理您的个人资料和登录密码。</p>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />

    <el-tabs v-model="activeTab" class="settings-tabs">
      <el-tab-pane label="个人资料" name="profile">
        <el-skeleton v-if="loadingProfile" :rows="5" animated />
        <el-form
          v-else
          ref="profileFormRef"
          :model="profileForm"
          :rules="profileRules"
          label-position="top"
          @submit.prevent="saveProfile"
        >
          <el-form-item label="登录账号">
            <el-input v-model="profileForm.username" disabled />
          </el-form-item>
          <el-form-item label="当前角色">
            <el-input :model-value="roleLabel" disabled />
          </el-form-item>
          <el-form-item label="姓名" prop="full_name">
            <el-input v-model.trim="profileForm.full_name" maxlength="100" placeholder="请输入姓名" />
          </el-form-item>
          <el-form-item label="邮箱" prop="email">
            <el-input v-model.trim="profileForm.email" type="email" maxlength="254" placeholder="请输入邮箱" />
          </el-form-item>
          <el-form-item label="手机号码" prop="phone">
            <el-input v-model.trim="profileForm.phone" maxlength="32" placeholder="请输入手机号码" />
          </el-form-item>
          <el-button type="primary" native-type="submit" :loading="savingProfile">保存个人资料</el-button>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="修改密码" name="password">
        <el-form
          ref="passwordFormRef"
          :model="passwordForm"
          :rules="passwordRules"
          label-position="top"
          @submit.prevent="savePassword"
        >
          <el-alert
            title="新密码至少 12 位，修改成功后需要重新登录。"
            type="info"
            :closable="false"
            show-icon
          />
          <el-form-item label="当前密码" prop="current_password">
            <el-input
              v-model="passwordForm.current_password"
              type="password"
              autocomplete="current-password"
              placeholder="请输入当前密码"
              show-password
            />
          </el-form-item>
          <el-form-item label="新密码" prop="new_password">
            <el-input
              v-model="passwordForm.new_password"
              type="password"
              autocomplete="new-password"
              placeholder="请输入新密码"
              show-password
            />
          </el-form-item>
          <el-form-item label="确认新密码" prop="confirm_password">
            <el-input
              v-model="passwordForm.confirm_password"
              type="password"
              autocomplete="new-password"
              placeholder="请再次输入新密码"
              show-password
              @keyup.enter="savePassword"
            />
          </el-form-item>
          <el-button type="primary" native-type="submit" :loading="savingPassword">确认修改密码</el-button>
        </el-form>
      </el-tab-pane>
    </el-tabs>
  </el-drawer>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { changeMyPassword, getMyProfile, updateMyProfile } from '../api/auth';

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  currentUser: { type: Object, default: null },
});

const emit = defineEmits(['update:modelValue', 'profile-updated', 'password-changed']);
const activeTab = ref('profile');
const loadingProfile = ref(false);
const savingProfile = ref(false);
const savingPassword = ref(false);
const errorMessage = ref('');
const profileFormRef = ref();
const passwordFormRef = ref();
const profileForm = reactive({ username: '', full_name: '', email: '', phone: '' });
const passwordForm = reactive({ current_password: '', new_password: '', confirm_password: '' });

const drawerVisible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
});
const roleLabel = computed(() => {
  const roles = props.currentUser?.roles?.filter(Boolean) || [];
  return roles.length ? roles.join(' / ') : '未分配角色';
});
const busy = computed(() => loadingProfile.value || savingProfile.value || savingPassword.value);

const profileRules = {
  email: [{ type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' }],
};
const passwordRules = {
  current_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 12, message: '新密码至少需要 12 位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== passwordForm.new_password) callback(new Error('两次输入的密码不一致'));
        else callback();
      },
      trigger: 'blur',
    },
  ],
};

function responseError(response, fallback) {
  const details = response?.data && typeof response.data === 'object' ? Object.values(response.data).flat() : [];
  return details.find((item) => typeof item === 'string') || response?.message || fallback;
}

function applyProfile(profile = {}) {
  profileForm.username = profile.username || props.currentUser?.username || '';
  profileForm.full_name = profile.full_name || '';
  profileForm.email = profile.email || '';
  profileForm.phone = profile.phone || '';
}

async function loadProfile() {
  errorMessage.value = '';
  loadingProfile.value = true;
  try {
    const response = await getMyProfile();
    if (!response.success) {
      errorMessage.value = responseError(response, '个人资料加载失败');
      return;
    }
    applyProfile(response.data);
  } finally {
    loadingProfile.value = false;
  }
}

async function saveProfile() {
  const valid = await profileFormRef.value?.validate().catch(() => false);
  if (!valid) return;
  errorMessage.value = '';
  savingProfile.value = true;
  try {
    const response = await updateMyProfile({
      full_name: profileForm.full_name,
      email: profileForm.email,
      phone: profileForm.phone,
    });
    if (!response.success) {
      errorMessage.value = responseError(response, '个人资料保存失败');
      return;
    }
    applyProfile(response.data);
    emit('profile-updated', response.data);
    ElMessage.success('个人资料已保存');
  } finally {
    savingProfile.value = false;
  }
}

async function savePassword() {
  const valid = await passwordFormRef.value?.validate().catch(() => false);
  if (!valid) return;
  errorMessage.value = '';
  savingPassword.value = true;
  try {
    const response = await changeMyPassword({ ...passwordForm });
    if (!response.success) {
      errorMessage.value = responseError(response, '密码修改失败');
      return;
    }
    Object.assign(passwordForm, { current_password: '', new_password: '', confirm_password: '' });
    emit('password-changed');
  } finally {
    savingPassword.value = false;
  }
}

watch(drawerVisible, (visible) => {
  if (visible) return;
  errorMessage.value = '';
  activeTab.value = 'profile';
  Object.assign(passwordForm, { current_password: '', new_password: '', confirm_password: '' });
});
</script>

<style scoped>
.settings-intro { margin: -8px 0 18px; color: #64748b; font-size: 13px; line-height: 1.6; }
.settings-tabs :deep(.el-alert) { margin-bottom: 18px; }
.settings-tabs :deep(.el-form) { padding-top: 12px; }
.settings-tabs :deep(.el-button[type='submit']) { min-width: 144px; }
</style>
