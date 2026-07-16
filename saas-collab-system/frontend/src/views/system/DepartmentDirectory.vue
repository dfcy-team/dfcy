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
    create-permission="system.organization.manage"
  />
</template>

<script setup>
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import { createDepartment, fetchDepartments } from '../../api/systemAdmin';

const columns = [
  { prop: 'name', label: '部门名称', width: 180 },
  { prop: 'parent_name', label: '上级部门', width: 180 },
  { prop: 'status', label: '状态', type: 'status' },
  { prop: 'tenant_id', label: '租户ID' }
];
const formFields = [
  { key: 'name', label: '部门名称', required: true },
  { key: 'status', label: '状态', type: 'select', default: 'active', options: [
    { label: '启用', value: 'active' }, { label: '停用', value: 'inactive' }
  ] }
];
</script>
