<template>
  <AdminResourcePage
    title="组织架构"
    subtitle="维护当前租户的部门层级，为角色数据范围和人员归属提供唯一组织来源。"
    boundary-note="部门名称在同一上级下必须唯一；跨租户部门不可见，也不可作为父级引用。"
    entity-label="部门"
    :loader="fetchDepartments"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="createDepartment"
    :edit-handler="updateDepartment"
    :delete-handler="deleteDepartment"
    create-permission="system.organization.manage"
    manage-permission="system.organization.manage"
    :operation-width="250"
  />
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import {
  createDepartment, deleteDepartment, fetchDepartments, updateDepartment
} from '../../api/systemAdmin';

const columns = [
  { prop: 'name', label: '部门名称', width: 180 },
  { prop: 'parent_name', label: '上级部门', width: 180 },
  { prop: 'status', label: '状态', type: 'status' },
  { prop: 'tenant_id', label: '租户ID' }
];
const departmentOptions = ref([]);
const formFields = computed(() => [
  { key: 'name', label: '部门名称', required: true },
  {
    key: 'parent_id', label: '上级部门', type: 'select', clearable: true,
    placeholder: '不选择表示根部门',
    options: departmentOptions.value.map((item) => ({ label: item.name, value: item.id }))
  },
  { key: 'status', label: '状态', type: 'select', default: 'active', options: [
    { label: '启用', value: 'active' }, { label: '停用', value: 'inactive' }
  ] }
]);

async function loadDepartmentOptions() {
  const response = await fetchDepartments({ page: 1, page_size: 100 });
  if (response?.success) departmentOptions.value = response.data?.results || [];
}

onMounted(loadDepartmentOptions);
</script>
