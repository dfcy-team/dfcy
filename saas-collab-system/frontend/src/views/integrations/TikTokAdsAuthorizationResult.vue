<script setup>
import { onBeforeUnmount, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { completeAdsDirectOAuth, getAdsSession } from '../../api/tiktokAds';
import TikTokAdsSessionPanel from '../../components/TikTokAdsSessionPanel.vue';
import { takeAdsReceipt, validAdsSessionId } from '../../utils/tiktokAdsBridge';
import { takeAdsDirectCallback, takeAdsManualReturnUrl, clearAdsManualReturn, ADS_DIRECT_PATH } from '../../utils/tiktokAdsDirect';
import { adsSessionUrl } from '../../utils/tiktokAdsBridge';
let receipt = takeAdsReceipt();
let direct = null;
try { direct = takeAdsDirectCallback(); } catch { /* Unavailable tab storage must not submit a callback. */ }
let manualReturnUrl = direct ? '' : takeAdsManualReturnUrl();
const canCopyReturn = ref(Boolean(manualReturnUrl));
onBeforeUnmount(() => { manualReturnUrl = ''; canCopyReturn.value = false; clearAdsManualReturn(); });
async function copyManualReturn() {
  if (!canCopyReturn.value || !manualReturnUrl) return;
  canCopyReturn.value = false;
  try {
    await navigator.clipboard.writeText(manualReturnUrl);
    message.value = '回调 URL 已复制，请返回原标签页粘贴。不要分享给他人；本页未提交授权。';
  } catch {
    message.value = '复制失败，回调已从本页清除。请返回原标签页重新准备授权，不要重复兑换旧授权码。';
  } finally { manualReturnUrl = ''; clearAdsManualReturn(); }
}
const sessionId = ref('');
const ready = ref(false);
const message = ref('正在完成独立广告授权，请勿刷新或重复提交。');
const router = useRouter();
const route = useRoute();
let generation = 0;
watch(() => route.query, async (query) => {
  const current = ++generation;
  ready.value = false;
  if (canCopyReturn.value) {
    message.value = '此标签页没有原授权会话证明，未提交授权。请复制回调 URL，返回准备手动授权的原标签页粘贴。刷新后无法恢复，请勿分享。';
    return;
  }
  const directPayload = direct;
  direct = null;
  if (directPayload) {
    receipt = null;
    try {
      const result = await completeAdsDirectOAuth(directPayload);
      if (current !== generation) return;
      const id = result.success ? validAdsSessionId(result.data?.session_id) : '';
      if (!id) { message.value = '广告授权结果尚未确认，请返回原店铺核对，不要重复提交授权码。'; return; }
      sessionId.value = id;
      await router.replace(adsSessionUrl(id));
      if (current !== generation) return;
      ready.value = true;
      message.value = '请逐个验证并选择要绑定的广告账户。尚未同步任何报表。';
    } catch {
      if (current === generation) message.value = '网络中断，结果尚未确认。请返回原店铺核对，不要重复提交授权码。';
    }
    return;
  }
  if (route.path === ADS_DIRECT_PATH) {
    message.value = '本标签页授权会话已过期或结果尚未确认，请返回原店铺核对，不要重复提交授权码。';
    return;
  }
  const resumeId = Object.keys(query).length === 1 ? validAdsSessionId(query.session_id) : '';
  const pending = receipt;
  receipt = null;
  sessionId.value = resumeId;
  if (pending) {
    pending.receipt_id = '';
    message.value = '旧版中转回执已停用，请返回原店铺重新发起 SaaS 直连授权。';
    return;
  }
  if (!resumeId) { message.value = '未找到有效的广告授权记录，请返回原店铺重新进入。'; return; }
  message.value = '正在恢复广告授权状态，不会再次兑换授权码。';
  try {
    const snapshot = await getAdsSession(resumeId);
    if (current !== generation) return;
    ready.value = Boolean(snapshot.success);
    message.value = snapshot.success ? '请逐个验证并选择要绑定的广告账户。尚未同步任何报表。' : '结果未确认或登录失效，请返回原店铺核对，不要重复提交回执。';
  } catch { if (current === generation) message.value = '网络中断，结果尚未确认。可刷新本页读取状态，不要重复提交。'; }
}, { immediate: true });
</script>
<template>
  <main style="max-width:1100px;margin:40px auto;padding:24px">
    <h1>TikTok Ads 独立授权</h1><p>{{ message }}</p>
    <el-button v-if="canCopyReturn" @click="copyManualReturn">复制回调URL，返回原标签页粘贴</el-button>
    <p v-if="sessionId">可收藏此页；刷新后只读取授权状态，不会重复兑换。</p>
    <TikTokAdsSessionPanel v-if="ready" :key="sessionId" :session-id="sessionId" />
    <el-button @click="router.replace('/master-data/stores')">返回店铺档案</el-button>
  </main>
</template>
