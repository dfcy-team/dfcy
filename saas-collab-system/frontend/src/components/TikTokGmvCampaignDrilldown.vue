<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue';
import { fetchTikTokDailySpend } from '../api/advertising';

const props = defineProps({ subjects: { type: Array, default: () => [] }, dateFrom: String, dateTo: String, advertiserId: String });
const store = ref('');
const kind = ref('all');
const campaigns = ref([]);
const selected = ref(null);
const loading = ref(false);
const error = ref('');
const root = ref(null);
let sequence = 0;
const stores = computed(() => [...new Map(props.subjects.map(s => [s.store_id, s])).values()]);
const rows = computed(() => campaigns.value.filter(c => kind.value === 'all' || c.campaign_type === kind.value));
function clear() {
  sequence++;
  campaigns.value = [];
  selected.value = null;
  error.value = '';
  loading.value = false;
}
watch(() => [store.value, props.dateFrom, props.dateTo, props.subjects, props.advertiserId], clear, { flush: 'sync' });
watch(kind, () => { selected.value = null; });
onBeforeUnmount(clear);
function openStore(id) {
  store.value = id;
  kind.value = 'all';
  root.value?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  return load();
}
defineExpose({ openStore });
async function load() {
  clear();
  if (!store.value) return;
  const current = sequence;
  loading.value = true;
  try {
    const response = await fetchTikTokDailySpend({ report_type: 'gmv_max_campaigns', store_id: store.value,
      date_from: props.dateFrom, date_to: props.dateTo, ...(props.advertiserId ? { advertiser_id: props.advertiserId } : {}) });
    if (current !== sequence) return;
    if (!response.success) throw new Error(response.message || '计划查询失败');
    if (response.data.warnings?.length) throw new Error('快照数量超出安全范围，请缩短日期范围。');
    campaigns.value = response.data.campaigns || [];
  } catch (e) {
    if (current === sequence) error.value = e.code === 'ECONNABORTED' ? '计划查询超时，请缩短日期范围后重试。' : (e.message || '计划查询失败');
  } finally {
    if (current === sequence) loading.value = false;
  }
}
</script>

<template>
  <section ref="root" class="campaign-drilldown">
    <h2>GMV Max 计划列表与详情</h2>
    <p>沿用上方日期范围，仅查询已存快照。现有快照未保存计划名称及商品／直播类型，统一标记未知，不推断分类。</p>
    <el-select v-model="store" placeholder="选择店铺" aria-label="计划店铺" style="width: 220px">
      <el-option v-for="s in stores" :key="s.store_id" :value="s.store_id" :label="s.store_code" />
    </el-select>
    <el-select v-model="kind" aria-label="计划类型" style="width: 180px">
      <el-option label="全部计划" value="all" />
      <el-option label="商品计划" value="product" />
      <el-option label="直播计划" value="live" />
      <el-option label="类型未知" value="unknown" />
    </el-select>
    <el-button :loading="loading" :disabled="!store" @click="load">查询计划</el-button>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-table :data="rows" border v-loading="loading">
      <el-table-column prop="campaign_id" label="计划 ID" min-width="180" />
      <el-table-column label="计划名称 / 类型"><template #default="{ row }">{{ row.campaign_name || '名称未知' }} / {{ row.campaign_type === 'unknown' ? '类型未知' : row.campaign_type }}</template></el-table-column>
      <el-table-column prop="advertiser_id" label="广告户 ID" min-width="180" />
      <el-table-column prop="currency" label="币种" />
      <el-table-column prop="cost" label="消耗" />
      <el-table-column prop="gross_revenue" label="报表收入" />
      <el-table-column prop="orders" label="报表订单" />
      <el-table-column label="操作"><template #default="{ row }"><el-button link type="primary" @click="selected = row">查看详情</el-button></template></el-table-column>
    </el-table>
    <section v-if="selected" class="campaign-detail">
      <h3>计划详情：{{ selected.campaign_id }}</h3>
      <p>{{ selected.store_code }} · {{ selected.advertiser_id }} · {{ selected.currency }} · {{ selected.timezone }}</p>
      <p>账户快照覆盖 {{ selected.covered_days }}/{{ selected.expected_days }} 天；未出现计划的日期不自动补零。商品及视频独立明细尚未接入。</p>
      <p>ROI：{{ selected.roi ?? '—' }}；平均下单成本：{{ selected.cost_per_order ?? '—' }}</p>
      <el-table :data="selected.days" border>
        <el-table-column prop="date" label="日期" />
        <el-table-column prop="cost" label="消耗" />
        <el-table-column prop="gross_revenue" label="报表收入" />
        <el-table-column prop="orders" label="报表订单" />
        <el-table-column prop="snapshot_id" label="来源快照" />
        <el-table-column prop="fetched_at" label="采集时间" min-width="200" />
      </el-table>
    </section>
  </section>
</template>

<style scoped>
.campaign-drilldown { margin: 24px 0; }
.campaign-drilldown .el-select, .campaign-drilldown .el-button { margin: 0 8px 12px 0; }
.campaign-detail { margin-top: 20px; padding: 16px; border: 1px solid #dce3ef; }
</style>
