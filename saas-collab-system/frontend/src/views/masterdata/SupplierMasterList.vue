<template>
  <section>
  <el-tabs v-if="canSupply && canMaster" v-model="surface"><el-tab-pane label="采购协同资料" name="supply"/><el-tab-pane label="基础维护" name="basic"/></el-tabs>
  <SupplyArchiveV2 v-if="canSupply && (!canMaster || surface==='supply')" kind="suppliers" />
  <AdminResourcePage
    v-else
    eyebrow="MASTER DATA"
    title="供应商档案"
    subtitle="统一维护供应商身份与脱敏联系人信息，供采购和协同链路引用。"
    boundary-note="编码留空时可按基础档案设置的规则自动生成；存在业务引用时不能删除，可按业务规则停用。联系方式只以脱敏形式回显。"
    entity-label="供应商"
    :loader="fetchSupplierMasters"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="(payload) => createMasterData('suppliers', payload)"
    :edit-handler="(id, payload) => updateMasterData('suppliers', id, payload)"
    :delete-handler="(id) => deleteMasterData('suppliers', id)"
    :status-handler="(row, status) => updateMasterDataStatus('suppliers', row.id, status)"
    create-permission="masterdata.manage"
    manage-permission="masterdata.manage"
    :operation-width="190"
  />
  </section>
</template>

<script setup>
import {computed,ref} from 'vue';
import {useAuthStore} from '../../stores/auth';
import SupplyArchiveV2 from './SupplyArchiveV2.vue';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import { createMasterData, deleteMasterData, fetchSupplierMasters, updateMasterData, updateMasterDataStatus } from '../../api/masterData';
const auth=useAuthStore();
const canSupply=computed(()=>!auth.authorizationStale&&(auth.hasPermission('supply.v2.view')||auth.hasRouteViewPermission?.('supply.v2.view')));
const canMaster=computed(()=>!auth.authorizationStale&&(auth.hasPermission('masterdata.view')||auth.hasRouteViewPermission?.('masterdata.view')));
const surface=ref(auth.hasPermission('supply.v2.manage')?'supply':auth.hasPermission('masterdata.manage')?'basic':'supply');

const columns = [
  { prop: 'code', label: '供应商编码', width: 170 }, { prop: 'name', label: '供应商名称', width: 220 },
  { prop: 'contact_alias', label: '联系人别名', width: 150 },
  { prop: 'contact_email_masked', label: '邮箱（脱敏）', width: 190 },
  { prop: 'contact_phone_masked', label: '手机（脱敏）', width: 150 },
  { prop: 'first_cooperation_date', label: '首次合作日期', width: 150 },
  { prop: 'payment_term_days', label: '账期天数', width: 120 },
  { prop: 'payment_term_start', label: '账期起算方式', width: 160, options: [
    { label: '未约定', value: 'unspecified' }, { label: '供应商发货日', value: 'shipment_date' },
    { label: '集货到仓日', value: 'collection_arrival' }, { label: '目的仓到仓日', value: 'warehouse_arrival' },
    { label: '对账确认日', value: 'reconciliation_date' },
  ] },
  { prop: 'status', label: '状态', type: 'status' }
];
const paymentTermStarts = [
  { label: '未约定', value: 'unspecified' },
  { label: '供应商发货日', value: 'shipment_date' },
  { label: '集货到仓日', value: 'collection_arrival' },
  { label: '目的仓到仓日', value: 'warehouse_arrival' },
  { label: '对账确认日', value: 'reconciliation_date' },
];
const formFields = [
  { key: 'code', label: '供应商编码', placeholder: '留空时按已启用的规则自动生成' }, { key: 'name', label: '供应商名称', required: true },
  { key: 'contact_alias', label: '联系人别名' }, { key: 'contact_email', label: '联系邮箱' },
  { key: 'contact_phone', label: '联系电话' },
  { key: 'first_cooperation_date', label: '首次合作日期', placeholder: 'YYYY-MM-DD' },
  { key: 'payment_term_days', label: '账期天数', placeholder: '0 至 3650；0 表示当天结算' },
  { key: 'payment_term_start', label: '账期起算方式', type: 'select', options: paymentTermStarts },
];
</script>
