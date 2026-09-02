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
    :operation-width="210"
  >
    <template #row-actions="{ row }">
      <el-button
        v-if="roleAccess.visible"
        link
        type="primary"
        :disabled="roleAccess.disabled"
        :title="roleAccess.reason"
        @click.stop="openRoleAssignment(row)"
      >分配角色</el-button>
    </template>
  </AdminResourcePage>

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
</template>

<script setup>
import { computed, ref } from 'vue';
import { ElMessage } from 'element-plus';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import { createUser, fetchAssignableRoles, fetchUsers, updateUserRoles, updateUserStatus } from '../../api/systemAdmin';
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

const columns = [
  { prop: 'username', label: '用户名', width: 160 },
  { prop: 'department_name', label: '部门', width: 150 },
  { prop: 'roles', label: '角色', type: 'list', width: 210 },
  { prop: 'email_masked', label: '邮箱（脱敏）', width: 190 },
  { prop: 'phone_masked', label: '手机（脱敏）', width: 140 },
  { prop: 'is_active', label: '状态', type: 'status' }
];
const formFields = [
  { key: 'username', label: '用户名', required: true, placeholder: '仅使用工作账号标识' },
  { key: 'initial_password', label: '初始密码', type: 'password', required: true, placeholder: '至少12位，提交后不回显' },
  { key: 'user_type', label: '用户类型', type: 'select', default: 'internal', options: [{ label: '内部用户', value: 'internal' }] }
];
const handleStatus = (row, status) => updateUserStatus(row.id, status === 'active');

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
</script>

<style scoped>
.role-user { margin: 0 0 16px; color: #475569; }
</style>
