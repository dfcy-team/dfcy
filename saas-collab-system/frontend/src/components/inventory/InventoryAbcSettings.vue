<template>
  <el-card class="settings-card" shadow="never">
    <template #header><h2>ABC 分类设置</h2></template>
    <p>按国家分别计算销售额与销量 ABC，再结合持续销售情况形成综合等级；SPU 与 SKU 独立评价。销售额 A 优先保障；销量 A 持续销售且未见明显集中成交时进入综合 A，否则先列 B。新品和资料不足单列。销售额、销量共用分档阈值。持续销售参考近 12 周至少 6 周、近 4 周至少 3 周有成交；单笔占比达到 30% 或单日达到 40% 时提示集中成交。</p>
    <p v-if="loading" role="status">正在读取…</p>
    <div v-if="loaded" class="abc-settings-fields">
      <label><span>ABC 分类</span><el-select v-model="state.abc_enabled" :disabled="disabled" style="width:140px"><el-option label="启用" :value="true"/><el-option label="停用" :value="false"/></el-select></label>
      <label v-for="field in fields" :key="field.key"><span>{{ field.label }}</span><el-input-number v-model="state[field.key]" :aria-label="field.label" :min="field.min" :max="field.max" :precision="field.precision" :disabled="disabled"/> {{ field.unit }}</label>
      <el-button v-if="canManage" type="primary" :loading="saving" :disabled="disabled || !dirty" @click="save">保存 ABC 设置</el-button>
    </div>
    <p v-if="feedback" role="status">{{ feedback }}</p>
  </el-card>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { requestApi } from '../../api/request';
import { useAuthStore } from '../../stores/auth';
const fields = [
  {key:'abc_window_days', label:'销售观察窗口', unit:'天', min:7, max:365, precision:0},
  {key:'abc_a_percent', label:'分项 A 类累计贡献占比', unit:'%', min:0.01, max:99.99, precision:2},
  {key:'abc_b_percent', label:'分项 A＋B 类累计贡献占比', unit:'%', min:0.02, max:100, precision:2},
  {key:'abc_stability_days', label:'新等级连续确认天数', unit:'天', min:1, max:14, precision:0},
];
const endpoint = '/api/internal/master-data/inventory-observation-settings/';
const auth = useAuthStore();
const state = ref({}), saved = ref(''), loaded = ref(false), loading = ref(false), saving = ref(false), feedback = ref('');
const canManage = computed(() => !auth.authorizationStale && auth.hasPermission('masterdata.settings.manage') && auth.hasAllDataScopeFor('masterdata.settings.manage'));
const disabled = computed(() => !loaded.value || !canManage.value || saving.value || loading.value);
const dirty = computed(() => JSON.stringify(state.value) !== saved.value);
let sequence = 0, controller;
function extract(data) {
  if (typeof data?.abc_enabled !== 'boolean') throw Error('ABC 参数数据不完整。');
  const values = {abc_enabled: data.abc_enabled};
  for (const f of fields) {
    const n = Number(data[f.key]);
    if (data[f.key] == null || !Number.isFinite(n) || n < f.min || n > f.max || (f.precision === 0 && !Number.isInteger(n))) throw Error('ABC 参数数据不完整。');
    values[f.key] = n;
  }
  if (values.abc_a_percent >= values.abc_b_percent) throw Error('ABC 参数数据无效。');
  return values;
}
async function load() {
  controller?.abort(); controller = new AbortController();
  const signal = controller.signal;
  const token = ++sequence;
  loaded.value = false; state.value = {}; saved.value = ''; feedback.value = ''; saving.value = false;
  if (auth.authorizationStale || !auth.currentUser) { loading.value = false; return; }
  loading.value = true;
  try {
    const response = await requestApi({method:'get', url:endpoint, signal});
    if (token !== sequence || auth.authorizationStale) return;
    if (!response?.success) throw Error(response?.message || 'ABC 参数加载失败。');
    state.value = extract(response.data); saved.value = JSON.stringify(state.value); loaded.value = true;
  } catch (error) { if (token === sequence) feedback.value = error.message; }
  finally { if (token === sequence) loading.value = false; }
}
async function save() {
  if (disabled.value || !dirty.value) return;
  let payload;
  try { payload = extract(state.value); } catch (error) { feedback.value = error.message; return; }
  controller?.abort(); controller = new AbortController();
  const signal = controller.signal;
  const token = ++sequence;
  saving.value = true; feedback.value = '';
  try {
    const response = await requestApi({method:'put', url:endpoint, data:payload, signal});
    if (token !== sequence || auth.authorizationStale) return;
    if (!response?.success) throw Error(response?.message || 'ABC 参数保存失败。');
    state.value = extract(response.data); saved.value = JSON.stringify(state.value);
    feedback.value = 'ABC 参数已保存。可在库存页面重新计算，或等待每日自动更新。';
  } catch (error) { if (token === sequence) feedback.value = error.message; }
  finally { if (token === sequence) saving.value = false; }
}
watch(() => [auth.authorizationStale, auth.currentUser], load, {immediate:true, deep:true, flush:'sync'});
onBeforeUnmount(() => { sequence++; controller?.abort(); });
</script>
<style scoped>
h2{margin:0;font-size:18px}.abc-settings-fields{display:flex;flex-wrap:wrap;gap:18px;align-items:flex-end}.abc-settings-fields label>span{display:block;margin-bottom:8px}
</style>
