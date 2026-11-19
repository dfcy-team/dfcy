<template>
  <aside v-if="countryId" class="abc-status">
    <span>销售额 ABC · {{ statusLabel }}</span>
    <span v-if="meta?.cutoff_date"> · 截止 {{ meta.cutoff_date }} · 近 {{ meta.window_days }} 天</span>
    <span v-if="meta?.stale"> · 快照已过期</span>
    <span v-if="meta?.config_pending"> · 参数已调整，等待重算</span>
    <el-button link :disabled="busy" @click="load">更新状态</el-button>
    <el-button v-if="canManage" link :loading="busy" :disabled="meta?.enabled === false || pending" @click="rebuild">重新计算 ABC</el-button>
    <p v-if="feedback" role="status">{{ feedback }}</p>
  </aside>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { requestApi } from '../../api/request';
import { useAuthStore } from '../../stores/auth';

const props = defineProps({ countryId: [Number, String] });
const auth = useAuthStore();
const meta = ref(null), feedback = ref(''), busy = ref(false);
const canManage = computed(() => !auth.authorizationStale && auth.hasPermission('masterdata.settings.manage'));
const pending = computed(() => ['queued', 'building'].includes(meta.value?.latest_status));
const statusLabel = computed(() => {
  if (meta.value?.enabled === false) return '分类已停用';
  if (pending.value) return '等待后台更新';
  if (meta.value?.status === 'ready') return '完整等级';
  if (meta.value?.status === 'partial') return '参考等级，资料尚未齐全';
  return '尚无完整分类结果';
});
const endpoint = '/api/internal/commerce/inventory/abc/';
let sequence = 0, timer, attempts = 0;

async function load() {
  clearTimeout(timer);
  if (!Number(props.countryId) || auth.authorizationStale) return;
  const token = ++sequence;
  try {
    const response = await requestApi({ method: 'get', url: endpoint, params: { country_id: Number(props.countryId) } });
    if (token !== sequence) return;
    if (!response?.success) throw new Error(response?.message || 'ABC 状态读取失败。');
    meta.value = response.data;
    if (pending.value && attempts++ < 40) timer = setTimeout(load, 15000);
  } catch (error) {
    if (token === sequence) feedback.value = error.message;
  }
}
async function rebuild() {
  if (!canManage.value || !Number(props.countryId) || busy.value || pending.value) return;
  const token = ++sequence;
  clearTimeout(timer);
  busy.value = true;
  feedback.value = '';
  try {
    const response = await requestApi({ method: 'post', url: endpoint, data: { country_id: Number(props.countryId) } });
    if (token !== sequence) return;
    if (!response?.success) throw new Error(response?.message || '提交失败。');
    feedback.value = '已提交后台计算，完成后重新查询即可读取新等级。';
    attempts = 0;
    await load();
  } catch (error) {
    if (token === sequence) feedback.value = error.message;
  } finally {
    busy.value = false;
  }
}
watch(() => [props.countryId, auth.authorizationStale], () => {
  clearTimeout(timer);
  sequence++;
  attempts = 0;
  meta.value = null;
  feedback.value = '';
  load();
}, { immediate: true });
onBeforeUnmount(() => { clearTimeout(timer); sequence++; });
</script>
<style scoped>
.abc-status{margin:10px 0;padding:8px 12px;background:#f5f8fc;border:1px solid #e2e9f2;border-radius:6px;color:#52677e;font-size:12px}
.abc-status p{margin:4px 0 0}
</style>
