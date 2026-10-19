<script setup>
import { onBeforeUnmount, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { getAdsSession, discoverAds, verifyAds, bindAds } from '../api/tiktokAds';
const props = defineProps({ sessionId: { type: String, required: true } });
const emit = defineEmits(['bound']);
const session = ref(null);
const busy = ref(false);
const autoVerifying = ref(false);
const selected = ref([]);
const error = ref('');
let bindingKey = '';
let generation = 0;
const statusLabel = value => ({ pending: '等待授权', exchanging: '正在确认授权', authorized: '授权已保存，系统自动核验后可确认绑定',
  unknown: '结果待核对，请勿重复提交', failed: '授权未完成', bound: '已绑定，同步未启用' }[value] || '读取中');
const verifyLabel = value => ({ verified: '已验证', unverified: '待验证', failed: '验证未通过' }[value] || '待验证');
const reasonLabel = value => value === 'account_verification_failed' ? '无法自动确认账户权限或币种时区，请重试验证' : value ? '请核对账户权限后重试' : '无';
function accept(response, currentGeneration, sessionId) {
  if (currentGeneration !== generation) return false;
  if (!response?.success || response.data?.session_id !== sessionId) {
    error.value = '操作未完成，请刷新授权状态，核对权限或配置；不要重复提交回执。';
    return false;
  }
  session.value = response.data;
  return true;
}
async function verifyPending(currentGeneration, sessionId) {
  if (session.value?.status !== 'authorized' || session.value.discovery_failed) return;
  const pending = (session.value.candidates || []).filter(row => row.verify_state === 'unverified');
  if (!pending.length) return;
  autoVerifying.value = true;
  try {
    // Keep the server's permission, expiry and account-membership checks authoritative.
    for (const candidate of pending) {
      if (currentGeneration !== generation || session.value?.status !== 'authorized') return;
      if (!session.value.candidates.some(row => row.advertiser_id === candidate.advertiser_id && row.verify_state === 'unverified')) continue;
      const response = await verifyAds(sessionId, candidate.advertiser_id);
      if (!accept(response, currentGeneration, sessionId)) return;
    }
    if ((session.value.candidates || []).some(row => row.verify_state === 'failed')) {
      error.value = '部分账户未通过自动验证，请查看原因后重试；不会自动绑定或开启同步。';
    }
  } finally {
    if (currentGeneration === generation) autoVerifying.value = false;
  }
}
async function run(operation, currentGeneration = generation) {
  if (busy.value) return;
  const sessionId = props.sessionId;
  busy.value = true;
  error.value = '';
  try {
    const response = await operation();
    if (!accept(response, currentGeneration, sessionId)) return false;
    if (response.data.discovery_failed) error.value = '授权已保存，但账户发现失败；可安全重试发现。';
    await verifyPending(currentGeneration, sessionId);
    return currentGeneration === generation;
  } catch {
    if (currentGeneration === generation) error.value = '网络异常，自动验证可能尚未完成；请刷新会话状态，不要重放授权回执。';
    return false;
  } finally { if (currentGeneration === generation) busy.value = false; }
}
watch(() => props.sessionId, () => {
  generation += 1;
  session.value = null;
  busy.value = false;
  autoVerifying.value = false;
  selected.value = [];
  bindingKey = '';
  run(() => getAdsSession(props.sessionId));
}, { immediate: true });
onBeforeUnmount(() => { generation += 1; });
async function bindSelected() {
  bindingKey ||= crypto.randomUUID();
  const completed = await run(() => bindAds(props.sessionId, { advertiser_ids: selected.value.map((c) => c.advertiser_id), idempotency_key: bindingKey }));
  if (completed && session.value?.status === 'bound') { ElMessage.success('广告账户已绑定，同步仍未启用。'); emit('bound'); }
}
</script>
<template>
  <section v-loading="busy" aria-label="TikTok Ads 授权会话">
    <p>授权状态：{{ statusLabel(session?.status) }}。账户可访问不代表报表已入库；绑定不会启用同步。</p>
    <p v-if="autoVerifying" role="status">正在自动核验账户权限、币种和时区，请稍候；无需逐个点击验证。</p>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" />
    <el-button :disabled="busy" @click="run(() => getAdsSession(sessionId))">刷新会话状态</el-button>
    <el-button :disabled="busy || session?.status !== 'authorized'" @click="run(() => discoverAds(sessionId))">重新发现广告账户</el-button>
    <el-table :data="session?.candidates || []" row-key="advertiser_id" @selection-change="selected = $event; bindingKey = ''">
      <el-table-column type="selection" :selectable="row => !busy && row.verify_state === 'verified' && session?.status === 'authorized'" />
      <el-table-column prop="name" label="账户名称" />
      <el-table-column prop="advertiser_id" label="广告户 ID" min-width="170" />
      <el-table-column prop="currency" label="币种" />
      <el-table-column prop="timezone" label="时区" min-width="150" />
      <el-table-column label="验证状态"><template #default="{ row }">{{ verifyLabel(row.verify_state) }}</template></el-table-column>
      <el-table-column label="原因"><template #default="{ row }">{{ reasonLabel(row.reason) }}</template></el-table-column>
      <el-table-column label="操作"><template #default="{ row }">
        <el-button link :disabled="busy || session?.status !== 'authorized'" @click="run(() => verifyAds(sessionId, row.advertiser_id))">验证账户</el-button>
      </template></el-table-column>
    </el-table>
    <el-button type="primary" :disabled="busy || !selected.length || session?.status !== 'authorized'" @click="bindSelected">确认绑定所选已验证账户</el-button>
  </section>
</template>
