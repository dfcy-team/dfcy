<template>
  <AdminResourcePage
    eyebrow="MASTER DATA"
    title="平台档案"
    subtitle="统一维护平台标识，供店铺、接口配置和业务模块引用。"
    boundary-note="平台档案不保存 API Key、Token 或登录凭据；存在启用店铺引用时禁止停用。"
    entity-label="平台"
    :loader="fetchPlatforms"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="(payload) => createMasterData('platforms', payload)"
    :status-handler="(row, status) => updateMasterDataStatus('platforms', row.id, status)"
    create-permission="masterdata.manage"
    manage-permission="masterdata.manage"
  />
</template>

<script setup>
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import { createMasterData, fetchPlatforms, updateMasterDataStatus } from '../../api/masterData';

const columns = [
  { prop: 'code', label: '平台编码', width: 170 }, { prop: 'name', label: '平台名称', width: 200 },
  { prop: 'platform_type', label: '平台类型' }, { prop: 'status', label: '状态', type: 'status' },
  { prop: 'tenant_id', label: '租户ID' }
];
const formFields = [
  { key: 'code', label: '平台编码', required: true }, { key: 'name', label: '平台名称', required: true },
  { key: 'platform_type', label: '平台类型', type: 'select', required: true, default: 'other', options: [
    { label: 'BigSeller', value: 'bigseller' }, { label: 'Shopee', value: 'shopee' },
    { label: 'TikTok', value: 'tiktok' }, { label: '其他', value: 'other' }
  ] }
];
</script>
