<template>
  <AdminResourcePage
    eyebrow="MASTER DATA"
    title="国家信息"
    subtitle="维护租户内国家名称、国家代码、币种和时区，供店铺、开发和刊登菜单引用。"
    boundary-note="沿用 CountrySiteMaster/sites 资源和既有数据；platform 字段仅作为兼容性提示，不再作为国家档案主字段。"
    entity-label="国家"
    :loader="fetchCountrySites"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="(payload) => createMasterData('sites', payload)"
    :edit-handler="(id, payload) => updateMasterData('sites', id, payload)"
    :status-handler="(row, status) => updateMasterDataStatus('sites', row.id, status)"
    create-permission="masterdata.manage"
    manage-permission="masterdata.manage"
  />
</template>

<script setup>
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import { createMasterData, fetchCountrySites, updateMasterData, updateMasterDataStatus } from '../../api/masterData';

const columns = [
  { prop: 'code', label: '国家档案编码', width: 150 },
  { prop: 'name', label: '国家名称', width: 180 },
  { prop: 'country_code', label: '国家代码', width: 110 },
  { prop: 'currency', label: '币种', width: 100 },
  { prop: 'timezone', label: '时区', width: 180 },
  { prop: 'status', label: '状态', type: 'status' },
];

const formFields = [
  { key: 'code', label: '国家档案编码', required: true, placeholder: '例如 TH' },
  { key: 'name', label: '国家名称', required: true, placeholder: '例如 泰国' },
  { key: 'country_code', label: '国家代码', required: true, placeholder: '例如 TH' },
  { key: 'currency', label: '币种', required: true, placeholder: '例如 THB' },
  { key: 'timezone', label: '时区', required: true, default: 'UTC', placeholder: '例如 Asia/Bangkok' },
];
</script>
