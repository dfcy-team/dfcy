<template>
  <AdminResourcePage
    ref="resourcePage"
    title="组织架构"
    subtitle="以共享组织树维护当前租户的部门层级、父级移动和启停状态。"
    boundary-note="树节点只显示当前权限范围，禁止跨租户读取；部门被用户或其他档案引用时由后端保护，新增、编辑、移动、停用和删除均需要 system.organization.manage。"
    entity-label="部门"
    :loader="fetchDepartments"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="handleCreate"
    :edit-handler="handleEdit"
    :delete-handler="handleDelete"
    :status-handler="handleStatus"
    create-permission="system.organization.manage"
    manage-permission="system.organization.manage"
    :operation-width="250"
  >
    <template #sidebar>
      <DepartmentTree
        ref="departmentTree"
        :nodes="treeNodes"
        :loading="treeLoading"
        :error-message="treeError"
        :can-manage="manageAccess.allowed"
        @select="selectDepartment"
        @add-root="addRootDepartment"
        @add-child="addChildDepartment"
        @edit="editDepartment"
        @toggle-status="toggleDepartment"
        @delete="deleteDepartment"
      />
    </template>
    <template #header-actions>
      <el-tag v-if="selectedDepartment" effect="plain">当前节点：{{ selectedDepartment.name }}</el-tag>
    </template>
  </AdminResourcePage>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import DepartmentTree from '../../components/DepartmentTree.vue';
import {
  createDepartment, deleteDepartment as deleteDepartmentRecord, fetchDepartmentTree, fetchDepartments, updateDepartment
} from '../../api/systemAdmin';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';
import { departmentDisplayName } from '../../utils/adminDisplayLabels';

const auth = useAuthStore();
const resourcePage = ref(null);
const departmentTree = ref(null);
const treeNodes = ref([]);
const treeLoading = ref(true);
const treeError = ref('');
const selectedDepartment = ref(null);
const manageAccess = computed(() => getActionAccess(auth, { permission: 'system.organization.manage' }));

const columns = [
  { prop: 'name', label: '部门名称', width: 180, format: (value) => departmentDisplayName(value) || '-' },
  { prop: 'parent_name', label: '上级部门', width: 180, format: (value) => departmentDisplayName(value) || '-' },
  { prop: 'status', label: '状态', type: 'status' },
  { prop: 'tenant_id', label: '租户编号' }
];

function flattenTree(nodes, result = []) {
  for (const node of nodes || []) {
    result.push(node);
    flattenTree(node.children, result);
  }
  return result;
}

const departmentOptions = computed(() => flattenTree(treeNodes.value)
  .map((item) => ({ label: departmentDisplayName(item.name), value: item.id })));

const formFields = computed(() => [
  { key: 'name', label: '部门名称', required: true },
  {
    key: 'parent_id', label: '上级部门', type: 'select', clearable: true,
    placeholder: '不选择表示根部门；选择后将移动到该父级',
    options: departmentOptions.value,
  },
  {
    key: 'status', label: '状态', type: 'select', default: 'active',
    options: [{ label: '启用', value: 'active' }, { label: '停用', value: 'inactive' }]
  }
]);

function unpackTree(response) {
  return response?.data?.items || response?.data?.results || [];
}

async function loadTree() {
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
  selectedDepartment.value = node;
}

function addRootDepartment() {
  if (manageAccess.value.allowed) resourcePage.value?.openCreate({ parent_id: null });
}

function addChildDepartment(node) {
  if (manageAccess.value.allowed) resourcePage.value?.openCreate({ parent_id: node.id });
}

function editDepartment(node) {
  if (manageAccess.value.allowed) resourcePage.value?.openEdit(node);
}

function toggleDepartment(node) {
  if (manageAccess.value.allowed) resourcePage.value?.confirmStatus(node);
}

function deleteDepartment(node) {
  if (manageAccess.value.allowed) resourcePage.value?.confirmDelete(node);
}

async function handleCreate(payload) {
  const response = await createDepartment(payload);
  if (response?.success) await loadTree();
  return response;
}

async function handleEdit(id, payload) {
  const response = await updateDepartment(id, payload);
  if (response?.success) await loadTree();
  return response;
}

async function handleStatus(row, status) {
  const response = await updateDepartment(row.id, { status });
  if (response?.success) await loadTree();
  return response;
}

async function handleDelete(id) {
  const response = await deleteDepartmentRecord(id);
  if (response?.success) await loadTree();
  return response;
}

onMounted(loadTree);
</script>
