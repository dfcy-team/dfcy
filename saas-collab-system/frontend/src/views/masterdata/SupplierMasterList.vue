<template>
  <AdminResourcePage
    eyebrow="MASTER DATA"
    title="供应商档案"
    subtitle="统一维护供应商身份与脱敏联系人信息，供采购和协同链路引用。"
    boundary-note="供应商只能访问自己的任务与绩效；存在进行中任务时禁止停用，联系方式只以脱敏形式回显。"
    entity-label="供应商"
    :loader="fetchSupplierMasters"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="(payload) => createMasterData('suppliers', payload)"
    :status-handler="(row, status) => updateMasterDataStatus('suppliers', row.id, status)"
    create-permission="masterdata.manage"
    manage-permission="masterdata.manage"
  />
</template>

<script setup>
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import { createMasterData, fetchSupplierMasters, updateMasterDataStatus } from '../../api/masterData';

const columns = [
  { prop: 'code', label: '供应商编码', width: 170 }, { prop: 'name', label: '供应商名称', width: 220 },
  { prop: 'contact_alias', label: '联系人别名', width: 150 },
  { prop: 'contact_email_masked', label: '邮箱（脱敏）', width: 190 },
  { prop: 'contact_phone_masked', label: '手机（脱敏）', width: 150 },
  { prop: 'status', label: '状态', type: 'status' }
];
const formFields = [
  { key: 'code', label: '供应商编码', required: true }, { key: 'name', label: '供应商名称', required: true },
  { key: 'contact_alias', label: '联系人别名' }, { key: 'contact_email', label: '联系邮箱' },
  { key: 'contact_phone', label: '联系电话' }
];
</script>
