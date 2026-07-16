<template>
  <AdminResourcePage
    eyebrow="MASTER DATA"
    title="仓库档案"
    subtitle="统一维护自营、三方和平台仓库，供库存和采购链路引用。"
    boundary-note="本页面不修改库存数量，也不触发补货、采购或真实平台动作。"
    entity-label="仓库"
    :loader="fetchWarehouses"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="(payload) => createMasterData('warehouses', payload)"
    :status-handler="(row, status) => updateMasterDataStatus('warehouses', row.id, status)"
    create-permission="masterdata.manage"
    manage-permission="masterdata.manage"
  />
</template>

<script setup>
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import { createMasterData, fetchWarehouses, updateMasterDataStatus } from '../../api/masterData';

const columns = [
  { prop: 'code', label: '仓库编码', width: 170 }, { prop: 'name', label: '仓库名称', width: 200 },
  { prop: 'country_code', label: '国家' }, { prop: 'warehouse_type', label: '仓库类型', width: 150 },
  { prop: 'status', label: '状态', type: 'status' }
];
const formFields = [
  { key: 'code', label: '仓库编码', required: true }, { key: 'name', label: '仓库名称', required: true },
  { key: 'country_code', label: '国家代码', required: true },
  { key: 'warehouse_type', label: '仓库类型', type: 'select', required: true, default: 'owned', options: [
    { label: '自营仓', value: 'owned' }, { label: '三方仓', value: 'third_party' }, { label: '平台仓', value: 'platform' }
  ] }
];
</script>
