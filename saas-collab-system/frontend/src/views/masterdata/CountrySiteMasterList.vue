<template>
  <AdminResourcePage
    eyebrow="MASTER DATA"
    title="国家信息"
    subtitle="维护租户内国家名称、国家代码、币种和时区，供店铺、开发和刊登菜单引用。"
    boundary-note="国家档案只维护国家、币种与时区口径，不保存店铺或平台凭据。"
    entity-label="国家"
    :loader="fetchCountrySites"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="(payload) => createMasterData('sites', payload)"
    :edit-handler="(id, payload) => updateMasterData('sites', id, payload)"
    :status-handler="(row, status) => updateMasterDataStatus('sites', row.id, status)"
    create-permission="masterdata.manage"
    manage-permission="masterdata.manage"
    search-label="国家"
    show-filter-labels
    show-page-size
    :operation-width="190"
  />
</template>

<script setup>
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import { createMasterData, fetchCountrySites, updateMasterData, updateMasterDataStatus } from '../../api/masterData';

const columns = [
  { prop: 'code', label: '国家档案编码', width: 150 }, { prop: 'name', label: '国家名称', width: 180 },
  { prop: 'country_code', label: '国家代码', width: 110 }, { prop: 'currency', label: '币种', width: 100 },
  { prop: 'timezone', label: '时区', width: 170 },
  { prop: 'status', label: '状态', type: 'status' },
];
const formFields = [
  { key: 'code', label: '国家档案编码', required: true, placeholder: '例如 country-th' },
  { key: 'name', label: '国家名称', required: true },
  { key: 'country_code', label: '国家代码', required: true, placeholder: '例如 TH' },
  { key: 'platform', label: '平台编码', placeholder: '选填，例如 shopee' },
  { key: 'currency', label: '币种', required: true, placeholder: '例如 THB' },
  { key: 'timezone', label: '时区', required: true, default: 'UTC', placeholder: '例如 Asia/Bangkok' },
  { key: 'status', label: '状态', type: 'select', required: true, default: 'active', options: [
    { label: '启用', value: 'active' }, { label: '停用', value: 'inactive' }
  ] },
];
</script>
