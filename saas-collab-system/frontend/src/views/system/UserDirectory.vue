<template>
  <AdminResourcePage
    ref="resourcePage"
    title="用户目录"
    subtitle="查看租户内账号、部门归属和角色绑定，执行受审计的账号启停。"
    boundary-note="邮箱和手机号仅显示脱敏值；初始密码仅在创建请求中传输，不进入页面日志、列表或详情。"
    entity-label="用户"
    :loader="fetchUsers"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="createUser"
    :status-handler="handleStatus"
    create-permission="system.users.manage"
    manage-permission="system.users.manage"
    :operation-width="270"
  >
    <template #row-actions="{ row }">
      <el-button
        v-if="roleAccess.visible"
        link
        type="primary"
        :disabled="roleAccess.disabled"
        @click.stop="openProfileMaintenance(row)"
      >维护档案</el-button>
      <el-button
        v-if="roleAccess.visible"
        link
        type="primary"
        :disabled="roleAccess.disabled"
        :title="roleAccess.reason"
        @click.stop="openRoleAssignment(row)"
      >分配角色</el-button>
      <el-button
        v-if="roleAccess.visible"
        link
        type="warning"
        :disabled="roleAccess.disabled"
        :title="roleAccess.reason"
        @click.stop="openPasswordReset(row)"
      >重置密码</el-button>
    </template>
  </AdminResourcePage>

  <el-dialog v-model="profileDialogOpen" title="维护用户档案" width="min(560px, 94vw)">
    <el-form label-position="top">
      <el-form-item label="用户名">
        <el-input :model-value="selectedUser.username" disabled />
      </el-form-item>
      <el-form-item label="用户姓名">
        <el-input v-model="profileForm.full_name" maxlength="100" placeholder="填写用户具体姓名" />
      </el-form-item>
      <el-form-item label="关联部门（可多选）">
        <el-select v-model="profileForm.department_ids" multiple filterable style="width: 100%" placeholder="选择用户所属部门">
          <el-option v-for="item in departmentOptions" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="profileDialogOpen = false">取消</el-button>
      <el-button type="primary" :loading="profileSaving" @click="saveProfile">保存档案</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="roleDialogOpen" title="分配用户角色" width="min(520px, 94vw)">
    <p class="role-user">用户：<strong>{{ selectedUser.username }}</strong></p>
    <el-form label-position="top">
      <el-form-item label="角色">
        <el-select
          v-model="selectedRoleCodes"
          multiple
          filterable
          :loading="roleOptionsLoading"
          placeholder="选择当前 tenant 的角色"
          style="width: 100%"
        >
          <el-option
            v-for="role in roleOptions"
            :key="role.code"
            :label="`${role.name} (${role.code})`"
            :value="role.code"
          />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="roleDialogOpen = false">取消</el-button>
      <el-button type="primary" :loading="roleSaving" @click="saveRoleAssignment">保存角色</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="passwordDialogOpen" title="重置用户密码" width="min(520px, 94vw)" @closed="clearPasswordForm">
    <el-alert title="密码提交后不会回显，也不会写入操作日志。" type="warning" :closable="false" show-icon />
    <el-form label-position="top" class="password-form">
      <el-form-item label="用户"><el-input :model-value="selectedUser.username" disabled /></el-form-item>
      <el-form-item label="新密码">
        <el-input v-model="passwordForm.new_password" type="password" show-password maxlength="128" placeholder="至少12位" />
      </el-form-item>
      <el-form-item label="确认新密码">
        <el-input v-model="passwordForm.confirm_password" type="password" show-password maxlength="128" placeholder="再次输入新密码" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="passwordDialogOpen = false">取消</el-button>
      <el-button type="danger" :loading="passwordSaving" @click="submitPasswordReset">确认重置</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import {
  createUser, fetchAssignableRoles, fetchDepartments, fetchUsers,
  resetUserPassword, updateUserProfile, updateUserRoles, updateUserStatus
} from '../../api/systemAdmin';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';

const auth = useAuthStore();
const resourcePage = ref(null);
const roleAccess = computed(() => getActionAccess(auth, { permission: 'system.users.manage' }));
const roleDialogOpen = ref(false);
const roleOptionsLoading = ref(false);
const roleSaving = ref(false);
const roleOptions = ref([]);
const selectedRoleCodes = ref([]);
const selectedUser = ref({});
const profileDialogOpen = ref(false);
const profileSaving = ref(false);
const profileForm = reactive({ full_name: '', department_ids: [] });
const departmentOptions = ref([]);
const passwordDialogOpen = ref(false);
const passwordSaving = ref(false);
const passwordForm = reactive({ new_password: '', confirm_password: '' });

const columns = [
  { prop: 'username', label: '用户名', width: 160 },
  { prop: 'full_name', label: '用户姓名', width: 140 },
  { prop: 'department_names', label: '关联部门', type: 'list', width: 220 },
  { prop: 'role_labels', label: '角色名称（角色编号）', type: 'list', width: 260 },
  { prop: 'email_masked', label: '邮箱（脱敏）', width: 190 },
  { prop: 'phone_masked', label: '手机（脱敏）', width: 140 },
  { prop: 'is_active', label: '状态', type: 'status' }
];
const formFields = computed(() => [
  { key: 'username', label: '用户名', required: true, placeholder: '仅使用工作账号标识' },
  { key: 'full_name', label: '用户姓名', placeholder: '填写用户具体姓名' },
  { key: 'initial_password', label: '初始密码', type: 'password', required: true, minLength: 12, placeholder: '至少12位，提交后不回显' },
  {
    key: 'department_ids',
    label: '关联部门',
    type: 'select',
    multiple: true,
    filterable: true,
    default: [],
    placeholder: '可多选用户所属部门',
    options: departmentOptions.value.map((item) => ({ label: item.name, value: item.id }))
  },
  { key: 'user_type', label: '用户类型', type: 'select', default: 'internal', options: [{ label: '内部用户', value: 'internal' }, { label: 'RPA 执行用户', value: 'rpa' }] }
]);
const handleStatus = (row, status) => updateUserStatus(row.id, status === 'active');

async function loadDepartmentOptions() {
  const response = await fetchDepartments({ page: 1, page_size: 100 });
  if (response?.success) departmentOptions.value = response.data?.results || [];
}

function openProfileMaintenance(row) {
  selectedUser.value = row;
  profileForm.full_name = row.full_name || '';
  const names = new Set(row.department_names || []);
  profileForm.department_ids = departmentOptions.value.filter((item) => names.has(item.name)).map((item) => item.id);
  profileDialogOpen.value = true;
}

async function saveProfile() {
  profileSaving.value = true;
  const response = await updateUserProfile(selectedUser.value.id, {
    full_name: profileForm.full_name.trim(),
    department_ids: profileForm.department_ids
  });
  profileSaving.value = false;
  if (!response?.success) {
    ElMessage.error(response?.message || '用户档案保存失败');
    return;
  }
  ElMessage.success('用户姓名和关联部门已保存');
  profileDialogOpen.value = false;
  await resourcePage.value?.loadData();
}

async function openRoleAssignment(row) {
  if (!roleAccess.value.allowed) {
    ElMessage.warning(roleAccess.value.reason);
    return;
  }
  selectedUser.value = row;
  selectedRoleCodes.value = [...(row.roles || [])];
  roleOptionsLoading.value = true;
  const response = await fetchAssignableRoles({ page: 1, page_size: 100 });
  roleOptionsLoading.value = false;
  if (!response?.success) {
    ElMessage.error(response?.message || '角色目录加载失败');
    return;
  }
  roleOptions.value = response.data?.results || [];
  roleDialogOpen.value = true;
}

async function saveRoleAssignment() {
  if (!roleAccess.value.allowed || !selectedUser.value.id) {
    ElMessage.warning(roleAccess.value.reason || '无权分配角色');
    return;
  }
  roleSaving.value = true;
  const response = await updateUserRoles(selectedUser.value.id, selectedRoleCodes.value);
  roleSaving.value = false;
  if (!response?.success) {
    ElMessage.error(response?.message || '角色保存失败');
    return;
  }
  ElMessage.success('用户角色已保存并记录审计');
  roleDialogOpen.value = false;
  await resourcePage.value?.loadData();
}

function clearPasswordForm() {
  passwordForm.new_password = '';
  passwordForm.confirm_password = '';
}

function openPasswordReset(row) {
  if (!roleAccess.value.allowed) {
    ElMessage.warning(roleAccess.value.reason);
    return;
  }
  selectedUser.value = row;
  clearPasswordForm();
  passwordDialogOpen.value = true;
}

async function submitPasswordReset() {
  if (!roleAccess.value.allowed || !selectedUser.value.id) {
    ElMessage.warning(roleAccess.value.reason || '无权重置密码');
    return;
  }
  if (passwordForm.new_password.length < 12) {
    ElMessage.warning('新密码至少需要12位');
    return;
  }
  if (passwordForm.new_password !== passwordForm.confirm_password) {
    ElMessage.warning('两次输入的密码不一致');
    return;
  }
  passwordSaving.value = true;
  const response = await resetUserPassword(selectedUser.value.id, { ...passwordForm });
  passwordSaving.value = false;
  if (!response?.success) {
    ElMessage.error(response?.message || '密码重置失败');
    return;
  }
  ElMessage.success('用户密码已重置并记录审计');
  passwordDialogOpen.value = false;
}

onMounted(loadDepartmentOptions);
</script>

<style scoped>
.role-user { margin: 0 0 16px; color: #475569; }
.password-form { margin-top: 16px; }
</style>
