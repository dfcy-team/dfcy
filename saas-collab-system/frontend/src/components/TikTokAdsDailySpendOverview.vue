<template>
  <AppPage :title="performance ? 'TikTok 广告投放分析' : 'TikTok 广告总览'" capability="只读已存数据"
    subtitle="默认查看马尼拉时间最近 7 个完整自然日；查询不会触发采集。"
    boundary-note="仅展示 GMV Max 已存数据。缺失数据不是零消耗；不同币种、时区不合并。当日数据尚未结束，仅供参考。">
    <el-form inline class="filters" @submit.prevent="load(1)">
      <el-form-item label="开始日期"><el-date-picker v-model="from" type="date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="结束日期"><el-date-picker v-model="to" type="date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="店铺">
        <el-select v-model="store" clearable placeholder="全部可见店铺" class="subject-select">
          <el-option v-for="item in stores" :key="item.store_id" :value="item.store_id" :label="item.store_code + ' ' + item.store_name" />
        </el-select>
      </el-form-item>
      <el-form-item label="广告账户">
        <el-select v-model="advertiser" clearable placeholder="全部可见广告账户" class="subject-select">
          <el-option v-for="item in advertisers" :key="item.mapping_id" :value="item.advertiser_id" :label="item.store_code + ' · ' + (item.advertiser_name || item.advertiser_id)" />
        </el-select>
      </el-form-item>
      <el-form-item><el-button type="primary" :loading="loading" @click="load(1)">查询已存数据</el-button></el-form-item>
    </el-form>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="report">
      <h2>GMV Max 店铺汇总（已入库）</h2>
      <label><input :checked="showAdvertisers" type="checkbox" @change="showAdvertisers = $event.target.checked" /> 按广告户查看（默认按店铺汇总）</label>
      <p class="coverage-note">广告户数和覆盖率按本区间有报表的广告户统计，不含历史关联户；缺失日期不补零。</p>
      <el-alert v-if="report.selected_subjects.some(s => !s.historical_binding_confirmed)" title="部分广告户缺少与当前店铺一致的历史绑定证据，未计入店铺汇总；原明细保留供核对。" type="warning" :closable="false" />
      <section v-for="item in (showAdvertisers ? report.gmv_max_overview : report.gmv_max_shop_overview) || []"
        :key="JSON.stringify([item.store_code, item.advertiser_id, item.platform_store_id, item.currency, item.timezone])" class="gmv-overview">
        <h3>{{ item.store_code }} · {{ showAdvertisers ? (item.advertiser_name || item.advertiser_id) : '店铺广告汇总' }}</h3>
        <p>{{ showAdvertisers ? item.advertiser_id : gmvCoverageLabel(item, report).accountCount + ' 个广告户' }} · {{ item.currency }} · {{ item.timezone }} · {{ report.date_from }} 至 {{ report.date_to }}</p>
        <div class="coverage-line">
          <el-tag :type="gmvCoverageLabel(item, report).type">{{ gmvCoverageLabel(item, report).label }}</el-tag>
          <el-tag v-if="collectionCount(item, 'failed')" type="danger">采集失败 {{ collectionCount(item, 'failed') }} 个广告户日，见下方明细</el-tag>
        </div>
        <div class="gmv-metrics">
          <div><span>成本</span><strong>{{ item.cost ?? '未知' }} {{ item.currency }}</strong></div>
          <div><span>SKU 订单数</span><strong>{{ item.orders ?? '未知' }}</strong></div>
          <div><span>平均下单成本</span><strong>{{ item.cost_per_order ?? '—' }} {{ item.currency }}</strong></div>
          <div><span>报表总收入</span><strong>{{ item.gross_revenue ?? '未知' }} {{ item.currency }}</strong></div>
          <div><span>ROI</span><strong>{{ item.roi ?? '—' }}</strong></div>
        </div>
      </section>
      <p>默认汇总同店铺、同币种、同时区的已存广告户报表，不要求配置主广告户。收入及订单为广告报表口径合计，不代表跨广告户去重的商城成交。ROI=收入合计/消耗合计；不同平台店铺身份、币种、时区分开，不与 BASIC 或商城 GMV 相加。</p>
      <h2>广告户每日明细与来源</h2>
      <el-alert v-if="performance" title="当前为 GMV Max 广告户日汇总，没有计划级表现数据；计划数不代表可查看计划、商品或视频明细。" type="info" :closable="false" class="notice" />
      <el-table :data="report.gmv_max_snapshots || []" border :empty-text="report.gmv_max_snapshots === null ? 'GMV Max 快照过多，缩小日期范围或店铺后重试；当前不显示金额。' : '尚无 GMV Max 快照，不代表零消耗。'">
        <el-table-column prop="date" label="日期" />
        <el-table-column prop="store_code" label="店铺" />
        <el-table-column prop="advertiser_name" label="广告户名称" />
        <el-table-column prop="advertiser_id" label="广告主 ID" min-width="180" />
        <el-table-column prop="currency" label="币种" />
        <el-table-column prop="cost" label="消耗" />
        <el-table-column prop="gross_revenue" label="报表收入" />
        <el-table-column prop="orders" label="报表订单" />
        <el-table-column label="ROI" :formatter="row => advertisingRatio(row.gross_revenue, row.cost)" />
        <el-table-column label="平均订单成本" :formatter="row => advertisingRatio(row.cost, row.orders)" />
        <el-table-column prop="campaign_count" label="计划数" />
        <el-table-column prop="timezone" label="报表时区" />
      </el-table>
      <h3>广告户每日采集状态</h3>
      <el-table :data="report.gmv_max_collection_days || []" border max-height="420" empty-text="暂无采集状态证据；不能判断为无广告数据。">
        <el-table-column prop="store_code" label="店铺" />
        <el-table-column prop="advertiser_id" label="广告户 ID" min-width="180" />
        <el-table-column prop="date" label="日期" min-width="120" />
        <el-table-column label="采集状态" min-width="200"><template #default="{ row }">
          <el-tag :type="row.status === 'failed' ? 'danger' : row.status === 'not_collected' ? 'warning' : 'success'">{{ collectionLabels[row.status] || '待核验' }}</el-tag>
        </template></el-table-column>
        <el-table-column label="原因" min-width="200"><template #default="{ row }">{{ collectionErrors[row.error_code] || (row.error_code ? '校验或采集失败，需检查同步记录' : '—') }}</template></el-table-column>
      </el-table>
      <el-alert v-for="warning in report.warnings" :key="warning" :title="warningLabels[warning] || warning" type="warning" :closable="false" show-icon class="notice" />
      <el-table :data="report.selected_subjects" border class="notice" empty-text="无可见账户">
        <el-table-column prop="store_code" label="店铺" />
        <el-table-column prop="advertiser_id" label="广告账户" min-width="180" />
        <el-table-column prop="advertiser_name" label="广告户名称" min-width="160" />
        <el-table-column label="采集开关（当前）"><template #default="{ row }"><el-tag :type="row.collection_enabled ? 'success' : 'info'">{{ row.collection_enabled ? '已开启' : '已关闭' }}</el-tag></template></el-table-column>
        <el-table-column label="本地绑定证据"><template #default="{ row }">{{ row.local_evidence === 'verified' ? '已核验' : '未核验' }}</template></el-table-column>
      </el-table>
    </template>
    <el-empty v-else-if="!loading && !error" description="请选择范围后查询已存数据" />
  </AppPage>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import AppPage from './AppPage.vue';
import { fetchTikTokDailySpend } from '../api/advertising';
import { advertisingRatio } from '../utils/advertisingRatio';
import { gmvCoverageLabel } from '../utils/gmvCoverageLabel';

const props = defineProps({ active: { type: Boolean, default: false }, performance: Boolean });
const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Manila', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
const part = (name) => parts.find((item) => item.type === name).value;
const today = Date.parse(part('year') + '-' + part('month') + '-' + part('day') + 'T00:00:00Z');
const from = ref(new Date(today - 7 * 86400000).toISOString().slice(0, 10));
const to = ref(new Date(today - 86400000).toISOString().slice(0, 10));
const store = ref('');
const advertiser = ref('');
const subjects = ref([]);
const stores = computed(() => [...new Map(subjects.value.map((item) => [item.store_id, item])).values()]);
const advertisers = computed(() => subjects.value.filter((item) => !store.value || item.store_id === store.value));
const loading = ref(false);
const error = ref('');
const report = ref(null);
const showAdvertisers = ref(false);
const collectionLabels = { success: '采集成功、有广告数据', no_data: '查询成功、无广告数据', failed: '采集失败', not_collected: '未采集／待核验' };
const collectionErrors = { gmv_max_store_not_verified: 'GMV Max 店铺绑定未验证',
  database_operation_failed: '数据库操作失败，需核对入库结果', oauth_flow_failed: '授权或凭据流程失败',
  provider_read_rejected: '官方接口请求未通过', shop_authorization_expired: '店铺授权已过期',
  advertiser_metadata_changed: '广告户币种或时区不一致' };
const warningLabels = {
  gmv_max_collection_limit_exceeded: '采集状态记录超过读取上限，请缩小日期范围或店铺；未将未知状态视为无数据。',
  collection_disabled: '部分账户采集开关已关闭，历史数据仍可查看。',
  local_evidence_unverified: '部分账户的当前本地绑定证据未核验；这不影响读取历史事实，也不代表实时授权有效。',
  fact_currency_differs_from_current_mapping: '存在事实币种与当前映射币种不一致的数据；保留原币种，不折算、不重新归类。',
  gmv_max_snapshot_limit_exceeded: 'GMV Max 快照数量超过读取上限，请缩小日期范围或选择店铺；不展示不完整金额。',
};
let sequence = 0;
let appliedQuery;
function collectionCount(item, status) {
  return (report.value?.gmv_max_collection_days || []).filter(row => row.store_code === item.store_code
    && (!item.advertiser_id || row.advertiser_id === item.advertiser_id)
    && row.currency === item.currency && row.timezone === item.timezone && row.status === status).length;
}
function invalidate() {
  sequence += 1;
  report.value = null;
  error.value = '';
  loading.value = false;
}
watch(store, () => { advertiser.value = ''; }, { flush: 'sync' });
watch([from, to, store, advertiser], invalidate, { flush: 'sync' });
watch(() => props.active, (active) => {
  invalidate();
  subjects.value = [];
  if (active) load(1);
}, { immediate: true });
onBeforeUnmount(invalidate);

async function load(page = 1) {
  if (!props.active) return;
  invalidate();
  const requestSequence = sequence;
  if (page === 1) {
    const days = (Date.parse(to.value) - Date.parse(from.value)) / 86400000;
    if (!Number.isFinite(days) || days < 0 || days >= 31) {
      error.value = '请选择明确的 1 至 31 天日期范围。';
      return;
    }
    appliedQuery = { date_from: from.value, date_to: to.value,
      ...(store.value ? { store_id: store.value } : {}),
      ...(advertiser.value ? { advertiser_id: advertiser.value } : {}) };
  }
  loading.value = true;
  try {
    const response = await fetchTikTokDailySpend({ ...appliedQuery, report_type: 'gmv_max', page, page_size: 50 });
    if (requestSequence !== sequence || !props.active) return;
    if (!response.success) throw new Error(response.message || '读取失败');
    report.value = response.data;
    subjects.value = response.data.subjects;
  } catch (failure) {
    if (requestSequence !== sequence || !props.active) return;
    subjects.value = [];
    error.value = failure.code === 'ECONNABORTED'
      ? '报表读取超时，请缩小日期范围或选择店铺后重试。不是授权失败，不需要重新授权。'
      : failure?.response?.data?.message || failure.message || '读取失败，无模拟数据回退。';
  } finally {
    if (requestSequence === sequence) loading.value = false;
  }
}
</script>

<style scoped>
.filters { margin: 16px 0; }
.subject-select { width: 240px; }
.notice { margin-bottom: 16px; }
.pagination { margin-top: 16px; }
.gmv-overview { margin: 16px 0; padding: 16px; border: 1px solid var(--el-border-color); border-radius: 8px; }
.coverage-line { display: flex; flex-wrap: wrap; gap: 8px; }
.coverage-note { color: var(--el-text-color-secondary); font-size: 12px; }
.gmv-metrics { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.gmv-metrics div { padding: 12px; background: var(--el-fill-color-light); border-radius: 4px; }
.gmv-metrics span, .gmv-metrics strong { display: block; overflow-wrap: anywhere; }
.gmv-metrics strong { margin-top: 8px; font-size: 20px; }
@media (max-width: 1000px) { .gmv-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 720px) { .subject-select { width: 100%; } }
</style>
