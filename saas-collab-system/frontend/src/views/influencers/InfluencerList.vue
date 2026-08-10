<template>
  <AdminResourcePage
    eyebrow="CREATOR CRM"
    title="达人管理"
    subtitle="集中维护达人平台身份、内容赛道、粉丝规模与合作状态。"
    boundary-note="数据按租户隔离；联系方式仅脱敏回显，新增与停用需达人管理权限。"
    entity-label="达人"
    :loader="fetchInfluencers"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="createInfluencer"
    :status-handler="updateInfluencerStatus"
    create-permission="influencers.manage"
    manage-permission="influencers.manage"
  />
</template>

<script setup>
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import { createInfluencer, fetchInfluencers, updateInfluencerStatus } from '../../api/influencers';

const columns = [
  { prop: 'code', label: '达人编码', width: 150 }, { prop: 'name', label: '达人名称', width: 150 },
  { prop: 'platform', label: '平台', width: 110 }, { prop: 'handle', label: '账号', width: 150 },
  { prop: 'category', label: '内容赛道', width: 130 }, { prop: 'follower_count', label: '粉丝数', width: 110 },
  { prop: 'cooperation_status', label: '合作状态', width: 120 },
  { prop: 'contact_phone_masked', label: '联系电话', width: 130 }, { prop: 'status', label: '状态', type: 'status' }
];
const formFields = [
  { key: 'code', label: '达人编码', required: true }, { key: 'name', label: '达人名称', required: true },
  { key: 'platform', label: '平台', required: true }, { key: 'handle', label: '平台账号' },
  { key: 'category', label: '内容赛道' }, { key: 'follower_count', label: '粉丝数', type: 'number' },
  { key: 'contact_name', label: '商务联系人' }, { key: 'contact_phone', label: '联系电话' },
  { key: 'contact_email', label: '联系邮箱' },
  { key: 'cooperation_status', label: '合作状态', type: 'select', options: [
    { label: '待接洽', value: 'prospect' }, { label: '已联系', value: 'contacted' },
    { label: '合作中', value: 'cooperating' }, { label: '已暂停', value: 'paused' }
  ] },
  { key: 'notes', label: '备注', type: 'textarea' }
];
</script>
