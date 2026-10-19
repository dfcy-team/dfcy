<script setup>
import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { completeTikTokBrowserAuthorization } from '../../api/integrations';
import { useAuthStore } from '../../stores/auth';
import { takeTikTokReceipt } from '../../utils/tiktokBrowserBridge';
import { tiktokTokenFailure } from '../../utils/tiktokTokenFailure';

const auth = useAuthStore();
const router = useRouter();
const busy = ref(true);
const success = ref(false);
const message = ref('正在核验本次 TikTok 店铺授权，请勿重复提交。');

onMounted(async () => {
  let receipt = takeTikTokReceipt();
  try {
    if (!receipt || !auth.isAuthenticated) {
      message.value = '授权结果已过期、页面已刷新或登录失效。请回到店铺重新发起授权，不要重复使用原回调。';
      return;
    }
    const response = await completeTikTokBrowserAuthorization({ receipt_token: receipt });
    const tokenFailure = tiktokTokenFailure(response);
    if (response?.success) {
      success.value = true;
      message.value = 'TikTok 店铺授权已保存到当前 SaaS 租户。尚未执行数据同步。';
    } else if (response?.data?.reason_code === 'OAUTH_STATE_CONSUMED') {
      message.value = '本次授权结果已处理，请回到店铺核对授权时间与状态；不会再次兑换授权码。';
    } else if (tokenFailure) {
      message.value = tokenFailure.message;
    } else {
      message.value = '本次授权未完成，或结果尚未确认。请先回到店铺核对授权状态，再决定是否重新发起。';
    }
  } catch {
    message.value = '网络中断或请求超时，授权结果尚未确认。请回到店铺核对状态，不要重复提交原授权码。';
  } finally {
    receipt = '';
    busy.value = false;
  }
});
</script>

<template>
  <main class="tk-result-page">
    <section class="tk-result-card" aria-live="polite">
      <p class="eyebrow">TikTok Shop</p>
      <h1>{{ busy ? '正在完成店铺授权' : success ? '店铺授权已完成' : '请核对授权结果' }}</h1>
      <p>{{ message }}</p>
      <el-button type="primary" :disabled="busy" @click="router.replace('/master-data/stores')">返回店铺档案</el-button>
    </section>
  </main>
</template>

<style scoped>
.tk-result-page{min-height:100vh;display:grid;place-items:center;padding:24px;background:#f5f7fb}.tk-result-card{width:min(100%,560px);padding:32px;border:1px solid #d8e1ec;border-radius:12px;background:#fff}.eyebrow{color:#0c7668;font-weight:700}.tk-result-card h1{margin:12px 0 20px}.tk-result-card p{line-height:1.8;color:#536479}.tk-result-card button{margin-top:16px}
</style>
