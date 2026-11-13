<template>
  <main class="inbound-result">
    <h1>入库结果</h1>
    <p v-if="loading" role="status">正在读取入库结果…</p>
    <p v-else-if="error" role="alert">{{ error }}</p>
    <template v-else-if="receipt">
      <h2>{{ receipt.number }}</h2>
      <p>{{ receipt.country }} · {{ receipt.warehouse }} · 发运批次 {{ receipt.batch_number }}</p>
      <p v-if="receipt.confirmed_at">确认时间 {{ new Date(receipt.confirmed_at).toLocaleString('zh-CN') }}</p>
      <dl>
        <div><dt>应收</dt><dd>{{ expected }}</dd></div>
        <div><dt>实收</dt><dd>{{ received }}</dd></div>
        <div><dt>差异</dt><dd>{{ received - expected }}</dd></div>
      </dl>
      <div class="table-scroll">
        <table>
          <thead><tr><th>SKU</th><th>商品</th><th>应收</th><th>实收</th><th>差异</th></tr></thead>
          <tbody>
            <tr v-for="(line, index) in receipt.lines" :key="index">
              <td>{{ line.sku }}</td><td>{{ line.name }}<small v-if="line.extra">额外实收</small></td>
              <td>{{ line.expected }}</td><td>{{ line.received }}</td><td>{{ line.received - line.expected }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </main>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { requestApi } from '../../api/request';

const route = useRoute();
const receipt = ref(null);
const loading = ref(false);
const error = ref('');
const expected = computed(() => receipt.value?.lines.reduce((sum, row) => sum + row.expected, 0) ?? 0);
const received = computed(() => receipt.value?.lines.reduce((sum, row) => sum + row.received, 0) ?? 0);

watch(() => route.params.token, async (token, _, onCleanup) => {
  let current = true;
  onCleanup(() => { current = false; });
  receipt.value = null;
  error.value = '';
  loading.value = true;
  try {
    const result = await requestApi({
      method: 'get',
      url: `/api/internal/supply-chain/v2/inbound-results/${encodeURIComponent(token)}/`,
    });
    if (current) {
      if (result.success) receipt.value = result.data;
      else error.value = result.message || '无法读取入库结果。';
    }
  } catch {
    if (current) error.value = '无法读取入库结果，请检查登录状态或链接。';
  } finally {
    if (current) loading.value = false;
  }
}, { immediate: true });
</script>

<style scoped>
.inbound-result { max-width: 920px; margin: 0 auto; padding: 24px 16px; color: #243247; }
h1 { font-size: 26px; } h2 { font-size: 18px; }
dl { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
dl div { background: #eff5fc; border-radius: 8px; padding: 12px; }
dd { margin: 4px 0 0; font-size: 22px; font-weight: 650; }
.table-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; min-width: 450px; }
th, td { text-align: left; border-bottom: 1px solid #dce4ef; padding: 10px; }
th { background: #f4f7fb; }
small { display: block; color: #475569; }
</style>
