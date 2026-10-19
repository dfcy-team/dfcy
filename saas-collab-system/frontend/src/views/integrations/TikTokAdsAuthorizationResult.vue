<script setup>
import { ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { completeAdsOAuth, getAdsSession } from '../../api/tiktokAds';
import TikTokAdsSessionPanel from '../../components/TikTokAdsSessionPanel.vue';
import { takeAdsReceipt, validAdsSessionId } from '../../utils/tiktokAdsBridge';
let receipt = takeAdsReceipt();
const sessionId = ref('');
const ready = ref(false);
const message = ref('正在完成独立广告授权，请勿刷新或重复提交。');
const router = useRouter();
const route = useRoute();
let generation = 0;
watch(() => route.query, async (query) => {
  const current = ++generation;
  ready.value = false;
  const resumeId = Object.keys(query).length === 1 ? validAdsSessionId(query.session_id) : '';
  const pending = receipt;
  receipt = null;
  sessionId.value = resumeId;
  let receiptId = pending?.session_id === resumeId ? pending.receipt_id : '';
  if (pending) pending.receipt_id = '';
  if (!resumeId) { message.value = '未找到有效的广告授权记录，请返回原店铺重新进入。'; return; }
  const completing = /^[0-9a-f]{64}$/.test(receiptId);
  message.value = completing ? '正在完成独立广告授权，请勿重复提交。' : '正在恢复广告授权状态，不会再次兑换授权码。';
  try {
    const result = completing
      ? await completeAdsOAuth({ session_id: resumeId, receipt_id: receiptId })
      : await getAdsSession(resumeId);
    const snapshot = result.success || !completing ? result : await getAdsSession(resumeId);
    if (current !== generation) return;
    ready.value = Boolean(snapshot.success);
    message.value = snapshot.success ? '请逐个验证并选择要绑定的广告账户。尚未同步任何报表。' : '结果未确认或登录失效，请返回原店铺核对，不要重复提交回执。';
  } catch { if (current === generation) message.value = '网络中断，结果尚未确认。可刷新本页读取状态，不要重复提交。'; }
  finally { receiptId = ''; }
}, { immediate: true });
</script>
<template>
  <main style="max-width:1100px;margin:40px auto;padding:24px">
    <h1>TikTok Ads 独立授权</h1><p>{{ message }}</p>
    <p v-if="sessionId">可收藏此页；刷新后只读取授权状态，不会重复兑换。</p>
    <TikTokAdsSessionPanel v-if="ready" :key="sessionId" :session-id="sessionId" />
    <el-button @click="router.replace('/master-data/stores')">返回店铺档案</el-button>
  </main>
</template>
