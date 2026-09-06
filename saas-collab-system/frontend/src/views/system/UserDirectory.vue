<template>
  <AdminResourcePage
    ref="resourcePage"
    title="用户目录"
    subtitle="从共享组织树筛选人员，维护角色绑定、账号状态和部门归属。"
    boundary-note="用户列表始终受租户、数据范围和字段权限约束；部门调整需要 system.users.manage，部门字段权限缺失时不显示相关数据和入口。"
    entity-label="用户"
    :loader="fetchUsers"
    :external-filters="departmentFilters"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="createUser"
    :status-handler="handleStatus"
    create-permission="system.users.manage"
    manage-permission="system.users.manage"
    :operation-width="320"
  >
    <template #sidebar>
      <DepartmentTree
        v-if="departmentTreeVisible"
        :nodes="treeNodes"
        :loading="treeLoading"
        :error-message="treeError"
        :can-manage="false"
        :show-all="true"
        :all-selected="allUsersSelected"
        :show-unassigned="true"
        :unassigned-selected="departmentFilters.unassigned"
        :selected-id="departmentFilters.department_id"
        @select="selectDepartment"
        @select-all="selectAllUsers"
        @select-unassigned="selectUnassigned"
      />
      <el-alert
        v-else
        :title="departmentFieldVisible
          ? '当前角色没有 system.organization.view，组织筛选树未加载；部门调整仍需用户管理权限。'
          : '当前角色没有部门字段权限，组织筛选和部门调整入口已隐藏。'"
        type="info"
        :closable="false"
        show-icon
      />
      <section v-if="departmentTreeVisible && departmentFilters.department_id" class="directory-scope">
        <strong>部门筛选范围</strong>
        <el-radio-group v-model="departmentFilters.include_descendants" @change="reloadUsers">
          <el-radio-button :value="false">仅直属</el-radio-button>
          <el-radio-button :value="true">包含下级</el-radio-button>
        </el-radio-group>
        <small>兼任部门人员按任一部门匹配；数据范围仍由后端最终校验。</small>
      </section>
    </template>
    <template #header-actions>
      <el-tag effect="plain">{{ filterSummary }}</el-tag>
    </template>
    <template #row-actions="{ row }">
      <el-button
        v-if="departmentAccess.visible && departmentFieldVisible"
        link
        type="primary"
        :disabled="departmentAccess.disabled"
        :title="departmentAccess.reason"
        @click.stop="openDepartmentDialog(row)"
      >调整部门</el-button>
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

  <el-dialog v-model="departmentDialogOpen" title="调整部门归属" width="min(560px, 94vw)">
    <p class="role-user">用户：<strong>{{ selectedUser.username }}</strong></p>
    <el-alert
      title="主部门用于 department_tree 数据范围锚定；兼任部门只增加组织归属，不改变主部门。"
      type="info"
      :closable="false"
      show-icon
    />
    <el-form label-position="top" class="department-form">
      <el-form-item label="主部门">
        <el-select v-model="selectedDepartmentId" clearable filterable placeholder="未分配主部门" style="width: 100%">
          <el-option v-for="item in departmentOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="兼任部门">
        <el-select
          v-model="selectedDepartmentIds"
          multiple
          filterable
          collapse-tags
          collapse-tags-tooltip
          placeholder="可多选兼任部门"
          style="width: 100%"
        >
          <el-option v-for="item in departmentOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="departmentDialogOpen = false">取消</el-button>
      <el-button
        type="primary"
        :loading="departmentSaving"
        :disabled="departmentAccess.disabled"
        @click="saveDepartmentAssignment"
      >保存部门</el-button>
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
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import DepartmentTree from '../../components/DepartmentTree.vue';
import {
  createUser, fetchAssignableRoles, fetchDepartmentTree, fetchUsers,
  updateUserDepartments, updateUserRoles, updateUserStatus
} from '../../api/systemAdmin';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';

const auth = useAuthStore();
const resourcePage = ref(null);
const treeNodes = ref([]);
const treeLoading = ref(true);
const treeError = ref('');
const departmentDialogOpen = ref(false);
const departmentSaving = ref(false);
const roleDialogOpen = ref(false);
const roleOptionsLoading = ref(false);
const roleSaving = ref(false);
const roleOptions = ref([]);
const selectedRoleCodes = ref([]);
const selectedDepartmentId = ref(null);
const selectedDepartmentIds = ref([]);
const selectedUser = ref({});
const departmentFilters = reactive({
  department_id: undefined,
  include_descendants: false,
  unassigned: false,
});

const roleAccess = computed(() => getActionAccess(auth, { permission: 'system.users.manage' }));
const departmentAccess = computed(() => getActionAccess(auth, { permission: 'system.users.manage' }));
const departmentFieldVisible = computed(() => auth.hasFieldPermission('field.system.users.department.view'));
const organizationViewAllowed = computed(() => auth.hasPermission('system.organization.view'));
const departmentTreeVisible = computed(() => departmentFieldVisible.value && organizationViewAllowed.value);
const allUsersSelected = computed(() => (
  !departmentFilters.department_id && !departmentFilters.unassigned && !departmentFilters.include_descendants
));
const filterSummary = computed(() => {
  if (departmentFilters.unassigned) return '未分配人员';
  if (!departmentFilters.department_id) return '全部可见用户';
  return departmentFilters.include_descendants ? '当前部门及下级' : '当前部门直属';
});

const columns = computed(() => [
  { prop: 'username', label: '用户名', width: 160 },
  ...(auth.hasFieldPermission('field.system.users.full_name.view')
    ? [{ prop: 'full_name', label: '姓名', width: 150 }]
    : []),
  ...(departmentFieldVisible.value
    ? [{ prop: 'department_name', label: '主部门', width: 150 }]
    : []),
  ...(auth.hasFieldPermission('field.system.users.roles.view')
    ? [{ prop: 'roles', label: '角色', type: 'list', width: 210 }]
    : []),
  { prop: 'email_masked', label: '邮箱（脱敏）', width: 190 },
  { prop: 'phone_masked', label: '手机（脱敏）', width: 140 },
  ...(auth.hasFieldPermission('field.system.users.status.view')
    ? [{ prop: 'is_active', label: '状态', type: 'status' }]
    : []),
]);

const formFields = [
  { key: 'username', label: '用户名', required: true, placeholder: '仅使用工作账号标识' },
  { key: 'initial_password', label: '初始密码', type: 'password', required: true, placeholder: '至少12位，提交后不回显' },
  { key: 'user_type', label: '用户类型', type: 'select', default: 'internal', options: [{ label: '内部用户', value: 'internal' }] }
];

function flattenTree(nodes, result = []) {
  for (const node of nodes || []) {
    result.push({ label: node.name, value: node.id });
    flattenTree(node.children, result);
  }
  return result;
}

const departmentOptions = computed(() => flattenTree(treeNodes.value));

function unpackTree(response) {
  return response?.data?.items || response?.data?.results || [];
}

async function loadTree() {
  if (!departmentTreeVisible.value) {
    treeLoading.value = false;
    treeError.value = '';
    treeNodes.value = [];
    return;
  }
  treeLoading.value = true;
  treeError.value = '';
  const response = await fetchDepartmentTree();
  treeLoading.value = false;
  if (!response?.success) {
    treeError.value = response?.message || '组织树加载失败';
    treeNodes.value = [];
    return;
  }
  treeNodes.value = unpackTree(response);
}

function selectDepartment(node) {
  departmentFilters.department_id = node.id;
  departmentFilters.include_descendants = false;
  departmentFilters.unassigned = false;
  reloadUsers();
}

function selectAllUsers() {
  departmentFilters.department_id = undefined;
  departmentFilters.include_descendants = false;
  departmentFilters.unassigned = false;
  reloadUsers();
}

function selectUnassigned() {
  departmentFilters.department_id = undefined;
  departmentFilters.include_descendants = false;
  departmentFilters.unassigned = true;
  reloadUsers();
}

function reloadUsers() {
  resourcePage.value?.loadData();
}

function openDepartmentDialog(row) {
  if (!departmentFieldVisible.value || !departmentAccess.value.allowed) {
    ElMessage.warning(departmentAccess.value.reason || '无权调整部门');
    return;
  }
  selectedUser.value = row;
  selectedDepartmentId.value = row.department_id ?? null;
  selectedDepartmentIds.value = [...(row.department_ids || [])];
  departmentDialogOpen.value = true;
}

async function saveDepartmentAssignment() {
  if (!departmentAccess.value.allowed || !selectedUser.value.id) return;
  departmentSaving.value = true;
  const departmentIds = [...new Set(selectedDepartmentIds.value)];
  if (selectedDepartmentId.value && !departmentIds.includes(selectedDepartmentId.value)) {
    departmentIds.unshift(selectedDepartmentId.value);
  }
  const response = await updateUserDepartments(
    selectedUser.value.id,
    selectedDepartmentId.value,
    departmentIds,
  );
  departmentSaving.value = false;
  if (!response?.success) {
    ElMessage.error(response?.message || '部门保存失败');
    return;
  }
  ElMessage.success('部门归属已保存并记录审计');
  departmentDialogOpen.value = false;
  await resourcePage.value?.loadData();
  await loadTree();
}

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

onMounted(loadTree);
watch(departmentTreeVisible, (visible) => {
  if (visible && !treeNodes.value.length) loadTree();
});
</script>

<style scoped>
.directory-scope { display: grid; gap: 8px; padding: 10px 0 2px; border-top: 1px solid #e5eaf0; }
.directory-scope strong { color: #334155; font-size: 12px; }
.directory-scope small { color: #64748b; font-size: 11px; line-height: 1.5; }
.role-user { margin: 0 0 16px; color: #475569; }
.department-form { margin-top: 16px; }
</style>
