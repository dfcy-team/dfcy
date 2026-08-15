<template>
  <AdminResourcePage
    eyebrow="MASTER DATA"
    title="国家站点信息"
    subtitle="维护租户内国家与平台站点信息，供店铺等业务档案选择。"
    boundary-note="直接复用现有 CountrySiteMaster/sites 资源，不覆盖国家站点业务模型。"
    entity-label="国家站点"
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
  { prop: 'code', label: '站点编码', width: 150 }, { prop: 'name', label: '国家名称', width: 180 },
  { prop: 'country_code', label: '国家代码', width: 110 }, { prop: 'platform', label: '平台', width: 120 },
  { prop: 'status', label: '状态', type: 'status' },
];
const formFields = [
  { key: 'code', label: '站点编码', required: true, placeholder: '例如 TH-SHOPEE' },
  { key: 'name', label: '国家名称', required: true },
  { key: 'country_code', label: '国家代码', required: true, placeholder: '例如 TH' },
  { key: 'platform', label: '平台', required: true, placeholder: '例如 shopee' },
];
</script>
