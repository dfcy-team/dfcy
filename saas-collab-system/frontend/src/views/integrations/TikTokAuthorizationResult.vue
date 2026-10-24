<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { completeTikTokDirectAuthorization, fetchTikTokShopBinding, confirmTikTokShopBinding, cancelTikTokShopBinding } from '../../api/integrations';
import { useAuthStore } from '../../stores/auth';
import { takeTikTokReceipt, takeTikTokDirectCallback, takeTikTokManualReturnUrl, clearTikTokManualReturn, isTikTokBindingId, TK_RESULT_PATH } from '../../utils/tiktokBrowserBridge';
import { tiktokCallbackFeedback } from '../../utils/tiktokCallbackFeedback';
import { tiktokTokenFailure } from '../../utils/tiktokTokenFailure';

const auth = useAuthStore();
const router = useRouter();
const route = useRoute();
const busy = ref(true);
const success = ref(false);
const message = ref('正在核验本次 TikTok 店铺授权，请勿重复提交。');
const binding = ref(null);
const savedTarget = ref(null);
// Callback material stays outside reactive/app/router state and is never rendered.
let manualReturnUrl = '';
const canCopyReturn = ref(false);
onBeforeUnmount(() => { manualReturnUrl = ''; canCopyReturn.value = false; clearTikTokManualReturn(); });
async function copyManualReturn() {
  if (!canCopyReturn.value || !manualReturnUrl) return;
  canCopyReturn.value = false;
  try {
    await navigator.clipboard.writeText(manualReturnUrl);
    message.value = '回调 URL 已复制，请返回原标签页粘贴。不要分享给他人；本页未提交授权。';
  } catch {
    message.value = '复制失败，回调已从本页清除。请返回原标签页重新准备授权，不要重复兑换旧授权码。';
  } finally { manualReturnUrl = ''; clearTikTokManualReturn(); }
}
const selectedShop = ref('');
const canConfirm = computed(() => binding.value?.status === 'pending_confirmation'
  && Date.parse(binding.value.expires_at) > Date.now()
  && binding.value.candidates.some((item) => item.platform_store_id === selectedShop.value));

async function acceptResponse(response, bindingOnly = false) {
  const data = response?.data;
  success.value = false;
  savedTarget.value = null;
  if (response?.success && data?.status === 'pending_confirmation') {
    if (!isTikTokBindingId(data.binding_id) || !Array.isArray(data.candidates)
        || !data.candidates.every((item) => typeof item.platform_store_id === 'string' && item.platform_store_id)) {
      throw new Error('Invalid binding response');
    }
    binding.value = data;
    selectedShop.value = '';
    await router.replace({ path: TK_RESULT_PATH, query: { binding_id: data.binding_id } });
    message.value = '请核对目标 SaaS 店铺，并手动选择一个 TikTok 店铺确认绑定。即使只有一个候选店铺，也需要确认。不会开启数据同步。';
    return;
  }
  binding.value = null;
  if (response?.success && data?.status === 'bound' && data.authorization) {
    success.value = true;
    if (data.store_code && data.store_name && data.authorization.platform_store_id) {
      savedTarget.value = {
        store_code: data.store_code,
        store_name: data.store_name,
        platform_store_id: data.authorization.platform_store_id,
      };
    }
    message.value = 'TikTok 店铺授权已保存到发起本次授权的 SaaS 店铺。尚未执行数据同步。';
  } else if (response?.success && !bindingOnly && data?.status === 'active') {
    success.value = true;
    message.value = 'TikTok 店铺授权已保存。尚未执行数据同步。';
  } else {
    const feedback = tiktokCallbackFeedback(response);
    message.value = tiktokTokenFailure(response)?.message || feedback.message;
  }
}

async function actOnBinding(action) {
  if (busy.value || !binding.value || action === 'confirm'
      && (!canConfirm.value || Date.parse(binding.value.expires_at) <= Date.now())) return;
  const id = binding.value.binding_id;
  busy.value = true;
  try {
    const response = action === 'confirm'
      ? await confirmTikTokShopBinding(id, selectedShop.value)
      : await cancelTikTokShopBinding(id);
    if (action === 'cancel' && response?.success) {
      binding.value = null;
      message.value = '已取消本次店铺绑定，未开启数据同步。';
    } else await acceptResponse(response, true);
  } catch {
    binding.value = null;
    message.value = '请求结果尚未确认。请刷新本页只读核对绑定状态，不要重复提交。';
  } finally { busy.value = false; }
}

onMounted(async () => {
  let receipt = takeTikTokReceipt();
  let direct = null;
  try {
    direct = takeTikTokDirectCallback();
    if (!direct) {
      manualReturnUrl = takeTikTokManualReturnUrl();
      if (manualReturnUrl) {
        canCopyReturn.value = true;
        message.value = '此标签页没有原授权会话证明，未提交授权。请复制回调 URL，返回准备手动授权的原标签页粘贴。刷新后无法恢复，请勿分享。';
        return;
      }
    }
    const bindingId = route.query.binding_id;
    if (!auth.isAuthenticated) {
      message.value = '授权结果已过期、页面已刷新或登录失效。请回到店铺重新发起授权，不要重复使用原回调。';
      return;
    }
    if (direct) {
      await acceptResponse(await completeTikTokDirectAuthorization(direct));
    } else if (receipt) {
      message.value = '旧版中转回执已停用，请返回店铺重新发起 SaaS 直连授权。';
    } else if (isTikTokBindingId(bindingId)) {
      await acceptResponse(await fetchTikTokShopBinding(bindingId), true);
    } else {
      message.value = '授权结果已过期、页面已刷新或登录失效。请回到店铺重新发起授权，不要重复使用原回调。';
    }
  } catch {
    message.value = '网络中断或请求超时，授权结果尚未确认。请回到店铺核对状态，不要重复提交原授权码。';
  } finally {
    receipt = '';
    direct = null;
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
      <section v-if="savedTarget" class="saved-target" aria-label="已保存的目标店铺">
        <h2>已保存到发起店铺</h2>
        <p>SaaS 店铺：{{ savedTarget.store_name }} / {{ savedTarget.store_code }}</p>
        <p>TikTok 店铺 ID：{{ savedTarget.platform_store_id }}</p>
      </section>
      <el-button v-if="canCopyReturn" :disabled="busy" @click="copyManualReturn">复制回调URL，返回原标签页粘贴</el-button>
      <section v-if="binding" class="binding-confirmation">
        <h2>确认店铺绑定</h2>
        <p>目标 SaaS 店铺：{{ binding.store_name }} / {{ binding.store_code }} / {{ binding.store_id }} / {{ binding.region }}</p>
        <p>有效期至：{{ binding.expires_at }}</p>
        <fieldset :disabled="busy">
          <legend>选择 TikTok 店铺</legend>
          <label v-for="candidate in binding.candidates" :key="candidate.platform_store_id" class="shop-choice">
            <input v-model="selectedShop" type="radio" name="tiktok-shop" :value="candidate.platform_store_id">
            {{ candidate.name }} / {{ candidate.platform_store_id }} / {{ candidate.region }}
          </label>
        </fieldset>
        <el-button type="primary" :disabled="busy || !canConfirm" @click="actOnBinding('confirm')">确认绑定所选店铺</el-button>
        <el-button :disabled="busy" @click="actOnBinding('cancel')">取消绑定</el-button>
      </section>
      <el-button type="primary" :disabled="busy" @click="router.replace('/master-data/stores')">返回店铺档案</el-button>
    </section>
  </main>
</template>

<style scoped>
.tk-result-page{min-height:100vh;display:grid;place-items:center;padding:24px;background:#f5f7fb}.tk-result-card{width:min(100%,560px);padding:32px;border:1px solid #d8e1ec;border-radius:12px;background:#fff}.eyebrow{color:#0c7668;font-weight:700}.tk-result-card h1{margin:12px 0 20px}.tk-result-card p{line-height:1.8;color:#536479}.tk-result-card button{margin-top:16px}
</style>

<style scoped>
.shop-choice{display:flex;gap:10px;align-items:center;margin:12px 0;overflow-wrap:anywhere}.binding-confirmation fieldset{border:1px solid #d8e1ec;border-radius:8px}.binding-confirmation p{overflow-wrap:anywhere}
</style>
